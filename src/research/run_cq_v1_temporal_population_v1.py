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
from src.selection.run_selection_engine_v2 import DEFAULT_CONFIG_PATH
from src.selection.selection_engine_v2 import load_selection_config


class _Interrupted(RuntimeError):
    def __init__(self, signum: int) -> None:
        super().__init__(f"signal={signum}")
        self.signum = signum


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build frozen 4h historical PIT CQ population without reading forward outcomes"
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


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

    def _handle_signal(signum: int, _frame: Any) -> None:
        raise _Interrupted(signum)

    try:
        if output_dir.exists() and any(output_dir.iterdir()):
            raise ValueError("output_dir must be empty for immutable temporal population build")
        output_dir.mkdir(parents=True, exist_ok=True)

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
        print(
            f"PHASE_END name=fetch_sampling_grid asofs={len(grid)} "
            f"first={grid[0].isoformat()} last={grid[-1].isoformat()}",
            flush=True,
        )

        all_rows: list[dict[str, Any]] = []
        next_id = 1
        with observations_path.open("w", encoding="utf-8") as observations:
            for index, candidate_asof in enumerate(grid, start=1):
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
                for row in rows:
                    observations.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                observations.flush()
                next_id += len(rows)
                all_rows.extend(rows)
                _write_json(
                    checkpoint_path,
                    {
                        "runner": RUNNER_NAME,
                        "terminal_state": "RUNNING",
                        "asofs_completed": index,
                        "asofs_total": len(grid),
                        "last_asof": candidate_asof.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "rows_written": len(all_rows),
                    },
                )
                print(
                    f"PHASE_END name=build_asof asof={candidate_asof.isoformat()} rows={len(rows)} "
                    f"total_rows={len(all_rows)} elapsed_s={time.perf_counter()-phase:.3f}",
                    flush=True,
                )

        summary = summarize(all_rows, grid=grid)
        summary["observations_sha256"] = _sha256(observations_path)
        _write_json(summary_path, summary)
        _write_json(
            checkpoint_path,
            {
                "runner": RUNNER_NAME,
                "terminal_state": "FINISHED",
                "asofs_completed": len(grid),
                "asofs_total": len(grid),
                "last_asof": summary["last_asof"],
                "rows_written": len(all_rows),
                "observations_sha256": summary["observations_sha256"],
            },
        )
        print(
            f"FINISHED runner={RUNNER_NAME} asofs={len(grid)} rows={len(all_rows)} "
            f"observations_sha256={summary['observations_sha256']} forward_outcome_reads=0 "
            f"production_ranking_changed=0 elapsed_s={time.perf_counter()-started:.3f}",
            flush=True,
        )
        return 0
    except _Interrupted as exc:
        print(
            f"INTERRUPTED runner={RUNNER_NAME} signal={exc.signum} resumable=0 "
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
