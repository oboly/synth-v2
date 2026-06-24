from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.market_context.breath_curve_core_v1 import MARKERS, parse_dt
from src.market_context.breath_curve_live_v1 import (
    BTC_SYMBOL,
    BreathCurveLiveCandle,
    build_breath_curve_live_by_symbol,
)


REPORT_NAME = "breath_curve_historical_replay_validation_v1"
VERSION = "0.1"
DEFAULT_TARGETS = (
    "2026-05-15T12:44:48Z",
    "2026-05-16T01:15:11Z",
)
LOOKBACK_DAYS = 180


@dataclass(frozen=True)
class ReferenceRow:
    symbol: str
    as_of_ts_utc: str
    anchor_ts_utc: str | None
    checkpoint_ratio: float | None
    selected_partial_offset_days: float | None
    future_target_expected_ts_utc: str | None
    source_row_json: dict[str, Any]


def _parse_targets(raw_values: list[str]) -> list[datetime]:
    return [parse_dt(value) for value in raw_values]


def _fmt_ts(ts: datetime) -> str:
    return ts.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _checkpoint_ratio_by_code() -> dict[str, float]:
    return {code: ratio for ratio, code, _kind in MARKERS}


def _load_reference_rows(targets: list[datetime]) -> dict[str, dict[str, list[ReferenceRow]]]:
    target_text = [_fmt_ts(target) for target in targets]
    placeholders = ",".join(["%s"] * len(target_text))
    query = f"""
        SELECT
            x.symbol,
            x.anchor_date,
            x.checkpoint_ratio,
            x.selected_partial_offset_days,
            x.source_row_json
        FROM research_breath_curve_policy_result x
        JOIN research_breath_curve_policy_run r
          ON r.research_breath_curve_policy_run_id = x.research_breath_curve_policy_run_id
        WHERE r.source_name = 'breath_curve_partial_to_full_v1'
          AND JSON_UNQUOTE(JSON_EXTRACT(x.source_row_json, '$.as_of_ts_utc')) IN ({placeholders})
        ORDER BY x.symbol ASC, x.anchor_date ASC, x.checkpoint_ratio ASC
    """
    out: dict[str, dict[str, list[ReferenceRow]]] = defaultdict(lambda: defaultdict(list))
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, tuple(target_text))
            rows = list(cur.fetchall())
    finally:
        conn.rollback()
        conn.close()

    for row in rows:
        raw_json = row.get("source_row_json")
        parsed_json = json.loads(raw_json) if isinstance(raw_json, str) else dict(raw_json or {})
        as_of_ts_utc = str(parsed_json.get("as_of_ts_utc") or "")
        symbol = str(row.get("symbol") or "").upper()
        out[as_of_ts_utc][symbol].append(
            ReferenceRow(
                symbol=symbol,
                as_of_ts_utc=as_of_ts_utc,
                anchor_ts_utc=parsed_json.get("anchor_ts_utc") or (
                    f"{row['anchor_date'].isoformat()}T00:00:00Z" if row.get("anchor_date") else None
                ),
                checkpoint_ratio=float(row["checkpoint_ratio"]) if row.get("checkpoint_ratio") is not None else None,
                selected_partial_offset_days=(
                    float(row["selected_partial_offset_days"])
                    if row.get("selected_partial_offset_days") is not None
                    else None
                ),
                future_target_expected_ts_utc=parsed_json.get("future_target_expected_ts_utc"),
                source_row_json=parsed_json,
            )
        )
    return out


def _fetch_candles_by_symbol(symbols: list[str], *, as_of_ts_utc: datetime) -> dict[str, list[BreathCurveLiveCandle]]:
    scoped_symbols = sorted(set([symbol.upper() for symbol in symbols if symbol] + [BTC_SYMBOL]))
    since_utc = as_of_ts_utc - timedelta(days=LOOKBACK_DAYS)
    placeholders = ",".join(["%s"] * len(scoped_symbols))
    query = f"""
        SELECT
            a.symbol,
            c.close_ts_utc,
            c.open_price,
            c.high_price,
            c.low_price,
            c.close_price
        FROM obs_market_candle c
        JOIN asset a
          ON a.asset_id = c.asset_id
        WHERE c.venue = %s
          AND c.interval_code = %s
          AND a.symbol IN ({placeholders})
          AND c.close_ts_utc >= %s
          AND c.close_ts_utc <= %s
        ORDER BY a.symbol ASC, c.close_ts_utc ASC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                query,
                ("bitvavo", "1d", *scoped_symbols, since_utc, as_of_ts_utc),
            )
            rows = list(cur.fetchall())
    finally:
        conn.rollback()
        conn.close()

    out: dict[str, list[BreathCurveLiveCandle]] = {symbol: [] for symbol in scoped_symbols}
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        close_ts = row.get("close_ts_utc")
        if close_ts is None or symbol not in out:
            continue
        close_ts_utc = close_ts.replace(tzinfo=UTC) if close_ts.tzinfo is None else close_ts.astimezone(UTC)
        open_price = _parse_decimal(row.get("open_price"))
        high_price = _parse_decimal(row.get("high_price"))
        low_price = _parse_decimal(row.get("low_price"))
        close_price = _parse_decimal(row.get("close_price"))
        if open_price is None or high_price is None or low_price is None or close_price is None:
            continue
        out[symbol].append(
            BreathCurveLiveCandle(
                close_ts_utc=close_ts_utc,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
            )
        )
    return out


def _compare_payload_to_reference(
    payload: dict[str, Any],
    reference_rows: list[ReferenceRow],
) -> dict[str, Any]:
    checkpoint_ratio = _checkpoint_ratio_by_code().get(str(payload.get("current_checkpoint") or "").upper())
    exact_match = False
    matched_reference: ReferenceRow | None = None
    mismatches: list[dict[str, Any]] = []

    for row in reference_rows:
        fields = {
            "anchor_ts_utc": payload.get("anchor_ts_utc") == row.anchor_ts_utc,
            "checkpoint_ratio": checkpoint_ratio == row.checkpoint_ratio,
            "selected_partial_offset_days": payload.get("phase_offset_days") == row.selected_partial_offset_days,
            "future_target_expected_ts_utc": payload.get("next_target_expected_ts_utc") == row.future_target_expected_ts_utc,
        }
        if all(fields.values()):
            exact_match = True
            matched_reference = row
            break
        mismatches.append(
            {
                "reference_anchor_ts_utc": row.anchor_ts_utc,
                "reference_checkpoint_ratio": row.checkpoint_ratio,
                "reference_selected_partial_offset_days": row.selected_partial_offset_days,
                "reference_future_target_expected_ts_utc": row.future_target_expected_ts_utc,
                "field_match": fields,
            }
        )

    return {
        "exact_match": exact_match,
        "matched_reference": asdict(matched_reference) if matched_reference else None,
        "mismatches": mismatches,
    }


def build_validation_report(targets: list[datetime]) -> dict[str, Any]:
    reference_by_asof = _load_reference_rows(targets)
    report_rows: list[dict[str, Any]] = []

    for target in targets:
        as_of_text = _fmt_ts(target)
        reference_rows_by_symbol = reference_by_asof.get(as_of_text, {})
        symbols = sorted(reference_rows_by_symbol.keys())
        candles_by_symbol = _fetch_candles_by_symbol(symbols, as_of_ts_utc=target) if symbols else {}
        payload_by_symbol = (
            build_breath_curve_live_by_symbol(
                candles_by_symbol=candles_by_symbol,
                as_of_ts_utc=target,
                symbols=symbols,
            )
            if symbols
            else {}
        )

        if not symbols:
            report_rows.append(
                {
                    "as_of_ts_utc": as_of_text,
                    "validated_availability_state": "UNAVAILABLE",
                    "warning": "REFERENCE_ARTIFACT_NOT_FOUND",
                    "rows": [],
                }
            )
            continue

        symbol_rows: list[dict[str, Any]] = []
        any_exact_match = False
        for symbol in symbols:
            payload = payload_by_symbol.get(symbol) or {}
            reference_rows = reference_rows_by_symbol.get(symbol, [])
            comparison = _compare_payload_to_reference(payload, reference_rows)
            exact_match = bool(comparison["exact_match"])
            any_exact_match = any_exact_match or exact_match
            symbol_rows.append(
                {
                    "symbol": symbol,
                    "provider_availability_state": payload.get("availability_state"),
                    "validated_availability_state": "AVAILABLE" if exact_match else "UNAVAILABLE",
                    "resolved_anchor_ts_utc": payload.get("anchor_ts_utc"),
                    "selected_phase_offset_days": payload.get("phase_offset_days"),
                    "current_checkpoint": payload.get("current_checkpoint"),
                    "next_checkpoint": payload.get("next_checkpoint"),
                    "next_target_expected_ts_utc": payload.get("next_target_expected_ts_utc"),
                    "resolver_candidate_count": payload.get("resolver_candidate_count"),
                    "reference_rows": [asdict(row) for row in reference_rows],
                    "comparison": comparison,
                }
            )

        report_rows.append(
            {
                "as_of_ts_utc": as_of_text,
                "validated_availability_state": "AVAILABLE" if any_exact_match else "UNAVAILABLE",
                "warning": None if any_exact_match else "REFERENCE_OUTPUT_NOT_REPRODUCED",
                "rows": symbol_rows,
            }
        )

    return {
        "report_name": REPORT_NAME,
        "version": VERSION,
        "targets": [_fmt_ts(target) for target in targets],
        "rows": report_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only historical replay validation for the live Breath Curve resolver.")
    parser.add_argument(
        "--target",
        action="append",
        dest="targets",
        help="Exact historical as-of timestamp to validate. May be repeated.",
    )
    args = parser.parse_args()

    targets = _parse_targets(args.targets or list(DEFAULT_TARGETS))
    print(json.dumps(build_validation_report(targets), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
