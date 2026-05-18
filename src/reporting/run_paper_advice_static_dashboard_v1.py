from __future__ import annotations

import argparse
import html
import json
import os
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pymysql
from dotenv import load_dotenv


POLICY_NAME = "paper_advice_static_dashboard_v1"
POLICY_VERSION = "0.1"

DEFAULT_OUTPUT_HTML = "data/reporting/paper_advice_dashboard_v1.html"

ADVICE_ORDER = {
    "WATCH_CORE": 1,
    "WATCH": 2,
    "BLOCK_24H": 3,
    "CORE_CONTEXT": 4,
    "WAIT": 5,
    "NO_NEW_BUY": 6,
    "AVOID": 7,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render latest paper advice observation rows to a static read-only HTML dashboard."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--lifecycle-candle-interval", default="1h")
    parser.add_argument("--output-html", default=DEFAULT_OUTPUT_HTML)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--title", default="Synth Paper Advice")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def get_connection() -> pymysql.connections.Connection:
    load_dotenv(dotenv_path=Path(".env"))

    return pymysql.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME", "synth"),
        cursorclass=pymysql.cursors.DictCursor,
    )


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def fmt_decimal(value: Any, places: int | None = None) -> str:
    dec = to_decimal(value)
    if dec is None:
        return "—"

    if places is not None:
        quant = Decimal("1." + ("0" * places))
        dec = dec.quantize(quant)

    text = format(dec, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    return text


def fmt_score(value: Any) -> str:
    dec = to_decimal(value)
    if dec is None:
        return "—"
    return f"{(dec * Decimal('100')).quantize(Decimal('0.1'))}%"


def fmt_range(low: Any, high: Any) -> str:
    left = fmt_decimal(low)
    right = fmt_decimal(high)

    if left == "—" and right == "—":
        return "—"
    if left == right:
        return left
    return f"{left} → {right}"


def esc(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return html.escape(value.isoformat(sep=" ", timespec="seconds"))
    return html.escape(str(value))


def parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)

    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nat"}:
        return None

    text = text.replace("T", " ").removesuffix("Z")
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def fmt_ts(value: Any) -> str:
    parsed = parse_ts(value)
    if parsed is None:
        return "not available"
    return parsed.isoformat(sep=" ", timespec="seconds")


def fmt_ts_local(value: Any, timezone: str = "Europe/Amsterdam") -> str:
    parsed = parse_ts(value)
    if parsed is None:
        return "not available"

    utc_value = parsed.replace(tzinfo=UTC)
    local_value = utc_value.astimezone(ZoneInfo(timezone))
    return local_value.strftime("%Y-%m-%d %H:%M:%S %Z")


def fmt_ts_local_first(value: Any, timezone: str = "Europe/Amsterdam") -> str:
    parsed = parse_ts(value)
    if parsed is None:
        return "not available"

    utc_text = parsed.strftime("%Y-%m-%d %H:%M:%S UTC")
    local_text = fmt_ts_local(parsed, timezone=timezone)
    return f"{local_text} · {utc_text}"


def latest_lifecycle_candle_ts(rows: list[dict[str, Any]]) -> datetime | None:
    timestamps = [ts for ts in (parse_ts(row.get("latest_close_ts_utc")) for row in rows) if ts is not None]
    if not timestamps:
        return None
    return max(timestamps)


def css_class(value: str | None) -> str:
    if not value:
        return "muted"

    normalized = value.upper()

    mapping = {
        "WATCH_CORE": "good",
        "WATCH": "watch",
        "BLOCK_24H": "block",
        "CORE_CONTEXT": "context",
        "WAIT": "wait",
        "NO_NEW_BUY": "danger",
        "AVOID": "danger",
        "HIGH": "danger",
        "ELEVATED": "block",
        "MODERATE": "watch",
        "UNKNOWN": "muted",
        "UP": "good",
        "DOWN": "danger",
        "PASS": "good",
        "FAIL": "muted",
        "BLOCK_FOR_24H": "block",
        "INSUFFICIENT_SAMPLE": "muted",
    }

    return mapping.get(normalized, "muted")


def zone_labels(leg_direction: str | None) -> tuple[str, str, str]:
    normalized = (leg_direction or "").strip().upper()
    if normalized == "UP":
        return ("Entry zone", "Upside TP zone", "Invalidation below")
    if normalized == "DOWN":
        return ("Reaction zone", "Downside entry zone", "Invalidation above reaction zone")
    return ("Zone", "Target zone", "Invalidation")


def zone_display_cells(row: dict[str, Any]) -> tuple[tuple[str, str], tuple[str, str], tuple[str, str]]:
    leg_direction = str(row.get("leg_direction") or "").strip().upper()
    zone_label, target_label, invalidation_label = zone_labels(leg_direction)
    reaction_zone = fmt_range(row.get("entry_zone_low"), row.get("entry_zone_high"))
    target_zone = fmt_range(row.get("tp_zone_low"), row.get("tp_zone_high"))
    invalidation = fmt_decimal(row.get("invalidation_price"))

    if leg_direction == "DOWN":
        return (
            (zone_label, reaction_zone),
            (invalidation_label, invalidation),
            (target_label, target_zone),
        )

    return (
        (zone_label, reaction_zone),
        (target_label, target_zone),
        (invalidation_label, invalidation),
    )


def _range_bounds(low: Any, high: Any) -> tuple[Decimal | None, Decimal | None]:
    values = [value for value in (to_decimal(low), to_decimal(high)) if value is not None]
    if not values:
        return None, None
    return min(values), max(values)


def zone_lifecycle_start_ts(row: dict[str, Any]) -> datetime | None:
    raw_source_ref = row.get("source_ref_json")
    if raw_source_ref:
        try:
            payload = json.loads(str(raw_source_ref))
            if isinstance(payload, dict):
                zone_ts = parse_ts(payload.get("zone_asof_ts_utc"))
                if zone_ts is not None:
                    return zone_ts
        except json.JSONDecodeError:
            pass

    return parse_ts(row.get("context_ts_utc")) or parse_ts(row.get("asof_ts_utc"))


def is_pullback_invalidated(row: dict[str, Any]) -> bool:
    return bool(row.get("path_invalidated"))


def pullback_lifecycle_badge(row: dict[str, Any]) -> tuple[str, str]:
    price = to_decimal(row.get("latest_close_price"))
    latest_high = to_decimal(row.get("latest_high_price"))
    latest_low = to_decimal(row.get("latest_low_price"))
    reaction_low, reaction_high = _range_bounds(row.get("entry_zone_low"), row.get("entry_zone_high"))
    downside_low, downside_high = _range_bounds(row.get("tp_zone_low"), row.get("tp_zone_high"))

    if price is None:
        return "PULLBACK WATCH", "watch"

    if is_pullback_invalidated(row):
        return "INVALIDATED", "danger"

    latest_overlaps_downside_entry = (
        latest_low is not None
        and latest_high is not None
        and downside_low is not None
        and downside_high is not None
        and latest_low <= downside_high
        and latest_high >= downside_low
    )

    if row.get("path_downside_entry_reached"):
        if (
            reaction_high is not None
            and (price > reaction_high or (latest_high is not None and latest_high > reaction_high))
        ):
            return "REACTION RETEST AFTER ENTRY", "watch"
        if price is not None and downside_high is not None and price > downside_high:
            return "POST-ENTRY BOUNCE", "watch"
        if latest_overlaps_downside_entry:
            return "DOWNSIDE ENTRY REACHED", "context"
        if price is not None and downside_low is not None and price < downside_low:
            return "BELOW DOWNSIDE ENTRY", "block"
        return "DOWNSIDE ENTRY REACHED", "context"

    if downside_low is not None and downside_high is not None:
        if latest_overlaps_downside_entry:
            return "DOWNSIDE ENTRY REACHED", "context"
        if price < downside_low:
            return "BELOW DOWNSIDE ENTRY", "block"

    if reaction_low is not None and reaction_high is not None and reaction_low <= price <= reaction_high:
        return "REACTION ZONE ACTIVE", "watch"

    if (
        reaction_low is not None
        and reaction_high is not None
        and latest_low is not None
        and latest_high is not None
        and latest_low <= reaction_high
        and latest_high >= reaction_low
    ):
        return "REACTION ZONE ACTIVE", "watch"

    if reaction_high is not None and (price > reaction_high or (latest_high is not None and latest_high > reaction_high)):
        return "REACTION RETEST", "watch"

    if (
        reaction_low is not None
        and downside_high is not None
        and price < reaction_low
        and price > downside_high
    ):
        return "PULLBACK IN PROGRESS", "watch"

    return "PULLBACK WATCH", "watch"


def display_badges(row: dict[str, Any]) -> list[tuple[str, str]]:
    badges: list[tuple[str, str]] = []
    leg_direction = str(row.get("leg_direction") or "").strip().upper()
    policy_decision = str(row.get("policy_decision") or "").strip().upper()
    setup_filter_state = str(row.get("setup_filter_state") or "").strip().upper()
    selection_state = str(row.get("selection_state") or "").strip().upper()

    if leg_direction == "DOWN":
        invalidated = is_pullback_invalidated(row)
        badges.append(pullback_lifecycle_badge(row))
        if invalidated:
            badges.append(("EXPIRED MAP", "danger"))
            badges.append(("RECOMPUTE NEEDED", "block"))
            badges.append(("NOT ACTIONABLE", "block"))

        badges.append(("WATCHLIST ONLY", "context"))

        if policy_decision == "BLOCK_FOR_24H" and not invalidated:
            badges.append(("NOT ACTIONABLE", "block"))

    if setup_filter_state == "FAIL":
        badges.append(("SETUP FAILED", "muted"))

    if selection_state in {"AVOID", "NO_EDGE_PERMISSION"}:
        badges.append(("NO EDGE", "danger"))

    return badges


def enrich_candle_context(
    conn: pymysql.connections.Connection,
    rows: list[dict[str, Any]],
    venue: str,
    advice_interval: str,
    lifecycle_candle_interval: str,
) -> None:
    asset_ids = sorted({int(row["asset_id"]) for row in rows if row.get("asset_id") is not None})
    if not asset_ids:
        return

    placeholders = ",".join(["%s"] * len(asset_ids))
    latest_params: list[Any] = [
        venue,
        lifecycle_candle_interval,
        *asset_ids,
        venue,
        lifecycle_candle_interval,
    ]

    lifecycle_starts: dict[int, datetime] = {}
    for row in rows:
        if row.get("asset_id") is None:
            continue
        start_ts = zone_lifecycle_start_ts(row)
        if start_ts is None:
            continue
        asset_id = int(row["asset_id"])
        existing = lifecycle_starts.get(asset_id)
        if existing is None or start_ts < existing:
            lifecycle_starts[asset_id] = start_ts
        row["zone_lifecycle_start_ts_utc"] = start_ts
        row["advice_interval_code"] = advice_interval
        row["lifecycle_candle_interval_code"] = lifecycle_candle_interval

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                c.asset_id,
                c.close_ts_utc,
                c.close_price,
                c.high_price,
                c.low_price
            FROM obs_market_candle c
            JOIN (
                SELECT asset_id, MAX(close_ts_utc) AS max_close_ts_utc
                FROM obs_market_candle
                WHERE venue = %s
                  AND interval_code = %s
                  AND asset_id IN ({placeholders})
                GROUP BY asset_id
            ) latest
              ON latest.asset_id = c.asset_id
             AND latest.max_close_ts_utc = c.close_ts_utc
            WHERE c.venue = %s
              AND c.interval_code = %s
            """,
            latest_params,
        )
        price_rows = {int(row["asset_id"]): row for row in cur.fetchall()}

    for row in rows:
        asset_id = row.get("asset_id")
        if asset_id is None:
            continue
        price_row = price_rows.get(int(asset_id))
        if not price_row:
            continue
        row["latest_close_price"] = price_row.get("close_price")
        row["latest_high_price"] = price_row.get("high_price")
        row["latest_low_price"] = price_row.get("low_price")
        row["latest_close_ts_utc"] = price_row.get("close_ts_utc")

    if not lifecycle_starts:
        return

    min_start_ts = min(lifecycle_starts.values())

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                asset_id,
                close_ts_utc,
                high_price,
                low_price
            FROM obs_market_candle
            WHERE venue = %s
              AND interval_code = %s
              AND asset_id IN ({placeholders})
              AND close_ts_utc >= %s
            ORDER BY asset_id, close_ts_utc
            """,
            [venue, lifecycle_candle_interval, *asset_ids, min_start_ts],
        )
        path_candles = list(cur.fetchall())

    candles_by_asset: dict[int, list[dict[str, Any]]] = {}
    for candle in path_candles:
        candles_by_asset.setdefault(int(candle["asset_id"]), []).append(candle)

    for row in rows:
        if str(row.get("leg_direction") or "").strip().upper() != "DOWN":
            continue
        if row.get("asset_id") is None:
            continue

        start_ts = row.get("zone_lifecycle_start_ts_utc")
        if not isinstance(start_ts, datetime):
            continue

        invalidation = to_decimal(row.get("invalidation_price"))
        downside_low, downside_high = _range_bounds(row.get("tp_zone_low"), row.get("tp_zone_high"))
        path_invalidated = False
        path_downside_entry_reached = False

        for candle in candles_by_asset.get(int(row["asset_id"]), []):
            close_ts = parse_ts(candle.get("close_ts_utc"))
            if close_ts is None or close_ts < start_ts:
                continue

            high = to_decimal(candle.get("high_price"))
            low = to_decimal(candle.get("low_price"))

            if invalidation is not None and high is not None and high >= invalidation:
                path_invalidated = True

            if (
                downside_low is not None
                and downside_high is not None
                and low is not None
                and high is not None
                and low <= downside_high
                and high >= downside_low
            ):
                path_downside_entry_reached = True

        row["path_invalidated"] = path_invalidated
        row["path_downside_entry_reached"] = path_downside_entry_reached


def fetch_latest_rows(
    conn: pymysql.connections.Connection,
    venue: str,
    interval: str,
    lifecycle_candle_interval: str,
    limit: int,
) -> tuple[datetime | None, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT MAX(asof_ts_utc) AS latest_asof
            FROM paper_advice_observation
            WHERE venue = %(venue)s
              AND interval_code = %(interval)s
            """,
            {"venue": venue, "interval": interval},
        )
        latest = cur.fetchone()

    latest_asof = latest["latest_asof"] if latest else None

    if latest_asof is None:
        return None, [], [], None

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                advice_state,
                COUNT(*) AS n
            FROM paper_advice_observation
            WHERE venue = %(venue)s
              AND interval_code = %(interval)s
              AND asof_ts_utc = %(latest_asof)s
            GROUP BY advice_state
            ORDER BY n DESC, advice_state ASC
            """,
            {"venue": venue, "interval": interval, "latest_asof": latest_asof},
        )
        counts = list(cur.fetchall())

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                asset_id,
                symbol,
                priority_rank,
                selection_state,
                selection_bias,
                selection_score,
                setup_filter_state,
                setup_filter_reason,
                policy_decision,
                suggested_horizon,
                allowed_now,
                aplus_bucket,
                aplus_phase,
                aplus_coherence,
                aplus_field,
                aplus_geometry,
                aplus_structural_role,
                aplus_expansion_quality,
                aplus_anchor_strength,
                aplus_strategic_bias,
                leg_direction,
                entry_zone_low,
                entry_zone_high,
                entry_zone_type,
                tp_zone_low,
                tp_zone_high,
                tp_zone_type,
                invalidation_price,
                zone_confidence_score,
                zone_alignment_score,
                advice_state,
                advice_action,
                confidence_score,
                risk_label,
                reason_codes_json,
                source_ref_json,
                asof_ts_utc,
                context_ts_utc
            FROM paper_advice_observation
            WHERE venue = %(venue)s
              AND interval_code = %(interval)s
              AND asof_ts_utc = %(latest_asof)s
            ORDER BY
                CASE advice_state
                    WHEN 'WATCH_CORE' THEN 1
                    WHEN 'WATCH' THEN 2
                    WHEN 'BLOCK_24H' THEN 3
                    WHEN 'CORE_CONTEXT' THEN 4
                    WHEN 'WAIT' THEN 5
                    WHEN 'NO_NEW_BUY' THEN 6
                    WHEN 'AVOID' THEN 7
                    ELSE 99
                END,
                confidence_score DESC,
                priority_rank IS NULL,
                priority_rank ASC,
                symbol ASC
            LIMIT %(limit)s
            """,
            {
                "venue": venue,
                "interval": interval,
                "latest_asof": latest_asof,
                "limit": int(limit),
            },
        )
        rows = list(cur.fetchall())

    enrich_candle_context(conn, rows, venue, interval, lifecycle_candle_interval)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                strategy_runtime_snapshot_id,
                snapshot_ts_utc,
                git_commit,
                runtime_scope,
                venue,
                interval_code,
                chain_name,
                live_trading_enabled,
                decision_gate_enabled,
                execution_enabled,
                notes
            FROM strategy_runtime_snapshot
            WHERE interval_code = %(interval)s
            ORDER BY strategy_runtime_snapshot_id DESC
            LIMIT 1
            """,
            {"interval": interval},
        )
        runtime = cur.fetchone()

    return latest_asof, rows, counts, runtime


def is_expired_recompute_map(row: dict[str, Any]) -> bool:
    leg_direction = str(row.get("leg_direction") or "").strip().upper()
    return leg_direction == "DOWN" and is_pullback_invalidated(row)


def split_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    primary_states = {"WATCH_CORE", "WATCH", "BLOCK_24H", "CORE_CONTEXT", "WAIT"}
    expired = [row for row in rows if is_expired_recompute_map(row)]
    expired_ids = {id(row) for row in expired}
    primary = [
        row
        for row in rows
        if id(row) not in expired_ids and str(row.get("advice_state", "")).upper() in primary_states
    ]
    primary_ids = {id(row) for row in primary}
    defensive = [row for row in rows if id(row) not in primary_ids and id(row) not in expired_ids]
    return primary, expired, defensive


def render_count_cards(counts: list[dict[str, Any]]) -> str:
    cards = []

    for row in counts:
        state = str(row["advice_state"])
        n = row["n"]
        cards.append(
            f"""
            <div class="metric {css_class(state)}">
                <div class="metric-label">{esc(state)}</div>
                <div class="metric-value">{esc(n)}</div>
            </div>
            """
        )

    return "\n".join(cards)


def render_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty">No rows.</div>'

    body = []

    for row in rows:
        advice_state = str(row.get("advice_state") or "")
        risk_label = str(row.get("risk_label") or "")
        leg_direction = str(row.get("leg_direction") or "")

        reason_codes = ""
        raw_reason_codes = row.get("reason_codes_json")
        if raw_reason_codes:
            try:
                parsed = json.loads(str(raw_reason_codes))
                if isinstance(parsed, list):
                    reason_codes = ", ".join(str(item) for item in parsed)
                elif isinstance(parsed, dict):
                    reason_codes = ", ".join(f"{k}={v}" for k, v in parsed.items())
                else:
                    reason_codes = str(parsed)
            except json.JSONDecodeError:
                reason_codes = str(raw_reason_codes)

        rank = row.get("priority_rank")
        rank_text = "—" if rank is None else str(rank)

        zone_cell_1, zone_cell_2, zone_cell_3 = zone_display_cells(row)
        row_class = "expired" if leg_direction.strip().upper() == "DOWN" and is_pullback_invalidated(row) else ""
        badges = display_badges(row)
        badge_html = ""
        if badges:
            badge_html = "".join(
                f'<span class="pill {esc(css_name)}">{esc(label)}</span>' for label, css_name in badges
            )
            badge_html = f'<div class="badge-row">{badge_html}</div>'

        body.append(
            f"""
            <tr class="{esc(row_class)}">
                <td class="mono center">{esc(rank_text)}</td>
                <td class="symbol">
                    {esc(row.get("symbol"))}
                    <div><span class="pill {css_class(leg_direction)}">{esc(leg_direction or "—")}</span></div>
                    {badge_html}
                </td>
                <td><span class="pill {css_class(advice_state)}">{esc(advice_state)}</span></td>
                <td>{esc(row.get("advice_action"))}</td>
                <td class="mono right">{fmt_score(row.get("confidence_score"))}</td>
                <td><span class="pill {css_class(risk_label)}">{esc(risk_label)}</span></td>
                <td class="mono">
                    <div class="cell-label">{esc(zone_cell_1[0])}</div>
                    {zone_cell_1[1]}
                </td>
                <td class="mono">
                    <div class="cell-label">{esc(zone_cell_2[0])}</div>
                    {zone_cell_2[1]}
                </td>
                <td class="mono">
                    <div class="cell-label">{esc(zone_cell_3[0])}</div>
                    {zone_cell_3[1]}
                </td>
                <td>{esc(row.get("selection_state"))}</td>
                <td>{esc(row.get("setup_filter_state"))}</td>
                <td>{esc(row.get("policy_decision"))}</td>
                <td>{esc(row.get("aplus_bucket"))}</td>
                <td class="muted small">{esc(reason_codes)}</td>
            </tr>
            """
        )

    return f"""
    <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th>Rank</th>
                    <th>Symbol / Leg</th>
                    <th>Advice</th>
                    <th>Action</th>
                    <th>Conf</th>
                    <th>Risk</th>
                    <th>Zone 1</th>
                    <th>Zone 2</th>
                    <th>Zone 3</th>
                    <th>Selection</th>
                    <th>Setup</th>
                    <th>Policy</th>
                    <th>A+</th>
                    <th>Reasons</th>
                </tr>
            </thead>
            <tbody>
                {''.join(body)}
            </tbody>
        </table>
    </div>
    """


def render_html(
    title: str,
    venue: str,
    interval: str,
    lifecycle_candle_interval: str,
    latest_asof: datetime | None,
    rows: list[dict[str, Any]],
    counts: list[dict[str, Any]],
    runtime: dict[str, Any] | None,
) -> str:
    generated_ts = datetime.now(UTC).replace(tzinfo=None)
    primary_rows, expired_rows, defensive_rows = split_rows(rows)
    latest_lifecycle_ts = latest_lifecycle_candle_ts(rows)

    latest_text = fmt_ts_local_first(latest_asof)
    latest_lifecycle_text = fmt_ts_local_first(latest_lifecycle_ts)
    generated_text = fmt_ts_local_first(generated_ts)
    runtime_text = "—"
    runtime_flags = "—"

    if runtime:
        runtime_text = (
            f"id={runtime.get('strategy_runtime_snapshot_id')} "
            f"snapshot={runtime.get('snapshot_ts_utc')} "
            f"chain={runtime.get('chain_name')}"
        )
        runtime_flags = (
            f"live_trading_enabled={runtime.get('live_trading_enabled')} · "
            f"decision_gate_enabled={runtime.get('decision_gate_enabled')} · "
            f"execution_enabled={runtime.get('execution_enabled')}"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="300">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{esc(title)}</title>
    <style>
        :root {{
            --bg: #0b1020;
            --panel: #121a2f;
            --panel2: #17213b;
            --line: #2a3659;
            --text: #edf2ff;
            --muted: #95a1bf;
            --good: #34d399;
            --watch: #fbbf24;
            --block: #fb923c;
            --danger: #fb7185;
            --context: #60a5fa;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            background: radial-gradient(circle at top left, #1f2a4d, var(--bg) 36rem);
            color: var(--text);
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }}
        .page {{
            max-width: 1600px;
            margin: 0 auto;
            padding: 24px;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            gap: 16px;
            align-items: flex-start;
            margin-bottom: 18px;
        }}
        h1 {{
            margin: 0 0 8px 0;
            font-size: 28px;
            letter-spacing: -0.04em;
        }}
        h2 {{
            margin: 26px 0 12px 0;
            font-size: 18px;
            letter-spacing: -0.02em;
        }}
        .subtitle {{
            color: var(--muted);
            font-size: 14px;
            line-height: 1.5;
        }}
        .badge {{
            display: inline-flex;
            align-items: center;
            border: 1px solid var(--line);
            background: rgba(18, 26, 47, 0.85);
            border-radius: 999px;
            padding: 7px 10px;
            color: var(--muted);
            font-size: 13px;
            white-space: nowrap;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
            margin: 18px 0;
        }}
        .metric {{
            border: 1px solid var(--line);
            background: linear-gradient(180deg, var(--panel), var(--panel2));
            border-radius: 18px;
            padding: 14px;
            min-height: 86px;
        }}
        .metric-label {{
            color: var(--muted);
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }}
        .metric-value {{
            font-size: 30px;
            font-weight: 800;
            margin-top: 8px;
        }}
        .panel {{
            border: 1px solid var(--line);
            background: rgba(18, 26, 47, 0.9);
            border-radius: 22px;
            padding: 16px;
            margin-top: 16px;
            box-shadow: 0 18px 50px rgba(0,0,0,0.26);
        }}
        .table-wrap {{
            width: 100%;
            overflow-x: auto;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        th {{
            text-align: left;
            color: var(--muted);
            font-weight: 650;
            border-bottom: 1px solid var(--line);
            padding: 10px 8px;
            white-space: nowrap;
        }}
        td {{
            border-bottom: 1px solid rgba(42, 54, 89, 0.55);
            padding: 10px 8px;
            vertical-align: top;
        }}
        tr:hover {{
            background: rgba(96, 165, 250, 0.07);
        }}
        tr.expired {{
            opacity: 0.68;
        }}
        tr.expired td:nth-child(7),
        tr.expired td:nth-child(8),
        tr.expired td:nth-child(9) {{
            color: var(--muted);
        }}
        .symbol {{
            font-weight: 800;
            font-size: 14px;
        }}
        .mono {{
            font-variant-numeric: tabular-nums;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        }}
        .right {{ text-align: right; }}
        .center {{ text-align: center; }}
        .small {{ font-size: 12px; }}
        .muted {{ color: var(--muted); }}
        .cell-label {{
            color: var(--muted);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            margin-bottom: 2px;
        }}
        .pill {{
            display: inline-flex;
            border-radius: 999px;
            border: 1px solid var(--line);
            padding: 4px 8px;
            font-size: 12px;
            white-space: nowrap;
            background: rgba(255,255,255,0.04);
        }}
        .badge-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            margin-top: 6px;
        }}
        .good {{ color: var(--good); }}
        .watch {{ color: var(--watch); }}
        .block {{ color: var(--block); }}
        .danger {{ color: var(--danger); }}
        .context {{ color: var(--context); }}
        .wait {{ color: var(--muted); }}
        .empty {{
            color: var(--muted);
            padding: 18px;
        }}
        .footer {{
            color: var(--muted);
            font-size: 12px;
            margin-top: 24px;
            line-height: 1.6;
        }}
        @media (max-width: 860px) {{
            .page {{ padding: 14px; }}
            .header {{ flex-direction: column; }}
            h1 {{ font-size: 23px; }}
            table {{ font-size: 12px; }}
            th, td {{ padding: 8px 6px; }}
        }}
    </style>
</head>
<body>
    <main class="page">
        <section class="header">
            <div>
                <h1>{esc(title)}</h1>
                <div class="subtitle">
                    Read-only paper navigation · venue={esc(venue)} · advice interval={esc(interval)} · lifecycle candles={esc(lifecycle_candle_interval)}<br>
                    latest advice snapshot: {esc(latest_text)}<br>
                    latest lifecycle candle: {esc(latest_lifecycle_text)}<br>
                    dashboard rendered: {esc(generated_text)}<br>
                    Setup/policy changes when the 4h chain writes a new paper_advice_observation snapshot. Lifecycle badges refresh from {esc(lifecycle_candle_interval)} candle path data when the dashboard refresh runner runs.
                </div>
            </div>
            <div class="badge">broker_calls=0 · broker_writes=0 · order_submission=0</div>
        </section>

        <section class="grid">
            {render_count_cards(counts)}
        </section>

        <section class="panel">
            <h2>Navigation candidates</h2>
            {render_table(primary_rows)}
        </section>

        <section class="panel">
            <h2>Expired / recompute-needed maps</h2>
            {render_table(expired_rows)}
        </section>

        <section class="panel">
            <h2>Defensive / no-new-buy rows</h2>
            {render_table(defensive_rows)}
        </section>

        <section class="footer">
            Generated: {esc(generated_text)}<br>
            Runtime: {esc(runtime_text)}<br>
            Runtime flags: {esc(runtime_flags)}<br>
            Boundary: this page is display-only. It does not call the broker, decision_gate, execution_planner, executor, or order APIs.
        </section>
    </main>
</body>
</html>
"""


def write_html(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def print_table(
    path: Path,
    latest_asof: datetime | None,
    rows: list[dict[str, Any]],
    counts: list[dict[str, Any]],
    lifecycle_candle_interval: str,
) -> None:
    print(f"report={POLICY_NAME} version={POLICY_VERSION}")
    print("scope=static-readonly paper-navigation")
    print("broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    print(f"latest_asof={latest_asof}")
    print(f"lifecycle_candle_interval={lifecycle_candle_interval}")
    print(f"rows={len(rows)}")
    print(f"output_html={path}")
    print()
    print("--- advice state counts ---")
    for row in counts:
        print(f"{row['advice_state']}={row['n']}")


def main() -> int:
    args = parse_args()
    output_path = Path(args.output_html)

    conn = get_connection()
    try:
        latest_asof, rows, counts, runtime = fetch_latest_rows(
            conn,
            venue=str(args.venue),
            interval=str(args.interval),
            lifecycle_candle_interval=str(args.lifecycle_candle_interval),
            limit=int(args.limit),
        )
    finally:
        conn.close()

    html_content = render_html(
        title=str(args.title),
        venue=str(args.venue),
        interval=str(args.interval),
        lifecycle_candle_interval=str(args.lifecycle_candle_interval),
        latest_asof=latest_asof,
        rows=rows,
        counts=counts,
        runtime=runtime,
    )

    write_html(output_path, html_content)

    if args.output == "json":
        print(
            json.dumps(
                {
                    "policy_name": POLICY_NAME,
                    "policy_version": POLICY_VERSION,
                    "latest_asof": latest_asof.isoformat(sep=" ") if latest_asof else None,
                    "lifecycle_candle_interval": str(args.lifecycle_candle_interval),
                    "rows": len(rows),
                    "output_html": str(output_path),
                    "broker_calls": 0,
                    "broker_writes": 0,
                    "order_submission": 0,
                    "live_orders": 0,
                },
                indent=2,
            )
        )
    else:
        print_table(output_path, latest_asof, rows, counts, str(args.lifecycle_candle_interval))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
