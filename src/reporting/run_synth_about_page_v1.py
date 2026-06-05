from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from src.reporting.dashboard_style_v1 import cockpit_base_css, cockpit_nav


REPORT_NAME = "run_synth_about_page_v1"
REPORT_VERSION = "0.1"
DEFAULT_OUTPUT_HTML = Path("/var/www/html/synth/about.html")
DEFAULT_HERO_SOURCE = Path("assets/brand/synth/synth-third-faction-triptych.png")
DEFAULT_HERO_OUTPUT = Path("/var/www/html/synth/assets/brand/synth-third-faction-triptych.png")
DEFAULT_HERO_HREF = "/synth/assets/brand/synth-third-faction-triptych.png"
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
    parser.add_argument("--hero-asset-source", default=str(DEFAULT_HERO_SOURCE))
    parser.add_argument("--hero-asset-output", default=str(DEFAULT_HERO_OUTPUT))
    parser.add_argument("--hero-asset-href", default=DEFAULT_HERO_HREF)
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
    return parser.parse_args()


def render_about_html(*, hero_href: str) -> str:
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
  <style>{css}</style>
</head>
<body>
  <div class="page">
    <header class="header">
      {cockpit_nav()}
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


def main() -> int:
    args = parse_args()
    output_html = Path(args.output_html)
    hero_source = Path(args.hero_asset_source)
    hero_output = Path(args.hero_asset_output)
    if not hero_source.exists():
        raise SystemExit(f"[error] hero asset missing: {hero_source}")

    output_html.parent.mkdir(parents=True, exist_ok=True)
    hero_output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(hero_source, hero_output)
    output_html.write_text(render_about_html(hero_href=args.hero_asset_href), encoding="utf-8")

    if args.output == "summary":
        print(f"report={REPORT_NAME}")
        print(f"version={REPORT_VERSION}")
        print(f"html_output={output_html}")
        print(f"hero_asset_output={hero_output}")
        print(f"hero_asset_href={args.hero_asset_href}")
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
