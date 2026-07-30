from __future__ import annotations

import argparse
import html
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.regime.run_active_regime_observation_v1 import classify_asset_class
from src.reporting.dashboard_style_v1 import (
    cockpit_base_css,
    cockpit_nav,
    pill_classes,
)
from src.reporting.dashboard_time_v1 import format_ui_now


REPORT_NAME = "breath_fibo_strategy_static_dashboard_v1"
REPORT_VERSION = "0.1"
DEFAULT_OUTPUT_HTML = "/tmp/breath_fibo_strategy_dashboard_v1.html"
FRESHNESS_MULTIPLIERS = {
    "15m": (1.5, 4.0),
    "1h": (1.5, 4.0),
    "4h": (1.5, 4.0),
    "1d": (1.5, 4.0),
}
INTERVAL_DELTAS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}
STRATEGY_STATE_ORDER = {
    "INVALIDATION_NEAR": 0,
    "TARGET_TOUCHED_TP_REVIEW": 1,
    "ENTRY_ZONE_NEAR": 2,
    "SUPPORT_REACTION_CANDIDATE": 3,
    "FIB_RETEST_CONTINUATION_CANDIDATE": 4,
    "WAIT_RETEST": 5,
    "FAILED_RECLAIM_FADE_RISK": 6,
    "MAP_INCOMPLETE": 7,
    "CONTEXT_ONLY": 8,
    "NO_STRATEGY_CONTEXT": 9,
}


@dataclass(frozen=True)
class PriceSnapshot:
    symbol: str
    current_price: Decimal | None
    latest_candle_ts_utc: datetime | None
    source: str


@dataclass(frozen=True)
class DashboardRow:
    asset: str
    current_price: Decimal | None
    interval: str
    latest_candle_ts_utc: datetime | None
    candle_freshness_state: str
    regime_context: str
    fibo_map_state: str
    current_leg: str
    nearest_support_or_entry_zone: str
    nearest_target_or_t1: str
    entry_zone: str
    invalidation_zone: str
    invalidation_source: str
    invalidation_method: str
    distance_to_target_pct: Decimal | None
    distance_to_entry_zone_pct: Decimal | None
    distance_to_invalidation_pct: Decimal | None
    manual_ladder_context: str
    primitive_signal_context: str
    strategy_candidate_state: str
    strategy_candidate_reason: str
    source_status: str
    source_modules: tuple[str, ...]
    debug_payload: dict[str, Any]


@dataclass(frozen=True)
class InvalidationResolution:
    invalidation_level: Decimal | None
    invalidation_source_module: str
    invalidation_source_field: str
    invalidation_method: str
    invalidation_source_status: str
    invalidation_note: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render the initial market-only Breath/Fibo strategy static dashboard."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--quote", default="EUR")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--output-html", default=DEFAULT_OUTPUT_HTML)
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
    return parser.parse_args(argv)


def esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def pill(label: str, tone: str = "muted") -> str:
    return f"<span class='pill {esc(pill_classes(tone, label))}'>{esc(label)}</span>"


def state_tone(label: str) -> str:
    value = str(label or "").upper()
    if value in {"INVALIDATION_NEAR", "FAILED_RECLAIM_FADE_RISK"}:
        return "bad"
    if value in {"TARGET_TOUCHED_TP_REVIEW", "WAIT_RETEST", "MAP_INCOMPLETE"}:
        return "warn"
    if value in {"SUPPORT_REACTION_CANDIDATE", "FIB_RETEST_CONTINUATION_CANDIDATE", "ENTRY_ZONE_NEAR"}:
        return "ok"
    if value in {"CONTEXT_ONLY", "NO_STRATEGY_CONTEXT"}:
        return "context"
    return "muted"


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan", "—", "unavailable"}:
        return None
    text = text.replace("%", "")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def first_decimal(source: dict[str, Any], keys: tuple[str, ...]) -> Decimal | None:
    for key in keys:
        value = to_decimal(source.get(key))
        if value is not None:
            return value
    return None


def first_text(source: dict[str, Any], keys: tuple[str, ...], default: str = "UNKNOWN") -> str:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def resolve_invalidation_level(fib_row: dict[str, Any] | None) -> InvalidationResolution:
    if fib_row:
        level = to_decimal(fib_row.get("invalidation_level"))
        if level is not None:
            return InvalidationResolution(
                invalidation_level=level,
                invalidation_source_module="canonical_fib_zone_map_v1",
                invalidation_source_field="invalidation_level",
                invalidation_method=str(fib_row.get("invalidation_method") or "UNKNOWN"),
                invalidation_source_status="FOUND",
                invalidation_note="Invalidation resolved from the persisted canonical map.",
            )
    return InvalidationResolution(
        invalidation_level=None,
        invalidation_source_module="UNKNOWN",
        invalidation_source_field="UNKNOWN",
        invalidation_method="MISSING_INVALIDATION",
        invalidation_source_status="MISSING_SOURCE",
        invalidation_note="No canonical fib-map invalidation level is available.",
    )


def fmt_price(value: Decimal | None) -> str:
    if value is None:
        return "—"
    places = Decimal("0.000001") if abs(value) < Decimal("1") else Decimal("0.01")
    try:
        return str(value.quantize(places))
    except Exception:
        return str(value)


def fmt_pct(value: Decimal | None) -> str:
    if value is None:
        return "—"
    try:
        return f"{value.quantize(Decimal('0.1'))}%"
    except Exception:
        return f"{value}%"


def fmt_ts(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def zone_text(low: Decimal | None, high: Decimal | None) -> str:
    if low is None and high is None:
        return "UNKNOWN"
    if low is not None and high is not None:
        if low > high:
            low, high = high, low
        if low == high:
            return fmt_price(low)
        return f"{fmt_price(low)}..{fmt_price(high)}"
    return fmt_price(low or high)


def midpoint(low: Decimal | None, high: Decimal | None) -> Decimal | None:
    if low is not None and high is not None:
        if low > high:
            low, high = high, low
        return (low + high) / Decimal("2")
    return low or high


def pct_distance(level: Decimal | None, current: Decimal | None) -> Decimal | None:
    if level is None or current is None or current == 0:
        return None
    return (level - current) / current * Decimal("100")


def now_utc() -> datetime:
    return datetime.now(UTC)


def atomic_text_write(content: str, destination: Path) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fchmod(handle.fileno(), 0o644)
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def freshness_state(interval: str, latest_ts: datetime | None) -> str:
    if latest_ts is None:
        return "MISSING_CANDLE"
    delta = INTERVAL_DELTAS.get(interval)
    if delta is None:
        return "UNKNOWN"
    age = now_utc() - latest_ts.astimezone(UTC)
    fresh_mult, stale_mult = FRESHNESS_MULTIPLIERS.get(interval, (1.5, 4.0))
    if age <= delta * fresh_mult:
        return "FRESH"
    if age <= delta * stale_mult:
        return "DELAYED"
    return "STALE"


def fetch_all_dicts(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        cursor = conn.cursor(dictionary=True)
    except TypeError:
        cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        if not rows:
            return []
        if isinstance(rows[0], dict):
            return [dict(row) for row in rows]
        columns = [str(desc[0]) for desc in cursor.description or []]
        return [dict(zip(columns, row)) for row in rows]
    finally:
        try:
            cursor.close()
        except Exception:
            pass


def try_query(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        return fetch_all_dicts(conn, sql, params)
    except Exception:
        return []


def fetch_canonical_fib_rows(
    conn: Any,
    *,
    venue: str,
    quote: str,
    interval: str,
) -> dict[str, dict[str, Any]]:
    rows = fetch_all_dicts(
        conn,
        """
        SELECT *
        FROM canonical_fib_zone_map_latest_v1
        WHERE venue = %s
          AND quote_currency = %s
          AND interval_code = %s
        ORDER BY symbol
        """,
        (venue, quote, interval),
    )
    return {str(row["symbol"]).upper(): row for row in rows}


def fetch_latest_price_rows(conn: Any, *, venue: str, interval: str, limit: int) -> dict[str, PriceSnapshot]:
    queries = (
        (
            """
            SELECT a.symbol AS symbol, c.close_price, c.close_ts_utc
            FROM obs_market_candle c
            JOIN asset a ON a.asset_id = c.asset_id
            JOIN (
                SELECT asset_id, MAX(close_ts_utc) AS max_close_ts_utc
                FROM obs_market_candle
                WHERE venue = %s AND interval_code = %s
                GROUP BY asset_id
            ) latest
              ON latest.asset_id = c.asset_id
             AND latest.max_close_ts_utc = c.close_ts_utc
            WHERE c.venue = %s
              AND c.interval_code = %s
            ORDER BY a.symbol
            LIMIT %s
            """,
            (venue, interval, venue, interval, limit),
        ),
        (
            """
            SELECT a.symbol AS symbol, c.close_price, c.close_ts_utc
            FROM obs_market_candle c
            JOIN asset a ON a.id = c.asset_id
            JOIN (
                SELECT asset_id, MAX(close_ts_utc) AS max_close_ts_utc
                FROM obs_market_candle
                WHERE venue = %s AND interval_code = %s
                GROUP BY asset_id
            ) latest
              ON latest.asset_id = c.asset_id
             AND latest.max_close_ts_utc = c.close_ts_utc
            WHERE c.venue = %s
              AND c.interval_code = %s
            ORDER BY a.symbol
            LIMIT %s
            """,
            (venue, interval, venue, interval, limit),
        ),
    )
    for sql, params in queries:
        rows = try_query(conn, sql, params)
        if not rows:
            continue
        out: dict[str, PriceSnapshot] = {}
        for row in rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            ts = row.get("close_ts_utc")
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                else:
                    ts = ts.astimezone(UTC)
            else:
                ts = None
            out[symbol] = PriceSnapshot(
                symbol=symbol,
                current_price=to_decimal(row.get("close_price")),
                latest_candle_ts_utc=ts,
                source="obs_market_candle",
            )
        if out:
            return out
    return {}


def fetch_regime_by_class(conn: Any, *, venue: str, interval: str) -> tuple[dict[str, dict[str, Any]], str]:
    sql = """
        SELECT *
        FROM active_regime_observation
        WHERE venue = %s
          AND interval_code = %s
          AND asof_ts_utc = (
              SELECT MAX(asof_ts_utc)
              FROM active_regime_observation
              WHERE venue = %s AND interval_code = %s
          )
    """
    rows = try_query(conn, sql, (venue, interval, venue, interval))
    by_class = {str(row.get("asset_class") or "").upper(): row for row in rows if row.get("asset_class")}
    latest = "—"
    if rows:
        ts = rows[0].get("asof_ts_utc")
        latest = fmt_ts(ts if isinstance(ts, datetime) else None)
    return by_class, latest


def format_regime_context(regime_row: dict[str, Any] | None) -> str:
    if not regime_row:
        return "UNKNOWN"
    return " · ".join(
        part
        for part in (
            str(regime_row.get("global_regime") or "").strip(),
            str(regime_row.get("asset_class_regime") or "").strip(),
            str(regime_row.get("global_class_regime") or "").strip(),
            f"asof={fmt_ts(regime_row.get('asof_ts_utc'))}" if regime_row.get("asof_ts_utc") else "",
        )
        if part
    ) or "UNKNOWN"


def status_blob(*values: Any) -> str:
    return " ".join(str(value or "").upper() for value in values)


def build_row(
    symbol: str,
    *,
    interval: str,
    price_row: PriceSnapshot | None,
    fib_row: dict[str, Any] | None,
    regime_row: dict[str, Any] | None,
) -> DashboardRow:
    source: dict[str, Any] = {}
    if fib_row:
        source.update({f"fib_{k}": v for k, v in fib_row.items()})

    current_price = price_row.current_price if price_row else None
    latest_candle_ts_utc = price_row.latest_candle_ts_utc if price_row else None
    candle_state = freshness_state(interval, latest_candle_ts_utc)
    map_ts = fib_row.get("input_latest_candle_ts_utc") if fib_row else None
    map_freshness = freshness_state(interval, map_ts if isinstance(map_ts, datetime) else None)
    map_age_hours = (
        (now_utc() - (map_ts.replace(tzinfo=UTC) if map_ts.tzinfo is None else map_ts.astimezone(UTC))).total_seconds()
        / 3600
        if isinstance(map_ts, datetime)
        else None
    )

    fib_state = "FIB_MAP_UNKNOWN"
    if fib_row:
        fib_state = " | ".join(
            (
                str(fib_row.get("map_status") or "UNKNOWN"),
                str(fib_row.get("map_quality") or "UNKNOWN"),
                f"age={map_age_hours:.1f}h/{map_freshness}" if map_age_hours is not None else "age=UNAVAILABLE",
                str(fib_row.get("map_version") or "UNKNOWN"),
                f"publication={str(fib_row.get('publication_id') or 'UNKNOWN')[:20]}",
            )
        ) or "FIB_MAP_FOUND"

    current_leg = first_text(source, ("fib_current_leg",), default="UNKNOWN").upper()
    entry_low = first_decimal(source, ("fib_entry_zone_low",))
    entry_high = first_decimal(source, ("fib_entry_zone_high",))
    support_low = first_decimal(source, ("fib_support_reaction_zone_low",))
    support_high = first_decimal(source, ("fib_support_reaction_zone_high",))
    entry_zone_mid = first_decimal(source, ("fib_entry_zone_mid",)) or midpoint(entry_low, entry_high)
    entry_zone = zone_text(entry_low, entry_high)
    nearest_support = zone_text(support_low or entry_low, support_high or entry_high)

    target_t1 = first_decimal(source, ("fib_target_t1",))
    target_t2 = first_decimal(source, ("fib_target_t2",))
    target_extension = first_decimal(source, ("fib_target_extension",))
    nearest_target = next(
        (
            target
            for target in (target_t1, target_t2, target_extension)
            if target is not None and (current_price is None or target > current_price)
        ),
        target_extension or target_t2 or target_t1,
    )
    invalidation_resolution = resolve_invalidation_level(fib_row)
    invalidation = invalidation_resolution.invalidation_level

    distance_to_target_pct = pct_distance(nearest_target, current_price)
    distance_to_entry_zone_pct = pct_distance(entry_zone_mid, current_price)
    distance_to_invalidation_pct = pct_distance(invalidation, current_price)

    manual_ladder_context = "unavailable"
    if target_t1 is not None or entry_zone_mid is not None or target_t2 is not None:
        manual_ladder_context = (
            f"T1={fmt_price(target_t1)} · entry_zone={entry_zone} · T2={fmt_price(target_t2)}"
        )

    primitive_signal_context = "unavailable"

    source_modules: list[str] = []
    if price_row:
        source_modules.append("obs_market_candle")
    if fib_row:
        source_modules.append("canonical_fib_zone_map_v1")
    if regime_row:
        source_modules.append("active_regime_observation")

    missing_sources: list[str] = []
    if not price_row:
        missing_sources.append("MISSING_PRICE_SOURCE")
    if not fib_row:
        missing_sources.append("FIB_MAP_UNKNOWN")
    if not regime_row:
        missing_sources.append("MISSING_REGIME_SOURCE")
    if primitive_signal_context == "unavailable":
        missing_sources.append("MISSING_PRIMITIVE_SIGNAL_CONTEXT")

    target_touched = current_price is not None and nearest_target is not None and current_price >= nearest_target
    invalidation_near = (
        distance_to_invalidation_pct is not None and distance_to_invalidation_pct <= 0 and abs(distance_to_invalidation_pct) <= Decimal("3.0")
    )
    entry_zone_near = distance_to_entry_zone_pct is not None and abs(distance_to_entry_zone_pct) <= Decimal("3.0")
    support_candidate = (
        current_price is not None
        and entry_low is not None
        and entry_high is not None
        and current_price >= entry_low
        and current_price <= entry_high
    )
    failed_reclaim = (
        current_leg == "UP"
        and current_price is not None
        and entry_low is not None
        and current_price < entry_low
        and not invalidation_near
    )
    wait_retest = (
        current_leg == "UP"
        and current_price is not None
        and entry_high is not None
        and current_price > entry_high
        and nearest_target is not None
        and current_price < nearest_target
        and not entry_zone_near
        and not support_candidate
    )

    map_available = (
        fib_row is not None
        and str(fib_row.get("map_status") or "") not in {"NO_DATA", "STALE"}
        and map_freshness in {"FRESH", "DELAYED"}
    )
    if not fib_row:
        state = "NO_STRATEGY_CONTEXT"
        reason = "No canonical fib map row is available."
    elif not map_available:
        state = "MAP_UNAVAILABLE"
        reason = (
            f"Canonical map is not current: map_status={fib_row.get('map_status')} "
            f"freshness={map_freshness}."
        )
    elif nearest_target is None or entry_zone_mid is None or invalidation is None:
        state = "MAP_INCOMPLETE"
        reason = "Canonical fib map is incomplete: target, Entry Zone, or invalidation is missing."
    elif invalidation_near:
        state = "INVALIDATION_NEAR"
        reason = f"Price is near invalidation {fmt_price(invalidation)}; fade/break risk is elevated."
    elif failed_reclaim:
        state = "FAILED_RECLAIM_FADE_RISK"
        reason = "Current context shows failed reclaim / failed breakout style risk."
    elif target_touched:
        state = "TARGET_TOUCHED_TP_REVIEW"
        reason = f"Nearest mapped target {fmt_price(nearest_target)} has been touched; review TP / runner map manually."
    elif entry_zone_near:
        state = "ENTRY_ZONE_NEAR"
        reason = f"Price is near Entry Zone {entry_zone}; check hold/retest behavior before acting manually."
    elif support_candidate and current_leg == "UP":
        state = "SUPPORT_REACTION_CANDIDATE"
        reason = f"Price is inside Entry Zone {entry_zone} with upside map still visible."
    elif wait_retest:
        state = "WAIT_RETEST"
        reason = f"Price is above Entry Zone {entry_zone} but below target {fmt_price(nearest_target)}; wait for retest rather than chase."
    elif current_leg == "UP" and distance_to_target_pct is not None and distance_to_target_pct > 0:
        state = "FIB_RETEST_CONTINUATION_CANDIDATE"
        reason = "Up-leg map remains intact between Entry Zone and next target; continuation is a research hypothesis only."
    else:
        state = "CONTEXT_ONLY"
        reason = "Map context is visible, but no stronger strategy hypothesis is near current price."

    regime_context = format_regime_context(regime_row)
    source_status = "; ".join(
        [
            f"price={'FOUND' if price_row else 'MISSING_SOURCE'}",
            f"canonical_fib_map={'FOUND' if fib_row else 'MISSING_SOURCE'}",
            "legacy_paper_context=NOT_READ",
            f"regime={'FOUND' if regime_row else 'MISSING_SOURCE'}",
            f"primitive={'FOUND' if primitive_signal_context != 'unavailable' else 'MISSING_SOURCE'}",
            f"invalidation_source={invalidation_resolution.invalidation_source_module}",
            f"invalidation_method={invalidation_resolution.invalidation_method}",
        ]
    )

    debug_payload = {
        "fib_row": fib_row or {},
        "regime_row": regime_row or {},
        "invalidation_resolution": asdict(invalidation_resolution),
        "missing_sources": missing_sources,
    }
    return DashboardRow(
        asset=symbol,
        current_price=current_price,
        interval=interval,
        latest_candle_ts_utc=latest_candle_ts_utc,
        candle_freshness_state=candle_state,
        regime_context=regime_context,
        fibo_map_state=fib_state,
        current_leg=current_leg,
        nearest_support_or_entry_zone=nearest_support,
        nearest_target_or_t1=fmt_price(nearest_target),
        entry_zone=entry_zone,
        invalidation_zone=fmt_price(invalidation),
        invalidation_source=f"{invalidation_resolution.invalidation_source_module}.{invalidation_resolution.invalidation_source_field}",
        invalidation_method=invalidation_resolution.invalidation_method,
        distance_to_target_pct=distance_to_target_pct,
        distance_to_entry_zone_pct=distance_to_entry_zone_pct,
        distance_to_invalidation_pct=distance_to_invalidation_pct,
        manual_ladder_context=manual_ladder_context,
        primitive_signal_context=primitive_signal_context,
        strategy_candidate_state=state,
        strategy_candidate_reason=reason,
        source_status=source_status,
        source_modules=tuple(source_modules),
        debug_payload=debug_payload,
    )


def build_rows(
    *,
    interval: str,
    price_rows: dict[str, PriceSnapshot],
    fib_rows: dict[str, dict[str, Any]],
    regime_by_class: dict[str, dict[str, Any]],
    limit: int,
) -> list[DashboardRow]:
    symbols = sorted(set(price_rows) | set(fib_rows))
    rows = []
    for symbol in symbols[:limit]:
        asset_class = classify_asset_class(symbol)
        row = build_row(
            symbol,
            interval=interval,
            price_row=price_rows.get(symbol),
            fib_row=fib_rows.get(symbol),
            regime_row=regime_by_class.get(asset_class),
        )
        rows.append(row)
    rows.sort(key=lambda row: (STRATEGY_STATE_ORDER.get(row.strategy_candidate_state, 99), row.asset))
    return rows


def render_html(rows: list[DashboardRow], *, venue: str, quote: str, interval: str) -> str:
    rendered_label = format_ui_now(now_utc=now_utc())
    headers = [
        "asset",
        "current_price",
        "interval",
        "latest_candle_ts_utc",
        "candle_freshness_state",
        "regime_context",
        "fibo_map_state",
        "current_leg",
        "nearest_support_or_entry_zone",
        "nearest_target_or_t1",
        "entry_zone",
        "invalidation_zone",
        "invalidation_source",
        "invalidation_method",
        "distance_to_target_pct",
        "distance_to_entry_zone_pct",
        "distance_to_invalidation_pct",
        "manual_ladder_context",
        "primitive_signal_context",
        "strategy_candidate_state",
        "strategy_candidate_reason",
        "source_status",
    ]
    body_rows = []
    for row in rows:
        body_rows.append(
            f"""
            <tr class="{esc('fresh-map' if row.candle_freshness_state == 'FRESH' else 'warning-map' if row.candle_freshness_state == 'DELAYED' else 'stale-map')}">
              <td class="sticky-col-symbol"><strong>{esc(row.asset)}</strong><div class="small muted">{esc(', '.join(row.source_modules) or '—')}</div></td>
              <td class="sticky-col-price num">{esc(fmt_price(row.current_price))}</td>
              <td>{esc(row.interval)}</td>
              <td class="mono">{esc(fmt_ts(row.latest_candle_ts_utc))}</td>
              <td>{pill(row.candle_freshness_state, 'ok' if row.candle_freshness_state == 'FRESH' else 'warn' if row.candle_freshness_state == 'DELAYED' else 'bad' if row.candle_freshness_state == 'STALE' else 'muted')}</td>
              <td>{esc(row.regime_context)}</td>
              <td>{esc(row.fibo_map_state)}</td>
              <td>{esc(row.current_leg)}</td>
              <td class="mono">{esc(row.nearest_support_or_entry_zone)}</td>
              <td class="mono">{esc(row.nearest_target_or_t1)}</td>
              <td class="mono">{esc(row.entry_zone)}</td>
              <td class="mono">{esc(row.invalidation_zone)}</td>
              <td>{esc(row.invalidation_source)}</td>
              <td>{esc(row.invalidation_method)}</td>
              <td class="num">{esc(fmt_pct(row.distance_to_target_pct))}</td>
              <td class="num">{esc(fmt_pct(row.distance_to_entry_zone_pct))}</td>
              <td class="num">{esc(fmt_pct(row.distance_to_invalidation_pct))}</td>
              <td>{esc(row.manual_ladder_context)}</td>
              <td>{esc(row.primitive_signal_context)}</td>
              <td>{pill(row.strategy_candidate_state, state_tone(row.strategy_candidate_state))}</td>
              <td><details><summary>{esc(row.strategy_candidate_reason[:110] + ('…' if len(row.strategy_candidate_reason) > 110 else ''))}</summary><div class="small">{esc(row.strategy_candidate_reason)}</div><pre>{esc(json.dumps(row.debug_payload, default=str, indent=2, sort_keys=True))}</pre></details></td>
              <td>{esc(row.source_status)}</td>
            </tr>
            """
        )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.strategy_candidate_state] = counts.get(row.strategy_candidate_state, 0) + 1
    counts_html = " ".join(pill(f"{k}:{v}", state_tone(k)) for k, v in sorted(counts.items()))
    header_cells = "".join(
        f"<th class=\"{'sticky-col-symbol' if h == 'asset' else 'sticky-col-price right' if h == 'current_price' else 'right' if h.startswith('distance_') else ''}\">{esc(h)}</th>"
        for h in headers
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Breath Fibo Strategy Dashboard</title>
  <style>{cockpit_base_css(min_table_width=2600)}</style>
</head>
<body>
  <header class="header">
    <div class="page">
      <h1>Breath / Fibo Strategy Dashboard v1</h1>
      <div class="muted">Market-only strategy hypotheses. No advice, no execution, no account logic.</div>
      <div class="small muted">venue={esc(venue)} · quote={esc(quote)} · interval={esc(interval)} · rendered={esc(rendered_label)}</div>
      {cockpit_nav(account_profile=None)}
      <div class="summary">{counts_html}</div>
      <div class="small muted">Breath/Fibo gives the frame. Regime gives the first Synth layer. Levels give the TP/reload/invalidation map. Nothing executes.</div>
    </div>
  </header>
  <main class="page">
    <section class="panel">
      <div class="table-wrap sticky-table">
        <table>
          <thead>
            <tr>{header_cells}</tr>
          </thead>
          <tbody>
            {''.join(body_rows)}
          </tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>"""


def print_summary(
    *,
    rows: list[DashboardRow],
    output_html: Path,
    interval: str,
) -> None:
    state_counts: dict[str, int] = {}
    invalidation_source_counts: dict[str, int] = {}
    invalidation_method_counts: dict[str, int] = {}
    missing_counts = {
        "canonical_fib_map_missing": 0,
        "regime_missing": 0,
        "legacy_paper_context_missing": 0,
        "primitive_missing": 0,
        "price_missing": 0,
    }
    entry_zone_state_count = 0
    canonical_fib_map_rows = 0
    legacy_context_rows = 0
    latest_ts: datetime | None = None
    for row in rows:
        state_counts[row.strategy_candidate_state] = state_counts.get(row.strategy_candidate_state, 0) + 1
        invalidation_source_counts[row.invalidation_source] = invalidation_source_counts.get(row.invalidation_source, 0) + 1
        invalidation_method_counts[row.invalidation_method] = invalidation_method_counts.get(row.invalidation_method, 0) + 1
        if row.strategy_candidate_state == "ENTRY_ZONE_NEAR":
            entry_zone_state_count += 1
        if "canonical_fib_map=FOUND" in row.source_status:
            canonical_fib_map_rows += 1
        else:
            missing_counts["canonical_fib_map_missing"] += 1
        if "regime=MISSING_SOURCE" in row.source_status:
            missing_counts["regime_missing"] += 1
        if "legacy_paper_context=NOT_READ" not in row.source_status:
            legacy_context_rows += 1
        if "primitive=MISSING_SOURCE" in row.source_status:
            missing_counts["primitive_missing"] += 1
        if "price=MISSING_SOURCE" in row.source_status:
            missing_counts["price_missing"] += 1
        if row.latest_candle_ts_utc and (latest_ts is None or row.latest_candle_ts_utc > latest_ts):
            latest_ts = row.latest_candle_ts_utc
    print(f"report={REPORT_NAME}")
    print(f"version={REPORT_VERSION}")
    print(f"rows={len(rows)}")
    print(f"output_html={output_html}")
    print("broker_private_calls=0 broker_writes=0 order_submission=0 decision_gate_changes=0 execution_planner_changes=0 executor=none account_awareness=0")
    print(f"latest_candle_ts_utc[{interval}]={fmt_ts(latest_ts)}")
    print(f"canonical_fib_map_rows={canonical_fib_map_rows}")
    print(f"legacy_context_rows={legacy_context_rows}")
    print("strategy_states_from_legacy_context=0")
    print("--- strategy_candidate_state counts ---")
    for key, value in sorted(state_counts.items()):
        print(f"{key}={value}")
    print("--- missing source counts ---")
    for key, value in missing_counts.items():
        print(f"{key}={value}")
    print("--- invalidation_source counts ---")
    for key, value in sorted(invalidation_source_counts.items()):
        print(f"{key}={value}")
    print("--- invalidation_method counts ---")
    for key, value in sorted(invalidation_method_counts.items()):
        print(f"{key}={value}")
    print(f"entry_zone_state_count={entry_zone_state_count}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    venue = str(args.venue)
    quote = str(args.quote).upper()
    interval = str(args.interval)
    conn = get_connection()
    try:
        fib_rows = fetch_canonical_fib_rows(
            conn,
            venue=venue,
            quote=quote,
            interval=interval,
        )
        price_rows = fetch_latest_price_rows(conn, venue=venue, interval=interval, limit=max(args.limit, 200))
        regime_by_class, _ = fetch_regime_by_class(conn, venue=venue, interval=interval)
    finally:
        conn.close()

    rows = build_rows(
        interval=interval,
        price_rows=price_rows,
        fib_rows=fib_rows,
        regime_by_class=regime_by_class,
        limit=args.limit,
    )

    html_text = render_html(rows, venue=venue, quote=quote, interval=interval)
    output_html = Path(args.output_html)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    atomic_text_write(html_text, output_html)

    if args.output == "summary":
        print_summary(rows=rows, output_html=output_html, interval=interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
