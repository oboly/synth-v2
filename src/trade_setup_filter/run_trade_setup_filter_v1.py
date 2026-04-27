from __future__ import annotations

"""
Synth v2 - Trade Setup Filter V1 runner.

LAYER:
market-only setup/context filter

BOUNDARY:
Allowed:
- latest market-only setup preview
- optional paper/research observation logging

Forbidden:
- account state
- order state
- execution planning
- broker/order actions
"""

import argparse
import json
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from src.trade_setup_filter.engine_v1 import evaluate_trade_setup
from src.trade_setup_filter.observation_repository import write_observations
from src.trade_setup_filter.repository import fetch_latest_candidates


DEFAULT_VENUE = "bitvavo"
DEFAULT_ENGINE_NAME = "selection_engine_v2"
DEFAULT_ENGINE_VERSION = "2.0"
FILTER_NAME = "trade_setup_filter_v1"
FILTER_VERSION = "1.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run market-only trade setup filter v1 preview."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--engine-name", default=DEFAULT_ENGINE_NAME)
    parser.add_argument("--engine-version", default=DEFAULT_ENGINE_VERSION)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--selection-state", default="WATCHLIST")
    parser.add_argument("--rank-min", type=int, default=4)
    parser.add_argument("--rank-max", type=int, default=10)
    parser.add_argument("--btc-prior-min", default="-0.015")
    parser.add_argument("--btc-prior-max", default="0.015")
    parser.add_argument(
        "--asset-suitability-mode",
        choices=("off", "candidate_weak_set"),
        default="candidate_weak_set",
    )
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _as_decimal(value: str) -> Decimal:
    return Decimal(str(value))


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _format_decimal(value: Decimal | None, places: int = 6) -> str:
    if value is None:
        return ""
    quant = Decimal("1").scaleb(-places)
    return str(value.quantize(quant))


def _print_table(rows: list[dict[str, Any]]) -> None:
    headers = [
        "symbol",
        "selection_state",
        "rank",
        "score",
        "btc_prior_24h",
        "setup_filter_state",
        "setup_filter_reason",
        "target_horizon",
    ]

    printable: list[list[str]] = []
    for row in rows:
        printable.append(
            [
                str(row["symbol"]),
                str(row["selection_state"]),
                "" if row["priority_rank"] is None else str(row["priority_rank"]),
                _format_decimal(row["selection_score"], places=6),
                _format_decimal(row["btc_prior_24h"], places=6),
                str(row["setup_filter_state"]),
                str(row["setup_filter_reason"]),
                str(row["target_horizon"]),
            ]
        )

    widths = [len(header) for header in headers]
    for row in printable:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def fmt(values: list[str]) -> str:
        return " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(values))

    print(fmt(headers))
    print("-+-".join("-" * width for width in widths))
    for row in printable:
        print(fmt(row))


def main() -> int:
    args = parse_args()

    candidates = fetch_latest_candidates(
        venue=str(args.venue),
        engine_name=str(args.engine_name),
        engine_version=str(args.engine_version),
        limit=int(args.limit),
    )

    decisions = [
        evaluate_trade_setup(
            candidate,
            required_selection_state=str(args.selection_state),
            rank_min=int(args.rank_min),
            rank_max=int(args.rank_max),
            btc_prior_min=_as_decimal(args.btc_prior_min),
            btc_prior_max=_as_decimal(args.btc_prior_max),
            asset_suitability_mode=str(args.asset_suitability_mode),
        )
        for candidate in candidates
    ]

    rows = [asdict(decision) for decision in decisions]

    if args.output == "json":
        print(json.dumps(rows, indent=2, ensure_ascii=False, default=_json_default))
    else:
        _print_table(rows)

    if args.write_db:
        written = write_observations(
            decisions,
            filter_name=FILTER_NAME,
            filter_version=FILTER_VERSION,
            asset_suitability_mode=str(args.asset_suitability_mode),
        )
        print(
            f"[DONE] wrote trade_setup_filter observations "
            f"rows={written} filter={FILTER_NAME} version={FILTER_VERSION} "
            f"asset_suitability_mode={args.asset_suitability_mode}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
