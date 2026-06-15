from __future__ import annotations

import argparse
import csv
import html
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "manual_ladder_static_dashboard_v1"
REPORT_VERSION = "0.1"

DEFAULT_OUTPUT_HTML = "/tmp/manual_ladder_dashboard_v1.html"
DEFAULT_FIB_MAP_ROWS = Path("data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv")


@dataclass(frozen=True)
class PriceSnapshot:
    symbol: str
    price: Decimal | None
    ts: Any | None
    source: str


@dataclass(frozen=True)
class DashboardRow:
    symbol: str
    current_price: Decimal | None
    price_ts: Any | None
    price_source: str
    breath_phase: str
    breath_context: str
    fib_map_source: str
    regime_context: str
    leg_direction: str
    invalidation: Decimal | None
    support_low: Decimal | None
    support_high: Decimal | None
    t1_target: Decimal | None
    t1_status: str
    next_target: Decimal | None
    runner_target: Decimal | None
    harvest_ladder: tuple[Decimal, ...]
    reload_ladder: tuple[Decimal, ...]
    state_labels: tuple[str, ...]
    manual_note: str
    source_modules: tuple[str, ...]
    debug_payload: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render the Synth v2.14 Breath-Fibo-Regime manual ladder dashboard."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--quote", default="EUR")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--output-html", default=DEFAULT_OUTPUT_HTML)
    parser.add_argument("--fib-map-rows", default=str(DEFAULT_FIB_MAP_ROWS))
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
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
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan", "—"}:
        return None
    text = text.replace("%", "")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def first_decimal(row: dict[str, Any], keys: tuple[str, ...]) -> Decimal | None:
    for key in keys:
        value = to_decimal(row.get(key))
        if value is not None:
            return value
    return None


def first_text(row: dict[str, Any], keys: tuple[str, ...], default: str = "not available") -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def fmt_price(value: Decimal | None) -> str:
    if value is None:
        return "—"
    if value == 0:
        return "0"
    places = Decimal("0.000001") if abs(value) < Decimal("1") else Decimal("0.01")
    try:
        return str(value.quantize(places))
    except Exception:
        return str(value)


def pct_distance(level: Decimal | None, current: Decimal | None) -> Decimal | None:
    if level is None or current is None or current == 0:
        return None
    return (level - current) / current * Decimal("100")


def fmt_pct(value: Decimal | None) -> str:
    if value is None:
        return "—"
    try:
        return f"{value.quantize(Decimal('0.1'))}%"
    except Exception:
        return f"{value}%"


def now_local_first() -> tuple[str, str]:
    now_utc = datetime.now(UTC)
    try:
        from zoneinfo import ZoneInfo

        local = now_utc.astimezone(ZoneInfo("Europe/Amsterdam"))
        return local.strftime("%Y-%m-%d %H:%M:%S %Z"), now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"), now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")


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


def load_fib_target_map_rows(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows_by_symbol: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            rows_by_symbol[symbol] = {f"fib_map_{key}": value for key, value in row.items()}
            rows_by_symbol[symbol]["fib_map_lookup_status"] = "FOUND"
    return rows_by_symbol


def fetch_latest_paper_advice_rows(conn: Any, *, venue: str, interval: str, limit: int) -> dict[str, dict[str, Any]]:
    sql = """
        SELECT *
        FROM paper_advice_observation
        WHERE venue = %s
          AND interval_code = %s
          AND asof_ts_utc = (
              SELECT MAX(asof_ts_utc)
              FROM paper_advice_observation
              WHERE venue = %s
                AND interval_code = %s
          )
        ORDER BY symbol
        LIMIT %s
    """
    rows = try_query(conn, sql, (venue, interval, venue, interval, limit))
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or row.get("asset_symbol") or "").strip().upper()
        if symbol:
            result[symbol] = row
    return result


def fetch_latest_price_rows(conn: Any, *, venue: str, interval: str, limit: int) -> dict[str, PriceSnapshot]:
    queries: tuple[tuple[str, tuple[Any, ...]], ...] = (
        (
            """
            SELECT a.symbol AS symbol, c.close_price AS price, c.close_ts_utc AS ts
            FROM obs_market_candle c
            JOIN asset a ON a.asset_id = c.asset_id
            WHERE c.venue = %s
              AND c.interval_code = %s
              AND c.close_ts_utc = (
                  SELECT MAX(c2.close_ts_utc)
                  FROM obs_market_candle c2
                  WHERE c2.venue = %s
                    AND c2.interval_code = %s
              )
            ORDER BY a.symbol
            LIMIT %s
            """,
            (venue, interval, venue, interval, limit),
        ),
        (
            """
            SELECT a.symbol AS symbol, c.close_price AS price, c.close_ts_utc AS ts
            FROM obs_market_candle c
            JOIN asset a ON a.id = c.asset_id
            WHERE c.venue = %s
              AND c.interval_code = %s
              AND c.close_ts_utc = (
                  SELECT MAX(c2.close_ts_utc)
                  FROM obs_market_candle c2
                  WHERE c2.venue = %s
                    AND c2.interval_code = %s
              )
            ORDER BY a.symbol
            LIMIT %s
            """,
            (venue, interval, venue, interval, limit),
        ),
        (
            """
            SELECT symbol, close_price AS price, close_ts_utc AS ts
            FROM obs_market_candle
            WHERE venue = %s
              AND interval_code = %s
              AND close_ts_utc = (
                  SELECT MAX(close_ts_utc)
                  FROM obs_market_candle
                  WHERE venue = %s
                    AND interval_code = %s
              )
            ORDER BY symbol
            LIMIT %s
            """,
            (venue, interval, venue, interval, limit),
        ),
    )
    for sql, params in queries:
        rows = try_query(conn, sql, params)
        if not rows:
            continue
        snapshots: dict[str, PriceSnapshot] = {}
        for row in rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            snapshots[symbol] = PriceSnapshot(
                symbol=symbol,
                price=to_decimal(row.get("price")),
                ts=row.get("ts"),
                source="obs_market_candle",
            )
        if snapshots:
            return snapshots
    return {}


def fetch_latest_regime_context(conn: Any) -> str:
    queries = (
        "SELECT * FROM strategy_runtime_snapshot ORDER BY asof_ts_utc DESC LIMIT 1",
        "SELECT * FROM market_regime_snapshot ORDER BY asof_ts_utc DESC LIMIT 1",
        "SELECT * FROM regime_snapshot ORDER BY asof_ts_utc DESC LIMIT 1",
    )
    for sql in queries:
        rows = try_query(conn, sql)
        if not rows:
            continue
        row = rows[0]
        candidates = (
            "market_regime",
            "regime_code",
            "runtime_regime",
            "market_damage_state",
            "regime_state",
            "state",
        )
        parts = [f"{key}={row[key]}" for key in candidates if row.get(key) not in (None, "")]
        asof = row.get("asof_ts_utc") or row.get("created_at_utc")
        if asof:
            parts.append(f"asof={asof}")
        return " · ".join(parts) if parts else "snapshot available"
    return "not available"


def manual_override(symbol: str) -> dict[str, Any]:
    if symbol == "ALGO":
        return {
            "manual_context_source": "CHAT_MANUAL_LADDER_CONTEXT",
            "current_price": "0.113067",
            "manual_harvest_1": "0.114",
            "manual_harvest_2": "0.120",
            "manual_reload_1": "0.106",
            "manual_reload_2": "0.101",
        }
    if symbol == "WLD":
        return {
            "manual_context_source": "CHAT_MANUAL_MAP_CONTEXT",
            "entry_zone_low": "0.286849",
            "entry_zone_high": "0.299955",
            "tp_zone_high": "0.355490",
            "invalidation_price": "0.244420",
        }
    return {}


def unique_levels(levels: list[Decimal | None]) -> tuple[Decimal, ...]:
    seen: set[str] = set()
    out: list[Decimal] = []
    for level in levels:
        if level is None:
            continue
        key = str(level.normalize())
        if key in seen:
            continue
        seen.add(key)
        out.append(level)
    return tuple(out)


def build_dashboard_row(
    symbol: str,
    *,
    paper_row: dict[str, Any] | None,
    fib_row: dict[str, Any] | None,
    price_snapshot: PriceSnapshot | None,
    regime_context: str,
) -> DashboardRow:
    source: dict[str, Any] = {}
    source.update(manual_override(symbol))
    if paper_row:
        source.update(paper_row)
    if fib_row:
        source.update(fib_row)

    current_price = (
        None if price_snapshot is None else price_snapshot.price
    ) or first_decimal(source, ("current_price", "close_price", "latest_close_price"))
    price_ts = None if price_snapshot is None else price_snapshot.ts
    price_source = "manual_context" if price_snapshot is None else price_snapshot.source

    leg_direction = first_text(
        source,
        (
            "leg_direction",
            "direction",
            "fib_map_leg_direction",
            "fib_map_direction",
            "trend_direction",
        ),
        default="unknown",
    ).upper()

    invalidation = first_decimal(
        source,
        (
            "invalidation_price",
            "fib_map_invalidation_price",
            "fib_map_invalidation",
            "risk_level",
        ),
    )

    support_low = first_decimal(
        source,
        (
            "entry_zone_low",
            "support_zone_low",
            "fib_map_reentry_zone_low",
            "fib_map_next_fibo_support_price",
            "manual_reload_2",
        ),
    )
    support_high = first_decimal(
        source,
        (
            "entry_zone_high",
            "support_zone_high",
            "fib_map_reentry_zone_high",
            "fib_map_local_reaction_price",
            "manual_reload_1",
        ),
    )
    if support_low is not None and support_high is not None and support_low > support_high:
        support_low, support_high = support_high, support_low

    t1_target = first_decimal(
        source,
        (
            "manual_harvest_1",
            "fib_map_local_reaction_price",
            "tp_zone_low",
            "target_zone_low",
            "next_reaction_price",
        ),
    )
    next_target = first_decimal(
        source,
        (
            "manual_harvest_2",
            "fib_map_next_extension_target_price",
            "tp_zone_high",
            "target_zone_high",
            "next_target_price",
        ),
    )
    runner_target = first_decimal(
        source,
        (
            "fib_map_main_extension_target_price",
            "fib_map_runner_target_price",
            "runner_target_price",
        ),
    )

    manual_reload_1 = first_decimal(source, ("manual_reload_1",))
    manual_reload_2 = first_decimal(source, ("manual_reload_2",))
    harvest_ladder = unique_levels([t1_target, next_target, runner_target])
    reload_ladder = unique_levels([manual_reload_1, support_high, support_low, manual_reload_2])

    t1_distance = pct_distance(t1_target, current_price)
    t1_touched = (
        current_price is not None and t1_target is not None and current_price >= t1_target
    )
    t1_status = "T1_TOUCHED" if t1_touched else "NEAR_T1" if t1_distance is not None and abs(t1_distance) <= Decimal("2.0") else "not touched"

    labels: list[str] = []
    if fib_row is None and not paper_row and not source.get("manual_context_source"):
        labels.append("NO_MAP")
    if fib_row is None:
        labels.append("FIB_MAP_UNKNOWN")
    if t1_status in {"T1_TOUCHED", "NEAR_T1"}:
        labels.append(t1_status)
    if t1_touched:
        labels.append("WAIT_RETEST")

    if current_price is not None:
        for level in reload_ladder:
            dist = pct_distance(level, current_price)
            if dist is not None and dist <= 0 and abs(dist) <= Decimal("3.0"):
                labels.append("REBUY_ZONE_NEAR")
                break
        inv_dist = pct_distance(invalidation, current_price)
        if inv_dist is not None and inv_dist <= 0 and abs(inv_dist) <= Decimal("3.0"):
            labels.append("INVALIDATION_NEAR")

    labels.append("MANUAL_ONLY")
    state_labels = tuple(dict.fromkeys(labels))

    source_modules = []
    if paper_row:
        source_modules.append("paper_advice_observation")
    if fib_row:
        source_modules.append("fibo_target_map_v1")
    if price_snapshot:
        source_modules.append("obs_market_candle")
    if source.get("manual_context_source"):
        source_modules.append(str(source["manual_context_source"]))

    return DashboardRow(
        symbol=symbol,
        current_price=current_price,
        price_ts=price_ts,
        price_source=price_source,
        breath_phase=first_text(
            source,
            (
                "aplus_phase",
                "phase",
                "breath_phase",
                "market_breath_phase",
                "fib_map_breath_phase",
            ),
        ),
        breath_context=first_text(
            source,
            (
                "aplus_bucket",
                "aplus_context",
                "breath_context",
                "market_breath_context_state",
                "comparison_bucket",
            ),
        ),
        fib_map_source="fibo_target_map_v1" if fib_row else first_text(source, ("manual_context_source",), "FIB_MAP_UNKNOWN"),
        regime_context=regime_context,
        leg_direction=leg_direction,
        invalidation=invalidation,
        support_low=support_low,
        support_high=support_high,
        t1_target=t1_target,
        t1_status=t1_status,
        next_target=next_target,
        runner_target=runner_target,
        harvest_ladder=harvest_ladder,
        reload_ladder=reload_ladder,
        state_labels=state_labels,
        manual_note="Manual only — place/cancel orders yourself.",
        source_modules=tuple(source_modules),
        debug_payload=source,
    )


def build_rows(
    *,
    paper_rows: dict[str, dict[str, Any]],
    fib_rows: dict[str, dict[str, Any]],
    price_rows: dict[str, PriceSnapshot],
    regime_context: str,
    limit: int,
) -> list[DashboardRow]:
    symbols = sorted(set(price_rows) | set(paper_rows) | set(fib_rows) | {"ALGO", "WLD"})
    rows = [
        build_dashboard_row(
            symbol,
            paper_row=paper_rows.get(symbol),
            fib_row=fib_rows.get(symbol),
            price_snapshot=price_rows.get(symbol),
            regime_context=regime_context,
        )
        for symbol in symbols[:limit]
    ]
    rows.sort(key=lambda row: (0 if row.t1_status in {"NEAR_T1", "T1_TOUCHED"} else 1, row.symbol))
    return rows


def pill_class(label: str) -> str:
    value = label.upper()
    if value in {"INVALIDATION_NEAR", "NO_MAP"} or "DAMAGE" in value or "CRASH" in value:
        return "bad"
    if value in {"WAIT_RETEST", "REBUY_ZONE_NEAR", "FIB_MAP_UNKNOWN"} or "CAUTION" in value:
        return "warn"
    if value in {"NEAR_T1", "T1_TOUCHED", "MANUAL_ONLY"}:
        return "ok"
    return "muted"


def pill(label: str) -> str:
    return f"<span class='pill {pill_class(label)}'>{esc(label)}</span>"


def ladder_html(levels: tuple[Decimal, ...], current: Decimal | None) -> str:
    if not levels:
        return "<span class='muted'>—</span>"
    parts = []
    for level in levels:
        parts.append(
            f"<div><span class='mono'>{esc(fmt_price(level))}</span> "
            f"<span class='muted'>({esc(fmt_pct(pct_distance(level, current)))})</span></div>"
        )
    return "".join(parts)


def support_html(row: DashboardRow) -> str:
    if row.support_low is None and row.support_high is None:
        return "—"
    if row.support_low is not None and row.support_high is not None and row.support_low != row.support_high:
        midpoint = (row.support_low + row.support_high) / Decimal("2")
        return (
            f"<span class='mono'>{esc(fmt_price(row.support_low))}..{esc(fmt_price(row.support_high))}</span>"
            f" <span class='muted'>mid {esc(fmt_pct(pct_distance(midpoint, row.current_price)))}</span>"
        )
    level = row.support_low or row.support_high
    return f"<span class='mono'>{esc(fmt_price(level))}</span> <span class='muted'>{esc(fmt_pct(pct_distance(level, row.current_price)))}</span>"


def target_block_html(row: DashboardRow) -> str:
    return f"""
    <div class="target-grid">
      <div><strong>T1</strong><br><span class="mono">{esc(fmt_price(row.t1_target))}</span><br><span class="muted">{esc(fmt_pct(pct_distance(row.t1_target, row.current_price)))}</span></div>
      <div><strong>T1 status</strong><br>{pill(row.t1_status)}</div>
      <div><strong>Next target</strong><br><span class="mono">{esc(fmt_price(row.next_target))}</span><br><span class="muted">{esc(fmt_pct(pct_distance(row.next_target, row.current_price)))}</span></div>
      <div><strong>Runner target</strong><br><span class="mono">{esc(fmt_price(row.runner_target))}</span><br><span class="muted">{esc(fmt_pct(pct_distance(row.runner_target, row.current_price)))}</span></div>
    </div>
    """


def render_row_card(row: DashboardRow) -> str:
    labels_html = " ".join(pill(label) for label in row.state_labels)
    source_modules = ", ".join(row.source_modules) if row.source_modules else "not available"
    debug_json = esc(json.dumps(row.debug_payload, default=str, indent=2, sort_keys=True))
    return f"""
    <section class="card">
      <div class="card-head">
        <div>
          <h2>{esc(row.symbol)}</h2>
          <div class="muted small">{esc(row.manual_note)}</div>
        </div>
        <div class="state">{labels_html}</div>
      </div>

      <div class="stack">
        <div class="layer breath">
          <h3>1. A+ Phase / Market Breath</h3>
          <div><strong>phase</strong>: {esc(row.breath_phase)}</div>
          <div><strong>context</strong>: {esc(row.breath_context)}</div>
        </div>

        <div class="layer map">
          <h3>2. Fibo / external map</h3>
          <div><strong>map source</strong>: {esc(row.fib_map_source)}</div>
          <div><strong>support / reaction / reload zone</strong>: {support_html(row)}</div>
          <div><strong>invalidation</strong>: <span class="mono">{esc(fmt_price(row.invalidation))}</span> <span class="muted">{esc(fmt_pct(pct_distance(row.invalidation, row.current_price)))}</span></div>
          {target_block_html(row)}
        </div>

        <div class="layer regime">
          <h3>3. Regime</h3>
          <div>{esc(row.regime_context)}</div>
          <div class="muted small">Regime is context, not permission.</div>
        </div>

        <div class="layer price">
          <h3>4. Price position</h3>
          <div><strong>current</strong>: <span class="mono">{esc(fmt_price(row.current_price))}</span></div>
          <div><strong>freshness/source</strong>: {esc(row.price_source)} · {esc(row.price_ts or "not available")}</div>
          <div><strong>leg</strong>: {esc(row.leg_direction)}</div>
        </div>

        <div class="layer confirm">
          <h3>5. Synth confirmation sensors</h3>
          <div class="muted small">Confirmation details remain secondary in v1; old advice/policy labels are not headline state.</div>
          <div><strong>sources</strong>: {esc(source_modules)}</div>
        </div>

        <div class="layer ladder">
          <h3>6. Manual ladder</h3>
          <div class="ladder-grid">
            <div><strong>Harvest ladder</strong>{ladder_html(row.harvest_ladder, row.current_price)}</div>
            <div><strong>Reload ladder</strong>{ladder_html(row.reload_ladder, row.current_price)}</div>
          </div>
        </div>

        <details class="debug">
          <summary>7. Debug details</summary>
          <pre>{debug_json}</pre>
        </details>
      </div>
    </section>
    """


def render_html(rows: list[DashboardRow], *, venue: str, quote: str, interval: str) -> str:
    local_ts, utc_ts = now_local_first()
    counts: dict[str, int] = {}
    for row in rows:
        for label in row.state_labels:
            counts[label] = counts.get(label, 0) + 1
    counts_html = " ".join(pill(f"{label}: {count}") for label, count in sorted(counts.items()))
    cards = "\n".join(render_row_card(row) for row in rows)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="300">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Synth Manual Ladders</title>
  <style>
    :root {{
      --bg: #080d18;
      --panel: #111a2e;
      --panel2: #17223b;
      --text: #ecf2ff;
      --muted: #93a4c2;
      --line: #293957;
      --bad: #ff7171;
      --warn: #ffd166;
      --ok: #66dfb2;
      --blue: #8fb3ff;
      --violet: #b69cff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: radial-gradient(circle at top left, #172345, var(--bg) 45%);
      color: var(--text);
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
    }}
    header {{
      padding: 24px;
      border-bottom: 1px solid var(--line);
      background: rgba(8,13,24,.84);
      position: sticky;
      top: 0;
      z-index: 10;
      backdrop-filter: blur(10px);
    }}
    h1, h2, h3 {{ margin: 0 0 10px; }}
    h1 {{ font-size: 26px; }}
    h2 {{ font-size: 22px; }}
    h3 {{ font-size: 14px; color: var(--blue); text-transform: uppercase; letter-spacing: .06em; }}
    main {{ padding: 18px; display: grid; gap: 18px; }}
    .muted {{ color: var(--muted); }}
    .small {{ font-size: 12px; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    .summary {{ margin-top: 12px; }}
    .card {{
      background: rgba(17,26,46,.94);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      box-shadow: 0 16px 42px rgba(0,0,0,.26);
    }}
    .card-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 10px;
      margin-bottom: 12px;
    }}
    .state {{ text-align: right; }}
    .stack {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 12px;
    }}
    .layer {{
      background: var(--panel2);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
      min-height: 118px;
    }}
    .breath {{ border-color: rgba(182,156,255,.35); }}
    .map {{ border-color: rgba(102,223,178,.35); }}
    .regime {{ border-color: rgba(255,209,102,.35); }}
    .ladder {{ border-color: rgba(143,179,255,.35); }}
    .pill {{
      display: inline-block;
      border-radius: 999px;
      padding: 4px 9px;
      margin: 2px;
      font-size: 12px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.04);
      white-space: nowrap;
    }}
    .pill.bad {{ color: var(--bad); border-color: rgba(255,113,113,.5); }}
    .pill.warn {{ color: var(--warn); border-color: rgba(255,209,102,.5); }}
    .pill.ok {{ color: var(--ok); border-color: rgba(102,223,178,.5); }}
    .pill.muted {{ color: var(--muted); }}
    .target-grid, .ladder-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 8px;
      margin-top: 8px;
    }}
    .target-grid > div, .ladder-grid > div {{
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px;
      background: rgba(0,0,0,.12);
    }}
    details.debug {{
      grid-column: 1 / -1;
      background: rgba(0,0,0,.18);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 10px;
    }}
    pre {{
      overflow-x: auto;
      white-space: pre-wrap;
      color: var(--muted);
      font-size: 12px;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Synth v2.14 — Breath-Fibo-Regime Manual Ladders</h1>
    <div class="muted">Venue={esc(venue)} · Quote={esc(quote)} · Interval={esc(interval)} · Rendered={esc(local_ts)} · UTC={esc(utc_ts)}</div>
    <div class="summary">{counts_html}</div>
    <div class="muted small">Manual review only. No broker calls, no broker writes, no order submission.</div>
  </header>
  <main>
    {cards}
  </main>
</body>
</html>
"""


def print_summary(rows: list[DashboardRow], output_html: Path) -> None:
    print(f"report={REPORT_NAME}")
    print(f"version={REPORT_VERSION}")
    print(f"rows={len(rows)}")
    print(f"output_html={output_html}")
    print("broker_private_calls=0")
    print("broker_writes=0")
    print("order_submission=0")
    print("executor=none")
    print("account_awareness=0")
    for row in rows[:10]:
        print(
            f"{row.symbol}: price={fmt_price(row.current_price)} "
            f"states={','.join(row.state_labels)} "
            f"t1={fmt_price(row.t1_target)} next={fmt_price(row.next_target)} "
            f"reload={','.join(fmt_price(level) for level in row.reload_ladder)}"
        )


def main() -> int:
    args = parse_args()
    output_html = Path(args.output_html)
    fib_rows = load_fib_target_map_rows(Path(args.fib_map_rows))

    conn = get_connection()
    try:
        paper_rows = fetch_latest_paper_advice_rows(
            conn,
            venue=args.venue,
            interval=args.interval,
            limit=args.limit,
        )
        price_rows = fetch_latest_price_rows(
            conn,
            venue=args.venue,
            interval=args.interval,
            limit=args.limit,
        )
        regime_context = fetch_latest_regime_context(conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    rows = build_rows(
        paper_rows=paper_rows,
        fib_rows=fib_rows,
        price_rows=price_rows,
        regime_context=regime_context,
        limit=args.limit,
    )

    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(
        render_html(rows, venue=args.venue, quote=args.quote, interval=args.interval),
        encoding="utf-8",
    )

    if args.output == "summary":
        print_summary(rows, output_html)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
