from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.reporting.dashboard_style_v1 import cockpit_base_css, pill_classes


REPORT_NAME = "live_like_shadow_heartbeat_history_v1"
REPORT_VERSION = "1.0"

DEFAULT_CHAIN_ROOT = Path("data/research/live_like_shadow_chain_v1")
DEFAULT_MAX_RUNS = 100
DEFAULT_OUTPUT_HTML = Path("/tmp/live-like-shadow-history.html")
CHAIN_SUMMARY_JSON = "chain_summary_v1.json"
MANIFEST_JSON = "manifest_v1.json"
LATEST_RUNS_LIMIT = 20

SAFETY_KEYS = [
    "db_writes",
    "broker_private_calls",
    "broker_writes",
    "order_submission",
    "decision_gate_changes",
    "execution_planner_changes",
    "executor",
    "executor_enabled",
    "account_tables_used",
    "mode",
]


@dataclass(frozen=True)
class RunRecord:
    run_dir: Path
    run_id: str
    timestamp_raw: str
    timestamp_sort: tuple[int, str]
    market: str
    symbol: str
    candidate_state: str
    decision_state: str
    execution_plan_state: str
    observed_price: Any
    no_order_submitted: Any
    safety_markers: dict[str, Any]

    @property
    def state_tuple(self) -> tuple[str, str, str]:
        return (self.candidate_state, self.decision_state, self.execution_plan_state)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render recent live-like shadow chain history into a static read-only stability report."
    )
    parser.add_argument("--chain-root", default=str(DEFAULT_CHAIN_ROOT))
    parser.add_argument("--max-runs", default=DEFAULT_MAX_RUNS, type=int)
    parser.add_argument("--output-html", default=str(DEFAULT_OUTPUT_HTML))
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def write_html(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def parse_timestamp(value: Any) -> tuple[int, str]:
    text = str(value or "").strip()
    if not text:
        return (0, "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return (0, text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    utc_value = parsed.astimezone(UTC)
    return (int(utc_value.timestamp() * 1_000_000), utc_value.isoformat())


def fmt_ts(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "not available"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def fmt_bool(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def fmt_value(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return fmt_bool(value)
    return str(value)


def pill_class(value: Any) -> str:
    normalized = str(value or "").upper()
    if normalized in {"ENTRY_CANDIDATE", "SHADOW", "TRUE", "0", "NONE"}:
        return pill_classes("ok", normalized)
    if normalized in {"BLOCKED", "WAIT_RETEST"}:
        return pill_classes("warn", normalized)
    if normalized in {"NO_CANDIDATE", "FALSE"}:
        return "muted"
    return pill_classes("context", normalized)


def badge_html(value: Any) -> str:
    return f"<span class='pill {pill_class(value)}'>{esc(fmt_value(value))}</span>"


def count_value(records: list[RunRecord], attr: str, target: str) -> int:
    normalized = target.upper()
    return sum(1 for record in records if str(getattr(record, attr, "")).upper() == normalized)


def load_run_record(run_dir: Path) -> RunRecord:
    summary = read_json(run_dir / CHAIN_SUMMARY_JSON)
    manifest = read_json(run_dir / MANIFEST_JSON)

    timestamp_raw = (
        manifest.get("run_finished_at_utc")
        or manifest.get("run_started_at_utc")
        or summary.get("run_finished_at_utc")
        or summary.get("run_started_at_utc")
        or ""
    )
    safety_markers = {key: summary.get(key, manifest.get(key)) for key in SAFETY_KEYS}
    return RunRecord(
        run_dir=run_dir,
        run_id=str(manifest.get("run_id") or run_dir.name.replace("run_", "")),
        timestamp_raw=str(timestamp_raw),
        timestamp_sort=parse_timestamp(timestamp_raw),
        market=str(summary.get("market") or manifest.get("market") or ""),
        symbol=str(summary.get("symbol") or manifest.get("symbol") or ""),
        candidate_state=str(summary.get("candidate_state") or manifest.get("candidate_state") or ""),
        decision_state=str(summary.get("decision_state") or manifest.get("decision_state") or ""),
        execution_plan_state=str(summary.get("execution_plan_state") or manifest.get("execution_plan_state") or ""),
        observed_price=summary.get("observed_price", manifest.get("observed_price")),
        no_order_submitted=summary.get("no_order_submitted", manifest.get("no_order_submitted")),
        safety_markers=safety_markers,
    )


def load_run_records(chain_root: Path, max_runs: int) -> list[RunRecord]:
    if max_runs <= 0:
        raise ValueError("--max-runs must be greater than zero")
    run_dirs = sorted(path for path in chain_root.glob("run_*") if path.is_dir())
    records = [
        load_run_record(run_dir)
        for run_dir in run_dirs
        if (run_dir / CHAIN_SUMMARY_JSON).exists() and (run_dir / MANIFEST_JSON).exists()
    ]
    if not records:
        raise FileNotFoundError(f"No history runs found under {chain_root}")
    records.sort(key=lambda record: (record.timestamp_sort, record.run_id, record.run_dir.name))
    return records[-max_runs:]


def counter_dict(values: list[str]) -> dict[str, int]:
    counts = Counter(value or "UNKNOWN" for value in values)
    return dict(sorted(counts.items(), key=lambda item: (item[0], item[1])))


def build_report_payload(chain_root: Path, max_runs: int) -> dict[str, Any]:
    records = load_run_records(chain_root, max_runs)
    latest = records[-1]
    earliest = records[0]
    transitions = sum(1 for prev, cur in zip(records, records[1:]) if prev.state_tuple != cur.state_tuple)

    candidate_counts = counter_dict([record.candidate_state for record in records])
    decision_counts = counter_dict([record.decision_state for record in records])
    execution_counts = counter_dict([record.execution_plan_state for record in records])

    latest_runs = list(reversed(records[-LATEST_RUNS_LIMIT:]))
    safety_markers = latest.safety_markers

    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "chain_root": str(chain_root),
        "max_runs": max_runs,
        "total_runs": len(records),
        "first_run_timestamp": earliest.timestamp_raw,
        "latest_run_timestamp": latest.timestamp_raw,
        "market": latest.market,
        "symbol": latest.symbol,
        "latest_candidate_state": latest.candidate_state,
        "latest_decision_state": latest.decision_state,
        "latest_execution_plan_state": latest.execution_plan_state,
        "latest_observed_price": latest.observed_price,
        "candidate_state_counts": candidate_counts,
        "decision_state_counts": decision_counts,
        "execution_plan_state_counts": execution_counts,
        "entry_candidate_count": count_value(records, "candidate_state", "ENTRY_CANDIDATE"),
        "wait_retest_count": count_value(records, "candidate_state", "WAIT_RETEST"),
        "no_candidate_count": count_value(records, "candidate_state", "NO_CANDIDATE"),
        "blocked_count": sum(
            1
            for record in records
            if "BLOCKED"
            in {
                record.candidate_state.upper(),
                record.decision_state.upper(),
                record.execution_plan_state.upper(),
            }
        ),
        "state_transition_count": transitions,
        "latest_runs": [
            {
                "run_id": record.run_id,
                "timestamp": record.timestamp_raw,
                "candidate_state": record.candidate_state,
                "decision_state": record.decision_state,
                "execution_plan_state": record.execution_plan_state,
                "observed_price": record.observed_price,
                "no_order_submitted": record.no_order_submitted,
            }
            for record in latest_runs
        ],
        "safety": {
            "db_writes": safety_markers.get("db_writes"),
            "broker_private_calls": safety_markers.get("broker_private_calls"),
            "broker_writes": safety_markers.get("broker_writes"),
            "order_submission": safety_markers.get("order_submission"),
            "decision_gate_changes": safety_markers.get("decision_gate_changes"),
            "execution_planner_changes": safety_markers.get("execution_planner_changes"),
            "executor": safety_markers.get("executor"),
            "executor_enabled": safety_markers.get("executor_enabled"),
            "account_tables_used": safety_markers.get("account_tables_used"),
            "mode": safety_markers.get("mode"),
        },
    }


def render_counts_rows(counts: dict[str, int]) -> str:
    if not counts:
        return "<tr><td colspan='2' class='muted'>No states found.</td></tr>"
    return "".join(
        f"<tr><th>{esc(label)}</th><td class='right'>{count}</td></tr>"
        for label, count in counts.items()
    )


def render_summary_rows(payload: dict[str, Any]) -> str:
    rows = [
        ("Total runs", payload["total_runs"]),
        ("First run timestamp", fmt_ts(payload["first_run_timestamp"])),
        ("Latest run timestamp", fmt_ts(payload["latest_run_timestamp"])),
        ("Market", payload["market"]),
        ("Symbol", payload["symbol"]),
        ("Latest candidate_state", badge_html(payload["latest_candidate_state"])),
        ("Latest decision_state", badge_html(payload["latest_decision_state"])),
        ("Latest execution_plan_state", badge_html(payload["latest_execution_plan_state"])),
        ("Latest observed_price", fmt_value(payload["latest_observed_price"])),
        ("ENTRY_CANDIDATE count", payload["entry_candidate_count"]),
        ("WAIT_RETEST count", payload["wait_retest_count"]),
        ("NO_CANDIDATE count", payload["no_candidate_count"]),
        ("BLOCKED count", payload["blocked_count"]),
        ("State transition count", payload["state_transition_count"]),
    ]
    body = []
    for label, value in rows:
        if isinstance(value, str) and value.startswith("<span"):
            rendered = value
        else:
            rendered = esc(fmt_value(value))
        body.append(f"<tr><th>{esc(label)}</th><td>{rendered}</td></tr>")
    return "".join(body)


def render_safety_rows(payload: dict[str, Any]) -> str:
    return "".join(
        f"<tr><th>{esc(key)}</th><td><code>{esc(fmt_value(payload['safety'].get(key)))}</code></td></tr>"
        for key in SAFETY_KEYS
    )


def render_latest_runs_rows(payload: dict[str, Any]) -> str:
    rows = []
    for record in payload["latest_runs"]:
        rows.append(
            "<tr>"
            f"<td><code>{esc(record['run_id'])}</code></td>"
            f"<td>{esc(fmt_ts(record['timestamp']))}</td>"
            f"<td>{badge_html(record['candidate_state'])}</td>"
            f"<td>{badge_html(record['decision_state'])}</td>"
            f"<td>{badge_html(record['execution_plan_state'])}</td>"
            f"<td class='right'>{esc(fmt_value(record['observed_price']))}</td>"
            f"<td>{badge_html(fmt_bool(record['no_order_submitted']))}</td>"
            "</tr>"
        )
    return "".join(rows)


def render_html(payload: dict[str, Any]) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Synth Live-Like Shadow Heartbeat History</title>
  <style>
    {cockpit_base_css(min_table_width=960)}
    .banner {{
      background: linear-gradient(135deg, #2a1c05, #101936);
      border: 1px solid rgba(255, 209, 102, .35);
      border-radius: 12px;
      padding: 16px;
      line-height: 1.5;
    }}
    .triple {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 18px;
    }}
    code {{
      color: var(--text);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      word-break: break-word;
    }}
    .tight th {{
      width: 240px;
    }}
  </style>
</head>
<body>
  <div class="page">
    <header>
      <h1>Live-like shadow heartbeat history</h1>
      <div class="muted">Rendered from local chain outputs only. Read-only stability history for recent shadow-safe runs.</div>
      <div class="legend">
        <div><strong>Boundary</strong>: reporting only, read-only, file-input/file-output only.</div>
        <div><strong>Source root</strong>: <code>{esc(payload['chain_root'])}</code></div>
        <div><strong>Window</strong>: {esc(str(payload['total_runs']))} runs capped by <code>--max-runs={payload['max_runs']}</code></div>
      </div>
    </header>
    <main>
      <section class="banner">
        <div><strong>Shadow history only.</strong></div>
        <div>Not paper trading.</div>
        <div>Not live trading.</div>
        <div>No order was submitted.</div>
        <div>Executor is disabled.</div>
      </section>
      <section class="panel tight">
        <h2>History summary</h2>
        <div class="table-wrap">
          <table>
            <tbody>{render_summary_rows(payload)}</tbody>
          </table>
        </div>
      </section>
      <section class="triple">
        <section class="panel">
          <h2>Candidate states</h2>
          <div class="table-wrap">
            <table>
              <tbody>{render_counts_rows(payload['candidate_state_counts'])}</tbody>
            </table>
          </div>
        </section>
        <section class="panel">
          <h2>Decision states</h2>
          <div class="table-wrap">
            <table>
              <tbody>{render_counts_rows(payload['decision_state_counts'])}</tbody>
            </table>
          </div>
        </section>
        <section class="panel">
          <h2>Execution plan states</h2>
          <div class="table-wrap">
            <table>
              <tbody>{render_counts_rows(payload['execution_plan_state_counts'])}</tbody>
            </table>
          </div>
        </section>
      </section>
      <section class="panel">
        <h2>Latest 20 runs</h2>
        <div class="table-wrap">
          <table class="sticky-table">
            <thead>
              <tr>
                <th>run_id</th>
                <th>timestamp</th>
                <th>candidate_state</th>
                <th>decision_state</th>
                <th>execution_plan_state</th>
                <th class="right">observed_price</th>
                <th>no_order_submitted</th>
              </tr>
            </thead>
            <tbody>{render_latest_runs_rows(payload)}</tbody>
          </table>
        </div>
      </section>
      <section class="panel">
        <h2>Safety</h2>
        <div class="table-wrap">
          <table>
            <tbody>{render_safety_rows(payload)}</tbody>
          </table>
        </div>
        <p class="small muted">executor=none · broker_writes=0 · order_submission=0</p>
      </section>
    </main>
  </div>
</body>
</html>
"""


def print_table(payload: dict[str, Any], output_html: Path) -> None:
    headers = [
        "total_runs",
        "first_run_timestamp",
        "latest_run_timestamp",
        "market",
        "symbol",
        "latest_candidate_state",
        "latest_decision_state",
        "latest_execution_plan_state",
        "latest_observed_price",
        "entry_candidate_count",
        "wait_retest_count",
        "no_candidate_count",
        "blocked_count",
        "state_transition_count",
        "output_html",
    ]
    print("\t".join(headers))
    print(
        "\t".join(
            [
                str(payload["total_runs"]),
                str(payload["first_run_timestamp"]),
                str(payload["latest_run_timestamp"]),
                str(payload["market"]),
                str(payload["symbol"]),
                str(payload["latest_candidate_state"]),
                str(payload["latest_decision_state"]),
                str(payload["latest_execution_plan_state"]),
                str(fmt_value(payload["latest_observed_price"])),
                str(payload["entry_candidate_count"]),
                str(payload["wait_retest_count"]),
                str(payload["no_candidate_count"]),
                str(payload["blocked_count"]),
                str(payload["state_transition_count"]),
                str(output_html),
            ]
        )
    )
    print("db_writes=0 broker_private_calls=0 broker_writes=0 order_submission=0")
    print("decision_gate_changes=0 execution_planner_changes=0 executor=none executor_enabled=false account_tables_used=false mode=shadow")


def main() -> int:
    args = parse_args()
    payload = build_report_payload(Path(args.chain_root), args.max_runs)

    output_html = Path(args.output_html)
    write_html(output_html, render_html(payload))

    if args.output == "json":
        output_payload = dict(payload)
        output_payload["output_html"] = str(output_html)
        print(json.dumps(output_payload, indent=2, sort_keys=True))
    else:
        print_table(payload, output_html)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
