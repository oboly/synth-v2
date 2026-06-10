"""
account_profile_home_v1.py

Generates /var/www/html/synth/accounts/<profile>/index.html for profiles
with an explicit active primary trading account link.

Read-only. No broker calls. No mutation.
Unlinked profiles produce no output — caller must check linkage first.
"""
from __future__ import annotations

import html as html_module
import os
from datetime import UTC, datetime
from pathlib import Path

from src.reporting.dashboard_style_v1 import synth_favicon_head_html


REPORT_NAME = "account_profile_home_v1"
REPORT_VERSION = "0.1"
DEFAULT_OUTPUT_ROOT = Path("/var/www/html/synth")
ACCOUNT_CONNECTION_READ_ONLY = "READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED"


def esc(value: object) -> str:
    return html_module.escape(str(value or ""), quote=True)


def render_account_profile_home(
    *,
    profile_code: str,
    venue: str,
    account_code: str,
    display_timezone: str,
    generated_ts_utc: datetime | None = None,
) -> str:
    now = generated_ts_utc or datetime.now(UTC)
    generated_text = now.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds") + " UTC"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Synth · {esc(profile_code)}</title>
  {synth_favicon_head_html().rstrip()}
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; background: #f5f1e8; color: #1a1a1a; }}
    .wrap {{ max-width: 960px; margin: 0 auto; }}
    .hero {{ background: linear-gradient(135deg, #f9f5ec, #e2ecdf); border: 1px solid #cbbfa7; border-radius: 16px; padding: 20px; }}
    .pill {{ display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
    .ok {{ background: #d9f3df; color: #0a5c2a; }}
    .muted {{ color: #666; font-size: 13px; }}
    .navlinks {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 18px; }}
    .navlinks a {{ color: #1d5f8c; text-decoration: none; font-weight: 600; padding: 8px 14px; background: white; border: 1px solid #d9cfbb; border-radius: 10px; }}
    .navlinks a:hover {{ background: #e8f0ed; }}
    .meta {{ margin-top: 14px; font-size: 12px; color: #888; }}
    .safety {{ margin-top: 18px; padding: 10px 14px; background: #f0f0f0; border-radius: 10px; font-size: 12px; color: #555; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="muted">Synth account home</div>
      <h1>{esc(profile_code)}</h1>
      <div>
        <span class="pill ok">{esc(ACCOUNT_CONNECTION_READ_ONLY)}</span>
      </div>
      <div class="meta">
        venue={esc(venue)} &middot; account_code={esc(account_code)} &middot; timezone={esc(display_timezone)}
      </div>
      <div class="meta">generated={esc(generated_text)}</div>

      <div class="navlinks">
        <a href="/synth/accounts/{esc(profile_code)}/wallet.html">Wallet</a>
        <a href="/synth/accounts/{esc(profile_code)}/profit-plan.html">Profit Plan</a>
        <a href="/synth/accounts/{esc(profile_code)}/open-orders-monitor.html">Open Orders Monitor</a>
        <a href="/synth/about.html">About</a>
      </div>

      <div class="safety">
        broker_writes=0 &middot; order_submission=0 &middot; executor=none &middot; read-only display
      </div>
    </div>
  </div>
</body>
</html>"""


def write_account_profile_home(
    *,
    profile_code: str,
    venue: str,
    account_code: str,
    display_timezone: str,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    generated_ts_utc: datetime | None = None,
) -> Path:
    """
    Write index.html for the given profile. Returns the output path.
    Caller must have verified explicit DB linkage before calling this.
    """
    output_dir = output_root / "accounts" / profile_code
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o755)
    output_path = output_dir / "index.html"
    content = render_account_profile_home(
        profile_code=profile_code,
        venue=venue,
        account_code=account_code,
        display_timezone=display_timezone,
        generated_ts_utc=generated_ts_utc,
    )
    output_path.write_text(content, encoding="utf-8")
    return output_path
