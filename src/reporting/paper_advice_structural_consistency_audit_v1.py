from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.reporting.paper_advice_severity_calibration_v1 import (
    calibrate_paper_advice_severity,
)
from src.reporting.structural_zone_context_coverage_audit_v1 import (
    StructuralZoneCoverageRow,
    build_coverage_rows,
)


REPORT_NAME = "paper_advice_structural_consistency_audit_v1"
VERSION = "0.1"

DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE = "EUR"
DEFAULT_INTERVAL = "4h"


@dataclass(frozen=True)
class PaperAdviceStructuralConsistencyRow:
    symbol: str
    asset_id: int
    venue: str
    interval_code: str
    zone_asof_ts_utc: str | None
    paper_advice_asof_ts_utc: str | None
    zone_has_leg_direction: bool
    zone_leg_direction: str | None
    advice_leg_direction: str | None
    zone_has_entry_zone: bool
    advice_has_entry_zone: bool
    zone_has_target_zone: bool
    advice_has_target_zone: bool
    zone_has_invalidation_price: bool
    advice_has_invalidation_price: bool
    price_snapshot_freshness: str
    ltf_candle_freshness: str
    structural_coverage_state: str
    paper_advice_state: str | None
    advice_action: str | None
    advice_severity: str | None
    advice_substate: str | None
    consistency_state: str
    mismatch_fields: str
    recommended_action: str


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _fmt_ts(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _has_zone(low: Any, high: Any) -> bool:
    return _has_value(low) and _has_value(high)


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def _zone_newer_than_advice(zone_ts: Any, advice_ts: Any) -> bool:
    if not isinstance(zone_ts, datetime) or not isinstance(advice_ts, datetime):
        return False
    return zone_ts.replace(tzinfo=None) > advice_ts.replace(tzinfo=None)


def fetch_latest_zones(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    symbols: set[str],
) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    placeholders = []
    params: dict[str, Any] = {"venue": venue, "interval_code": interval_code}
    for idx, symbol in enumerate(sorted(symbols)):
        key = f"symbol_{idx}"
        placeholders.append(f"%({key})s")
        params[key] = symbol

    sql = f"""
    WITH latest_zone AS (
        SELECT asset_id, MAX(asof_ts_utc) AS asof_ts_utc
        FROM execution_zone_context
        WHERE venue = %(venue)s
          AND interval_code = %(interval_code)s
        GROUP BY asset_id
    )
    SELECT
        a.asset_id,
        a.symbol,
        z.asof_ts_utc,
        CASE
            WHEN z.notes LIKE 'leg_direction=%%'
                THEN SUBSTRING_INDEX(SUBSTRING_INDEX(z.notes, 'leg_direction=', -1), ';', 1)
            ELSE NULL
        END AS leg_direction,
        z.expected_entry_zone_low AS entry_zone_low,
        z.expected_entry_zone_high AS entry_zone_high,
        z.expected_take_profit_zone_low AS tp_zone_low,
        z.expected_take_profit_zone_high AS tp_zone_high,
        z.invalidation_price
    FROM latest_zone lz
    JOIN execution_zone_context z
      ON z.asset_id = lz.asset_id
     AND z.asof_ts_utc = lz.asof_ts_utc
     AND z.venue = %(venue)s
     AND z.interval_code = %(interval_code)s
    JOIN asset a
      ON a.asset_id = z.asset_id
    WHERE a.symbol IN ({', '.join(placeholders)})
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    return {str(row["symbol"]).upper(): row for row in rows}


def fetch_latest_paper_advice(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    symbols: set[str],
) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    placeholders = []
    params: dict[str, Any] = {"venue": venue, "interval_code": interval_code}
    for idx, symbol in enumerate(sorted(symbols)):
        key = f"symbol_{idx}"
        placeholders.append(f"%({key})s")
        params[key] = symbol

    sql = f"""
    WITH latest_advice AS (
        SELECT asset_id, MAX(asof_ts_utc) AS asof_ts_utc
        FROM paper_advice_observation
        WHERE venue = %(venue)s
          AND interval_code = %(interval_code)s
        GROUP BY asset_id
    )
    SELECT
        p.asset_id,
        p.symbol,
        p.asof_ts_utc,
        p.advice_state,
        p.advice_action,
        p.risk_label,
        p.reason_codes_json,
        p.selection_state,
        p.setup_filter_state,
        p.setup_filter_reason,
        p.policy_decision,
        p.aplus_bucket,
        p.leg_direction,
        p.entry_zone_low,
        p.entry_zone_high,
        p.tp_zone_low,
        p.tp_zone_high,
        p.invalidation_price
    FROM latest_advice la
    JOIN paper_advice_observation p
      ON p.asset_id = la.asset_id
     AND p.asof_ts_utc = la.asof_ts_utc
     AND p.venue = %(venue)s
     AND p.interval_code = %(interval_code)s
    WHERE p.symbol IN ({', '.join(placeholders)})
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    return {str(row["symbol"]).upper(): row for row in rows}


def _field_mismatches(
    *,
    zone: dict[str, Any] | None,
    advice: dict[str, Any] | None,
    coverage: StructuralZoneCoverageRow,
) -> list[str]:
    mismatches: list[str] = []
    if coverage.coverage_state not in {"STRUCTURAL_MAP_READY", "STRUCTURAL_MAP_STALE"}:
        mismatches.append(f"structural_coverage:{coverage.coverage_state}")
    if zone is None:
        mismatches.append("zone:execution_zone_context")
    if advice is None:
        mismatches.append("paper_advice_observation")
        return mismatches

    if zone is not None and _zone_newer_than_advice(zone.get("asof_ts_utc"), advice.get("asof_ts_utc")):
        mismatches.append("paper_advice_stale_vs_zone")

    zone_leg = _norm(None if zone is None else zone.get("leg_direction"))
    advice_leg = _norm(advice.get("leg_direction"))
    if zone_leg in {"UP", "DOWN"} and advice_leg not in {"UP", "DOWN"}:
        mismatches.append("advice:leg_direction")
    elif zone_leg in {"UP", "DOWN"} and advice_leg in {"UP", "DOWN"} and zone_leg != advice_leg:
        mismatches.append("leg_direction_mismatch")

    if zone is not None and _has_zone(zone.get("entry_zone_low"), zone.get("entry_zone_high")) and not _has_zone(
        advice.get("entry_zone_low"), advice.get("entry_zone_high")
    ):
        mismatches.append("advice:entry_zone")
    if zone is not None and _has_zone(zone.get("tp_zone_low"), zone.get("tp_zone_high")) and not _has_zone(
        advice.get("tp_zone_low"), advice.get("tp_zone_high")
    ):
        mismatches.append("advice:target_zone")
    if zone is not None and _has_value(zone.get("invalidation_price")) and not _has_value(advice.get("invalidation_price")):
        mismatches.append("advice:invalidation_price")

    return mismatches


def _classify_consistency(
    *,
    zone: dict[str, Any] | None,
    advice: dict[str, Any] | None,
    coverage_state: str,
    mismatches: list[str],
) -> tuple[str, str]:
    if coverage_state in {"PRICE_DATA_MISSING", "LTF_DATA_MISSING"}:
        return "INSUFFICIENT_DATA", "SKIP_INSUFFICIENT_DATA"
    if zone is None and advice is None:
        return "ZONE_MISSING_ADVICE_MISSING", "REFRESH_ZONE_AND_ADVICE_FOR_ASSET"
    if zone is None:
        return "ZONE_MISSING_ADVICE_MISSING", "REFRESH_ZONE_AND_ADVICE_FOR_ASSET"
    if advice is None and coverage_state in {"STRUCTURAL_MAP_READY", "STRUCTURAL_MAP_STALE"}:
        return "ZONE_READY_ADVICE_MISSING", "REFRESH_PAPER_ADVICE_FOR_ASSET"
    if advice is None:
        return "INSUFFICIENT_DATA", "SKIP_INSUFFICIENT_DATA"
    if "paper_advice_stale_vs_zone" in mismatches:
        return "PAPER_ADVICE_STALE_VS_ZONE", "REFRESH_PAPER_ADVICE_FOR_ASSET"
    if any(field.startswith("advice:") for field in mismatches):
        return "PAPER_ADVICE_MISSING_STRUCTURAL_FIELDS", "REFRESH_PAPER_ADVICE_FOR_ASSET"
    if "leg_direction_mismatch" in mismatches:
        return "ASSET_INTERVAL_MISMATCH", "CHECK_ASSET_INTERVAL_JOIN"
    if coverage_state not in {"STRUCTURAL_MAP_READY", "STRUCTURAL_MAP_STALE"}:
        return "ZONE_MISSING_ADVICE_MISSING", "REFRESH_ZONE_AND_ADVICE_FOR_ASSET"
    return "CONSISTENT", "NO_ACTION"


def build_consistency_rows(
    conn: Any,
    *,
    venue: str = DEFAULT_VENUE,
    quote_currency: str = DEFAULT_QUOTE,
    interval_code: str = DEFAULT_INTERVAL,
    symbols: list[str] | set[str] | tuple[str, ...] | None = None,
) -> list[PaperAdviceStructuralConsistencyRow]:
    coverage_rows = build_coverage_rows(
        conn,
        venue=venue,
        quote_currency=quote_currency,
        structural_interval_code=interval_code,
        symbols=symbols,
    )
    coverage_by_symbol = {row.symbol.upper(): row for row in coverage_rows}
    all_symbols = set(coverage_by_symbol)
    zones = fetch_latest_zones(
        conn,
        venue=venue,
        interval_code=interval_code,
        symbols=all_symbols,
    )
    advice = fetch_latest_paper_advice(
        conn,
        venue=venue,
        interval_code=interval_code,
        symbols=all_symbols,
    )

    rows: list[PaperAdviceStructuralConsistencyRow] = []
    for symbol in sorted(all_symbols):
        coverage = coverage_by_symbol[symbol]
        zone = zones.get(symbol)
        advice_row = advice.get(symbol)
        mismatches = _field_mismatches(zone=zone, advice=advice_row, coverage=coverage)
        consistency_state, recommended_action = _classify_consistency(
            zone=zone,
            advice=advice_row,
            coverage_state=coverage.coverage_state,
            mismatches=mismatches,
        )
        severity = None if advice_row is None else calibrate_paper_advice_severity(advice_row)

        rows.append(
            PaperAdviceStructuralConsistencyRow(
                symbol=symbol,
                asset_id=coverage.asset_id,
                venue=venue,
                interval_code=interval_code,
                zone_asof_ts_utc=_fmt_ts(None if zone is None else zone.get("asof_ts_utc")),
                paper_advice_asof_ts_utc=_fmt_ts(None if advice_row is None else advice_row.get("asof_ts_utc")),
                zone_has_leg_direction=bool(zone and _norm(zone.get("leg_direction")) in {"UP", "DOWN"}),
                zone_leg_direction=None if zone is None else (_norm(zone.get("leg_direction")) or None),
                advice_leg_direction=None if advice_row is None else (_norm(advice_row.get("leg_direction")) or None),
                zone_has_entry_zone=bool(zone and _has_zone(zone.get("entry_zone_low"), zone.get("entry_zone_high"))),
                advice_has_entry_zone=bool(
                    advice_row and _has_zone(advice_row.get("entry_zone_low"), advice_row.get("entry_zone_high"))
                ),
                zone_has_target_zone=bool(zone and _has_zone(zone.get("tp_zone_low"), zone.get("tp_zone_high"))),
                advice_has_target_zone=bool(
                    advice_row and _has_zone(advice_row.get("tp_zone_low"), advice_row.get("tp_zone_high"))
                ),
                zone_has_invalidation_price=bool(zone and _has_value(zone.get("invalidation_price"))),
                advice_has_invalidation_price=bool(advice_row and _has_value(advice_row.get("invalidation_price"))),
                price_snapshot_freshness=coverage.price_snapshot_freshness,
                ltf_candle_freshness=coverage.ltf_candle_freshness,
                structural_coverage_state=coverage.coverage_state,
                paper_advice_state=None if advice_row is None else str(advice_row.get("advice_state") or ""),
                advice_action=None if advice_row is None else str(advice_row.get("advice_action") or ""),
                advice_severity=None if severity is None else severity.advice_severity,
                advice_substate=None if severity is None else severity.advice_substate,
                consistency_state=consistency_state,
                mismatch_fields=",".join(mismatches),
                recommended_action=recommended_action,
            )
        )
    return rows


def render_table(rows: list[PaperAdviceStructuralConsistencyRow]) -> str:
    lines = [
        f"report={REPORT_NAME} version={VERSION}",
        "scope=read-only paper-advice-structural-consistency-audit",
        "input=asset execution_zone_context paper_advice_observation market_price_snapshot obs_market_candle",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        "selection_engine=none decision_gate=none execution_planner=none executor=none",
        "",
        "symbol | consistency_state | mismatch_fields | zone_asof | advice_asof | zone_leg | advice_leg | coverage | advice_state | action | severity | recommended_action",
        "-------+-------------------+-----------------+-----------+-------------+----------+------------+----------+--------------+--------+----------+-------------------",
    ]
    for row in rows:
        severity = "/".join(part for part in [row.advice_severity, row.advice_substate] if part)
        lines.append(
            " | ".join(
                [
                    row.symbol,
                    row.consistency_state,
                    row.mismatch_fields,
                    row.zone_asof_ts_utc or "",
                    row.paper_advice_asof_ts_utc or "",
                    row.zone_leg_direction or "",
                    row.advice_leg_direction or "",
                    row.structural_coverage_state,
                    row.paper_advice_state or "",
                    row.advice_action or "",
                    severity,
                    row.recommended_action,
                ]
            )
        )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit paper advice structural field consistency against latest 4h zone context."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    conn = get_connection()
    try:
        rows = build_consistency_rows(
            conn,
            venue=str(args.venue),
            quote_currency=str(args.quote),
            interval_code=str(args.interval),
            symbols=args.symbols,
        )
        conn.rollback()
    finally:
        conn.close()

    if args.output == "json":
        print(json.dumps([asdict(row) for row in rows], indent=2, default=_json_default))
    else:
        print(render_table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
