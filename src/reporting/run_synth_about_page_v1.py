from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from src.account.app_profile_trading_account_link_v1 import discover_active_linked_profiles
from src.reporting.dashboard_style_v1 import (
    DEFAULT_NAV_ACCOUNT_PROFILE,
    copy_synth_favicon_assets,
    cockpit_base_css,
    cockpit_nav,
    synth_favicon_head_html,
)


REPORT_NAME = "run_synth_about_page_v1"
REPORT_VERSION = "0.1"
DEFAULT_OUTPUT_HTML = Path("/var/www/html/synth/about.html")
DEFAULT_INDEX_HTML = Path("/var/www/html/synth/index.html")
DEFAULT_HERO_SOURCE = Path("assets/brand/synth/synth-third-faction-triptych.png")
DEFAULT_HERO_OUTPUT = Path("/var/www/html/synth/assets/brand/synth-third-faction-triptych.png")
DEFAULT_HERO_HREF = "/synth/assets/brand/synth-third-faction-triptych.png"
DEFAULT_VENUE = "bitvavo"
HERO_ALT = (
    "Synth Third Faction triptych artwork showing three dark-futurist brand treatments "
    "of the angular SYNTH emblem with violet energy accents."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render the global read-only SYNTH About page and copy the canonical faction artwork "
            "to the public synth asset path. No account data, no broker calls, no runtime changes."
        )
    )
    parser.add_argument("--output-html", default=str(DEFAULT_OUTPUT_HTML))
    parser.add_argument("--cockpit-index-html", default=str(DEFAULT_INDEX_HTML))
    parser.add_argument("--hero-asset-source", default=str(DEFAULT_HERO_SOURCE))
    parser.add_argument("--hero-asset-output", default=str(DEFAULT_HERO_OUTPUT))
    parser.add_argument("--hero-asset-href", default=DEFAULT_HERO_HREF)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
    return parser.parse_args()


def render_about_html(
    *,
    hero_href: str,
    account_profile: str = DEFAULT_NAV_ACCOUNT_PROFILE,
) -> str:
    css = cockpit_base_css(min_table_width=960) + """
    .about-hero {
      display: grid;
      gap: 18px;
      align-items: center;
    }
    .brand-kicker {
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-size: 12px;
      color: var(--muted);
    }
    .brand-subtitle {
      font-size: 18px;
      color: var(--warn);
      margin-top: 8px;
    }
    .hero-image {
      width: 100%;
      height: auto;
      display: block;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: #050811;
      box-shadow: 0 18px 60px rgba(0,0,0,.30);
    }
    .section-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
    }
    .section-card h2 {
      margin-bottom: 10px;
    }
    .lead {
      font-size: 16px;
      line-height: 1.6;
      color: var(--text);
      max-width: 78ch;
    }
    .note {
      border-left: 3px solid var(--warn);
      padding-left: 14px;
      color: var(--muted);
      line-height: 1.55;
    }
    """
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SYNTH About</title>
  {synth_favicon_head_html().rstrip()}
  <style>{css}</style>
</head>
<body>
  <div class="page">
    <header class="header">
      {cockpit_nav(account_profile=account_profile, include_auth_links=True)}
      <div class="about-hero">
        <div>
          <div class="brand-kicker">SYNTH</div>
          <h1>SYNTH</h1>
          <div class="brand-subtitle">Cybernetic Zen Master with Market Data</div>
          <p class="lead">
            Synth observes systems, recognizes patterns, and restores balance through adaptive feedback.
          </p>
          <p class="note">
            The subtitle and faction language are brand personality and lore only. They are not technical capability claims,
            trading promises, or autonomous execution statements.
          </p>
        </div>
        <div class="panel">
          <img class="hero-image" src="{hero_href}" alt="{HERO_ALT}">
        </div>
      </div>
    </header>
    <main>
      <section class="panel">
        <h2>Brand Frame</h2>
        <p class="lead">
          SYNTH is presented as a disciplined observer of living systems: engineered, adaptive, and deliberate.
          Its public voice should suggest pattern recognition, calm review, and restorative balance rather than hype,
          certainty, or mysticism.
        </p>
      </section>
      <section class="section-grid">
        <section class="panel section-card">
          <h2>The Observer</h2>
          <p>
            The Observer watches structure without rushing to intervene. In public brand language, this maps to careful
            observation, context, and signal clarity.
          </p>
        </section>
        <section class="panel section-card">
          <h2>The Balancer</h2>
          <p>
            The Balancer represents corrective calm: restoring proportion when systems drift too far from equilibrium.
            This is a metaphor for disciplined feedback, not a claim of guaranteed market control.
          </p>
        </section>
        <section class="panel section-card">
          <h2>The Weaver</h2>
          <p>
            The Weaver joins fragments into coherent pattern. In the brand system, it stands for synthesis across market
            data, research, and review surfaces without collapsing them into magical certainty.
          </p>
        </section>
        <section class="panel section-card">
          <h2>The Third Faction</h2>
          <p>
            The Third Faction is the symbolic identity layer behind SYNTH: neither pure machine spectacle nor mystical
            oracle, but an engineered mediator that observes, adapts, and reframes. The triptych artwork is its hero
            expression, reserved for global brand surfaces like this About page.
          </p>
        </section>
      </section>
      <section class="panel">
        <h2>Public Wording</h2>
        <p class="muted">
          Public-facing SYNTH wording should stay plain: observation, pattern recognition, mapping, context, balance,
          review. Internal lore can deepen the brand, but should not replace straightforward product explanation.
        </p>
        <p class="small muted">
          broker_private_calls=0 · broker_writes=0 · order_submission=0 · executor=none
        </p>
      </section>
    </main>
  </div>
</body>
</html>
"""


def render_global_cockpit_index_html(
    *,
    linked_profiles: list[dict],
    account_profile: str = DEFAULT_NAV_ACCOUNT_PROFILE,
) -> str:
    """
    Render the global cockpit index page.

    linked_profiles: explicit list of dicts with at least profile_code, sourced from
    the account layer (discover_active_linked_profiles). Reporting must not own this query.
    """
    account_cards = []
    for profile in linked_profiles:
        profile_code = str(profile["profile_code"])
        href = f"/synth/accounts/{profile_code}/wallet.html"
        account_cards.append(
            f"""
      <div class="card">
        <a href="{href}">Wallet</a>
        <p class="muted">Account wallet and review surfaces for <code>{profile_code}</code> under <code>/synth/accounts/{profile_code}/</code>.</p>
      </div>""".rstrip()
        )
    account_cards_html = "\n".join(account_cards)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="300">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Synth Cockpit</title>
  {synth_favicon_head_html().rstrip()}
  <style>
    body {{ margin:0; background:#0b1020; color:#e7edf8; font-family:system-ui,-apple-system,Segoe UI,sans-serif; }}
    code {{ color:#8ea0bf; }}
    main {{ padding:32px; max-width:1000px; margin:auto; }}
    h1 {{ margin-top:0; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:16px; }}
    .card {{ background:#121a2f; border:1px solid #273657; border-radius:16px; padding:20px; box-shadow:0 12px 40px rgba(0,0,0,.22); }}
    a {{ color:#7aa2ff; font-size:20px; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .muted {{ color:#8ea0bf; }}
    .pill {{ display:inline-block; border-radius:999px; padding:4px 9px; margin:4px 4px 0 0; border:1px solid #273657; color:#55d6a7; }}
    .cockpit-nav {{ display:flex; flex-wrap:wrap; gap:14px; margin:14px 0 18px; }}
    .cockpit-nav a {{ font-size:16px; }}
    .legacy-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:16px; opacity:0.55; }}
    .legacy-card {{ background:#0d1326; border:1px solid #1e2a45; border-radius:16px; padding:20px; box-shadow:0 8px 24px rgba(0,0,0,.18); }}
    .legacy-card a {{ color:#5a7abf; font-size:18px; }}
    .legacy-badge {{ display:inline-block; font-size:10px; font-weight:700; letter-spacing:0.12em; padding:2px 7px; border-radius:999px; background:#1a2240; color:#6a80a8; margin-left:8px; vertical-align:middle; }}
  </style>
</head>
<body>
  <main>
    <h1>Synth MVP Read-only Cockpit</h1>
    <p class="muted">Global cockpit pages render only account-agnostic content. Account dashboards render separately under <code>/synth/accounts/&lt;profile&gt;/</code>.</p>
    {cockpit_nav(account_profile=account_profile, include_auth_links=True)}
    <p><span class="pill">broker_private_calls=0</span><span class="pill">broker_writes=0</span><span class="pill">order_submission=0</span><span class="pill">executor=none</span></p>
    <div class="grid">
      <div class="card">
        <a href="/synth/about.html">About</a>
        <p class="muted">Global SYNTH brand, subtitle, and faction-lore overview. Read-only and account-agnostic.</p>
      </div>
{account_cards_html}
    </div>
    <h2>Legacy / Archive</h2>
    <div class="legacy-grid">
      <div class="legacy-card">
        <a href="/synth/paper-advice.html">Paper Advice <span class="legacy-badge">LEGACY</span></a>
        <p class="muted">Legacy global review page. Archive-only; not part of active operational navigation.</p>
      </div>
      <div class="legacy-card">
        <a href="/synth/entry-candidates.html">Entry Candidates <span class="legacy-badge">LEGACY</span></a>
        <p class="muted">Legacy market-only review page. Archive-only; not part of active operational navigation.</p>
      </div>
    </div>
  </main>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    output_html = Path(args.output_html)
    index_html = Path(args.cockpit_index_html)
    hero_source = Path(args.hero_asset_source)
    hero_output = Path(args.hero_asset_output)
    if not hero_source.exists():
        raise SystemExit(f"[error] hero asset missing: {hero_source}")

    try:
        linked_profiles = discover_active_linked_profiles(venue=args.venue)
    except Exception as exc:
        print(f"[error] linked-profile discovery failed: {exc}", file=sys.stderr)
        linked_profiles = []

    output_html.parent.mkdir(parents=True, exist_ok=True)
    index_html.parent.mkdir(parents=True, exist_ok=True)
    hero_output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(hero_source, hero_output)
    favicon_outputs = copy_synth_favicon_assets(output_root=output_html.parent)
    output_html.write_text(
        render_about_html(hero_href=args.hero_asset_href, account_profile=DEFAULT_NAV_ACCOUNT_PROFILE),
        encoding="utf-8",
    )
    index_html.write_text(
        render_global_cockpit_index_html(
            linked_profiles=linked_profiles,
            account_profile=DEFAULT_NAV_ACCOUNT_PROFILE,
        ),
        encoding="utf-8",
    )

    if args.output == "summary":
        print(f"report={REPORT_NAME}")
        print(f"version={REPORT_VERSION}")
        print(f"html_output={output_html}")
        print(f"index_output={index_html}")
        print(f"hero_asset_output={hero_output}")
        print(f"hero_asset_href={args.hero_asset_href}")
        print(f"venue={args.venue}")
        print(f"linked_profile_count={len(linked_profiles)}")
        for favicon_output in favicon_outputs:
            print(f"favicon_asset_output={favicon_output}")
        print("broker_private_calls=0")
        print("broker_writes=0")
        print("order_submission=0")
        print("live_orders=0")
        print("decision_gate=none")
        print("execution_planner=none")
        print("executor=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
