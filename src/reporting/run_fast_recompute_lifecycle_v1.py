from __future__ import annotations

import argparse
import html
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.common.db import get_connection
from src.market_data.market_price_snapshot_v1 import (
    MarketPriceSnapshot,
    fetch_latest_prices_by_symbol,
)
from src.reporting.dashboard_style_v1 import cockpit_base_css, cockpit_nav, pill_classes
from src.reporting.entry_zone_state_v1 import (
    classify_price_progress_state,
    classify_target_state,
)
from src.reporting.fast_lifecycle_recompute_v1 import classify_fast_lifecycle
from src.reporting.next_zone_preview_v1 import format_zone, preview_next_zones


REPORT_NAME = "fast_recompute_lifecycle_v1"
REPORT_VERSION = "0.1"

DEFAULT_OUTPUT_HTML = "/var/www/html/synth/recompute-lifecycle.html"

RECOMPUTE_TRIGGER_LABELS = {
    "MAP_RECOMPUTE_NEEDED",
    "TARGET_REACHED_STALE",
    "RECLAIM_CONFIRMED",
    "DOWN_MAP_INVALIDATED_BY_RECLAIM",
    "INVALIDATION_TOUCHED",
    "UP_MAP_INVALIDATED_BY_BREAKDOWN",
    "TARGET_OVERSHOT",
}

TARGET_FINISHED_LABELS = {
    "TARGET_REACHED",
    "DOWNSIDE_TARGET_REACHED",
}


@dataclass(frozen=True)
class RecomputeLifecycleRow:
    asset_id: int | None
    symbol: str
    venue: str
    interval_code: str
    asof_ts_utc: datetime | None
    current_price: Decimal | None
    market_price_age_min: Decimal | None
    advice_age_min: Decimal | None
    lifecycle_state: str
    recompute_needed: bool
    recompute_reason: str
    leg_direction: str
    target_state: str
    price_progress_state: str
    next_zone_state: str
    next_reaction_zone: str
    next_target_zone: str
    recommended_refresh_scope: str
    freshness_state: str
    post_refresh_state: str
    cooldown_label: str
    display_severity: str
    priority: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a market-only recompute lifecycle worklist from latest paper advice maps."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--quote", default="EUR")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--fresh-min", type=Decimal, default=Decimal("30"))
    parser.add_argument("--output-html", default=None)
    parser.add_argument("--output", choices=("summary", "table", "json", "none"), default="table")
    return parser.parse_args()


def esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def dec_text(value: Decimal | None, places: str = "0.000000") -> str:
    if value is None:
        return ""
    try:
        return str(value.quantize(Decimal(places)))
    except Exception:
        return str(value)


def age_minutes(ts: datetime | None, *, now_utc: datetime) -> Decimal | None:
    if ts is None:
        return None
    return Decimal(str((now_utc.replace(tzinfo=None) - ts).total_seconds())) / Decimal("60")


def now_local_label() -> str:
    return datetime.now(UTC).astimezone(ZoneInfo("Europe/Amsterdam")).strftime(
        "%Y-%m-%d %H:%M:%S %Z Amsterdam time"
    )


def labels_text(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            parts.extend(str(item).upper() for item in value if item is not None)
        else:
            parts.append(str(value).upper())
    return " ".join(parts)


def css_class(value: str | None) -> str:
    normalized = str(value or "").upper()
    if normalized in {
        "ZONE_AND_ADVICE_RECOMPUTE",
        "MAP_RECOMPUTE_NEEDED",
        "REFRESH_NEEDED",
        "RECOMPUTED_BUT_STILL_TRIGGERING",
        "REFRESH_FAILED_OR_STALE",
        "DISPLAY_CRITICAL",
    }:
        return pill_classes("bad", normalized)
    if normalized in {
        "ADVICE_ONLY_REVIEW",
        "WAIT_FOR_NEXT_CANDLE",
        "TARGET_REACHED",
        "DOWNSIDE_TARGET_REACHED",
        "RECLAIM_CONFIRMED",
        "INVALIDATION_TOUCHED",
        "TARGET_REACHED_STALE",
        "TARGET_OVERSHOT",
        "COOLDOWN_MONITOR",
        "DISPLAY_WATCH",
    }:
        return pill_classes("warn", normalized)
    if normalized in {
        "SKIP_ACTIVE_MAP",
        "CURRENT_MAP_ACTIVE",
        "FRESH_REVIEW",
        "NO_REFRESH_NEEDED",
        "REFRESHED_THIS_RUN",
        "DISPLAY_CONTEXT",
    }:
        return pill_classes("ok", normalized)
    if normalized in {
        "REFRESHED_RECENTLY",
        "COOLDOWN_ALREADY_REFRESHED_THIS_CANDLE",
        "SKIPPED_ALREADY_REFRESHED_THIS_ASOF",
        "DISPLAY_MUTED",
    }:
        return pill_classes("muted", normalized)
    if normalized.startswith("SKIP"):
        return pill_classes("muted", normalized)
    return pill_classes("muted", normalized)


def fetch_latest_advice_rows(
    conn: Any,
    *,
    venue: str,
    interval: str,
    limit: int,
) -> tuple[datetime | None, list[dict[str, Any]]]:
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

    latest_asof = None if not latest else latest.get("latest_asof")
    if latest_asof is None:
        return None, []

    with conn.cursor() as cur:
        cur.execute(
            """
            WITH ranked_advice AS (
                SELECT
                    paper_advice_observation_id,
                    asset_id,
                    symbol,
                    venue,
                    interval_code,
                    asof_ts_utc,
                    selection_state,
                    setup_filter_state,
                    setup_filter_reason,
                    policy_decision,
                    advice_state,
                    advice_action,
                    leg_direction,
                    entry_zone_low,
                    entry_zone_high,
                    tp_zone_low,
                    tp_zone_high,
                    invalidation_price,
                    confidence_score,
                    source_ref_json,
                    ROW_NUMBER() OVER (
                        PARTITION BY asset_id
                        ORDER BY asof_ts_utc DESC, paper_advice_observation_id DESC
                    ) AS rn
                FROM paper_advice_observation
                WHERE venue = %(venue)s
                  AND interval_code = %(interval)s
            )
            SELECT
                asset_id,
                symbol,
                venue,
                interval_code,
                asof_ts_utc,
                selection_state,
                setup_filter_state,
                setup_filter_reason,
                policy_decision,
                advice_state,
                advice_action,
                leg_direction,
                entry_zone_low,
                entry_zone_high,
                tp_zone_low,
                tp_zone_high,
                invalidation_price,
                confidence_score,
                source_ref_json
            FROM ranked_advice
            WHERE rn = 1
            ORDER BY
                confidence_score DESC,
                symbol ASC
            LIMIT %(limit)s
            """,
            {
                "venue": venue,
                "interval": interval,
                "limit": int(limit),
            },
        )
        return latest_asof, list(cur.fetchall())


def json_loads_dict(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def fast_recompute_refresh_ref(row: dict[str, Any]) -> dict[str, Any]:
    source_ref = json_loads_dict(row.get("source_ref_json"))
    refresh_ref = json_loads_dict(source_ref.get("fast_recompute_refresh"))
    if refresh_ref.get("refreshed_by") != "fast_recompute_lifecycle_refresh_v1":
        return {}
    return refresh_ref


def same_asof_text(left: Any, right: Any) -> bool:
    def text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.isoformat(sep=" ", timespec="microseconds")
        return str(value)

    return text(left) == text(right)


def classify_post_refresh_display(
    *,
    row: dict[str, Any],
    recompute_needed: bool,
    recommended_refresh_scope: str,
    lifecycle_state: str,
) -> tuple[str, str, str]:
    refresh_ref = fast_recompute_refresh_ref(row)
    if not refresh_ref:
        if recommended_refresh_scope == "SKIP_ACTIVE_MAP":
            return "NO_REFRESH_NEEDED", "", "DISPLAY_CONTEXT"
        if recommended_refresh_scope in {"ZONE_AND_ADVICE_RECOMPUTE", "ADVICE_ONLY_REVIEW"}:
            return "REFRESH_NEEDED", "", "DISPLAY_CRITICAL"
        return "NO_REFRESH_NEEDED", "", "DISPLAY_MUTED"

    cooldown_label = "COOLDOWN_ALREADY_REFRESHED_THIS_CANDLE"
    if same_asof_text(row.get("asof_ts_utc"), refresh_ref.get("recompute_asof_ts_utc")):
        if lifecycle_state in {"INVALIDATION_TOUCHED"}:
            return "RECOMPUTED_BUT_STILL_TRIGGERING", cooldown_label, "DISPLAY_CRITICAL"
        if recompute_needed or recommended_refresh_scope == "ZONE_AND_ADVICE_RECOMPUTE":
            return "COOLDOWN_MONITOR", cooldown_label, "DISPLAY_WATCH"
        return "REFRESHED_RECENTLY", cooldown_label, "DISPLAY_MUTED"

    if recompute_needed:
        return "REFRESH_NEEDED", "", "DISPLAY_CRITICAL"
    return "REFRESHED_RECENTLY", cooldown_label, "DISPLAY_MUTED"


def recommended_scope(
    *,
    label_text: str,
    lifecycle_state: str,
    recompute_needed: bool,
    next_zone_state: str,
    advice_age_min: Decimal | None,
    fresh_min: Decimal,
) -> tuple[str, str, int]:
    if "UNKNOWN" in label_text or next_zone_state == "NEXT_ZONE_UNKNOWN":
        return "SKIP_UNKNOWN_DATA", "UNKNOWN_DATA", 90
    if (
        recompute_needed
        or "MAP_RECOMPUTE_NEEDED" in label_text
        or any(label in label_text for label in RECOMPUTE_TRIGGER_LABELS)
    ):
        if "RECLAIM_CONFIRMED" in label_text or "INVALIDATION_TOUCHED" in label_text:
            return "ZONE_AND_ADVICE_RECOMPUTE", "RECLAIM_OR_INVALIDATION_TRIGGER", 1
        if "TARGET_REACHED_STALE" in label_text:
            return "ZONE_AND_ADVICE_RECOMPUTE", "TARGET_REACHED_STALE_TRIGGER", 2
        return "ZONE_AND_ADVICE_RECOMPUTE", "RECOMPUTE_TRIGGER", 0
    if any(label in label_text for label in TARGET_FINISHED_LABELS):
        if advice_age_min is not None and advice_age_min <= fresh_min:
            return "WAIT_FOR_NEXT_CANDLE", "FRESH_TARGET_REVIEW", 4
        return "ADVICE_ONLY_REVIEW", "TARGET_FINISHED_REVIEW", 3
    if lifecycle_state in {"ACTIVE_MAP", "CURRENT_MAP_ACTIVE"}:
        return "SKIP_ACTIVE_MAP", "ACTIVE_MAP", 99
    return "SKIP_UNKNOWN_DATA", "NO_REFRESH_TRIGGER", 98


def build_recompute_rows(
    advice_rows: list[dict[str, Any]],
    *,
    venue: str,
    interval: str,
    price_by_symbol: dict[str, MarketPriceSnapshot],
    fresh_min: Decimal = Decimal("30"),
    now_utc: datetime | None = None,
) -> list[RecomputeLifecycleRow]:
    now = now_utc or datetime.now(UTC)
    output: list[RecomputeLifecycleRow] = []
    for row in advice_rows:
        symbol = str(row.get("symbol") or "").upper()
        snapshot = price_by_symbol.get(symbol)
        current_price = None if snapshot is None else snapshot.price
        lifecycle = classify_fast_lifecycle(
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            tp_zone_low=row.get("tp_zone_low"),
            tp_zone_high=row.get("tp_zone_high"),
            invalidation_price=row.get("invalidation_price"),
        )
        target_state = classify_target_state(
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            tp_zone_low=row.get("tp_zone_low"),
            tp_zone_high=row.get("tp_zone_high"),
        )
        progress = classify_price_progress_state(
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            entry_zone_low=row.get("entry_zone_low"),
            entry_zone_high=row.get("entry_zone_high"),
            tp_zone_low=row.get("tp_zone_low"),
            tp_zone_high=row.get("tp_zone_high"),
            in_position_context=False,
        )
        next_preview = preview_next_zones(
            symbol=symbol,
            leg_direction=row.get("leg_direction"),
            current_price=current_price,
            entry_zone_low=row.get("entry_zone_low"),
            entry_zone_high=row.get("entry_zone_high"),
            tp_zone_low=row.get("tp_zone_low"),
            tp_zone_high=row.get("tp_zone_high"),
            invalidation_price=row.get("invalidation_price"),
            lifecycle_state=lifecycle.lifecycle_state,
            lifecycle_reason=lifecycle.recompute_reason,
            target_state=target_state,
            price_progress_state=progress.progress_state,
        )
        text = labels_text(
            lifecycle.lifecycle_state,
            lifecycle.recompute_reason,
            target_state,
            progress.progress_state,
        )
        advice_age = age_minutes(row.get("asof_ts_utc"), now_utc=now)
        scope, freshness_state, priority = recommended_scope(
            label_text=text,
            lifecycle_state=lifecycle.lifecycle_state,
            recompute_needed=lifecycle.recompute_needed,
            next_zone_state=next_preview.next_zone_state,
            advice_age_min=advice_age,
            fresh_min=fresh_min,
        )
        if scope in {"SKIP_ACTIVE_MAP", "SKIP_UNKNOWN_DATA"} and not any(
            label in text for label in RECOMPUTE_TRIGGER_LABELS | TARGET_FINISHED_LABELS
        ):
            continue
        post_refresh_state, cooldown_label, display_severity = classify_post_refresh_display(
            row=row,
            recompute_needed=lifecycle.recompute_needed,
            recommended_refresh_scope=scope,
            lifecycle_state=lifecycle.lifecycle_state,
        )
        output.append(
            RecomputeLifecycleRow(
                asset_id=None if row.get("asset_id") is None else int(row["asset_id"]),
                symbol=symbol,
                venue=str(row.get("venue") or venue),
                interval_code=str(row.get("interval_code") or interval),
                asof_ts_utc=row.get("asof_ts_utc"),
                current_price=current_price,
                market_price_age_min=None if snapshot is None else age_minutes(snapshot.observed_ts_utc, now_utc=now),
                advice_age_min=advice_age,
                lifecycle_state=lifecycle.lifecycle_state,
                recompute_needed=lifecycle.recompute_needed,
                recompute_reason=lifecycle.recompute_reason,
                leg_direction=str(row.get("leg_direction") or ""),
                target_state=target_state,
                price_progress_state=progress.progress_state,
                next_zone_state=next_preview.next_zone_state,
                next_reaction_zone=format_zone(next_preview.next_reaction_zone),
                next_target_zone=format_zone(next_preview.next_target_zone),
                recommended_refresh_scope=scope,
                freshness_state=freshness_state,
                post_refresh_state=post_refresh_state,
                cooldown_label=cooldown_label,
                display_severity=display_severity,
                priority=priority,
            )
        )

    output.sort(
        key=lambda item: (
            item.priority,
            item.market_price_age_min is None,
            item.market_price_age_min or Decimal("999999"),
            item.symbol,
        )
    )
    return output


def row_to_json(row: RecomputeLifecycleRow) -> dict[str, Any]:
    out = asdict(row)
    for key, value in list(out.items()):
        if isinstance(value, Decimal):
            out[key] = str(value)
        elif isinstance(value, datetime):
            out[key] = value.isoformat(sep=" ", timespec="microseconds")
    return out


def render_rows_table(rows: list[RecomputeLifecycleRow], *, limit: int | None = None) -> str:
    selected = rows if limit is None else rows[:limit]
    if not selected:
        return '<div class="empty">No recompute lifecycle rows.</div>'
    body = []
    for row in selected:
        recompute_label = "MAP_RECOMPUTE_NEEDED" if row.recompute_needed else "SKIP_ACTIVE_MAP"
        if row.post_refresh_state in {"REFRESHED_RECENTLY", "COOLDOWN_MONITOR"}:
            recompute_label = row.post_refresh_state
        body.append(
            "<tr>"
            f"<td class='sticky-symbol'><strong>{esc(row.symbol)}</strong></td>"
            f"<td><span class='pill {css_class(row.post_refresh_state)}'>{esc(row.post_refresh_state)}</span></td>"
            f"<td><span class='pill {css_class(row.display_severity)}'>{esc(row.display_severity)}</span></td>"
            f"<td><span class='pill {css_class(row.recommended_refresh_scope)}'>{esc(row.recommended_refresh_scope)}</span></td>"
            f"<td><span class='pill {css_class(row.lifecycle_state)}'>{esc(row.lifecycle_state)}</span></td>"
            f"<td><span class='pill {css_class(recompute_label)}'>{esc(recompute_label)}</span></td>"
            f"<td class='small'>{esc(row.recompute_reason)}</td>"
            f"<td><span class='pill {css_class(row.cooldown_label)}'>{esc(row.cooldown_label)}</span></td>"
            f"<td class='num sticky-price'>{esc(dec_text(row.current_price))}</td>"
            f"<td>{esc(row.leg_direction)}</td>"
            f"<td><span class='pill {css_class(row.next_zone_state)}'>{esc(row.next_zone_state)}</span></td>"
            f"<td class='zone-value'>{esc(row.next_reaction_zone)}</td>"
            f"<td class='zone-value'>{esc(row.next_target_zone)}</td>"
            f"<td class='num'>{esc(dec_text(row.market_price_age_min, '0.1'))}</td>"
            f"<td class='num'>{esc(dec_text(row.advice_age_min, '0.1'))}</td>"
            f"<td><span class='pill {css_class(row.freshness_state)}'>{esc(row.freshness_state)}</span></td>"
            "</tr>"
        )
    return f"""
    <div class="table-wrap">
      <table>
        <thead>
            <tr>
              <th class="sticky-symbol">Symbol</th>
              <th>Post-refresh state</th>
              <th>Display severity</th>
              <th>Refresh scope</th>
              <th>Lifecycle</th>
              <th>Recompute</th>
              <th>Reason</th>
              <th>Cooldown</th>
            <th class="sticky-price">Current price</th>
            <th>Old leg</th>
            <th>Next-zone state</th>
            <th>Next reaction zone</th>
            <th>Next target zone</th>
            <th>Price age min</th>
            <th>Advice age min</th>
            <th>Freshness</th>
          </tr>
        </thead>
        <tbody>{''.join(body)}</tbody>
      </table>
    </div>
    """


def render_html(rows: list[RecomputeLifecycleRow], *, venue: str, interval: str) -> str:
    generated = now_local_label()
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Synth Recompute Lifecycle</title>
  <style>{cockpit_base_css(min_table_width=1500)}</style>
</head>
<body>
  <header>
    <h1>Maps needing refresh</h1>
    <div class="muted">Rendered {esc(generated)} · venue={esc(venue)} · interval={esc(interval)}</div>
    {cockpit_nav()}
    <div class="legend">
      <div><strong>Refresh candidate, not trade advice.</strong></div>
      <div>This page is market-only and account-agnostic. It identifies stale, finished, reclaimed, or invalidated advice maps for future zone/advice refresh.</div>
      <div><strong>Post-refresh state</strong> separates old trigger labels from refreshed, cooldown, and still-actionable refresh state.</div>
      <div><strong>Safety</strong>: broker_private_calls=0 broker_writes=0 order_submission=0 executor=none account_awareness=0</div>
    </div>
  </header>
  <main>
    <section class="card priority">
      <h2>Maps needing refresh <span class="muted">({len(rows)})</span></h2>
      {render_rows_table(rows)}
    </section>
  </main>
</body>
</html>
"""


def print_table(rows: list[RecomputeLifecycleRow]) -> None:
    headers = [
        "symbol",
        "post_refresh",
        "display_severity",
        "scope",
        "lifecycle",
        "recompute",
        "reason",
        "cooldown",
        "price",
        "leg",
        "next_zone",
        "next_reaction",
        "next_target",
    ]
    print("\t".join(headers))
    for row in rows:
        print(
            "\t".join(
                [
                    row.symbol,
                    row.post_refresh_state,
                    row.display_severity,
                    row.recommended_refresh_scope,
                    row.lifecycle_state,
                    (
                        row.post_refresh_state
                        if row.post_refresh_state in {"REFRESHED_RECENTLY", "COOLDOWN_MONITOR"}
                        else "YES" if row.recompute_needed else "NO"
                    ),
                    row.recompute_reason,
                    row.cooldown_label,
                    dec_text(row.current_price),
                    row.leg_direction,
                    row.next_zone_state,
                    row.next_reaction_zone,
                    row.next_target_zone,
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
    finally:
        conn.close()

    rows = build_recompute_rows(
        advice_rows,
        venue=str(args.venue),
        interval=str(args.interval),
        price_by_symbol=price_by_symbol,
        fresh_min=Decimal(str(args.fresh_min)),
    )

    if args.output_html:
        output_path = Path(args.output_html)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            render_html(rows, venue=str(args.venue), interval=str(args.interval)),
            encoding="utf-8",
        )

    if args.output == "summary":
        print(f"report={REPORT_NAME} version={REPORT_VERSION}")
        print("scope=market-only account-agnostic recompute lifecycle worklist")
        print("broker_private_calls=0 broker_writes=0 order_submission=0 executor=none account_awareness=0")
        print(f"rows={len(rows)} market_price_snapshot_rows={len(price_by_symbol)}")
        if args.output_html:
            print(f"output_html={args.output_html}")
    elif args.output == "table":
        print_table(rows)
        print("broker_private_calls=0 broker_writes=0 order_submission=0 executor=none account_awareness=0")
    elif args.output == "json":
        print(
            json.dumps(
                {
                    "report": REPORT_NAME,
                    "version": REPORT_VERSION,
                    "rows": [row_to_json(row) for row in rows],
                    "broker_private_calls": 0,
                    "broker_writes": 0,
                    "order_submission": 0,
                    "executor": "none",
                    "account_awareness": 0,
                },
                indent=2,
                sort_keys=True,
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
