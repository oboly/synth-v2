from __future__ import annotations

import argparse
import hashlib
import json
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.db import get_db_connection
from src.research.cq_v1_temporal_population_v1 import (
    END_ASOF_UTC,
    RUNNER_NAME,
    START_ASOF_UTC,
    build_rows_for_asof,
    fetch_sampling_grid,
    summarize,
)
from src.selection.selection_engine_v2 import load_selection_config

PINNED_SELECTION_CONFIG_PATH = "configs/selection_engine_v2.yaml"
PINNED_SELECTION_CONFIG_SHA256 = "08cec05f70cb8b2ff43b24a90dc4b8fb1f09d3535f9a791f05af3ddf57dff65b"


class _Interrupted(RuntimeError):
    def __init__(self, signum: int) -> None:
        super().__init__(f"signal={signum}")
        self.signum = signum


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build frozen 4h historical PIT CQ population without reading forward outcomes"
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--config", default=PINNED_SELECTION_CONFIG_PATH)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--max-asofs", type=int, default=0)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _grid_sha256(grid: list[datetime]) -> str:
    payload = "\n".join(
        value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") for value in grid
    ) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _validate_pinned_config(path: str) -> tuple[Path, str]:
    if path != PINNED_SELECTION_CONFIG_PATH:
        raise ValueError(f"selection config path must be pinned to {PINNED_SELECTION_CONFIG_PATH}")
    config_path = Path(path)
    digest = _sha256(config_path)
    if digest != PINNED_SELECTION_CONFIG_SHA256:
        raise ValueError(
            "selection config SHA256 mismatch: "
            f"expected={PINNED_SELECTION_CONFIG_SHA256} actual={digest}"
        )
    return config_path, digest


def _identity_payload(
    *,
    venue: str,
    limit: int,
    max_asofs: int,
    grid: list[datetime],
    config_sha256: str,
) -> dict[str, Any]:
    return {
        "runner": RUNNER_NAME,
        "venue": venue,
        "limit": limit,
        "max_asofs": max_asofs,
        "grid_sha256": _grid_sha256(grid),
        "asofs_total": len(grid),
        "selection_config_path": PINNED_SELECTION_CONFIG_PATH,
        "selection_config_sha256": config_sha256,
    }


def _load_checkpoint_rows(
    observations_path: Path,
    *,
    rows_written: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not observations_path.exists():
        if rows_written:
            raise ValueError("checkpoint rows_written requires observations.jsonl")
        return rows

    raw_lines = observations_path.read_text(encoding="utf-8").splitlines()
    if len(raw_lines) < rows_written:
        raise ValueError("observations.jsonl shorter than checkpoint rows_written")

    for index, line in enumerate(raw_lines[:rows_written], start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed checkpointed observation row {index}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"checkpointed observation row {index} is not an object")
        if int(row.get("temporal_observation_id", -1)) != index:
            raise ValueError(f"checkpointed temporal_observation_id mismatch at row {index}")
        rows.append(row)

    # A signal can arrive after one or more rows of the next as-of were flushed but
    # before its checkpoint was committed. Those rows are not checkpoint-owned.
    with observations_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return rows


def run(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    output_dir = Path(args.output_dir)
    observations_path = output_dir / "observations.jsonl"
    summary_path = output_dir / "summary.json"
    checkpoint_path = output_dir / "checkpoint.json"

    print(
        f"STARTED runner={RUNNER_NAME} venue={args.venue} limit={args.limit} "
        f"max_asofs={args.max_asofs} output_dir={output_dir}",
        flush=True,
    )
    print(
        "SAFETY research_only=1 market_only=1 account_awareness=0 model_retuning=0 "
        "forward_outcome_reads=0 production_ranking_changes=0 decision_gate=none "
        "execution_planner=none executor=none broker_private_calls=0 broker_writes=0 "
        "order_submission=0 live_orders=0 runtime_activation=0",
        flush=True,
    )

    conn = None
    previous_handlers: dict[int, Any] = {}
    checkpoint: dict[str, Any] | None = None

    def _handle_signal(signum: int, _frame: Any) -> None:
        raise _Interrupted(signum)

    try:
        _, config_sha256 = _validate_pinned_config(args.config)

        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _handle_signal)

        conn = get_db_connection()
        selection_config = load_selection_config(args.config)

        print("PHASE_START name=fetch_sampling_grid", flush=True)
        grid = fetch_sampling_grid(
            conn,
            venue=args.venue,
            start_asof=START_ASOF_UTC,
            end_asof=END_ASOF_UTC,
        )
        if args.max_asofs > 0:
            grid = grid[: args.max_asofs]
        if not grid:
            raise ValueError("no actual MRP snapshots satisfy frozen 4h sampling grid")
        identity = _identity_payload(
            venue=args.venue,
            limit=args.limit,
            max_asofs=args.max_asofs,
            grid=grid,
            config_sha256=config_sha256,
        )
        print(
            f"PHASE_END name=fetch_sampling_grid asofs={len(grid)} "
            f"first={grid[0].isoformat()} last={grid[-1].isoformat()}",
            flush=True,
        )

        if output_dir.exists() and any(output_dir.iterdir()):
            if not checkpoint_path.exists():
                raise ValueError("non-empty output_dir without checkpoint cannot be resumed")
            checkpoint = _load_json(checkpoint_path)
            for key, expected in identity.items():
                if checkpoint.get(key) != expected:
                    raise ValueError(
                        f"resume identity mismatch for {key}: "
                        f"checkpoint={checkpoint.get(key)!r} expected={expected!r}"
                    )
            if checkpoint.get("terminal_state") == "FINISHED":
                if not summary_path.exists() or not observations_path.exists():
                    raise ValueError("FINISHED checkpoint missing immutable output artifact")
                expected_hash = checkpoint.get("observations_sha256")
                if expected_hash != _sha256(observations_path):
                    raise ValueError("FINISHED observations SHA256 mismatch")
                print(
                    f"FINISHED runner={RUNNER_NAME} resume_noop=1 asofs={len(grid)} "
                    f"rows={checkpoint.get('rows_written', 0)} observations_sha256={expected_hash} "
                    "forward_outcome_reads=0 production_ranking_changed=0",
                    flush=True,
                )
                return 0
            completed = int(checkpoint.get("asofs_completed", 0))
            rows_written = int(checkpoint.get("rows_written", 0))
            if completed < 0 or completed > len(grid) or rows_written < 0:
                raise ValueError("invalid resume checkpoint counts")
            all_rows = _load_checkpoint_rows(observations_path, rows_written=rows_written)
            start_index = completed
            print(
                f"RESUME runner={RUNNER_NAME} asofs_completed={completed} "
                f"rows_written={rows_written}",
                flush=True,
            )
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            all_rows = []
            start_index = 0
            checkpoint = {
                **identity,
                "terminal_state": "RUNNING",
                "asofs_completed": 0,
                "rows_written": 0,
                "last_asof": None,
            }
            _write_json(checkpoint_path, checkpoint)

        next_id = len(all_rows) + 1
        with observations_path.open("a", encoding="utf-8") as observations:
            for zero_index in range(start_index, len(grid)):
                index = zero_index + 1
                candidate_asof = grid[zero_index]
                phase = time.perf_counter()
                print(
                    f"PHASE_START name=build_asof index={index}/{len(grid)} "
                    f"asof={candidate_asof.isoformat()}",
                    flush=True,
                )
                rows = build_rows_for_asof(
                    conn,
                    venue=args.venue,
                    candidate_asof=candidate_asof,
                    limit=args.limit,
                    selection_config=selection_config,
                    observation_id_start=next_id,
                )
                # build_rows_for_asof may skip ranked candidates with incomplete evidence.
                # Re-number emitted rows only, keeping persisted IDs globally contiguous.
                for row in rows:
                    row["temporal_observation_id"] = next_id
                    next_id += 1
                    observations.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                observations.flush()
                all_rows.extend(rows)
                checkpoint = {
                    **identity,
                    "terminal_state": "RUNNING",
                    "asofs_completed": index,
                    "last_asof": candidate_asof.astimezone(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "rows_written": len(all_rows),
                }
                _write_json(checkpoint_path, checkpoint)
                print(
                    f"PHASE_END name=build_asof asof={candidate_asof.isoformat()} rows={len(rows)} "
                    f"total_rows={len(all_rows)} elapsed_s={time.perf_counter()-phase:.3f}",
                    flush=True,
                )

        summary = summarize(all_rows, grid=grid)
        summary["observations_sha256"] = _sha256(observations_path)
        summary["selection_config_path"] = PINNED_SELECTION_CONFIG_PATH
        summary["selection_config_sha256"] = config_sha256
        summary["grid_sha256"] = identity["grid_sha256"]
        _write_json(summary_path, summary)
        checkpoint = {
            **identity,
            "terminal_state": "FINISHED",
            "asofs_completed": len(grid),
            "last_asof": summary["last_asof"],
            "rows_written": len(all_rows),
            "observations_sha256": summary["observations_sha256"],
        }
        _write_json(checkpoint_path, checkpoint)
        print(
            f"FINISHED runner={RUNNER_NAME} asofs={len(grid)} rows={len(all_rows)} "
            f"observations_sha256={summary['observations_sha256']} forward_outcome_reads=0 "
            f"production_ranking_changed=0 elapsed_s={time.perf_counter()-started:.3f}",
            flush=True,
        )
        return 0
    except _Interrupted as exc:
        print(
            f"INTERRUPTED runner={RUNNER_NAME} signal={exc.signum} resumable=1 "
            f"elapsed_s={time.perf_counter()-started:.3f}",
            flush=True,
        )
        return 130
    except Exception as exc:
        print(
            f"FAILED runner={RUNNER_NAME} reason={type(exc).__name__}:{exc} "
            f"elapsed_s={time.perf_counter()-started:.3f}",
            flush=True,
        )
        return 1
    finally:
        if conn is not None:
            conn.close()
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
