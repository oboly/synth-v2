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
from src.reporting.paper_advice_structural_consistency_audit_v1 import (
    PaperAdviceStructuralConsistencyRow,
    build_consistency_rows,
)
from src.zone.engine_v1 import build_zone_engine_result
from src.zone.repository import ZoneRepository


REPORT_NAME = "structural_missing_refresh_v1"
REPORT_VERSION = "0.1"

DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL = "4h"
DEFAULT_QUOTE = "EUR"
DEFAULT_SLEEVE_CODE = "SWING_STRUCTURAL"
DEFAULT_MAX_ASSETS = 8
DEFAULT_LOOKBACK_CANDLES = 120
DEFAULT_SWING_WINDOW = 5
DEFAULT_SR_TOLERANCE_BPS = "60"
MIN_STRUCTURAL_CANDLES = 20

ELIGIBLE_COVERAGE_STATES = {"MARKET_DATA_READY_BUT_STRUCTURE_MISSING"}
ELIGIBLE_CONSISTENCY_STATES = {"ZONE_MISSING_ADVICE_MISSING"}
ELIGIBLE_RECOMMENDED_ACTIONS = {"REFRESH_ZONE_AND_ADVICE_FOR_ASSET"}

SAFETY_LINE = (
    "broker_private_calls=0 broker_calls=0 broker_writes=0 order_submission=0 "
    "live_orders=0 decision_gate_changes=0 execution_planner_changes=0 "
    "executor=none account_awareness=0"
)


@dataclass(frozen=True)
class AssetEligibility:
    asset_id: int
    symbol: str
    is_enabled: bool
    is_tradeable: bool


@dataclass(frozen=True)
class StructuralMissingRefreshRow:
    symbol: str
    asset_id: int | None
    coverage_state_before: str
    advice_state_before: str | None
    recommended_action_before: str
    refresh_scope: str
    zone_refresh_action: str
    zone_asof_after: str | None
    paper_advice_action: str
    advice_asof_after: str | None
    final_consistency_state: str
    reason: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh missing structural zone context and paper advice for market-data-ready assets."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--sleeve-code", default=DEFAULT_SLEEVE_CODE)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--max-assets", type=int, default=DEFAULT_MAX_ASSETS)
    parser.add_argument("--lookback-candles", type=int, default=DEFAULT_LOOKBACK_CANDLES)
    parser.add_argument("--swing-window", type=int, default=DEFAULT_SWING_WINDOW)
    parser.add_argument("--sr-tolerance-bps", default=DEFAULT_SR_TOLERANCE_BPS)
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("table", "json", "summary"), default="table")
    return parser.parse_args(argv)


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="microseconds")
    return str(value)


def normalize_symbols(symbols: list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
    return sorted({str(symbol).strip().upper() for symbol in symbols or [] if str(symbol).strip()})


def fetch_asset_eligibility(conn: Any, symbols: list[str]) -> dict[str, AssetEligibility]:
    if not symbols:
        return {}
    placeholders = []
    params: dict[str, Any] = {}
    for idx, symbol in enumerate(symbols):
        key = f"symbol_{idx}"
        placeholders.append(f"%({key})s")
        params[key] = symbol
    sql = f"""
    SELECT
        asset_id,
        symbol,
        is_enabled,
        is_tradeable
    FROM asset
    WHERE UPPER(symbol) IN ({', '.join(placeholders)})
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    return {
        str(row["symbol"]).upper(): AssetEligibility(
            asset_id=int(row["asset_id"]),
            symbol=str(row["symbol"]).upper(),
            is_enabled=bool(int(row.get("is_enabled") or 0)),
            is_tradeable=bool(int(row.get("is_tradeable") or 0)),
        )
        for row in rows
    }


def fetch_latest_zone_asof(
    conn: Any,
    *,
    asset_id: int,
    venue: str,
    interval: str,
    sleeve_code: str,
) -> str | None:
    sql = """
    SELECT MAX(asof_ts_utc) AS asof_ts_utc
    FROM execution_zone_context
    WHERE asset_id = %(asset_id)s
      AND venue = %(venue)s
      AND interval_code = %(interval)s
      AND sleeve_code = %(sleeve_code)s
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "asset_id": asset_id,
                "venue": venue,
                "interval": interval,
                "sleeve_code": sleeve_code,
            },
        )
        row = cur.fetchone()
    value = None if row is None else row.get("asof_ts_utc")
    return None if value is None else str(value)


def fetch_latest_advice_asof(conn: Any, *, asset_id: int, venue: str, interval: str) -> str | None:
    sql = """
    SELECT MAX(asof_ts_utc) AS asof_ts_utc
    FROM paper_advice_observation
    WHERE asset_id = %(asset_id)s
      AND venue = %(venue)s
      AND interval_code = %(interval)s
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"asset_id": asset_id, "venue": venue, "interval": interval})
        row = cur.fetchone()
    value = None if row is None else row.get("asof_ts_utc")
    return None if value is None else str(value)


def refresh_paper_advice_for_asset(
    conn: Any,
    *,
    asset_id: int,
    venue: str,
    interval: str,
    write_db: bool,
) -> tuple[str, str | None]:
    if not write_db:
        return "DRY_RUN_PAPER_ADVICE_REFRESH", None

    aplus_prediction_ts, aplus_rows = parse_aplus_table1(Path("db://latest"))
    input_rows = fetch_latest_inputs(
        conn,
        venue=venue,
        interval_code=interval,
        limit=None,
        asset_ids=[asset_id],
    )
    if not input_rows:
        return "SKIPPED_PAPER_ADVICE_INPUT_MISSING", None

    output_rows = build_output_rows(
        input_rows,
        aplus_rows=aplus_rows,
        interval_code=interval,
        aplus_raw_path=Path("db://latest"),
        aplus_prediction_ts=aplus_prediction_ts,
    )
    written = write_rows(conn, output_rows)
    if written <= 0:
        return "SKIPPED_PAPER_ADVICE_NOT_WRITTEN", None
    return "PAPER_ADVICE_REFRESHED", fetch_latest_advice_asof(
        conn,
        asset_id=asset_id,
        venue=venue,
        interval=interval,
    )


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
    if len(candles) < MIN_STRUCTURAL_CANDLES:
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


def row_is_eligible(row: PaperAdviceStructuralConsistencyRow) -> bool:
    return (
        row.structural_coverage_state in ELIGIBLE_COVERAGE_STATES
        and row.consistency_state in ELIGIBLE_CONSISTENCY_STATES
        and row.recommended_action in ELIGIBLE_RECOMMENDED_ACTIONS
    )


def build_final_state_by_symbol(
    conn: Any,
    *,
    venue: str,
    quote: str,
    interval: str,
    symbols: list[str],
) -> dict[str, PaperAdviceStructuralConsistencyRow]:
    rows = build_consistency_rows(
        conn,
        venue=venue,
        quote_currency=quote,
        interval_code=interval,
        symbols=symbols,
    )
    return {row.symbol.upper(): row for row in rows}


def build_refresh_rows(
    conn: Any,
    *,
    args: argparse.Namespace,
) -> list[StructuralMissingRefreshRow]:
    requested_symbols = normalize_symbols(args.symbols)
    before_rows = build_consistency_rows(
        conn,
        venue=str(args.venue),
        quote_currency=str(args.quote),
        interval_code=str(args.interval),
        symbols=requested_symbols or None,
    )
    before_by_symbol = {row.symbol.upper(): row for row in before_rows}
    symbols = sorted(before_by_symbol)
    eligibility = fetch_asset_eligibility(conn, symbols)
    selected_symbols: set[str] = set()
    eligible_symbols = [row.symbol for row in before_rows if row_is_eligible(row)]
    for symbol in eligible_symbols:
        asset = eligibility.get(symbol)
        if asset is None or not asset.is_enabled or not asset.is_tradeable:
            continue
        selected_symbols.add(symbol)
        if len(selected_symbols) >= int(args.max_assets):
            break

    repo = ZoneRepository()
    output: list[StructuralMissingRefreshRow] = []
    refreshed_symbols: list[str] = []

    for before in before_rows:
        symbol = before.symbol.upper()
        asset = eligibility.get(symbol)
        asset_id = None if asset is None else asset.asset_id
        zone_action = "NOT_RUN"
        paper_action = "NOT_RUN"
        zone_asof_after = None
        advice_asof_after = None
        final_state = before.consistency_state
        reason = ""

        if asset is None or not asset.is_enabled or not asset.is_tradeable:
            scope = "SKIPPED_NOT_ENABLED"
            reason = "asset_missing_or_not_enabled_tradeable"
        elif not row_is_eligible(before):
            if before.structural_coverage_state == "STRUCTURAL_MAP_READY":
                scope = "SKIPPED_ALREADY_STRUCTURAL_MAP_READY"
                reason = "structural_map_already_ready"
            elif before.price_snapshot_freshness != "PRICE_SNAPSHOT_FRESH" or before.ltf_candle_freshness != "LTF_CANDLES_FRESH":
                scope = "SKIPPED_NO_RECENT_MARKET_DATA"
                reason = f"price={before.price_snapshot_freshness};ltf={before.ltf_candle_freshness}"
            else:
                scope = "SKIPPED_UNKNOWN_DATA"
                reason = f"consistency={before.consistency_state};coverage={before.structural_coverage_state}"
        elif symbol not in selected_symbols:
            scope = "SKIPPED_MAX_ASSETS_THROTTLE"
            reason = "eligible_but_beyond_max_assets"
        else:
            candles = repo.fetch_recent_candles(
                asset_id=asset.asset_id,
                symbol=symbol,
                venue=str(args.venue),
                interval_code=str(args.interval),
                limit=int(args.lookback_candles),
            )
            if len(candles) < MIN_STRUCTURAL_CANDLES:
                scope = "SKIPPED_NO_RECENT_MARKET_DATA"
                reason = f"structural_candles={len(candles)};min_required={MIN_STRUCTURAL_CANDLES}"
            else:
                scope = "STRUCTURAL_ZONE_AND_ADVICE_REFRESH"
                reason = "market_data_ready_structure_missing"
                if not bool(args.write_db):
                    zone_action = "DRY_RUN_ZONE_REFRESH"
                    paper_action = "DRY_RUN_PAPER_ADVICE_REFRESH"
                else:
                    zone_action, zone_dt = refresh_zone_for_asset(
                        repo=repo,
                        asset_id=asset.asset_id,
                        symbol=symbol,
                        venue=str(args.venue),
                        interval=str(args.interval),
                        sleeve_code=str(args.sleeve_code),
                        lookback_candles=int(args.lookback_candles),
                        swing_window=int(args.swing_window),
                        sr_tolerance_bps=Decimal(str(args.sr_tolerance_bps)),
                        write_db=True,
                    )
                    zone_asof_after = None if zone_dt is None else str(zone_dt)
                    if zone_action == "ZONE_RECOMPUTED":
                        conn.rollback()
                        paper_action, advice_asof_after = refresh_paper_advice_for_asset(
                            conn,
                            asset_id=asset.asset_id,
                            venue=str(args.venue),
                            interval=str(args.interval),
                            write_db=True,
                        )
                        refreshed_symbols.append(symbol)
                    else:
                        scope = "STRUCTURAL_ZONE_REFRESH_ONLY"
                        paper_action = "SKIPPED_ZONE_REFRESH_NOT_AVAILABLE"
                    zone_asof_after = zone_asof_after or fetch_latest_zone_asof(
                        conn,
                        asset_id=asset.asset_id,
                        venue=str(args.venue),
                        interval=str(args.interval),
                        sleeve_code=str(args.sleeve_code),
                    )

        output.append(
            StructuralMissingRefreshRow(
                symbol=symbol,
                asset_id=asset_id,
                coverage_state_before=before.structural_coverage_state,
                advice_state_before=before.paper_advice_state,
                recommended_action_before=before.recommended_action,
                refresh_scope=scope,
                zone_refresh_action=zone_action,
                zone_asof_after=zone_asof_after,
                paper_advice_action=paper_action,
                advice_asof_after=advice_asof_after,
                final_consistency_state=final_state,
                reason=reason,
            )
        )

    if refreshed_symbols:
        final_by_symbol = build_final_state_by_symbol(
            conn,
            venue=str(args.venue),
            quote=str(args.quote),
            interval=str(args.interval),
            symbols=refreshed_symbols,
        )
        updated: list[StructuralMissingRefreshRow] = []
        for row in output:
            final = final_by_symbol.get(row.symbol)
            if final is None:
                updated.append(row)
                continue
            updated.append(
                StructuralMissingRefreshRow(
                    **{
                        **asdict(row),
                        "advice_asof_after": row.advice_asof_after or final.paper_advice_asof_ts_utc,
                        "zone_asof_after": row.zone_asof_after or final.zone_asof_ts_utc,
                        "final_consistency_state": final.consistency_state,
                    }
                )
            )
        output = updated

    return output


def print_table(rows: list[StructuralMissingRefreshRow]) -> None:
    headers = [
        "symbol",
        "asset_id",
        "coverage_state_before",
        "advice_state_before",
        "recommended_action_before",
        "refresh_scope",
        "zone_action",
        "zone_asof_after",
        "paper_advice_action",
        "advice_asof_after",
        "final_consistency",
        "reason",
    ]
    print(" | ".join(headers))
    print("-+-".join("-" * len(header) for header in headers))
    for row in rows:
        print(
            " | ".join(
                [
                    row.symbol,
                    "" if row.asset_id is None else str(row.asset_id),
                    row.coverage_state_before,
                    row.advice_state_before or "",
                    row.recommended_action_before,
                    row.refresh_scope,
                    row.zone_refresh_action,
                    row.zone_asof_after or "",
                    row.paper_advice_action,
                    row.advice_asof_after or "",
                    row.final_consistency_state,
                    row.reason,
                ]
            )
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    conn = get_connection()
    try:
        rows = build_refresh_rows(conn, args=args)
        conn.rollback()
    finally:
        conn.close()

    if args.output == "json":
        print(
            json.dumps(
                {
                    "report": REPORT_NAME,
                    "version": REPORT_VERSION,
                    "write_db": bool(args.write_db),
                    "rows": [asdict(row) for row in rows],
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
    elif args.output == "summary":
        refreshed = sum(1 for row in rows if row.paper_advice_action == "PAPER_ADVICE_REFRESHED")
        skipped = sum(1 for row in rows if row.refresh_scope.startswith("SKIPPED_"))
        print(f"report={REPORT_NAME} version={REPORT_VERSION}")
        print(f"write_db={bool(args.write_db)} rows={len(rows)} refreshed={refreshed} skipped={skipped}")
        print(SAFETY_LINE)
    else:
        print_table(rows)
        print(SAFETY_LINE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
