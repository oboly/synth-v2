from __future__ import annotations

import argparse
import csv
import json
from bisect import bisect_right
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from types import SimpleNamespace
from typing import Any

from src.common.db import get_connection
from src.reporting.run_position_rotation_static_dashboard_v1 import lifecycle_preview_state
from src.research.run_position_rotation_preview_v1 import (
    classify_position_lifecycle,
    classify_rotation,
    dec,
    risk_state_for_advice,
    target_state_for_advice,
)
from src.reporting.intrabar_lifecycle_context_v1 import _intrabar_target_touch_overlay


REPORT_NAME = "position_lifecycle_outcome_validation_v1"
REPORT_VERSION = "1.0"

DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE = "EUR"
DEFAULT_INTERVAL = "4h"
DEFAULT_TRADING_ACCOUNT_ID = 2
DEFAULT_MAX_EVENTS = 1000
DEFAULT_EVENT_MODE = "all"
DEFAULT_COOLDOWN_MINUTES = 30
DEFAULT_MIN_BUCKET_COUNT = 20
DEFAULT_OUTPUT_DIR = Path("data/research/position_lifecycle_outcome_validation_v1")

OUTPUT_ROWS = "outcome_rows_v1.jsonl"
OUTPUT_SUMMARY = "outcome_summary_v1.json"
OUTPUT_MANIFEST = "manifest_v1.json"
OUTPUT_BUCKET_ACTION_REASON_CSV = "bucket_summary_by_action_reason_v1.csv"
OUTPUT_BUCKET_SYMBOL_CSV = "bucket_summary_by_symbol_v1.csv"
OUTPUT_BUCKET_ACTION_REASON_ADJUSTED_CSV = "bucket_summary_by_action_reason_adjusted_v1.csv"
OUTPUT_BUCKET_SYMBOL_ADJUSTED_CSV = "bucket_summary_by_symbol_adjusted_v1.csv"
OUTPUT_PROMOTION_CANDIDATES_CSV = "lifecycle_bucket_promotion_candidates_v1.csv"
OUTPUT_PROMOTION_CANDIDATES_JSON = "lifecycle_bucket_promotion_candidates_v1.json"

EVENT_MODES = ("all", "transition-only", "cooldown")
HORIZON_LABELS: list[tuple[str, timedelta]] = [
    ("15m", timedelta(minutes=15)),
    ("30m", timedelta(minutes=30)),
    ("1h", timedelta(hours=1)),
    ("2h", timedelta(hours=2)),
    ("4h", timedelta(hours=4)),
    ("8h", timedelta(hours=8)),
    ("24h", timedelta(hours=24)),
]
MAX_HORIZON = HORIZON_LABELS[-1][1]
INTRABAR_DECISION_FRESH_AFTER = timedelta(minutes=5)
REDUCE_ACTIONS = {"TRIM_REVIEW", "REDUCE_REVIEW"}
LONG_ACTIONS = {"HOLD", "RELOAD_REVIEW"}
NEUTRAL_ACTIONS = {"NO_POSITION_LIFECYCLE_EDGE"}


@dataclass(frozen=True)
class PositionSnapshotRow:
    event_ts_utc: datetime
    trading_account_id: int
    asset_id: int
    symbol: str
    venue: str
    quantity_base: Decimal | None
    average_entry_price_eur: Decimal | None
    mark_price_eur: Decimal | None
    position_value_eur: Decimal | None
    source_name: str | None


@dataclass(frozen=True)
class PricePoint:
    observed_ts_utc: datetime
    price: Decimal


@dataclass(frozen=True)
class Candle:
    close_ts_utc: datetime
    close_price: Decimal
    high_price: Decimal
    low_price: Decimal


@dataclass(frozen=True)
class LifecycleEvent:
    event_ts_utc: datetime
    symbol: str
    venue: str
    quote: str
    interval: str
    trading_account_id: int
    position_lifecycle_action: str
    position_lifecycle_reason: str
    paper_action: str | None
    policy_action: str | None
    position_review_state: str | None
    selection_state: str | None
    setup_filter_state: str | None
    setup_fail_reason: str | None
    aplus_bucket: str | None
    advice_reason_codes: list[str]
    leg_direction: str | None
    target_state: str
    risk_state: str
    current_price: Decimal | None
    current_price_source: str
    position_qty: Decimal | None
    position_value: Decimal | None
    average_entry_price_eur: Decimal | None
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    tp_zone_low: Decimal | None
    tp_zone_high: Decimal | None
    invalidation_price: Decimal | None
    source_modules: list[str]
    missing_inputs: list[str]
    transition_from_action: str | None
    transition_changed: bool
    intrabar_target_touch_label: str | None
    intrabar_target_touch_context: str | None
    intrabar_target_touch_age_minutes: Decimal | None
    intrabar_stale_for_decision: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate position lifecycle review labels against forward outcomes "
            "(research-only, account-aware read-only, no executor)."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--trading-account-id", type=int, default=DEFAULT_TRADING_ACCOUNT_ID)
    parser.add_argument("--max-events", type=int, default=DEFAULT_MAX_EVENTS)
    parser.add_argument("--event-mode", choices=EVENT_MODES, default=DEFAULT_EVENT_MODE)
    parser.add_argument("--cooldown-minutes", type=int, default=DEFAULT_COOLDOWN_MINUTES)
    parser.add_argument("--min-bucket-count", type=int, default=DEFAULT_MIN_BUCKET_COUNT)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def parse_ts(value: Any) -> datetime:
    text = str(value or "").strip()
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def fmt_ts(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return fmt_ts(value)
    return value


def average_or_none(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def median_or_none(values: list[float]) -> float | None:
    return round(float(median(values)), 6) if values else None


def increment_count(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def dec_to_float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def pct_return(base_price: Decimal | None, future_price: Decimal | None) -> Decimal | None:
    if base_price is None or future_price is None or base_price <= 0:
        return None
    return ((future_price / base_price) - Decimal("1")) * Decimal("100")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=json_default) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True, default=json_default) + "\n")


def table_exists(conn: Any, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES LIKE %s", (table_name,))
        return cur.fetchone() is not None


def table_columns(conn: Any, table_name: str) -> list[str]:
    if not table_exists(conn, table_name):
        return []
    with conn.cursor() as cur:
        cur.execute(f"SHOW COLUMNS FROM {table_name}")
        return [str(row["Field"]) for row in cur.fetchall()]


def table_coverage(conn: Any, *, table_name: str, ts_col: str, where_sql: str = "", params: tuple[Any, ...] = ()) -> dict[str, Any]:
    if not table_exists(conn, table_name):
        return {"table": table_name, "exists": False}
    sql = f"SELECT COUNT(*) AS row_count, MIN({ts_col}) AS min_ts, MAX({ts_col}) AS max_ts, COUNT(DISTINCT {ts_col}) AS distinct_ts FROM {table_name} {where_sql}"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone() or {}
    return {
        "table": table_name,
        "exists": True,
        "row_count": int(row.get("row_count") or 0),
        "min_ts": fmt_ts(row.get("min_ts")),
        "max_ts": fmt_ts(row.get("max_ts")),
        "distinct_ts": int(row.get("distinct_ts") or 0),
    }


def build_data_availability_audit(conn: Any, *, venue: str, quote: str, interval: str, trading_account_id: int) -> dict[str, Any]:
    audit: dict[str, Any] = {
        "status": "ok",
        "warnings": [],
        "blockers": [],
        "reconstruction_mode": "paper_advice_history_plus_position_snapshots_plus_15m_candles",
        "stored_lifecycle_history_available": False,
    }
    audit["account_position_snapshot"] = table_coverage(
        conn,
        table_name="account_position_snapshot",
        ts_col="snapshot_ts_utc",
        where_sql="WHERE trading_account_id = %s",
        params=(int(trading_account_id),),
    )
    audit["market_price_snapshot"] = table_coverage(
        conn,
        table_name="market_price_snapshot",
        ts_col="observed_ts_utc",
        where_sql="WHERE venue = %s AND quote_currency = %s",
        params=(venue, quote.upper()),
    )
    audit["paper_advice_observation"] = table_coverage(
        conn,
        table_name="paper_advice_observation",
        ts_col="asof_ts_utc",
        where_sql="WHERE venue = %s AND interval_code = %s",
        params=(venue, interval),
    )
    audit["execution_zone_context"] = table_coverage(
        conn,
        table_name="execution_zone_context",
        ts_col="asof_ts_utc",
        where_sql="WHERE venue = %s AND interval_code = %s",
        params=(venue, interval),
    )
    audit["obs_market_candle_15m"] = table_coverage(
        conn,
        table_name="obs_market_candle",
        ts_col="close_ts_utc",
        where_sql="WHERE venue = %s AND interval_code = '15m'",
        params=(venue,),
    )
    audit["obs_market_candle_30m"] = table_coverage(
        conn,
        table_name="obs_market_candle",
        ts_col="close_ts_utc",
        where_sql="WHERE venue = %s AND interval_code = '30m'",
        params=(venue,),
    )
    audit["position_rotation_history_tables"] = []
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES LIKE 'position_rotation%'")
        audit["position_rotation_history_tables"] = [list(row.values())[0] for row in cur.fetchall()]

    advice_cols = set(table_columns(conn, "paper_advice_observation"))
    required_advice_cols = {
        "symbol",
        "asset_id",
        "venue",
        "interval_code",
        "asof_ts_utc",
        "leg_direction",
        "entry_zone_low",
        "entry_zone_high",
        "tp_zone_low",
        "tp_zone_high",
        "invalidation_price",
        "advice_action",
        "advice_state",
        "selection_state",
        "setup_filter_reason",
    }
    missing_advice_cols = sorted(required_advice_cols - advice_cols)
    if missing_advice_cols:
        audit["blockers"].append(f"paper_advice_observation_missing_columns={','.join(missing_advice_cols)}")

    if audit["account_position_snapshot"]["row_count"] == 0:
        audit["blockers"].append("account_position_snapshot_empty")
    if audit["paper_advice_observation"]["row_count"] == 0:
        audit["blockers"].append("paper_advice_observation_empty")
    if audit["obs_market_candle_15m"]["row_count"] == 0:
        audit["blockers"].append("obs_market_candle_15m_empty")

    if audit["execution_zone_context"]["distinct_ts"] <= 1:
        audit["warnings"].append("execution_zone_context_has_no_reliable_history_using_paper_advice_zone_fields_instead")
    if audit["obs_market_candle_30m"]["row_count"] == 0:
        audit["warnings"].append("obs_market_candle_30m_missing_derived_from_15m")
    if not audit["position_rotation_history_tables"]:
        audit["warnings"].append("no_stored_position_rotation_history_table_reconstructing_events")

    if audit["blockers"]:
        audit["status"] = "blocked"
    elif audit["warnings"]:
        audit["status"] = "warning"
    return audit


def fetch_position_history(conn: Any, *, venue: str, trading_account_id: int) -> list[PositionSnapshotRow]:
    sql = """
    SELECT
        snapshot_ts_utc,
        trading_account_id,
        asset_id,
        symbol,
        venue,
        quantity_base,
        average_entry_price_eur,
        mark_price_eur,
        (quantity_base * mark_price_eur) AS position_value_eur,
        source_name
    FROM account_position_snapshot
    WHERE venue = %(venue)s
      AND trading_account_id = %(trading_account_id)s
      AND quantity_base > 0
    ORDER BY snapshot_ts_utc ASC, symbol ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"venue": venue, "trading_account_id": int(trading_account_id)})
        rows = list(cur.fetchall())
    out: list[PositionSnapshotRow] = []
    for row in rows:
        out.append(
            PositionSnapshotRow(
                event_ts_utc=row["snapshot_ts_utc"].replace(tzinfo=UTC),
                trading_account_id=int(row["trading_account_id"]),
                asset_id=int(row["asset_id"]),
                symbol=str(row["symbol"]).upper(),
                venue=str(row["venue"]),
                quantity_base=dec(row.get("quantity_base")),
                average_entry_price_eur=dec(row.get("average_entry_price_eur")),
                mark_price_eur=dec(row.get("mark_price_eur")),
                position_value_eur=dec(row.get("position_value_eur")),
                source_name=row.get("source_name"),
            )
        )
    return out


def fetch_historical_advice(conn: Any, *, venue: str, interval: str, symbols: set[str]) -> dict[str, list[dict[str, Any]]]:
    if not symbols:
        return {}
    params: dict[str, Any] = {"venue": venue, "interval": interval}
    placeholders: list[str] = []
    for idx, symbol in enumerate(sorted(symbols)):
        key = f"symbol_{idx}"
        params[key] = symbol
        placeholders.append(f"%({key})s")
    sql = f"""
    SELECT
        paper_advice_observation_id,
        asset_id,
        symbol,
        venue,
        interval_code,
        asof_ts_utc,
        selection_state,
        selection_score,
        priority_rank,
        setup_filter_state,
        setup_filter_reason,
        aplus_bucket,
        policy_decision,
        advice_state,
        advice_action,
        leg_direction,
        entry_zone_low,
        entry_zone_high,
        tp_zone_low,
        tp_zone_high,
        invalidation_price,
        reason_codes_json
    FROM paper_advice_observation
    WHERE venue = %(venue)s
      AND interval_code = %(interval)s
      AND symbol IN ({', '.join(placeholders)})
    ORDER BY symbol ASC, asof_ts_utc ASC, paper_advice_observation_id ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        symbol = str(row["symbol"]).upper()
        normalized = dict(row)
        if normalized.get("asof_ts_utc") is not None:
            normalized["asof_ts_utc"] = normalized["asof_ts_utc"].replace(tzinfo=UTC)
        out.setdefault(symbol, []).append(normalized)
    return out


def fetch_price_history(
    conn: Any,
    *,
    venue: str,
    quote: str,
    symbols: set[str],
    from_ts: datetime,
    to_ts: datetime,
) -> dict[str, list[PricePoint]]:
    if not symbols:
        return {}
    params: dict[str, Any] = {"venue": venue, "quote": quote.upper(), "from_ts": from_ts, "to_ts": to_ts}
    placeholders: list[str] = []
    for idx, symbol in enumerate(sorted(symbols)):
        key = f"symbol_{idx}"
        params[key] = symbol
        placeholders.append(f"%({key})s")
    sql = f"""
    SELECT symbol, observed_ts_utc, price
    FROM market_price_snapshot
    WHERE venue = %(venue)s
      AND quote_currency = %(quote)s
      AND observed_ts_utc >= %(from_ts)s
      AND observed_ts_utc <= %(to_ts)s
      AND symbol IN ({', '.join(placeholders)})
    ORDER BY symbol ASC, observed_ts_utc ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    out: dict[str, list[PricePoint]] = {}
    for row in rows:
        out.setdefault(str(row["symbol"]).upper(), []).append(
            PricePoint(
                observed_ts_utc=row["observed_ts_utc"].replace(tzinfo=UTC),
                price=dec(row["price"]) or Decimal("0"),
            )
        )
    return out


def fetch_15m_candle_history(
    conn: Any,
    *,
    venue: str,
    symbols: set[str],
    from_ts: datetime,
    to_ts: datetime,
) -> dict[str, list[Candle]]:
    if not symbols:
        return {}
    params: dict[str, Any] = {"venue": venue, "from_ts": from_ts, "to_ts": to_ts}
    placeholders: list[str] = []
    for idx, symbol in enumerate(sorted(symbols)):
        key = f"symbol_{idx}"
        params[key] = symbol
        placeholders.append(f"%({key})s")
    sql = f"""
    SELECT a.symbol, c.close_ts_utc, c.close_price, c.high_price, c.low_price
    FROM obs_market_candle c
    JOIN asset a
      ON a.asset_id = c.asset_id
    WHERE c.venue = %(venue)s
      AND c.interval_code = '15m'
      AND c.close_ts_utc >= %(from_ts)s
      AND c.close_ts_utc <= %(to_ts)s
      AND a.symbol IN ({', '.join(placeholders)})
    ORDER BY a.symbol ASC, c.close_ts_utc ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    out: dict[str, list[Candle]] = {}
    for row in rows:
        out.setdefault(str(row["symbol"]).upper(), []).append(
            Candle(
                close_ts_utc=row["close_ts_utc"].replace(tzinfo=UTC),
                close_price=dec(row["close_price"]) or Decimal("0"),
                high_price=dec(row["high_price"]) or Decimal("0"),
                low_price=dec(row["low_price"]) or Decimal("0"),
            )
        )
    return out


def latest_row_at_or_before(rows: list[Any], ts_values: list[datetime], event_ts: datetime) -> Any | None:
    idx = bisect_right(ts_values, event_ts) - 1
    if idx < 0:
        return None
    return rows[idx]


def current_price_for_event(
    *,
    position: PositionSnapshotRow,
    price_history_by_symbol: dict[str, list[PricePoint]],
) -> tuple[Decimal | None, str]:
    rows = price_history_by_symbol.get(position.symbol, [])
    if rows:
        ts_values = [row.observed_ts_utc for row in rows]
        item = latest_row_at_or_before(rows, ts_values, position.event_ts_utc)
        if item is not None and item.observed_ts_utc >= position.event_ts_utc - timedelta(minutes=15):
            return item.price, "market_price_snapshot"
    if position.mark_price_eur is not None:
        return position.mark_price_eur, "account_position_snapshot.mark_price_eur"
    return None, "missing"


def intrabar_overlay_for_event(
    *,
    event_ts_utc: datetime,
    advice_row: dict[str, Any] | None,
    current_price: Decimal | None,
    candles_by_symbol: dict[str, list[Candle]],
    symbol: str,
) -> SimpleNamespace | None:
    if advice_row is None:
        return None
    candles = candles_by_symbol.get(symbol, [])
    if not candles:
        return None
    ts_values = [c.close_ts_utc for c in candles]
    latest_candle = latest_row_at_or_before(candles, ts_values, event_ts_utc)
    if latest_candle is None:
        return None
    touch_label, touch_context, touched_value, touch_age_minutes = _intrabar_target_touch_overlay(
        leg_direction=advice_row.get("leg_direction"),
        current_price=current_price,
        tp_zone_low=dec(advice_row.get("tp_zone_low")),
        tp_zone_high=dec(advice_row.get("tp_zone_high")),
        latest_15m_high=latest_candle.high_price,
        latest_15m_low=latest_candle.low_price,
        latest_15m_close_ts=latest_candle.close_ts_utc.replace(tzinfo=None),
        now_utc=event_ts_utc,
    )
    intrabar_lifecycle_state = "INTRABAR_ACTIVE"
    if touch_context == "TARGET_TOUCHED_RECENTLY":
        intrabar_lifecycle_state = "TARGET_TOUCHED_RECENTLY"
    data_quality_state = "LTF_CANDLES_FRESH"
    if touch_age_minutes is not None and touch_age_minutes > Decimal(str(INTRABAR_DECISION_FRESH_AFTER.total_seconds() / 60)):
        data_quality_state = "LTF_CANDLES_FRESH;STALE_FOR_INTRABAR_DECISION"
    return SimpleNamespace(
        intrabar_lifecycle_state=intrabar_lifecycle_state,
        target_touch_label=touch_label,
        target_touch_context_label=touch_context,
        touched_high_or_low=touched_value,
        target_touch_age_minutes=touch_age_minutes,
        data_quality_state=data_quality_state,
    )


def reconstruct_events(
    *,
    positions: list[PositionSnapshotRow],
    advice_history_by_symbol: dict[str, list[dict[str, Any]]],
    price_history_by_symbol: dict[str, list[PricePoint]],
    candles_by_symbol: dict[str, list[Candle]],
    quote: str,
    interval: str,
) -> tuple[list[LifecycleEvent], dict[str, int]]:
    events: list[LifecycleEvent] = []
    skip_counts: dict[str, int] = {}
    previous_action_by_symbol: dict[str, str] = {}

    advice_ts_cache: dict[str, list[datetime]] = {
        symbol: [row["asof_ts_utc"] for row in rows]
        for symbol, rows in advice_history_by_symbol.items()
    }

    for position in positions:
        advice_rows = advice_history_by_symbol.get(position.symbol, [])
        advice_ts_values = advice_ts_cache.get(position.symbol, [])
        advice_row = latest_row_at_or_before(advice_rows, advice_ts_values, position.event_ts_utc)
        if advice_row is None:
            increment_count(skip_counts, "missing_historical_paper_advice")
            continue

        current_price, current_price_source = current_price_for_event(
            position=position,
            price_history_by_symbol=price_history_by_symbol,
        )
        target_state = target_state_for_advice(advice_row, current_price)
        risk_state = risk_state_for_advice(advice_row, current_price)
        position_payload = {
            "quantity_base": position.quantity_base,
            "average_entry_price_eur": position.average_entry_price_eur,
        }
        base_action, base_reason, base_source_modules, base_missing_inputs, price_vs_entry_pct, target_distance_pct, invalidation_distance_pct = classify_position_lifecycle(
            position_row=position_payload,
            advice_row=advice_row,
            position_source_state="FRESH",
            current_price=current_price,
            target_state=target_state,
            risk_state=risk_state,
        )
        rotation_state, _, _ = classify_rotation(
            position_row=position_payload,
            advice_row=advice_row,
            position_source_state="FRESH",
            target_state=target_state,
            risk_state=risk_state,
        )

        intrabar_row = intrabar_overlay_for_event(
            event_ts_utc=position.event_ts_utc,
            advice_row=advice_row,
            current_price=current_price,
            candles_by_symbol=candles_by_symbol,
            symbol=position.symbol,
        )
        lifecycle_row = SimpleNamespace(
            position_lifecycle_action=base_action,
            position_lifecycle_reason=base_reason,
            position_lifecycle_source_modules=base_source_modules,
            position_lifecycle_missing_inputs=base_missing_inputs,
            entry_zone_low=dec(advice_row.get("entry_zone_low")),
            entry_zone_high=dec(advice_row.get("entry_zone_high")),
            leg_direction=advice_row.get("leg_direction"),
            position_lifecycle_price_vs_entry_pct=price_vs_entry_pct,
            rotation_state=rotation_state,
        )
        final_action, final_reason, final_source_modules, final_missing_inputs, _ = lifecycle_preview_state(
            row=lifecycle_row,
            current_price=current_price,
            intrabar_row=intrabar_row,
        )

        raw_reason_codes = advice_row.get("reason_codes_json")
        parsed_reason_codes: list[str] = []
        if isinstance(raw_reason_codes, str) and raw_reason_codes.strip():
            try:
                parsed = json.loads(raw_reason_codes)
                if isinstance(parsed, list):
                    parsed_reason_codes = [str(item).upper() for item in parsed if str(item).strip()]
            except Exception:
                parsed_reason_codes = []

        previous_action = previous_action_by_symbol.get(position.symbol)
        transition_changed = previous_action is not None and previous_action != final_action
        events.append(
            LifecycleEvent(
                event_ts_utc=position.event_ts_utc,
                symbol=position.symbol,
                venue=position.venue,
                quote=quote.upper(),
                interval=interval,
                trading_account_id=position.trading_account_id,
                position_lifecycle_action=final_action,
                position_lifecycle_reason=final_reason,
                paper_action=str(advice_row.get("advice_action") or "") or None,
                policy_action=str(advice_row.get("policy_decision") or "") or None,
                position_review_state=rotation_state,
                selection_state=str(advice_row.get("selection_state") or "") or None,
                setup_filter_state=str(advice_row.get("setup_filter_state") or "") or None,
                setup_fail_reason=str(advice_row.get("setup_filter_reason") or "") or None,
                aplus_bucket=str(advice_row.get("aplus_bucket") or "") or None,
                advice_reason_codes=parsed_reason_codes,
                leg_direction=str(advice_row.get("leg_direction") or "") or None,
                target_state=target_state,
                risk_state=risk_state,
                current_price=current_price,
                current_price_source=current_price_source,
                position_qty=position.quantity_base,
                position_value=position.position_value_eur,
                average_entry_price_eur=position.average_entry_price_eur,
                entry_zone_low=dec(advice_row.get("entry_zone_low")),
                entry_zone_high=dec(advice_row.get("entry_zone_high")),
                tp_zone_low=dec(advice_row.get("tp_zone_low")),
                tp_zone_high=dec(advice_row.get("tp_zone_high")),
                invalidation_price=dec(advice_row.get("invalidation_price")),
                source_modules=list(dict.fromkeys(final_source_modules + ([current_price_source] if current_price_source != "missing" else []))),
                missing_inputs=final_missing_inputs,
                transition_from_action=previous_action,
                transition_changed=transition_changed,
                intrabar_target_touch_label=None if intrabar_row is None else intrabar_row.target_touch_label,
                intrabar_target_touch_context=None if intrabar_row is None else intrabar_row.target_touch_context_label,
                intrabar_target_touch_age_minutes=None if intrabar_row is None else intrabar_row.target_touch_age_minutes,
                intrabar_stale_for_decision=False if intrabar_row is None else ("STALE_FOR_INTRABAR_DECISION" in str(intrabar_row.data_quality_state or "")),
            )
        )
        previous_action_by_symbol[position.symbol] = final_action
    return events, skip_counts


def filter_events(events: list[LifecycleEvent], *, event_mode: str, cooldown_minutes: int) -> tuple[list[LifecycleEvent], dict[str, int]]:
    if event_mode == "all":
        return list(events), {}
    skip_counts: dict[str, int] = {}
    filtered: list[LifecycleEvent] = []
    previous_action_by_symbol: dict[str, str] = {}
    next_allowed_by_symbol_action: dict[tuple[str, str], datetime] = {}
    cooldown_delta = timedelta(minutes=cooldown_minutes)
    for event in events:
        if event_mode == "transition-only":
            previous = previous_action_by_symbol.get(event.symbol)
            previous_action_by_symbol[event.symbol] = event.position_lifecycle_action
            if previous is not None and previous == event.position_lifecycle_action:
                increment_count(skip_counts, "skipped_transition_duplicate")
                continue
            filtered.append(event)
            continue
        key = (event.symbol, event.position_lifecycle_action)
        next_allowed = next_allowed_by_symbol_action.get(key)
        if next_allowed is not None and event.event_ts_utc < next_allowed:
            increment_count(skip_counts, "skipped_cooldown")
            continue
        next_allowed_by_symbol_action[key] = event.event_ts_utc + cooldown_delta
        filtered.append(event)
    return filtered, skip_counts


def horizon_outcomes_for_event(event: LifecycleEvent, candles_by_symbol: dict[str, list[Candle]]) -> dict[str, Any]:
    rows = candles_by_symbol.get(event.symbol, [])
    if not rows or event.current_price is None or event.current_price <= 0:
        return {
            "forward_returns": {},
            "sample_completeness_flags": {f"complete_{label}": False for label, _ in HORIZON_LABELS},
            "max_favorable_excursion_pct": None,
            "max_adverse_excursion_pct": None,
            "drawdown_after_event_pct": None,
            "hit_target_like_move": None,
            "broke_invalidation_like_move": None,
        }
    ts_values = [row.close_ts_utc for row in rows]
    base_idx = bisect_right(ts_values, event.event_ts_utc)
    future_rows = rows[base_idx:]
    forward_returns: dict[str, float | None] = {}
    completeness_flags: dict[str, bool] = {}
    horizon_end_rows: list[Candle] = []
    for label, delta in HORIZON_LABELS:
        target_ts = event.event_ts_utc + delta
        idx = bisect_right(ts_values, target_ts - timedelta(microseconds=1))
        if idx >= len(rows):
            forward_returns[label] = None
            completeness_flags[f"complete_{label}"] = False
            continue
        candle = rows[idx]
        if candle.close_ts_utc < target_ts:
            forward_returns[label] = None
            completeness_flags[f"complete_{label}"] = False
            continue
        forward_returns[label] = dec_to_float(pct_return(event.current_price, candle.close_price))
        completeness_flags[f"complete_{label}"] = True
        horizon_end_rows.append(candle)

    horizon_end_ts = None if not horizon_end_rows else max(row.close_ts_utc for row in horizon_end_rows if row is not None)
    path_rows = [row for row in future_rows if horizon_end_ts is not None and row.close_ts_utc <= horizon_end_ts]
    max_high = None if not path_rows else max(row.high_price for row in path_rows)
    min_low = None if not path_rows else min(row.low_price for row in path_rows)
    mfe = pct_return(event.current_price, max_high)
    mae = pct_return(event.current_price, min_low)

    hit_target_like_move: bool | None = None
    if path_rows and event.tp_zone_low is not None:
        path_high = max(row.high_price for row in path_rows)
        path_low = min(row.low_price for row in path_rows)
        if str(event.leg_direction or "").upper() == "DOWN":
            hit_target_like_move = bool(event.tp_zone_high is not None and path_low <= event.tp_zone_high)
        else:
            hit_target_like_move = path_high >= event.tp_zone_low

    broke_invalidation_like_move: bool | None = None
    if path_rows and event.invalidation_price is not None:
        path_high = max(row.high_price for row in path_rows)
        path_low = min(row.low_price for row in path_rows)
        if str(event.leg_direction or "").upper() == "DOWN":
            broke_invalidation_like_move = path_high >= event.invalidation_price
        else:
            broke_invalidation_like_move = path_low <= event.invalidation_price

    return {
        "forward_returns": forward_returns,
        "sample_completeness_flags": completeness_flags,
        "max_favorable_excursion_pct": dec_to_float(mfe),
        "max_adverse_excursion_pct": dec_to_float(mae),
        "drawdown_after_event_pct": dec_to_float(mae),
        "hit_target_like_move": hit_target_like_move,
        "broke_invalidation_like_move": broke_invalidation_like_move,
    }


def truncate_events_for_max(
    events: list[LifecycleEvent],
    *,
    max_events: int | None,
    candles_by_symbol: dict[str, list[Candle]],
) -> list[LifecycleEvent]:
    if not max_events or len(events) <= int(max_events):
        return list(events)
    latest_candle_by_symbol = {
        symbol: rows[-1].close_ts_utc
        for symbol, rows in candles_by_symbol.items()
        if rows
    }
    eligible_complete_24h = [
        event
        for event in events
        if latest_candle_by_symbol.get(event.symbol) is not None
        and latest_candle_by_symbol[event.symbol] >= event.event_ts_utc + MAX_HORIZON
    ]
    if len(eligible_complete_24h) >= int(max_events):
        return eligible_complete_24h[-int(max_events):]
    if eligible_complete_24h:
        return eligible_complete_24h
    return events[: int(max_events)]


def event_to_row(event: LifecycleEvent, outcomes: dict[str, Any]) -> dict[str, Any]:
    row = asdict(event)
    row["event_ts_utc"] = fmt_ts(event.event_ts_utc)
    row["current_price"] = dec_to_float(event.current_price)
    row["position_qty"] = dec_to_float(event.position_qty)
    row["position_value"] = dec_to_float(event.position_value)
    row["average_entry_price_eur"] = dec_to_float(event.average_entry_price_eur)
    row["entry_zone_low"] = dec_to_float(event.entry_zone_low)
    row["entry_zone_high"] = dec_to_float(event.entry_zone_high)
    row["tp_zone_low"] = dec_to_float(event.tp_zone_low)
    row["tp_zone_high"] = dec_to_float(event.tp_zone_high)
    row["invalidation_price"] = dec_to_float(event.invalidation_price)
    row["intrabar_target_touch_age_minutes"] = dec_to_float(event.intrabar_target_touch_age_minutes)
    row.update(outcomes)
    primary_reason_bucket, secondary_reason_buckets = derive_reason_buckets(row)
    row["reason_bucket"] = primary_reason_bucket
    row["secondary_reason_buckets"] = secondary_reason_buckets
    row["market_leg_bucket"] = derive_market_leg_bucket(row)
    row["freshness_bucket"] = derive_freshness_bucket(row)
    row["action_intent_polarity"] = action_intent_polarity(row)
    add_adjusted_metrics(row)
    return row


def values_for_key(rows: list[dict[str, Any]], *, match_key: str, match_value: str, value_key: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        if str(row.get(match_key) or "") != match_value:
            continue
        value = row.get(value_key)
        if isinstance(value, (int, float)):
            out.append(float(value))
    return out


def midpoint(low: float | None, high: float | None) -> float | None:
    if low is not None and high is not None:
        return (low + high) / 2.0
    return low if low is not None else high


def near_zone_pct(current_price: float | None, low: float | None, high: float | None) -> float | None:
    if current_price is None or current_price <= 0:
        return None
    if low is None and high is None:
        return None
    if low is not None and high is not None:
        lo, hi = min(low, high), max(low, high)
        if lo <= current_price <= hi:
            return 0.0
        reference = lo if current_price < lo else hi
        return abs((current_price / reference) - 1.0) * 100.0
    reference = low if low is not None else high
    if reference is None or reference <= 0:
        return None
    return abs((current_price / reference) - 1.0) * 100.0


def has_any_text(*values: str) -> bool:
    return any(str(value or "").strip() for value in values)


def unique_labels(labels: list[str]) -> list[str]:
    return list(dict.fromkeys(label for label in labels if label))


def derive_reason_buckets(row: dict[str, Any]) -> tuple[str, list[str]]:
    intrabar_context = str(row.get("intrabar_target_touch_context") or "").upper()
    intrabar_label = str(row.get("intrabar_target_touch_label") or "").upper()
    reason_text = str(row.get("position_lifecycle_reason") or "").upper()
    risk_state = str(row.get("risk_state") or "").upper()
    target_state = str(row.get("target_state") or "").upper()
    selection_state = str(row.get("selection_state") or "").upper()
    setup_filter_state = str(row.get("setup_filter_state") or "").upper()
    setup_fail_reason = str(row.get("setup_fail_reason") or "").upper()
    policy_action = str(row.get("policy_action") or "").upper()
    paper_action = str(row.get("paper_action") or "").upper()
    aplus_bucket = str(row.get("aplus_bucket") or "").upper()
    leg = str(row.get("leg_direction") or "").upper()
    advice_reason_codes = [str(code or "").upper() for code in (row.get("advice_reason_codes") or [])]
    joined_reason_codes = " ".join(advice_reason_codes)

    current_price = row.get("current_price")
    entry_zone_low = row.get("entry_zone_low")
    entry_zone_high = row.get("entry_zone_high")
    tp_zone_low = row.get("tp_zone_low")
    tp_zone_high = row.get("tp_zone_high")
    secondary: list[str] = []

    if "VERIFY LIVE CHART" in reason_text or (row.get("intrabar_stale_for_decision") and intrabar_label == "EXTENSION_TOUCHED_INTRABAR"):
        secondary.append("TARGET_REACHED_STALE")
    elif target_state == "TARGET_REACHED" and intrabar_label == "EXTENSION_TOUCHED_INTRABAR":
        secondary.append("TARGET_REACHED_FRESH")
    if intrabar_context == "TARGET_TOUCHED_RECENTLY":
        secondary.append("TARGET_TOUCH_INTRABAR")
    if intrabar_label == "EXTENSION_TOUCHED_INTRABAR":
        secondary.append("EXTENSION_TOUCH_INTRABAR")

    if "INVALIDATION_TOUCHED" in reason_text or "INVALIDATION_TOUCHED" in joined_reason_codes:
        secondary.append("INVALIDATION_TOUCHED")
    if "RECLAIM_NEAR" in reason_text or "RECLAIM_NEAR" in joined_reason_codes or paper_action == "WAIT_FOR_MARKET_RECLAIM":
        secondary.append("RECLAIM_NEAR")
    if risk_state == "RECLAIM_CONFIRMED" or "RECLAIM_CONFIRMED" in joined_reason_codes:
        secondary.append("RECLAIM_CONFIRMED")
    if risk_state == "RISK_NEAR":
        secondary.append("INVALIDATION_NEAR")

    if policy_action.startswith("WAIT_") or "WAIT_RECOMPUTE" in paper_action or "WAIT_RECOMPUTE" in reason_text:
        secondary.append("WAIT_RECOMPUTE")
    if "RECOMPUTE" in policy_action or "RECOMPUTE" in reason_text or "MAP_RECOMPUTE_NEEDED" in joined_reason_codes:
        secondary.append("RECOMPUTE_PENDING")

    if "CHASE" in policy_action or "CHASE" in setup_fail_reason or "CHASE" in reason_text or "ENTRY_WINDOW_PASSED" in joined_reason_codes:
        secondary.append("CHASE_RISK")
    if setup_fail_reason == "MARKET_DAMAGE_RISK":
        secondary.append("MARKET_DAMAGE_RISK")
    if setup_fail_reason == "MARKET_DAMAGE_CAUTION":
        secondary.append("MARKET_DAMAGE_CAUTION")
    if setup_fail_reason == "SELECTION_STATE_NOT_ELIGIBLE" or selection_state == "AVOID":
        secondary.append("SELECTION_STATE_NOT_ELIGIBLE")

    if aplus_bucket == "APLUS_AVOID":
        secondary.append("APLUS_AVOID")
    if "STALE_APLUS_CONTEXT" in reason_text or "STALE_APLUS_CONTEXT" in joined_reason_codes:
        secondary.append("STALE_APLUS_CONTEXT")
    if aplus_bucket.startswith("APLUS_") and aplus_bucket != "APLUS_AVOID":
        secondary.append("APLUS_CONTEXT")

    entry_distance = near_zone_pct(current_price, entry_zone_low, entry_zone_high)
    if entry_distance is not None and entry_distance <= 2.0:
        if leg == "DOWN":
            secondary.append("REACTION_ZONE_NEAR")
        else:
            secondary.append("ENTRY_ZONE_NEAR")

    target_mid = midpoint(tp_zone_low, tp_zone_high)
    if (
        leg == "UP"
        and target_state == "TARGET_PENDING"
        and current_price is not None
        and target_mid is not None
        and target_mid < current_price
    ):
        secondary.append("SUPPORT_RETEST_BELOW")

    priority = [
        "TARGET_REACHED_STALE",
        "TARGET_TOUCH_INTRABAR",
        "EXTENSION_TOUCH_INTRABAR",
        "TARGET_REACHED_FRESH",
        "INVALIDATION_TOUCHED",
        "RECLAIM_CONFIRMED",
        "RECLAIM_NEAR",
        "INVALIDATION_NEAR",
        "CHASE_RISK",
        "MARKET_DAMAGE_RISK",
        "MARKET_DAMAGE_CAUTION",
        "WAIT_RECOMPUTE",
        "RECOMPUTE_PENDING",
        "APLUS_AVOID",
        "STALE_APLUS_CONTEXT",
        "APLUS_CONTEXT",
        "SUPPORT_RETEST_BELOW",
        "REACTION_ZONE_NEAR",
        "ENTRY_ZONE_NEAR",
        "SELECTION_STATE_NOT_ELIGIBLE",
    ]
    secondary = unique_labels(secondary)
    for bucket in priority:
        if bucket in secondary:
            return bucket, secondary

    if setup_fail_reason or has_any_text(setup_filter_state):
        secondary.append("SETUP_FAIL")
        return "SETUP_FAIL", unique_labels(secondary)
    return "UNKNOWN_REASON_BUCKET", secondary


def derive_market_leg_bucket(row: dict[str, Any]) -> str:
    leg = str(row.get("leg_direction") or "").upper()
    return leg if leg in {"UP", "DOWN"} else "UNKNOWN"


def derive_freshness_bucket(row: dict[str, Any]) -> str:
    if row.get("intrabar_stale_for_decision"):
        return "STALE"
    if str(row.get("current_price_source") or "").upper() != "MISSING":
        return "FRESH"
    return "UNKNOWN"


def action_intent_polarity(row: dict[str, Any]) -> str:
    action = str(row.get("position_lifecycle_action") or "").upper()
    if action in LONG_ACTIONS:
        return "long_exposure_keep" if action == "HOLD" else "long_exposure_add_or_restore"
    if action in REDUCE_ACTIONS:
        return "reduce_exposure_review"
    return "neutral"


def positive_part(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, value)


def negative_part_magnitude(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, -value)


def adjusted_score_for_action(action: str, forward_return: float | None) -> float | None:
    if forward_return is None:
        return None
    normalized = str(action or "").upper()
    if normalized in LONG_ACTIONS:
        return forward_return
    if normalized in REDUCE_ACTIONS:
        return -forward_return
    return None


def add_adjusted_metrics(row: dict[str, Any]) -> None:
    action = str(row.get("position_lifecycle_action") or "").upper()
    forward_returns = row.get("forward_returns") or {}
    for label, _ in HORIZON_LABELS:
        raw = forward_returns.get(label)
        row[f"adjusted_return_score_{label}"] = adjusted_score_for_action(action, raw)
        if action in REDUCE_ACTIONS:
            row[f"avoided_drawdown_score_{label}"] = negative_part_magnitude(raw)
            row[f"opportunity_cost_{label}"] = positive_part(raw)
            row[f"upside_capture_score_{label}"] = None
            row[f"adverse_move_score_{label}"] = None
        elif action in LONG_ACTIONS:
            row[f"avoided_drawdown_score_{label}"] = None
            row[f"opportunity_cost_{label}"] = None
            row[f"upside_capture_score_{label}"] = positive_part(raw)
            row[f"adverse_move_score_{label}"] = negative_part_magnitude(raw)
        else:
            row[f"avoided_drawdown_score_{label}"] = None
            row[f"opportunity_cost_{label}"] = None
            row[f"upside_capture_score_{label}"] = None
            row[f"adverse_move_score_{label}"] = None


def group_metrics(rows: list[dict[str, Any]], *, match: callable) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "count": sum(1 for row in rows if match(row)),
        "avg_mfe_pct": average_or_none(values_for_group(rows, match=match, value_key="max_favorable_excursion_pct")),
        "median_mfe_pct": median_or_none(values_for_group(rows, match=match, value_key="max_favorable_excursion_pct")),
        "avg_mae_pct": average_or_none(values_for_group(rows, match=match, value_key="max_adverse_excursion_pct")),
        "median_mae_pct": median_or_none(values_for_group(rows, match=match, value_key="max_adverse_excursion_pct")),
    }
    for label, _ in HORIZON_LABELS:
        values = [
            float((row.get("forward_returns") or {}).get(label))
            for row in rows
            if match(row) and (row.get("forward_returns") or {}).get(label) is not None
        ]
        summary[f"complete_{label}"] = sum(
            1 for row in rows if match(row) and bool((row.get("sample_completeness_flags") or {}).get(f"complete_{label}"))
        )
        summary[f"avg_return_pct_{label}"] = average_or_none(values)
        summary[f"median_return_pct_{label}"] = median_or_none(values)
        adjusted_values = values_for_group(rows, match=match, value_key=f"adjusted_return_score_{label}")
        summary[f"avg_adjusted_score_{label}"] = average_or_none(adjusted_values)
        summary[f"median_adjusted_score_{label}"] = median_or_none(adjusted_values)
    for label in ("4h", "24h"):
        summary[f"avg_avoided_drawdown_{label}"] = average_or_none(
            values_for_group(rows, match=match, value_key=f"avoided_drawdown_score_{label}")
        )
        summary[f"avg_opportunity_cost_{label}"] = average_or_none(
            values_for_group(rows, match=match, value_key=f"opportunity_cost_{label}")
        )
        summary[f"avg_upside_capture_{label}"] = average_or_none(
            values_for_group(rows, match=match, value_key=f"upside_capture_score_{label}")
        )
        summary[f"avg_adverse_move_{label}"] = average_or_none(
            values_for_group(rows, match=match, value_key=f"adverse_move_score_{label}")
        )
    return summary


def values_for_group(rows: list[dict[str, Any]], *, match: callable, value_key: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        if not match(row):
            continue
        value = row.get(value_key)
        if isinstance(value, (int, float)):
            out.append(float(value))
    return out


def build_group_summary(rows: list[dict[str, Any]], *, key_name: str, key_fn: callable) -> dict[str, dict[str, Any]]:
    keys = sorted({str(key_fn(row) or "") for row in rows if str(key_fn(row) or "")})
    out: dict[str, dict[str, Any]] = {}
    for key in keys:
        out[key] = group_metrics(rows, match=lambda row, key=key: str(key_fn(row) or "") == key)
    return out


def flatten_summary_to_csv_rows(summary: dict[str, dict[str, Any]], *, key_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, metrics in summary.items():
        row = {key_name: key}
        row.update(metrics)
        rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def top_csv_rows_for_action_reason(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return flatten_summary_to_csv_rows(summary["action_reason_bucket_summary"], key_name="action_reason_bucket")


def top_csv_rows_for_symbol(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return flatten_summary_to_csv_rows(summary["symbol_summary"], key_name="symbol")


def adjusted_csv_rows_for_action_reason(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return flatten_summary_to_csv_rows(summary["action_reason_bucket_summary"], key_name="action_reason_bucket")


def adjusted_csv_rows_for_symbol(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return flatten_summary_to_csv_rows(summary["symbol_summary"], key_name="symbol")


def promotion_candidate_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bucket, metrics in summary.get("action_reason_bucket_summary", {}).items():
        row = {"action_reason_bucket": bucket}
        row.update(metrics)
        rows.append(row)
    return rows


def action_from_bucket_name(bucket_name: str) -> str:
    return str(bucket_name.split("|", 1)[0] if "|" in bucket_name else bucket_name).upper()


def classify_bucket_diagnostics(
    action_reason_summary: dict[str, dict[str, Any]],
    *,
    min_bucket_count: int,
) -> dict[str, Any]:
    eligible: list[tuple[str, dict[str, Any]]] = [
        (bucket, metrics)
        for bucket, metrics in action_reason_summary.items()
        if int(metrics.get("count") or 0) >= int(min_bucket_count)
    ]
    promotion_candidate_buckets: list[dict[str, Any]] = []
    strong_promotion_candidate_buckets: list[dict[str, Any]] = []
    rejection_candidate_buckets: list[dict[str, Any]] = []
    needs_more_sample_buckets: list[dict[str, Any]] = []
    high_opportunity_cost_buckets: list[dict[str, Any]] = []
    high_protection_buckets: list[dict[str, Any]] = []
    high_reload_upside_buckets: list[dict[str, Any]] = []

    for bucket, metrics in action_reason_summary.items():
        row = {"action_reason_bucket": bucket}
        row.update(metrics)
        count = int(metrics.get("count") or 0)
        avg_adjusted_4h = metrics.get("avg_adjusted_score_4h")
        avg_adjusted_24h = metrics.get("avg_adjusted_score_24h")
        action = action_from_bucket_name(bucket)
        if count < int(min_bucket_count):
            needs_more_sample_buckets.append(row)
            continue
        if avg_adjusted_4h is not None and avg_adjusted_4h > 0 and (avg_adjusted_24h is None or avg_adjusted_24h >= 0):
            promotion_candidate_buckets.append(row)
            if avg_adjusted_4h >= 0.5:
                strong_promotion_candidate_buckets.append(row)
        if avg_adjusted_4h is not None and avg_adjusted_4h < 0:
            rejection_candidate_buckets.append(row)
        if action in REDUCE_ACTIONS and metrics.get("avg_opportunity_cost_4h") is not None:
            high_opportunity_cost_buckets.append(row)
        if action in REDUCE_ACTIONS and metrics.get("avg_avoided_drawdown_4h") is not None:
            high_protection_buckets.append(row)
        if action in LONG_ACTIONS and metrics.get("avg_upside_capture_4h") is not None:
            high_reload_upside_buckets.append(row)

    return {
        "min_bucket_count": int(min_bucket_count),
        "promotion_candidate_buckets": sorted(
            promotion_candidate_buckets,
            key=lambda row: (float(row.get("avg_adjusted_score_4h") or 0.0), int(row.get("count") or 0), row["action_reason_bucket"]),
            reverse=True,
        ),
        "strong_promotion_candidate_buckets": sorted(
            strong_promotion_candidate_buckets,
            key=lambda row: (float(row.get("avg_adjusted_score_4h") or 0.0), int(row.get("count") or 0), row["action_reason_bucket"]),
            reverse=True,
        ),
        "rejection_candidate_buckets": sorted(
            rejection_candidate_buckets,
            key=lambda row: (float(row.get("avg_adjusted_score_4h") or 0.0), int(row.get("count") or 0), row["action_reason_bucket"]),
        ),
        "needs_more_sample_buckets": sorted(
            needs_more_sample_buckets,
            key=lambda row: (int(row.get("count") or 0), row["action_reason_bucket"]),
            reverse=True,
        ),
        "high_opportunity_cost_buckets": sorted(
            high_opportunity_cost_buckets,
            key=lambda row: (float(row.get("avg_opportunity_cost_4h") or 0.0), int(row.get("count") or 0), row["action_reason_bucket"]),
            reverse=True,
        ),
        "high_protection_buckets": sorted(
            high_protection_buckets,
            key=lambda row: (float(row.get("avg_avoided_drawdown_4h") or 0.0), int(row.get("count") or 0), row["action_reason_bucket"]),
            reverse=True,
        ),
        "high_reload_upside_buckets": sorted(
            high_reload_upside_buckets,
            key=lambda row: (float(row.get("avg_upside_capture_4h") or 0.0), int(row.get("count") or 0), row["action_reason_bucket"]),
            reverse=True,
        ),
    }


def build_action_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    actions = sorted({str(row.get("position_lifecycle_action") or "") for row in rows if row.get("position_lifecycle_action")})
    out: dict[str, dict[str, Any]] = {}
    for action in actions:
        out[action] = group_metrics(rows, match=lambda row, action=action: str(row.get("position_lifecycle_action") or "") == action)
    return out


def build_summary(
    *,
    args: argparse.Namespace,
    audit: dict[str, Any],
    events_discovered: int,
    events_used: int,
    skip_counts: dict[str, int],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    action_counts = Counter(str(row.get("position_lifecycle_action") or "") for row in rows)
    primary_reason_counts = Counter(str(row.get("reason_bucket") or "") for row in rows if row.get("reason_bucket"))
    secondary_reason_counts: Counter[str] = Counter()
    for row in rows:
        for bucket in row.get("secondary_reason_buckets") or []:
            secondary_reason_counts[str(bucket)] += 1
    summary = {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "venue": args.venue,
        "quote": args.quote.upper(),
        "interval": args.interval,
        "trading_account_id": int(args.trading_account_id),
        "event_mode": args.event_mode,
        "cooldown_minutes": int(args.cooldown_minutes),
        "data_availability_audit": audit,
        "events_discovered": events_discovered,
        "events_used": events_used,
        "events_skipped_by_reason": dict(sorted(skip_counts.items())),
        "symbols_count": len(sorted({str(row.get("symbol") or "") for row in rows if row.get("symbol")})),
        "symbols": sorted({str(row.get("symbol") or "") for row in rows if row.get("symbol")}),
        "lifecycle_action_counts": dict(sorted(action_counts.items())),
        "top_primary_reason_buckets": [
            {"bucket": bucket, "count": count}
            for bucket, count in primary_reason_counts.most_common(10)
        ],
        "top_secondary_reason_buckets": [
            {"bucket": bucket, "count": count}
            for bucket, count in secondary_reason_counts.most_common(10)
        ],
        "setup_fail_fallback_count": int(primary_reason_counts.get("SETUP_FAIL", 0)),
        "complete_15m": sum(1 for row in rows if bool((row.get("sample_completeness_flags") or {}).get("complete_15m"))),
        "complete_30m": sum(1 for row in rows if bool((row.get("sample_completeness_flags") or {}).get("complete_30m"))),
        "complete_1h": sum(1 for row in rows if bool((row.get("sample_completeness_flags") or {}).get("complete_1h"))),
        "complete_2h": sum(1 for row in rows if bool((row.get("sample_completeness_flags") or {}).get("complete_2h"))),
        "complete_4h": sum(1 for row in rows if bool((row.get("sample_completeness_flags") or {}).get("complete_4h"))),
        "complete_8h": sum(1 for row in rows if bool((row.get("sample_completeness_flags") or {}).get("complete_8h"))),
        "complete_24h": sum(1 for row in rows if bool((row.get("sample_completeness_flags") or {}).get("complete_24h"))),
        "action_summary": build_action_summary(rows),
        "reason_bucket_summary": build_group_summary(rows, key_name="reason_bucket", key_fn=lambda row: row.get("reason_bucket")),
        "action_reason_bucket_summary": build_group_summary(
            rows,
            key_name="action_reason_bucket",
            key_fn=lambda row: f"{row.get('position_lifecycle_action')}|{row.get('reason_bucket')}",
        ),
        "symbol_summary": build_group_summary(rows, key_name="symbol", key_fn=lambda row: row.get("symbol")),
        "action_symbol_summary": build_group_summary(
            rows,
            key_name="action_symbol",
            key_fn=lambda row: f"{row.get('position_lifecycle_action')}|{row.get('symbol')}",
        ),
        "market_leg_summary": build_group_summary(rows, key_name="market_leg_bucket", key_fn=lambda row: row.get("market_leg_bucket")),
        "freshness_bucket_summary": build_group_summary(rows, key_name="freshness_bucket", key_fn=lambda row: row.get("freshness_bucket")),
        "safety": {
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "executor": "none",
            "live_trading": False,
        },
    }
    summary.update(
        classify_bucket_diagnostics(
            summary["action_reason_bucket_summary"],
            min_bucket_count=int(args.min_bucket_count),
        )
    )
    if rows:
        summary["first_event_ts"] = rows[0]["event_ts_utc"]
        summary["latest_event_ts"] = rows[-1]["event_ts_utc"]
    else:
        summary["first_event_ts"] = None
        summary["latest_event_ts"] = None
    return summary


def print_summary(summary: dict[str, Any], output_mode: str) -> None:
    if output_mode == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True, default=json_default))
        return
    print(f"report={summary['report']} version={summary['version']}")
    print(
        f"audit_status={summary['data_availability_audit']['status']} "
        f"events_discovered={summary['events_discovered']} events_used={summary['events_used']} "
        f"venue={summary['venue']} quote={summary['quote']} interval={summary['interval']} "
        f"account={summary['trading_account_id']} event_mode={summary['event_mode']}"
    )
    print(
        " ".join(
            [
                f"complete_15m={summary['complete_15m']}",
                f"complete_30m={summary['complete_30m']}",
                f"complete_1h={summary['complete_1h']}",
                f"complete_2h={summary['complete_2h']}",
                f"complete_4h={summary['complete_4h']}",
                f"complete_8h={summary['complete_8h']}",
                f"complete_24h={summary['complete_24h']}",
            ]
        )
    )
    if summary["events_skipped_by_reason"]:
        print("skipped " + " ".join(f"{k}={v}" for k, v in summary["events_skipped_by_reason"].items()))
    print(
        "safety "
        f"broker_calls={summary['safety']['broker_calls']} "
        f"broker_writes={summary['safety']['broker_writes']} "
        f"order_submission={summary['safety']['order_submission']} "
        f"executor={summary['safety']['executor']} "
        f"live_trading={str(summary['safety']['live_trading']).lower()}"
    )
    print(
        "primary_reason_buckets "
        + " ; ".join(f"{item['bucket']}:{item['count']}" for item in summary["top_primary_reason_buckets"])
    )
    if summary["top_secondary_reason_buckets"]:
        print(
            "secondary_reason_buckets "
            + " ; ".join(f"{item['bucket']}:{item['count']}" for item in summary["top_secondary_reason_buckets"])
        )
    print(f"setup_fail_fallback_count={summary['setup_fail_fallback_count']}")
    for action, item in summary["action_summary"].items():
        print(
            f"{action} count={item['count']} "
            f"avg15m={item['avg_return_pct_15m']} med15m={item['median_return_pct_15m']} "
            f"avg1h={item['avg_return_pct_1h']} med1h={item['median_return_pct_1h']} "
            f"avg4h={item['avg_return_pct_4h']} med4h={item['median_return_pct_4h']} "
            f"avg24h={item['avg_return_pct_24h']} med24h={item['median_return_pct_24h']} "
            f"adj4h={item['avg_adjusted_score_4h']} adj24h={item['avg_adjusted_score_24h']} "
            f"avg_mfe={item['avg_mfe_pct']} avg_mae={item['avg_mae_pct']}"
        )
    top_count = sorted(
        summary["action_reason_bucket_summary"].items(),
        key=lambda item: (item[1]["count"], item[0]),
        reverse=True,
    )[:10]
    print("top_action_reason_by_count " + " ; ".join(f"{k}:{v['count']}" for k, v in top_count))
    top_avg4h = sorted(
        [(k, v) for k, v in summary["action_reason_bucket_summary"].items() if v["count"] >= 20 and v["avg_return_pct_4h"] is not None],
        key=lambda item: item[1]["avg_return_pct_4h"],
        reverse=True,
    )[:10]
    print("top_action_reason_by_avg4h " + " ; ".join(f"{k}:{v['avg_return_pct_4h']}" for k, v in top_avg4h))
    worst_avg4h = sorted(
        [(k, v) for k, v in summary["action_reason_bucket_summary"].items() if v["count"] >= 20 and v["avg_return_pct_4h"] is not None],
        key=lambda item: item[1]["avg_return_pct_4h"],
    )[:10]
    print("worst_action_reason_by_avg4h " + " ; ".join(f"{k}:{v['avg_return_pct_4h']}" for k, v in worst_avg4h))
    top_symbols = sorted(
        summary["symbol_summary"].items(),
        key=lambda item: (item[1]["count"], item[0]),
        reverse=True,
    )[:10]
    print("top_symbols " + " ; ".join(f"{k}:{v['count']}" for k, v in top_symbols))
    adjusted_top = sorted(
        [(k, v) for k, v in summary["action_reason_bucket_summary"].items() if v["count"] >= 20 and v["avg_adjusted_score_4h"] is not None],
        key=lambda item: item[1]["avg_adjusted_score_4h"],
        reverse=True,
    )[:10]
    print("top_action_reason_by_adjusted4h " + " ; ".join(f"{k}:{v['avg_adjusted_score_4h']}" for k, v in adjusted_top))
    adjusted_worst = sorted(
        [(k, v) for k, v in summary["action_reason_bucket_summary"].items() if v["count"] >= 20 and v["avg_adjusted_score_4h"] is not None],
        key=lambda item: item[1]["avg_adjusted_score_4h"],
    )[:10]
    print("worst_action_reason_by_adjusted4h " + " ; ".join(f"{k}:{v['avg_adjusted_score_4h']}" for k, v in adjusted_worst))
    top_avoided = sorted(
        [(k, v) for k, v in summary["action_reason_bucket_summary"].items() if v["count"] >= 20 and v["avg_avoided_drawdown_4h"] is not None],
        key=lambda item: item[1]["avg_avoided_drawdown_4h"],
        reverse=True,
    )[:10]
    print("top_action_reason_by_avoided_drawdown4h " + " ; ".join(f"{k}:{v['avg_avoided_drawdown_4h']}" for k, v in top_avoided))
    top_opportunity_cost = sorted(
        [(k, v) for k, v in summary["action_reason_bucket_summary"].items() if v["count"] >= 20 and v["avg_opportunity_cost_4h"] is not None],
        key=lambda item: item[1]["avg_opportunity_cost_4h"],
        reverse=True,
    )[:10]
    print("top_action_reason_by_opportunity_cost4h " + " ; ".join(f"{k}:{v['avg_opportunity_cost_4h']}" for k, v in top_opportunity_cost))
    top_upside_capture = sorted(
        [
            (k, v)
            for k, v in summary["action_reason_bucket_summary"].items()
            if v["count"] >= 20
            and v["avg_upside_capture_4h"] is not None
            and (k.startswith("HOLD|") or k.startswith("RELOAD_REVIEW|"))
        ],
        key=lambda item: item[1]["avg_upside_capture_4h"],
        reverse=True,
    )[:10]
    print("top_hold_reload_by_upside_capture4h " + " ; ".join(f"{k}:{v['avg_upside_capture_4h']}" for k, v in top_upside_capture))
    print(
        "promotion_candidate_buckets "
        + " ; ".join(
            f"{row['action_reason_bucket']}:{row['avg_adjusted_score_4h']}"
            for row in summary["promotion_candidate_buckets"][:10]
        )
    )
    print(
        "strong_promotion_candidate_buckets "
        + " ; ".join(
            f"{row['action_reason_bucket']}:{row['avg_adjusted_score_4h']}"
            for row in summary["strong_promotion_candidate_buckets"][:10]
        )
    )
    print(
        "rejection_candidate_buckets "
        + " ; ".join(
            f"{row['action_reason_bucket']}:{row['avg_adjusted_score_4h']}"
            for row in summary["rejection_candidate_buckets"][:10]
        )
    )
    print(
        "high_opportunity_cost_buckets "
        + " ; ".join(
            f"{row['action_reason_bucket']}:{row['avg_opportunity_cost_4h']}"
            for row in summary["high_opportunity_cost_buckets"][:10]
        )
    )
    print(
        "high_protection_buckets "
        + " ; ".join(
            f"{row['action_reason_bucket']}:{row['avg_avoided_drawdown_4h']}"
            for row in summary["high_protection_buckets"][:10]
        )
    )
    print(
        "high_reload_upside_buckets "
        + " ; ".join(
            f"{row['action_reason_bucket']}:{row['avg_upside_capture_4h']}"
            for row in summary["high_reload_upside_buckets"][:10]
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.cooldown_minutes <= 0:
        raise ValueError("--cooldown-minutes must be greater than zero")

    conn = get_connection()
    try:
        audit = build_data_availability_audit(
            conn,
            venue=args.venue,
            quote=args.quote,
            interval=args.interval,
            trading_account_id=args.trading_account_id,
        )
        if audit["status"] == "blocked":
            summary = build_summary(
                args=args,
                audit=audit,
                events_discovered=0,
                events_used=0,
                skip_counts={"blocked_by_audit": 1},
                rows=[],
            )
            print_summary(summary, args.output)
            if args.write_files:
                output_dir = Path(args.output_dir)
                write_json(output_dir / OUTPUT_SUMMARY, summary)
                write_json(output_dir / OUTPUT_MANIFEST, {"report": REPORT_NAME, "version": REPORT_VERSION, "audit_status": audit["status"]})
            return 1

        positions = fetch_position_history(
            conn,
            venue=args.venue,
            trading_account_id=args.trading_account_id,
        )
        symbols = {row.symbol for row in positions}
        advice_history_by_symbol = fetch_historical_advice(
            conn,
            venue=args.venue,
            interval=args.interval,
            symbols=symbols,
        )
        if not positions or not advice_history_by_symbol:
            summary = build_summary(
                args=args,
                audit=audit,
                events_discovered=0,
                events_used=0,
                skip_counts={"missing_positions_or_advice_history": 1},
                rows=[],
            )
            print_summary(summary, args.output)
            return 1

        min_ts = min(row.event_ts_utc for row in positions) - timedelta(minutes=20)
        max_ts = max(row.event_ts_utc for row in positions) + MAX_HORIZON + timedelta(minutes=20)
        price_history_by_symbol = fetch_price_history(
            conn,
            venue=args.venue,
            quote=args.quote,
            symbols=symbols,
            from_ts=min_ts,
            to_ts=max_ts,
        )
        candles_by_symbol = fetch_15m_candle_history(
            conn,
            venue=args.venue,
            symbols=symbols,
            from_ts=min_ts,
            to_ts=max_ts,
        )
    finally:
        conn.close()

    events, reconstruct_skip_counts = reconstruct_events(
        positions=positions,
        advice_history_by_symbol=advice_history_by_symbol,
        price_history_by_symbol=price_history_by_symbol,
        candles_by_symbol=candles_by_symbol,
        quote=args.quote,
        interval=args.interval,
    )
    filtered_events, filter_skip_counts = filter_events(
        events,
        event_mode=args.event_mode,
        cooldown_minutes=args.cooldown_minutes,
    )
    filtered_events = truncate_events_for_max(
        filtered_events,
        max_events=args.max_events,
        candles_by_symbol=candles_by_symbol,
    )

    rows: list[dict[str, Any]] = []
    for event in filtered_events:
        outcomes = horizon_outcomes_for_event(event, candles_by_symbol)
        rows.append(event_to_row(event, outcomes))

    skip_counts = dict(Counter(reconstruct_skip_counts) + Counter(filter_skip_counts))
    summary = build_summary(
        args=args,
        audit=audit,
        events_discovered=len(events),
        events_used=len(rows),
        skip_counts=skip_counts,
        rows=rows,
    )

    if args.write_files:
        output_dir = Path(args.output_dir)
        write_jsonl(output_dir / OUTPUT_ROWS, rows)
        write_json(output_dir / OUTPUT_SUMMARY, summary)
        write_csv(output_dir / OUTPUT_BUCKET_ACTION_REASON_CSV, top_csv_rows_for_action_reason(summary))
        write_csv(output_dir / OUTPUT_BUCKET_SYMBOL_CSV, top_csv_rows_for_symbol(summary))
        write_csv(output_dir / OUTPUT_BUCKET_ACTION_REASON_ADJUSTED_CSV, adjusted_csv_rows_for_action_reason(summary))
        write_csv(output_dir / OUTPUT_BUCKET_SYMBOL_ADJUSTED_CSV, adjusted_csv_rows_for_symbol(summary))
        write_csv(output_dir / OUTPUT_PROMOTION_CANDIDATES_CSV, promotion_candidate_rows(summary))
        write_json(
            output_dir / OUTPUT_PROMOTION_CANDIDATES_JSON,
            {
                "report": REPORT_NAME,
                "version": REPORT_VERSION,
                "min_bucket_count": int(args.min_bucket_count),
                "promotion_candidate_buckets": summary["promotion_candidate_buckets"],
                "strong_promotion_candidate_buckets": summary["strong_promotion_candidate_buckets"],
                "rejection_candidate_buckets": summary["rejection_candidate_buckets"],
                "needs_more_sample_buckets": summary["needs_more_sample_buckets"],
                "high_opportunity_cost_buckets": summary["high_opportunity_cost_buckets"],
                "high_protection_buckets": summary["high_protection_buckets"],
                "high_reload_upside_buckets": summary["high_reload_upside_buckets"],
            },
        )
        write_json(
            output_dir / OUTPUT_MANIFEST,
            {
                "report": REPORT_NAME,
                "version": REPORT_VERSION,
                "generated_at_utc": fmt_ts(datetime.now(UTC)),
                "output_rows_v1_jsonl": str(output_dir / OUTPUT_ROWS),
                "output_summary_v1_json": str(output_dir / OUTPUT_SUMMARY),
                "bucket_summary_by_action_reason_v1_csv": str(output_dir / OUTPUT_BUCKET_ACTION_REASON_CSV),
                "bucket_summary_by_symbol_v1_csv": str(output_dir / OUTPUT_BUCKET_SYMBOL_CSV),
                "bucket_summary_by_action_reason_adjusted_v1_csv": str(output_dir / OUTPUT_BUCKET_ACTION_REASON_ADJUSTED_CSV),
                "bucket_summary_by_symbol_adjusted_v1_csv": str(output_dir / OUTPUT_BUCKET_SYMBOL_ADJUSTED_CSV),
                "lifecycle_bucket_promotion_candidates_v1_csv": str(output_dir / OUTPUT_PROMOTION_CANDIDATES_CSV),
                "lifecycle_bucket_promotion_candidates_v1_json": str(output_dir / OUTPUT_PROMOTION_CANDIDATES_JSON),
                "audit_status": audit["status"],
                "reconstruction_mode": audit["reconstruction_mode"],
            },
        )

    print_summary(summary, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
