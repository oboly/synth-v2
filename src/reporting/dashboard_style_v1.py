from __future__ import annotations

import shutil
from pathlib import Path

SYNTH_BRAND_ASSET_DIR = Path("assets/brand/synth")
SYNTH_FAVICON_FILENAMES = (
    "favicon.svg",
    "favicon-16x16.png",
    "favicon-32x32.png",
    "apple-touch-icon.png",
    "favicon.ico",
)
SYNTH_FAVICON_PUBLIC_ROOT = "/synth/assets/brand/synth"


LIFECYCLE_CRITICAL_LABELS = {
    "INVALIDATION_TOUCHED",
    "MAP_RECOMPUTE_NEEDED",
    "TARGET_REACHED_STALE",
    "TARGET_OVERSHOT",
    "RECLAIM_NEAR",
    "RECLAIM_CONFIRMED",
    "DOWN_MAP_INVALIDATED_BY_RECLAIM",
    "UP_MAP_INVALIDATED_BY_BREAKDOWN",
    "TARGET_REACHED",
    "DOWNSIDE_TARGET_REACHED",
}

OLD_MAP_CONTEXT_LABELS = {
    "RISK_OK",
    "RISK_NEAR",
    "TARGET_PENDING",
    "ACTIVE_MAP",
    "FRESH_MAP",
    "HOLD",
    "HOLD_REVIEW",
    "REDUCE_CANDIDATE",
    "EXIT_CANDIDATE",
    "WATCHLIST",
    "PREPARE",
    "PASS",
    "FAIL",
}

OLD_MAP_CONTEXT_PREFIXES = ("APLUS_",)


def pill_context_class(value: object) -> str:
    label = str(value or "").upper()
    if label in LIFECYCLE_CRITICAL_LABELS:
        return "lifecycle-critical"
    if label in OLD_MAP_CONTEXT_LABELS or any(label.startswith(prefix) for prefix in OLD_MAP_CONTEXT_PREFIXES):
        return "old-map-context"
    return ""


def pill_classes(tone: str, value: object) -> str:
    context = pill_context_class(value)
    return f"{tone} {context}".strip()


def account_dashboard_links(profile: str) -> dict[str, str]:
    normalized_profile = str(profile or "").strip().lower()
    if not normalized_profile:
        raise ValueError("account profile required for account dashboard links")
    return {
        "about": "/synth/about.html",
        "wallet": f"/synth/accounts/{normalized_profile}/wallet.html",
        "profit_plan": f"/synth/accounts/{normalized_profile}/profit-plan.html",
        "open_orders_monitor": f"/synth/accounts/{normalized_profile}/open-orders-monitor.html",
    }


def cockpit_nav(*, account_profile: str | None = None, include_auth_links: bool = False) -> str:
    if account_profile:
        links = account_dashboard_links(account_profile)
        items: tuple[tuple[str, str], ...] = (
            ("About", links["about"]),
            ("Wallet", links["wallet"]),
            ("Profit Plan", links["profit_plan"]),
            ("Open Orders Monitor", links["open_orders_monitor"]),
        )
    else:
        items = (
            ("Cockpit", "/synth/index.html"),
            ("Fibonacci Map", "/synth/fibo-map.html"),
            ("About", "/synth/about.html"),
        )
    if include_auth_links:
        items = items + (
            ("Register", "/synth/register.html"),
            ("Login", "/synth/login.html"),
        )
    links_html = "\n".join(f'      <a href="{href}">{label}</a>' for label, href in items)
    return (
        '\n    <nav class="cockpit-nav" aria-label="Cockpit navigation">\n'
        f"{links_html}\n"
        "    </nav>\n    "
    )


def synth_favicon_head_html(*, public_root: str = SYNTH_FAVICON_PUBLIC_ROOT) -> str:
    root = public_root.rstrip("/")
    return (
        f'  <link rel="icon" type="image/svg+xml" href="{root}/favicon.svg">\n'
        f'  <link rel="icon" type="image/png" sizes="32x32" href="{root}/favicon-32x32.png">\n'
        f'  <link rel="icon" type="image/png" sizes="16x16" href="{root}/favicon-16x16.png">\n'
        f'  <link rel="apple-touch-icon" sizes="180x180" href="{root}/apple-touch-icon.png">\n'
        f'  <link rel="shortcut icon" href="{root}/favicon.ico">\n'
    )


def copy_synth_favicon_assets(*, output_root: Path, source_dir: Path = SYNTH_BRAND_ASSET_DIR) -> list[Path]:
    target_dir = Path(output_root) / "assets" / "brand" / "synth"
    target_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for filename in SYNTH_FAVICON_FILENAMES:
        source = source_dir / filename
        target = target_dir / filename
        shutil.copy2(source, target)
        target.chmod(0o644)
        copied.append(target)
    return copied


def cockpit_base_css(*, min_table_width: int = 1800) -> str:
    return f"""
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
      --context: #7aa2ff;
      --sticky-bg: #151f39;
      --sticky-header-bg: #111a31;
      --stale-bg: rgba(82, 23, 31, .34);
      --stale-line: rgba(255, 107, 107, .34);
      --fresh-bg: rgba(23, 82, 58, .24);
      --fresh-line: rgba(85, 214, 167, .28);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
      font-size: 14px;
    }}
    .page {{
      max-width: 1760px;
      margin: 0 auto;
      padding: 18px;
    }}
    header, .header {{
      padding: 24px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(135deg, #101936, #0b1020);
    }}
    h1, h2 {{ margin: 0 0 12px; }}
    .muted {{ color: var(--muted); }}
    .small {{ font-size: 12px; }}
    .num, .right {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .center {{ text-align: center; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    main {{
      padding: 18px;
      display: grid;
      gap: 18px;
    }}
    .metric, .card, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 16px;
      box-shadow: 0 12px 40px rgba(0,0,0,.22);
    }}
    .panel.priority, .card.priority {{
      border-color: rgba(85,214,167,.38);
      box-shadow: inset 0 1px 0 rgba(85,214,167,.16), 0 12px 40px rgba(0,0,0,.22);
    }}
    .panel.harvest, .card.harvest {{
      border-color: rgba(255,209,102,.42);
      box-shadow: inset 0 1px 0 rgba(255,209,102,.16), 0 12px 40px rgba(0,0,0,.22);
    }}
    .panel.downside, .card.downside {{
      border-color: rgba(122,162,255,.38);
      box-shadow: inset 0 1px 0 rgba(122,162,255,.14), 0 12px 40px rgba(0,0,0,.22);
    }}
    .legend, .help {{
      display: grid;
      gap: 6px;
      margin-top: 16px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }}
    .legend strong, .help strong {{ color: var(--text); }}
    .pill, .badge {{
      display: inline-block;
      border-radius: 999px;
      padding: 3px 8px;
      margin: 2px;
      font-size: 12px;
      border: 1px solid var(--line);
      background: var(--panel2);
      white-space: nowrap;
    }}
    .pill.bad, .badge.bad, .bad {{ color: var(--bad); }}
    .pill.warn, .badge.warn, .warn, .watch {{ color: var(--warn); }}
    .pill.ok, .badge.ok, .ok, .good {{ color: var(--ok); }}
    .pill.context, .badge.context, .context {{ color: var(--context); }}
    .pill.muted, .badge.muted, .muted, .wait {{ color: var(--muted); }}
    .pill.bad {{ border-color: rgba(255,107,107,.45); }}
    .pill.warn {{ border-color: rgba(255,209,102,.45); }}
    .pill.ok {{ border-color: rgba(85,214,167,.45); }}
    .pill.context {{ border-color: rgba(122,162,255,.45); }}
    .table-wrap {{
      width: 100%;
      overflow-x: auto;
      overscroll-behavior-x: contain;
    }}
    table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      min-width: {min_table_width}px;
      font-size: 13px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 9px 8px;
      text-align: left;
      vertical-align: top;
      background-clip: padding-box;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .04em;
      white-space: nowrap;
    }}
    .sticky-table thead th, thead.sticky-header th, th.sticky-header {{
      position: sticky;
      top: 0;
      z-index: 6;
      background: var(--sticky-header-bg);
      box-shadow: 0 1px 0 var(--line);
    }}
    tr:hover td {{ background-color: rgba(122,162,255,.06); }}
    tr.fresh-map td, tr.workflow-fresh td {{
      background-color: var(--fresh-bg);
      border-bottom-color: var(--fresh-line);
    }}
    tr.warning-map td, tr.workflow-warning td {{
      background-color: rgba(107, 80, 24, .20);
      border-bottom-color: rgba(255, 209, 102, .28);
    }}
    tr.stale-map td, tr.workflow-stale td {{
      background-color: var(--stale-bg);
      border-bottom-color: var(--stale-line);
    }}
    tr.stale-map .zone-value, tr.workflow-stale .zone-value {{
      color: #79849f;
    }}
    tr.stale-map .pill.old-map-context,
    tr.workflow-stale .pill.old-map-context {{
      opacity: .48;
      filter: saturate(.55);
      border-color: rgba(142,160,191,.26);
    }}
    tr.stale-map .pill.lifecycle-critical,
    tr.workflow-stale .pill.lifecycle-critical {{
      opacity: 1;
      filter: none;
      font-weight: 750;
      border-color: rgba(255,209,102,.70);
      box-shadow: 0 0 0 1px rgba(255,209,102,.14) inset;
    }}
    tr.stale-map .pill.lifecycle-critical.bad,
    tr.workflow-stale .pill.lifecycle-critical.bad {{
      border-color: rgba(255,107,107,.80);
      box-shadow: 0 0 0 1px rgba(255,107,107,.18) inset;
    }}
    .sticky-symbol, .sticky-price, .sticky-target,
    .sticky-col-symbol, .sticky-col-price, .sticky-col-target {{
      position: sticky;
      z-index: 3;
      background: var(--sticky-bg);
      box-shadow: 1px 0 0 var(--line);
    }}
    tr.fresh-map .sticky-symbol, tr.fresh-map .sticky-price, tr.fresh-map .sticky-target,
    tr.fresh-map .sticky-col-symbol, tr.fresh-map .sticky-col-price, tr.fresh-map .sticky-col-target {{
      background: #15372f;
    }}
    tr.warning-map .sticky-symbol, tr.warning-map .sticky-price, tr.warning-map .sticky-target,
    tr.warning-map .sticky-col-symbol, tr.warning-map .sticky-col-price, tr.warning-map .sticky-col-target {{
      background: #332c21;
    }}
    tr.stale-map .sticky-symbol, tr.stale-map .sticky-price, tr.stale-map .sticky-target,
    tr.workflow-stale .sticky-symbol, tr.workflow-stale .sticky-price, tr.workflow-stale .sticky-target,
    tr.stale-map .sticky-col-symbol, tr.stale-map .sticky-col-price, tr.stale-map .sticky-col-target,
    tr.workflow-stale .sticky-col-symbol, tr.workflow-stale .sticky-col-price, tr.workflow-stale .sticky-col-target {{
      background: #321b27;
    }}
    th.sticky-symbol, th.sticky-price, th.sticky-target,
    th.sticky-col-symbol, th.sticky-col-price, th.sticky-col-target {{
      z-index: 8;
      background: var(--sticky-header-bg);
    }}
    .sticky-symbol, .sticky-col-symbol {{ left: 0; min-width: 108px; }}
    .sticky-price, .sticky-col-price {{ left: 108px; min-width: 126px; }}
    .sticky-target, .sticky-col-target {{
      right: 0;
      min-width: 170px;
      max-width: 240px;
      box-shadow: -1px 0 0 var(--line);
    }}
    .zone-value {{ font-variant-numeric: tabular-nums; }}
    a {{ color: var(--context); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .cockpit-nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      margin-top: 12px;
    }}
    .cockpit-nav a {{ font-size: 14px; }}
    .empty {{ color: var(--muted); padding: 12px 0; }}
    .footer {{ color: var(--muted); font-size: 12px; margin-top: 24px; line-height: 1.6; }}
    @media (max-width: 860px) {{
      .page {{ padding: 12px; }}
      header, .header {{ padding: 16px; }}
      main {{ padding: 12px; }}
      table {{ font-size: 12px; }}
      th, td {{ padding: 8px 6px; }}
      .sticky-symbol, .sticky-col-symbol {{ min-width: 94px; }}
      .sticky-price, .sticky-col-price {{ left: 94px; min-width: 112px; }}
      .sticky-target, .sticky-col-target {{ min-width: 146px; max-width: 190px; }}
    }}
    """
