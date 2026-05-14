from __future__ import annotations

import argparse
import html
import json
import os
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

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


def fetch_latest_rows(
    conn: pymysql.connections.Connection,
    venue: str,
    interval: str,
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


def split_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    primary_states = {"WATCH_CORE", "WATCH", "BLOCK_24H", "CORE_CONTEXT", "WAIT"}
    primary = [row for row in rows if str(row.get("advice_state", "")).upper() in primary_states]
    defensive = [row for row in rows if row not in primary]
    return primary, defensive


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

        body.append(
            f"""
            <tr>
                <td class="mono center">{esc(rank_text)}</td>
                <td class="symbol">{esc(row.get("symbol"))}</td>
                <td><span class="pill {css_class(advice_state)}">{esc(advice_state)}</span></td>
                <td>{esc(row.get("advice_action"))}</td>
                <td class="mono right">{fmt_score(row.get("confidence_score"))}</td>
                <td><span class="pill {css_class(risk_label)}">{esc(risk_label)}</span></td>
                <td><span class="pill {css_class(leg_direction)}">{esc(leg_direction or "—")}</span></td>
                <td class="mono">{fmt_range(row.get("entry_zone_low"), row.get("entry_zone_high"))}</td>
                <td class="mono">{fmt_range(row.get("tp_zone_low"), row.get("tp_zone_high"))}</td>
                <td class="mono">{fmt_decimal(row.get("invalidation_price"))}</td>
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
                    <th>Symbol</th>
                    <th>Advice</th>
                    <th>Action</th>
                    <th>Conf</th>
                    <th>Risk</th>
                    <th>Leg</th>
                    <th>Entry zone</th>
                    <th>TP zone</th>
                    <th>Invalidation</th>
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
    latest_asof: datetime | None,
    rows: list[dict[str, Any]],
    counts: list[dict[str, Any]],
    runtime: dict[str, Any] | None,
) -> str:
    generated_ts = datetime.now(UTC).replace(tzinfo=None)
    primary_rows, defensive_rows = split_rows(rows)

    latest_text = latest_asof.isoformat(sep=" ", timespec="seconds") if latest_asof else "NO DATA"
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
        .pill {{
            display: inline-flex;
            border-radius: 999px;
            border: 1px solid var(--line);
            padding: 4px 8px;
            font-size: 12px;
            white-space: nowrap;
            background: rgba(255,255,255,0.04);
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
                    Read-only paper navigation · venue={esc(venue)} · interval={esc(interval)} · latest advice={esc(latest_text)}<br>
                    Static page refreshes every 5 minutes. Data changes when the 4h chain writes a new paper_advice_observation snapshot.
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
            <h2>Defensive / no-new-buy rows</h2>
            {render_table(defensive_rows)}
        </section>

        <section class="footer">
            Generated UTC: {esc(generated_ts)}<br>
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


def print_table(path: Path, latest_asof: datetime | None, rows: list[dict[str, Any]], counts: list[dict[str, Any]]) -> None:
    print(f"report={POLICY_NAME} version={POLICY_VERSION}")
    print("scope=static-readonly paper-navigation")
    print("broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    print(f"latest_asof={latest_asof}")
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
            limit=int(args.limit),
        )
    finally:
        conn.close()

    html_content = render_html(
        title=str(args.title),
        venue=str(args.venue),
        interval=str(args.interval),
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
        print_table(output_path, latest_asof, rows, counts)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
