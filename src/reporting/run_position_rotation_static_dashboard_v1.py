from __future__ import annotations

import argparse
import html
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.research.run_position_rotation_preview_v1 import (
    build_rows,
    fetch_latest_paper_advice_rows,
    fetch_latest_position_rows,
)


REPORT_NAME = "position_rotation_static_dashboard_v1"
REPORT_VERSION = "0.1"

DEFAULT_OUTPUT_HTML = "/var/www/html/synth/rotation-preview.html"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render static HTML dashboard for read-only position rotation preview."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--trading-account-id", type=int, default=2)
    parser.add_argument("--stale-days", type=Decimal, default=Decimal("1.0"))
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--output-html", default=DEFAULT_OUTPUT_HTML)
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
    return parser.parse_args()


def esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def dec_text(value: Decimal | None, places: str = "0.01") -> str:
    if value is None:
        return ""
    try:
        return str(value.quantize(Decimal(places)))
    except Exception:
        return str(value)


def now_local_first() -> tuple[str, str]:
    now_utc = datetime.now(UTC)
    try:
        from zoneinfo import ZoneInfo

        local = now_utc.astimezone(ZoneInfo("Europe/Amsterdam"))
        return local.strftime("%Y-%m-%d %H:%M:%S %Z"), now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"), now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")


def pill_class(text: str | None) -> str:
    value = (text or "").upper()
    if "REDUCE" in value or "AVOID" in value or "DO_NOT_ADD" in value or "HIGH" in value:
        return "bad"
    if "CAUTION" in value or "WATCH" in value or "REVIEW" in value or "MODERATE" in value:
        return "warn"
    if "HOLD" in value or "CORE" in value or "FRESH" in value:
        return "ok"
    return "muted"


def render_html(rows: list[Any], *, venue: str, interval: str, account_id: int) -> str:
    local_ts, utc_ts = now_local_first()

    state_counts: dict[str, int] = {}
    total_value = Decimal("0")
    for row in rows:
        state_counts[row.rotation_state] = state_counts.get(row.rotation_state, 0) + 1
        if row.position_value_eur is not None:
            total_value += row.position_value_eur

    reduce_rows = [r for r in rows if "REDUCE" in r.rotation_state or "EXIT" in r.rotation_state]
    review_rows = [r for r in rows if "REVIEW" in r.rotation_state and r not in reduce_rows]
    hold_rows = [r for r in rows if r not in reduce_rows and r not in review_rows]

    def table_rows(table_rows: list[Any]) -> str:
        out = []
        for row in table_rows:
            tp_zone = ""
            if row.tp_zone_low is not None or row.tp_zone_high is not None:
                tp_zone = f"{dec_text(row.tp_zone_low, '0.000000')}..{dec_text(row.tp_zone_high, '0.000000')}"

            better = ", ".join(row.better_candidates[:3]) if row.better_candidates else ""

            out.append(
                "<tr>"
                f"<td><strong>{esc(row.position_symbol)}</strong></td>"
                f"<td class='num'>{esc(dec_text(row.position_value_eur, '0.01'))}</td>"
                f"<td class='num'>{esc(dec_text(row.quantity_base, '0.000000'))}</td>"
                f"<td><span class='pill {pill_class(row.position_source_state)}'>{esc(row.position_source_state)}</span></td>"
                f"<td class='num'>{esc(dec_text(row.position_source_age_days, '0.01'))}</td>"
                f"<td>{esc(row.selection_state)}</td>"
                f"<td><span class='pill {pill_class(row.setup_filter_reason)}'>{esc(row.setup_filter_reason)}</span></td>"
                f"<td>{esc(row.leg_direction)}</td>"
                f"<td><span class='pill {pill_class(row.advice_action)}'>{esc(row.advice_action)}</span></td>"
                f"<td><span class='pill {pill_class(row.aplus_bucket)}'>{esc(row.aplus_bucket)}</span></td>"
                f"<td>{esc(tp_zone)}</td>"
                f"<td><span class='pill {pill_class(row.rotation_state)}'>{esc(row.rotation_state)}</span></td>"
                f"<td class='num'>{esc(row.rotation_pressure_score)}</td>"
                f"<td class='small'>{esc(better)}</td>"
                "</tr>"
            )
        return "\n".join(out)

    def section(title: str, table_rows_data: list[Any]) -> str:
        return f"""
        <section class="card">
          <h2>{esc(title)} <span class="muted">({len(table_rows_data)})</span></h2>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Value €</th>
                  <th>Qty</th>
                  <th>Source</th>
                  <th>Age d</th>
                  <th>Selection</th>
                  <th>Setup reason</th>
                  <th>Leg</th>
                  <th>Action</th>
                  <th>A+</th>
                  <th>TP / target zone</th>
                  <th>Rotation</th>
                  <th>Score</th>
                  <th>Better candidates</th>
                </tr>
              </thead>
              <tbody>
                {table_rows(table_rows_data)}
              </tbody>
            </table>
          </div>
        </section>
        """

    counts_html = "".join(
        f"<span class='pill {pill_class(k)}'>{esc(k)}: {v}</span>"
        for k, v in sorted(state_counts.items())
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="300">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Synth Rotation Preview</title>
  <style>
    :root {{
      --bg: #0b1020;
      --panel: #121a2f;
      --panel2: #18223d;
      --text: #e7edf8;
      --muted: #8ea0bf;
      --line: #273657;
      --bad: #ff6b6b;
      --warn: #ffd166;
      --ok: #55d6a7;
      --blue: #7aa2ff;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
    }}
    header {{
      padding: 24px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(135deg, #101936, #0b1020);
    }}
    h1, h2 {{ margin: 0 0 12px; }}
    .muted {{ color: var(--muted); }}
    .small {{ font-size: 12px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .metric, .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 16px;
      box-shadow: 0 12px 40px rgba(0,0,0,.22);
    }}
    main {{ padding: 18px; display: grid; gap: 18px; }}
    .pill {{
      display: inline-block;
      border-radius: 999px;
      padding: 3px 8px;
      margin: 2px;
      font-size: 12px;
      border: 1px solid var(--line);
      background: var(--panel2);
      white-space: nowrap;
    }}
    .pill.bad {{ color: var(--bad); border-color: rgba(255,107,107,.45); }}
    .pill.warn {{ color: var(--warn); border-color: rgba(255,209,102,.45); }}
    .pill.ok {{ color: var(--ok); border-color: rgba(85,214,167,.45); }}
    .pill.muted {{ color: var(--muted); }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 1300px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 9px 8px; text-align: left; }}
    th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    a {{ color: var(--blue); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <header>
    <h1>Position Rotation Preview</h1>
    <div class="muted">Rendered {esc(local_ts)} · {esc(utc_ts)}</div>
    <div class="muted">venue={esc(venue)} · interval={esc(interval)} · trading_account_id={esc(account_id)}</div>
    <div style="margin-top:12px">
      <a href="./index.html">Cockpit</a> ·
      <a href="./paper-advice.html">Paper Advice</a>
    </div>
    <div class="grid">
      <div class="metric"><div class="muted">Rows</div><h2>{len(rows)}</h2></div>
      <div class="metric"><div class="muted">Total position value</div><h2>€ {esc(dec_text(total_value, '0.01'))}</h2></div>
      <div class="metric"><div class="muted">State counts</div>{counts_html}</div>
      <div class="metric"><div class="muted">Safety</div><span class="pill ok">broker_writes=0</span><span class="pill ok">order_submission=0</span><span class="pill ok">executor=none</span></div>
    </div>
  </header>
  <main>
    {section("Reduce / exit review candidates", reduce_rows)}
    {section("Hold review", review_rows)}
    {section("Hold / other", hold_rows)}
  </main>
</body>
</html>
"""


def write_index(output_dir: Path) -> Path:
    local_ts, utc_ts = now_local_first()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "index.html"
    target.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="300">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Synth Cockpit</title>
  <style>
    body {{ margin:0; background:#0b1020; color:#e7edf8; font-family:system-ui,-apple-system,Segoe UI,sans-serif; }}
    main {{ padding:32px; max-width:1000px; margin:auto; }}
    h1 {{ margin-top:0; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:16px; }}
    .card {{ background:#121a2f; border:1px solid #273657; border-radius:16px; padding:20px; box-shadow:0 12px 40px rgba(0,0,0,.22); }}
    a {{ color:#7aa2ff; font-size:20px; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .muted {{ color:#8ea0bf; }}
    .pill {{ display:inline-block; border-radius:999px; padding:4px 9px; margin:4px 4px 0 0; border:1px solid #273657; color:#55d6a7; }}
  </style>
</head>
<body>
  <main>
    <h1>Synth MVP Read-only Cockpit</h1>
    <p class="muted">Rendered {esc(local_ts)} · {esc(utc_ts)}</p>
    <p><span class="pill">broker_writes=0</span><span class="pill">order_submission=0</span><span class="pill">executor=none</span></p>
    <div class="grid">
      <div class="card">
        <a href="./paper-advice.html">Paper Advice</a>
        <p class="muted">Market/setup/A+ context and paper navigation.</p>
      </div>
      <div class="card">
        <a href="./rotation-preview.html">Rotation Preview</a>
        <p class="muted">Account-aware read-only HOLD / REDUCE review dashboard.</p>
      </div>
    </div>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    return target


def main() -> int:
    args = parse_args()

    conn = get_connection()
    try:
        position_rows = fetch_latest_position_rows(
            conn,
            venue=args.venue,
            trading_account_id=args.trading_account_id,
            limit=args.limit,
        )
        advice_by_symbol = fetch_latest_paper_advice_rows(
            conn,
            venue=args.venue,
            interval=args.interval,
        )
    finally:
        conn.close()

    rows = build_rows(
        position_rows,
        advice_by_symbol,
        stale_days=args.stale_days,
    )

    output_path = Path(args.output_html)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_html(
            rows,
            venue=args.venue,
            interval=args.interval,
            account_id=args.trading_account_id,
        ),
        encoding="utf-8",
    )
    index_path = write_index(output_path.parent)

    if args.output == "summary":
        print(f"report={REPORT_NAME} version={REPORT_VERSION}")
        print("scope=read-only account-aware static dashboard")
        print("broker_writes=0 order_submission=0 executor=none")
        print(f"rows={len(rows)} output_html={output_path}")
        print(f"index_html={index_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
