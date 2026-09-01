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
from src.research.cq_v1_temporal_population_v1 import RUNNER_NAME, build_rows_for_asof, sampling_grid, summarize
from src.research.cq_v1_temporal_sampling_v1 import CONTRACT_PATH, load_contract
from src.selection.selection_engine_v2 import load_selection_config

PINNED_SELECTION_CONFIG_PATH = "configs/selection_engine_v2.yaml"
PINNED_SELECTION_CONFIG_SHA256 = "08cec05f70cb8b2ff43b24a90dc4b8fb1f09d3535f9a791f05af3ddf57dff65b"


class _Interrupted(RuntimeError):
    def __init__(self, signum: int) -> None:
        super().__init__(f"signal={signum}")
        self.signum = signum


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build canonical daily historical PIT CQ v1 population without reading outcomes")
    parser.add_argument("--venue", default="bitvavo")
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
    payload = "\n".join(v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") for v in grid) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _validate_selection_config() -> tuple[Path, str]:
    path = Path(PINNED_SELECTION_CONFIG_PATH)
    digest = _sha256(path)
    if digest != PINNED_SELECTION_CONFIG_SHA256:
        raise ValueError(f"selection config SHA256 mismatch: expected={PINNED_SELECTION_CONFIG_SHA256} actual={digest}")
    return path, digest


def _identity_payload(*, venue: str, limit: int, max_asofs: int, grid: list[datetime], temporal_contract_sha256: str, selection_config_sha256: str) -> dict[str, Any]:
    return {
        "runner": RUNNER_NAME,
        "venue": venue,
        "limit": limit,
        "max_asofs": max_asofs,
        "grid_sha256": _grid_sha256(grid),
        "asofs_total": len(grid),
        "temporal_contract_path": str(CONTRACT_PATH),
        "temporal_contract_sha256": temporal_contract_sha256,
        "selection_config_path": PINNED_SELECTION_CONFIG_PATH,
        "selection_config_sha256": selection_config_sha256,
    }


def _load_checkpoint_rows(path: Path, *, rows_written: int) -> list[dict[str, Any]]:
    if not path.exists():
        if rows_written:
            raise ValueError("checkpoint rows_written requires observations.jsonl")
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < rows_written:
        raise ValueError("observations.jsonl shorter than checkpoint rows_written")
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(lines[:rows_written], start=1):
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"checkpointed observation row {index} is not an object")
        if int(row.get("temporal_observation_id", -1)) != index:
            raise ValueError(f"checkpointed temporal_observation_id mismatch at row {index}")
        rows.append(row)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return rows


def run(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    output_dir = Path(args.output_dir)
    observations_path = output_dir / "observations.jsonl"
    summary_path = output_dir / "summary.json"
    checkpoint_path = output_dir / "checkpoint.json"

    print(f"STARTED runner={RUNNER_NAME} venue={args.venue} limit={args.limit} max_asofs={args.max_asofs} output_dir={output_dir}", flush=True)
    print("SAFETY research_only=1 market_only=1 account_awareness=0 outcomes_read=0 model_retuning=0 production_ranking_changes=0 decision_gate=none execution_planner=none executor=none broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 runtime_activation=0", flush=True)

    conn = None
    previous_handlers: dict[int, Any] = {}

    def _handle_signal(signum: int, _frame: Any) -> None:
        raise _Interrupted(signum)

    try:
        temporal_contract = load_contract(CONTRACT_PATH)
        temporal_contract_sha256 = _sha256(CONTRACT_PATH)
        _, selection_config_sha256 = _validate_selection_config()
        selection_config = load_selection_config(PINNED_SELECTION_CONFIG_PATH)
        grid = sampling_grid(temporal_contract)
        if args.max_asofs > 0:
            grid = grid[: args.max_asofs]
        if not grid:
            raise ValueError("frozen temporal contract yielded no as-ofs")

        identity = _identity_payload(
            venue=args.venue,
            limit=args.limit,
            max_asofs=args.max_asofs,
            grid=grid,
            temporal_contract_sha256=temporal_contract_sha256,
            selection_config_sha256=selection_config_sha256,
        )

        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _handle_signal)

        conn = get_db_connection()

        if output_dir.exists() and any(output_dir.iterdir()):
            if not checkpoint_path.exists():
                raise ValueError("non-empty output_dir without checkpoint cannot be resumed")
            checkpoint = _load_json(checkpoint_path)
            for key, expected in identity.items():
                if checkpoint.get(key) != expected:
                    raise ValueError(f"resume identity mismatch for {key}: checkpoint={checkpoint.get(key)!r} expected={expected!r}")
            if checkpoint.get("terminal_state") == "FINISHED":
                expected_hash = checkpoint.get("observations_sha256")
                if not observations_path.exists() or expected_hash != _sha256(observations_path):
                    raise ValueError("FINISHED observations SHA256 mismatch")
                print(f"FINISHED runner={RUNNER_NAME} resume_noop=1 asofs={len(grid)} rows={checkpoint.get('rows_written', 0)} observations_sha256={expected_hash} outcomes_read=0", flush=True)
                return 0
            completed = int(checkpoint.get("asofs_completed", 0))
            rows_written = int(checkpoint.get("rows_written", 0))
            all_rows = _load_checkpoint_rows(observations_path, rows_written=rows_written)
            start_index = completed
            print(f"RESUME runner={RUNNER_NAME} asofs_completed={completed} rows_written={rows_written}", flush=True)
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            all_rows = []
            start_index = 0
            _write_json(checkpoint_path, {**identity, "terminal_state": "RUNNING", "asofs_completed": 0, "rows_written": 0, "last_asof": None})

        next_id = len(all_rows) + 1
        with observations_path.open("a", encoding="utf-8") as observations:
            for zero_index in range(start_index, len(grid)):
                index = zero_index + 1
                asof = grid[zero_index]
                rows = build_rows_for_asof(
                    conn,
                    venue=args.venue,
                    candidate_asof=asof,
                    limit=args.limit,
                    selection_config=selection_config,
                    temporal_contract=temporal_contract,
                    observation_id_start=next_id,
                )
                for row in rows:
                    row["temporal_observation_id"] = next_id
                    next_id += 1
                    observations.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                observations.flush()
                all_rows.extend(rows)
                _write_json(checkpoint_path, {
                    **identity,
                    "terminal_state": "RUNNING",
                    "asofs_completed": index,
                    "rows_written": len(all_rows),
                    "last_asof": asof.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                })
                print(f"PHASE_END name=build_asof index={index}/{len(grid)} asof={asof.isoformat()} rows={len(rows)} total_rows={len(all_rows)}", flush=True)

        summary = summarize(all_rows, grid=grid)
        summary["observations_sha256"] = _sha256(observations_path)
        summary["temporal_contract_path"] = str(CONTRACT_PATH)
        summary["temporal_contract_sha256"] = temporal_contract_sha256
        summary["selection_config_path"] = PINNED_SELECTION_CONFIG_PATH
        summary["selection_config_sha256"] = selection_config_sha256
        summary["grid_sha256"] = identity["grid_sha256"]
        _write_json(summary_path, summary)
        _write_json(checkpoint_path, {
            **identity,
            "terminal_state": "FINISHED",
            "asofs_completed": len(grid),
            "rows_written": len(all_rows),
            "last_asof": summary["last_asof"],
            "observations_sha256": summary["observations_sha256"],
        })
        print(f"FINISHED runner={RUNNER_NAME} asofs={len(grid)} rows={len(all_rows)} observations_sha256={summary['observations_sha256']} outcomes_read=0 production_ranking_changed=0 elapsed_s={time.perf_counter()-started:.3f}", flush=True)
        return 0
    except _Interrupted as exc:
        print(f"INTERRUPTED runner={RUNNER_NAME} signal={exc.signum} resumable=1 elapsed_s={time.perf_counter()-started:.3f}", flush=True)
        return 130
    except Exception as exc:
        print(f"FAILED runner={RUNNER_NAME} reason={type(exc).__name__}:{exc} elapsed_s={time.perf_counter()-started:.3f}", flush=True)
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
