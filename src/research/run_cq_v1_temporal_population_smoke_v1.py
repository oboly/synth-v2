from __future__ import annotations

import argparse
import json
import signal
import time
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_db_connection
from src.research.cq_v1_temporal_population_v1 import build_asof_population, load_temporal_contract
from src.research.cq_v1_temporal_sampling_v1 import derive_asofs
from src.research.run_cq_v1_temporal_population_v1 import (
    DEFAULT_SELECTION_CONFIG,
    PINNED_SELECTION_CONFIG_SHA256,
    _bind_selection_config_provenance,
    _validate_selection_config,
)
from src.selection.selection_engine_v2 import load_selection_config

RUNNER_NAME = "cq_v1_temporal_population_smoke_v1"
WORKER_COUNT = 1


class _Interrupted(RuntimeError):
    def __init__(self, signum: int) -> None:
        super().__init__(f"signal={signum}")
        self.signum = signum


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only one-asof CQ v1 temporal population smoke")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--asof-index", type=int, default=1, help="1-based frozen as-of index")
    parser.add_argument("--asset-id", type=int, default=None, help="optional single query/build asset")
    parser.add_argument("--selection-config", default=DEFAULT_SELECTION_CONFIG)
    return parser.parse_args(argv)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    conn = None
    previous_handlers: dict[int, Any] = {}

    def _handle_signal(signum: int, _frame: Any) -> None:
        raise _Interrupted(signum)

    try:
        contract = load_temporal_contract()
        asofs = derive_asofs(contract)
        if args.asof_index < 1 or args.asof_index > len(asofs):
            raise ValueError(f"--asof-index must be between 1 and {len(asofs)}")
        asof = asofs[args.asof_index - 1]
        config_path, config_sha = _validate_selection_config(args.selection_config)
        if config_sha != PINNED_SELECTION_CONFIG_SHA256:
            raise ValueError("selection config SHA unexpectedly changed after validation")
        config = load_selection_config(str(config_path))

        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _handle_signal)

        print(
            f"STARTED runner={RUNNER_NAME} mode=SMOKE scope=one_asof workers={WORKER_COUNT} "
            f"venue={args.venue} asof_index={args.asof_index}/{len(asofs)} "
            f"asof={asof.isoformat()} asset_id={args.asset_id if args.asset_id is not None else 'ALL'}",
            flush=True,
        )
        print(
            "SAFETY research_only=1 market_only=1 account_awareness=0 outcomes_read=0 db_writes=0 "
            "model_retuning=0 production_ranking_changes=0 decision_gate=none execution_planner=none "
            "executor=none broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 runtime_activation=0",
            flush=True,
        )

        connect_started = time.monotonic()
        conn = get_db_connection()
        print(
            f"PHASE phase=db_connect status=finished elapsed_s={time.monotonic() - connect_started:.3f}",
            flush=True,
        )
        query_started = time.monotonic()
        print(
            f"QUERY phase=asof_population status=started asof={asof.isoformat()} asset_id={args.asset_id if args.asset_id is not None else 'ALL'}",
            flush=True,
        )
        rows = build_asof_population(
            conn,
            contract=contract,
            asof_ts_utc=asof,
            venue=args.venue,
            selection_config=config,
            asset_id=args.asset_id,
        )
        _bind_selection_config_provenance(rows, config_sha)
        query_elapsed = time.monotonic() - query_started
        print(
            f"QUERY phase=asof_population status=finished rows={len(rows)} elapsed_s={query_elapsed:.3f}",
            flush=True,
        )

        if args.asset_id is not None:
            if not rows:
                raise ValueError(f"asset_id={args.asset_id} produced no row at frozen asof {asof.isoformat()}")
            if len(rows) != 1 or int(rows[0]["asset_id"]) != args.asset_id:
                raise ValueError(f"asset_id={args.asset_id} did not remain single-asset bounded")

        for row in rows:
            print(json.dumps(row, sort_keys=True, default=_json_default), flush=True)
        print(
            f"FINISHED runner={RUNNER_NAME} asof={asof.isoformat()} source_rows={len(rows)} "
            f"output_rows={len(rows)} outcomes_read=0 db_writes=0 elapsed_s={time.monotonic() - started:.3f}",
            flush=True,
        )
        return 0
    except _Interrupted as exc:
        print(
            f"INTERRUPTED runner={RUNNER_NAME} signal={exc.signum} outcomes_read=0 db_writes=0 "
            f"elapsed_s={time.monotonic() - started:.3f}",
            flush=True,
        )
        return 130
    except Exception as exc:
        print(
            f"FAILED runner={RUNNER_NAME} error={type(exc).__name__}:{exc} outcomes_read=0 db_writes=0 "
            f"elapsed_s={time.monotonic() - started:.3f}",
            flush=True,
        )
        raise
    finally:
        if conn is not None:
            conn.close()
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
