"""CLI for the canonical controlled automatic BUY DRY_RUN acceptance path."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_db_connection
from src.entry_policy.automatic_buy_dry_run_acceptance_v1 import (
    EXECUTOR_IDENTITY,
    EXECUTOR_MODE,
    RUNTIME_OWNER,
    SAFETY_MARKERS,
    run_automatic_buy_dry_run_acceptance_v1,
)
from src.entry_policy.automatic_buy_runtime_input_writer_v1 import AutomaticBuyRuntimeInputSourceV1

RUNNER_NAME = "run_automatic_buy_dry_run_acceptance_v1"


def _source_from_json(value: dict[str, Any]) -> AutomaticBuyRuntimeInputSourceV1:
    timestamp_fields = {
        "evaluation_ts_utc", "setup_observed_ts_utc", "account_observed_ts_utc",
        "free_quote_balance_observed_ts_utc",
    }
    decimal_fields = {
        "current_price", "entry_zone_low", "entry_zone_high", "re_entry_zone_low",
        "re_entry_zone_high", "free_quote_balance_eur", "proposed_position_amount_eur",
        "current_bucket_amount_eur", "current_asset_exposure_pct", "max_automatic_buy_notional_eur",
    }
    converted = dict(value)
    for field in timestamp_fields:
        converted[field] = datetime.fromisoformat(str(converted[field]).replace("Z", "+00:00"))
    for field in decimal_fields:
        if converted.get(field) is not None:
            converted[field] = Decimal(str(converted[field]))
    return AutomaticBuyRuntimeInputSourceV1(**converted)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Controlled automatic BUY DRY_RUN acceptance only.")
    parser.add_argument("--input-json", required=True, type=Path)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    print(
        f"STARTED runner={RUNNER_NAME} executor_mode={EXECUTOR_MODE} "
        f"runtime_owner={RUNTIME_OWNER} executor_identity={EXECUTOR_IDENTITY}",
        flush=True,
    )
    print(" ".join(SAFETY_MARKERS), flush=True)
    conn = None
    try:
        source = _source_from_json(json.loads(args.input_json.read_text()))
        conn = get_db_connection()
        try:
            result = run_automatic_buy_dry_run_acceptance_v1(conn, source=source)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as exc:
        print(f"FAILED runner={RUNNER_NAME} detail={exc}", file=sys.stderr, flush=True)
        return 1
    print(json.dumps(result.as_dict(), sort_keys=True, default=str), flush=True)
    print(f"FINISHED runner={RUNNER_NAME} result=ok", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
