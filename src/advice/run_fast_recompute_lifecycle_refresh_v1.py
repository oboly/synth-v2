from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.advice.run_paper_advice_policy_v1 import (
    build_output_rows,
    fetch_latest_inputs,
    parse_aplus_table1,
    write_rows,
)
from src.common.db import get_connection
from src.market_data.market_price_snapshot_v1 import fetch_latest_prices_by_symbol
from src.reporting.run_fast_recompute_lifecycle_v1 import (
    RecomputeLifecycleRow,
    build_recompute_rows,
    fetch_latest_advice_rows,
)
from src.zone.engine_v1 import build_zone_engine_result
from src.zone.repository import ZoneRepository


REPORT_NAME = "fast_recompute_lifecycle_refresh_v1"
REPORT_VERSION = "0.1"

ENABLED_SCOPES = {"ZONE_AND_ADVICE_RECOMPUTE"}

SAFETY_LINE = (
    "broker_private_calls=0 broker_calls=0 broker_writes=0 order_submission=0 "
    "live_orders=0 decision_gate_changes=0 execution_planner_changes=0 "
    "executor=none account_awareness=0"
)


@dataclass(frozen=True)
class RefreshResultRow:
    symbol: str
    asset_id: int | None
    recommended_refresh_scope: str
    lifecycle_state: str
    recompute_reason: str
    old_leg_direction: str
    current_price: Decimal | None
    old_next_zone_state: str
    action_taken: str
    zone_result_state: str
    new_zone_asof_ts_utc: datetime | None
    paper_advice_refreshed: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Consume the fast recompute lifecycle worklist and refresh market-only zones/advice."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--quote", default="EUR")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--sleeve-code", default="SWING_STRUCTURAL")
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--max-assets", type=int, default=6)
    parser.add_argument("--lookback-candles", type=int, default=120)
    parser.add_argument("--swing-window", type=int, default=5)
    parser.add_argument("--sr-tolerance-bps", default="60")
    parser.add_argument("--include-advice-only-review", action="store_true")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("summary", "table", "json"), default="table")
    return parser.parse_args()


def dec_text(value: Decimal | None, places: str = "0.000000") -> str:
    if value is None:
        return ""
    try:
        return str(value.quantize(Decimal(places)))
    except Exception:
        return str(value)


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="microseconds")
    return str(value)


def resolve_asset_ids(conn: Any, symbols: list[str]) -> dict[str, int]:
    normalized = sorted({symbol.upper() for symbol in symbols if symbol})
    if not normalized:
        return {}
    placeholders = []
    params: dict[str, Any] = {}
    for idx, symbol in enumerate(normalized):
        key = f"symbol_{idx}"
        placeholders.append(f"%({key})s")
        params[key] = symbol
    sql = f"""
    SELECT asset_id, symbol
    FROM asset
    WHERE UPPER(symbol) IN ({', '.join(placeholders)})
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    return {str(row["symbol"]).upper(): int(row["asset_id"]) for row in rows}


def selected_worklist_rows(
    rows: list[RecomputeLifecycleRow],
    *,
    max_assets: int,
    include_advice_only_review: bool,
) -> list[RecomputeLifecycleRow]:
    enabled = set(ENABLED_SCOPES)
    if include_advice_only_review:
        enabled.add("ADVICE_ONLY_REVIEW")
    selected = [row for row in rows if row.recommended_refresh_scope in enabled]
    return selected[:max_assets]


def refresh_zone_for_asset(
    *,
    repo: ZoneRepository,
    asset_id: int,
    symbol: str,
    venue: str,
    interval: str,
    sleeve_code: str,
    lookback_candles: int,
    swing_window: int,
    sr_tolerance_bps: Decimal,
    write_db: bool,
) -> tuple[str, datetime | None]:
    candles = repo.fetch_recent_candles(
        asset_id=asset_id,
        symbol=symbol,
        venue=venue,
        interval_code=interval,
        limit=lookback_candles,
    )
    if len(candles) < 20:
        return "SKIPPED_ZONE_RESULT_MISSING", None

    result = build_zone_engine_result(
        repo=repo,
        candles=candles,
        swing_window=swing_window,
        sr_tolerance_bps=sr_tolerance_bps,
        sleeve_code=sleeve_code,
    )
    if result is None or result.execution_context is None:
        return "SKIPPED_ZONE_RESULT_MISSING", None

    if write_db:
        repo.upsert_fib_observation(result.fib_observation)
        for zone in result.zones:
            repo.upsert_zone_observation(zone)
        repo.delete_execution_zone_context_scope(
            venue=venue,
            interval_code=interval,
            sleeve_code=sleeve_code,
            asset_id=asset_id,
        )
        repo.upsert_execution_zone_context(result.execution_context)

    return "ZONE_RECOMPUTED", result.execution_context.asof_ts_utc


def refresh_paper_advice_for_assets(
    *,
    conn: Any,
    asset_ids: list[int],
    venue: str,
    interval: str,
    write_db: bool,
) -> int:
    if not asset_ids or not write_db:
        return 0
    conn.rollback()
    aplus_prediction_ts, aplus_rows = parse_aplus_table1(Path("db://latest"))
    input_rows = fetch_latest_inputs(
        conn,
        venue=venue,
        interval_code=interval,
        limit=None,
        asset_ids=asset_ids,
    )
    output_rows = build_output_rows(
        input_rows,
        aplus_rows=aplus_rows,
        interval_code=interval,
        aplus_raw_path=Path("db://latest"),
        aplus_prediction_ts=aplus_prediction_ts,
    )
    return write_rows(conn, output_rows)


def build_refresh_rows(
    *,
    worklist_rows: list[RecomputeLifecycleRow],
    asset_by_symbol: dict[str, int],
    args: argparse.Namespace,
) -> tuple[list[RefreshResultRow], list[int]]:
    repo = ZoneRepository()
    output: list[RefreshResultRow] = []
    refreshed_asset_ids: list[int] = []
    selected = selected_worklist_rows(
        worklist_rows,
        max_assets=int(args.max_assets),
        include_advice_only_review=bool(args.include_advice_only_review),
    )
    selected_symbols = {row.symbol for row in selected}

    for row in worklist_rows:
        asset_id = asset_by_symbol.get(row.symbol)
        if row.symbol not in selected_symbols:
            action = "SKIPPED_SCOPE_NOT_ENABLED"
            zone_state = "NOT_SELECTED"
            new_asof = None
            paper_refreshed = "NO"
        elif asset_id is None:
            action = "SKIPPED_ASSET_NOT_FOUND"
            zone_state = "ASSET_NOT_FOUND"
            new_asof = None
            paper_refreshed = "NO"
        elif row.recommended_refresh_scope not in ENABLED_SCOPES:
            action = "SKIPPED_SCOPE_NOT_ENABLED"
            zone_state = "SCOPE_NOT_ENABLED"
            new_asof = None
            paper_refreshed = "NO"
        elif not args.write_db:
            action = "DRY_RUN_ZONE_AND_ADVICE_RECOMPUTE"
            zone_state = "DRY_RUN"
            new_asof = None
            paper_refreshed = "NO"
        else:
            try:
                zone_state, new_asof = refresh_zone_for_asset(
                    repo=repo,
                    asset_id=asset_id,
                    symbol=row.symbol,
                    venue=str(args.venue),
                    interval=str(args.interval),
                    sleeve_code=str(args.sleeve_code),
                    lookback_candles=int(args.lookback_candles),
                    swing_window=int(args.swing_window),
                    sr_tolerance_bps=Decimal(str(args.sr_tolerance_bps)),
                    write_db=True,
                )
                if zone_state == "ZONE_RECOMPUTED":
                    action = "ZONE_RECOMPUTED"
                    refreshed_asset_ids.append(asset_id)
                else:
                    action = zone_state
                paper_refreshed = "NO"
            except Exception:
                action = "FAILED_SAFE"
                zone_state = "FAILED_SAFE"
                new_asof = None
                paper_refreshed = "NO"

        output.append(
            RefreshResultRow(
                symbol=row.symbol,
                asset_id=asset_id,
                recommended_refresh_scope=row.recommended_refresh_scope,
                lifecycle_state=row.lifecycle_state,
                recompute_reason=row.recompute_reason,
                old_leg_direction=row.leg_direction,
                current_price=row.current_price,
                old_next_zone_state=row.next_zone_state,
                action_taken=action,
                zone_result_state=zone_state,
                new_zone_asof_ts_utc=new_asof,
                paper_advice_refreshed=paper_refreshed,
            )
        )

    return output, list(dict.fromkeys(refreshed_asset_ids))


def mark_paper_refreshed(rows: list[RefreshResultRow], refreshed_asset_ids: set[int]) -> list[RefreshResultRow]:
    output: list[RefreshResultRow] = []
    for row in rows:
        if row.asset_id in refreshed_asset_ids and row.action_taken == "ZONE_RECOMPUTED":
            output.append(
                RefreshResultRow(
                    **{
                        **asdict(row),
                        "action_taken": "PAPER_ADVICE_REFRESHED",
                        "paper_advice_refreshed": "YES",
                    }
                )
            )
        else:
            output.append(row)
    return output


def print_table(rows: list[RefreshResultRow]) -> None:
    headers = [
        "symbol",
        "asset_id",
        "scope",
        "lifecycle",
        "reason",
        "old_leg",
        "price",
        "old_next_zone",
        "action",
        "zone_state",
        "new_zone_asof",
        "paper_advice",
    ]
    print(" | ".join(headers))
    print("-+-".join("-" * len(header) for header in headers))
    for row in rows:
        print(
            " | ".join(
                [
                    row.symbol,
                    "" if row.asset_id is None else str(row.asset_id),
                    row.recommended_refresh_scope,
                    row.lifecycle_state,
                    row.recompute_reason,
                    row.old_leg_direction,
                    dec_text(row.current_price),
                    row.old_next_zone_state,
                    row.action_taken,
                    row.zone_result_state,
                    "" if row.new_zone_asof_ts_utc is None else str(row.new_zone_asof_ts_utc),
                    row.paper_advice_refreshed,
                ]
            )
        )


def main() -> int:
    args = parse_args()

    conn = get_connection()
    try:
        _, advice_rows = fetch_latest_advice_rows(
            conn,
            venue=str(args.venue),
            interval=str(args.interval),
            limit=int(args.limit),
        )
        price_by_symbol = fetch_latest_prices_by_symbol(
            conn,
            venue=str(args.venue),
            quote_currency=str(args.quote),
            symbols=[str(row.get("symbol") or "").upper() for row in advice_rows],
        )
        worklist_rows = build_recompute_rows(
            advice_rows,
            venue=str(args.venue),
            interval=str(args.interval),
            price_by_symbol=price_by_symbol,
        )
        asset_by_symbol = resolve_asset_ids(conn, [row.symbol for row in worklist_rows])
        result_rows, refreshed_asset_ids = build_refresh_rows(
            worklist_rows=worklist_rows,
            asset_by_symbol=asset_by_symbol,
            args=args,
        )
        advice_written = refresh_paper_advice_for_assets(
            conn=conn,
            asset_ids=refreshed_asset_ids,
            venue=str(args.venue),
            interval=str(args.interval),
            write_db=bool(args.write_db),
        )
        if advice_written:
            result_rows = mark_paper_refreshed(result_rows, set(refreshed_asset_ids))
    finally:
        conn.close()

    if args.output == "summary":
        print(f"report={REPORT_NAME} version={REPORT_VERSION}")
        print(f"write_db={bool(args.write_db)} candidates={len(worklist_rows)} rows={len(result_rows)}")
        print(f"zone_refreshed_assets={len(refreshed_asset_ids)} paper_advice_rows_written={advice_written}")
        print(SAFETY_LINE)
    elif args.output == "json":
        print(
            json.dumps(
                {
                    "report": REPORT_NAME,
                    "version": REPORT_VERSION,
                    "write_db": bool(args.write_db),
                    "rows": [asdict(row) for row in result_rows],
                    "paper_advice_rows_written": advice_written,
                    "broker_private_calls": 0,
                    "broker_calls": 0,
                    "broker_writes": 0,
                    "order_submission": 0,
                    "live_orders": 0,
                    "decision_gate_changes": 0,
                    "execution_planner_changes": 0,
                    "executor": "none",
                    "account_awareness": 0,
                },
                indent=2,
                sort_keys=True,
                default=json_default,
            )
        )
    else:
        print_table(result_rows)
        print(SAFETY_LINE)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
