from __future__ import annotations

import argparse
import json
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only one-asof CQ v1 temporal population smoke"
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--asof-index", type=int, default=1, help="1-based frozen as-of index")
    parser.add_argument("--asset-id", type=int, default=None, help="optional single output asset")
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
    contract = load_temporal_contract()
    asofs = derive_asofs(contract)
    if args.asof_index < 1 or args.asof_index > len(asofs):
        raise ValueError(f"--asof-index must be between 1 and {len(asofs)}")
    asof = asofs[args.asof_index - 1]
    config_path, config_sha = _validate_selection_config(args.selection_config)
    if config_sha != PINNED_SELECTION_CONFIG_SHA256:
        raise ValueError("selection config SHA unexpectedly changed after validation")
    config = load_selection_config(str(config_path))

    print(
        f"STARTED runner={RUNNER_NAME} mode=SMOKE scope=one_asof workers={WORKER_COUNT} "
        f"venue={args.venue} asof_index={args.asof_index}/{len(asofs)} "
        f"asof={asof.isoformat()} asset_id={args.asset_id if args.asset_id is not None else 'ALL'}",
        flush=True,
    )
    print(
        "SAFETY research_only=1 market_only=1 outcomes_read=0 db_writes=0 "
        "broker_private_calls=0 broker_writes=0 order_submission=0 runtime_activation=0",
        flush=True,
    )

    conn = None
    try:
        connect_started = time.monotonic()
        conn = get_db_connection()
        print(
            f"PHASE phase=db_connect status=finished elapsed_s={time.monotonic() - connect_started:.3f}",
            flush=True,
        )
        query_started = time.monotonic()
        rows = build_asof_population(
            conn,
            contract=contract,
            asof_ts_utc=asof,
            venue=args.venue,
            selection_config=config,
        )
        _bind_selection_config_provenance(rows, config_sha)
        query_elapsed = time.monotonic() - query_started
        print(
            f"QUERY phase=asof_population status=finished rows={len(rows)} elapsed_s={query_elapsed:.3f}",
            flush=True,
        )

        selected = rows
        if args.asset_id is not None:
            selected = [row for row in rows if int(row["asset_id"]) == args.asset_id]
            if not selected:
                raise ValueError(
                    f"asset_id={args.asset_id} produced no row at frozen asof {asof.isoformat()}"
                )
            if len(selected) != 1:
                raise ValueError(f"asset_id={args.asset_id} produced duplicate smoke rows")

        for row in selected:
            print(json.dumps(row, sort_keys=True, default=_json_default), flush=True)
        print(
            f"FINISHED runner={RUNNER_NAME} asof={asof.isoformat()} source_rows={len(rows)} "
            f"output_rows={len(selected)} outcomes_read=0 db_writes=0 "
            f"elapsed_s={time.monotonic() - started:.3f}",
            flush=True,
        )
        return 0
    finally:
        if conn is not None:
            conn.close()


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
