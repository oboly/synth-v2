from __future__ import annotations

import argparse
import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.reporting.dashboard_style_v1 import cockpit_base_css, pill_classes


REPORT_NAME = "live_like_shadow_chain_static_dashboard_v1"
REPORT_VERSION = "1.0"

DEFAULT_CHAIN_ROOT = Path("data/research/live_like_shadow_chain_v1")
DEFAULT_OUTPUT_HTML = Path("/tmp/live-like-shadow-chain.html")
CHAIN_SUMMARY_JSON = "chain_summary_v1.json"
MANIFEST_JSON = "manifest_v1.json"

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

LINKED_ARTIFACTS = {
    "candidate_run_dir": "strategy_candidate_v1.json",
    "decision_run_dir": "decision_preview_v1.json",
    "execution_plan_run_dir": "execution_plan_preview_v1.json",
    "shadow_event_run_dir": "shadow_event_v1.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render latest live-like shadow chain run into a static read-only HTML dashboard."
    )
    parser.add_argument(
        "--chain-run-dir",
        default=None,
        help="Optional live-like shadow chain run directory. Defaults to latest data/research/live_like_shadow_chain_v1/run_*",
    )
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


def find_latest_chain_run(chain_root: Path) -> Path:
    run_dirs = sorted(
        path for path in chain_root.glob("run_*") if path.is_dir() and (path / CHAIN_SUMMARY_JSON).exists()
    )
    if not run_dirs:
        raise FileNotFoundError(f"No chain runs found under {chain_root}")
    return run_dirs[-1]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_artifact_path(raw_path: Any) -> Path | None:
    text = str(raw_path or "").strip()
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        return path
    return repo_root() / path


def load_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    return read_json(path)


def pill_class(value: Any) -> str:
    normalized = str(value or "").upper()
    if normalized in {"SHADOW", "TRUE", "0", "NONE", "NO_CANDIDATE"}:
        return pill_classes("ok", normalized)
    if normalized in {"BLOCKED", "FALSE"}:
        return pill_classes("warn", normalized)
    return "muted"


def badge_html(value: Any) -> str:
    return f"<span class='pill {pill_class(value)}'>{esc(value)}</span>"


def fmt_bool(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def fmt_ts(value: Any) -> str:
    if not value:
        return "not available"
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def collect_dashboard_payload(chain_run_dir: Path) -> dict[str, Any]:
    chain_summary = read_json(chain_run_dir / CHAIN_SUMMARY_JSON)
    manifest = read_json(chain_run_dir / MANIFEST_JSON)

    linked_payloads: dict[str, dict[str, Any] | None] = {}
    linked_paths: dict[str, str] = {}
    for key, filename in LINKED_ARTIFACTS.items():
        run_dir_path = resolve_artifact_path(chain_summary.get(key) or manifest.get(key))
        linked_paths[key] = str(run_dir_path) if run_dir_path else ""
        linked_payloads[key] = load_optional_json(None if run_dir_path is None else run_dir_path / filename)

    candidate_payload = linked_payloads.get("candidate_run_dir") or {}
    decision_payload = linked_payloads.get("decision_run_dir") or {}
    execution_payload = linked_payloads.get("execution_plan_run_dir") or {}
    shadow_payload = linked_payloads.get("shadow_event_run_dir") or {}

    safety_markers = {key: chain_summary.get(key, manifest.get(key)) for key in SAFETY_KEYS}

    return {
        "chain_run_dir": str(chain_run_dir),
        "chain_summary": chain_summary,
        "manifest": manifest,
        "linked_paths": linked_paths,
        "candidate_payload": candidate_payload,
        "decision_payload": decision_payload,
        "execution_payload": execution_payload,
        "shadow_payload": shadow_payload,
        "market": chain_summary.get("market") or candidate_payload.get("source_context", {}).get("market"),
        "symbol": chain_summary.get("symbol") or candidate_payload.get("symbol"),
        "candidate_state": chain_summary.get("candidate_state") or candidate_payload.get("candidate_state"),
        "decision_state": chain_summary.get("decision_state") or decision_payload.get("decision_state"),
        "execution_plan_state": chain_summary.get("execution_plan_state") or execution_payload.get("execution_plan_state"),
        "no_order_submitted": chain_summary.get("no_order_submitted", shadow_payload.get("no_order_submitted")),
        "observed_price": shadow_payload.get(
            "observed_price",
            candidate_payload.get("source_context", {}).get("price_at_emit"),
        ),
        "safety_markers": safety_markers,
    }


def render_rows(payload: dict[str, Any]) -> str:
    summary_rows = [
        ("Market", payload["market"]),
        ("Symbol", payload["symbol"]),
        ("Candidate state", badge_html(payload["candidate_state"])),
        ("Decision state", badge_html(payload["decision_state"])),
        ("Execution plan state", badge_html(payload["execution_plan_state"])),
        ("No order submitted", badge_html(fmt_bool(payload["no_order_submitted"]))),
        ("Observed price", payload["observed_price"]),
    ]
    body = []
    for label, value in summary_rows:
        rendered = value if isinstance(value, str) and value.startswith("<span") else esc(value if value is not None else "—")
        body.append(f"<tr><th>{esc(label)}</th><td>{rendered}</td></tr>")
    return "".join(body)


def render_source_rows(payload: dict[str, Any]) -> str:
    labels = [
        ("Chain run dir", payload["chain_run_dir"]),
        ("Candidate run dir", payload["linked_paths"].get("candidate_run_dir")),
        ("Decision run dir", payload["linked_paths"].get("decision_run_dir")),
        ("Execution plan run dir", payload["linked_paths"].get("execution_plan_run_dir")),
        ("Shadow event run dir", payload["linked_paths"].get("shadow_event_run_dir")),
    ]
    return "".join(f"<tr><th>{esc(label)}</th><td><code>{esc(value or 'not available')}</code></td></tr>" for label, value in labels)


def render_safety_rows(payload: dict[str, Any]) -> str:
    rows = []
    for key in SAFETY_KEYS:
        value = payload["safety_markers"].get(key)
        rendered = fmt_bool(value) if isinstance(value, bool) else value
        rows.append(f"<tr><th>{esc(key)}</th><td><code>{esc(rendered)}</code></td></tr>")
    return "".join(rows)


def render_html(payload: dict[str, Any]) -> str:
    manifest = payload["manifest"]
    generated_at = fmt_ts(manifest.get("run_finished_at_utc"))
    started_at = fmt_ts(manifest.get("run_started_at_utc"))
    finished_at = fmt_ts(manifest.get("run_finished_at_utc"))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Synth Live-Like Shadow Chain</title>
  <style>
    {cockpit_base_css(min_table_width=900)}
    .banner {{
      background: linear-gradient(135deg, #2a1c05, #101936);
      border: 1px solid rgba(255, 209, 102, .35);
      border-radius: 12px;
      padding: 16px;
      line-height: 1.5;
    }}
    .stack {{
      display: grid;
      gap: 18px;
    }}
    table {{
      min-width: 100%;
    }}
    th {{
      width: 240px;
    }}
    code {{
      color: var(--text);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      word-break: break-word;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Live-like shadow chain</h1>
    <div class="muted">Rendered from file artifacts only. Generated from latest chain run at {esc(generated_at)}.</div>
    <div class="legend">
      <div><strong>Boundary</strong>: reporting only, read-only, file-input/file-output only.</div>
      <div><strong>Run window</strong>: started {esc(started_at)} · finished {esc(finished_at)}</div>
    </div>
  </header>
  <main class="stack">
    <section class="banner">
      <div><strong>Shadow preview only.</strong></div>
      <div>Not paper trading.</div>
      <div>Not live trading.</div>
      <div>No order was submitted.</div>
      <div>Executor is disabled.</div>
    </section>
    <section class="panel">
      <h2>Latest chain state</h2>
      <div class="table-wrap">
        <table>
          <tbody>{render_rows(payload)}</tbody>
        </table>
      </div>
    </section>
    <section class="panel">
      <h2>Source run dirs</h2>
      <div class="table-wrap">
        <table>
          <tbody>{render_source_rows(payload)}</tbody>
        </table>
      </div>
    </section>
    <section class="panel">
      <h2>Safety markers</h2>
      <div class="table-wrap">
        <table>
          <tbody>{render_safety_rows(payload)}</tbody>
        </table>
      </div>
      <p class="small muted">executor=none · broker_writes=0 · order_submission=0</p>
    </section>
  </main>
</body>
</html>
"""


def print_table(payload: dict[str, Any], output_html: Path) -> None:
    headers = [
        "market",
        "symbol",
        "candidate_state",
        "decision_state",
        "execution_plan_state",
        "no_order_submitted",
        "observed_price",
        "output_html",
    ]
    print("\t".join(headers))
    print(
        "\t".join(
            [
                str(payload["market"] or ""),
                str(payload["symbol"] or ""),
                str(payload["candidate_state"] or ""),
                str(payload["decision_state"] or ""),
                str(payload["execution_plan_state"] or ""),
                fmt_bool(payload["no_order_submitted"]),
                str(payload["observed_price"] or ""),
                str(output_html),
            ]
        )
    )
    print("db_writes=0 broker_private_calls=0 broker_writes=0 order_submission=0")
    print("decision_gate_changes=0 execution_planner_changes=0 executor=none executor_enabled=false account_tables_used=false mode=shadow")


def main() -> int:
    args = parse_args()
    chain_run_dir = Path(args.chain_run_dir) if args.chain_run_dir else find_latest_chain_run(DEFAULT_CHAIN_ROOT)
    payload = collect_dashboard_payload(chain_run_dir)

    output_html = Path(args.output_html)
    write_html(output_html, render_html(payload))

    if args.output == "json":
        print(
            json.dumps(
                {
                    "report": REPORT_NAME,
                    "version": REPORT_VERSION,
                    "chain_run_dir": payload["chain_run_dir"],
                    "output_html": str(output_html),
                    "market": payload["market"],
                    "symbol": payload["symbol"],
                    "candidate_state": payload["candidate_state"],
                    "decision_state": payload["decision_state"],
                    "execution_plan_state": payload["execution_plan_state"],
                    "no_order_submitted": payload["no_order_submitted"],
                    "observed_price": payload["observed_price"],
                    "safety_markers": payload["safety_markers"],
                    "source_run_dirs": payload["linked_paths"],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print_table(payload, output_html)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
