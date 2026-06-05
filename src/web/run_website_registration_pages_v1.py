from __future__ import annotations

import argparse
from pathlib import Path

from src.reporting.dashboard_style_v1 import cockpit_base_css


DEFAULT_OUTPUT_ROOT = Path("/var/www/html/synth")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render minimal SYNTH registration foundation pages. "
            "Static page render only; no dashboard URL changes, no broker calls."
        )
    )
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
    return parser.parse_args()


def _page_shell(*, title: str, body_html: str) -> str:
    css = cockpit_base_css(min_table_width=960) + """
    .auth-wrap { max-width: 780px; margin: 0 auto; }
    .auth-card { background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 22px; }
    .auth-grid { display: grid; gap: 12px; margin-top: 14px; }
    .auth-field { display: grid; gap: 6px; }
    .auth-field label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }
    .auth-field input, .auth-field textarea {
      width: 100%; border-radius: 10px; border: 1px solid var(--line); background: rgba(255,255,255,.04);
      color: var(--text); padding: 11px 12px; font: inherit;
    }
    .auth-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 16px; }
    .auth-actions button, .auth-actions a {
      border-radius: 10px; border: 1px solid var(--line); padding: 10px 14px; text-decoration: none;
      color: var(--text); background: rgba(255,255,255,.05);
    }
    .auth-note { color: var(--muted); line-height: 1.55; }
    .status-pill { display: inline-block; margin-top: 8px; }
    """
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>{css}</style>
</head>
<body>
  <div class="page auth-wrap">
    <header class="header">
      <h1>SYNTH</h1>
      <div class="muted">Cybernetic Zen Master with Market Data</div>
      <div class="small muted">Registration foundation only. Existing public dashboard URLs remain unchanged.</div>
    </header>
    <main>
      <section class="auth-card">
        {body_html}
      </section>
    </main>
  </div>
</body>
</html>"""


def render_register_page() -> str:
    return _page_shell(
        title="SYNTH Register",
        body_html="""
        <h2>Register</h2>
        <p class="auth-note">Create a SYNTH website profile. This does not create a trading account and does not collect exchange API credentials.</p>
        <form class="auth-grid">
          <div class="auth-field"><label>Email address</label><input type="email" name="email" autocomplete="email"></div>
          <div class="auth-field"><label>Alias / profile code</label><input type="text" name="profile_code" autocomplete="username"></div>
          <div class="auth-field"><label>Password</label><input type="password" name="password" autocomplete="new-password"></div>
          <div class="auth-field"><label>Proof-of-human response</label><textarea name="proof_response" rows="3"></textarea></div>
          <div class="auth-actions"><button type="button" disabled>Registration submits through the isolated auth service</button></div>
        </form>
        """,
    )


def render_login_page() -> str:
    return _page_shell(
        title="SYNTH Login",
        body_html="""
        <h2>Login</h2>
        <p class="auth-note">Use your verified email address or profile code. Existing public dashboard pages remain public and unchanged in this foundation batch.</p>
        <form class="auth-grid">
          <div class="auth-field"><label>Email or profile code</label><input type="text" name="login_value" autocomplete="username"></div>
          <div class="auth-field"><label>Password</label><input type="password" name="password" autocomplete="current-password"></div>
          <div class="auth-actions"><button type="button" disabled>Login submits through the isolated auth service</button></div>
        </form>
        """,
    )


def render_verify_result_page() -> str:
    return _page_shell(
        title="SYNTH Verification",
        body_html="""
        <h2>Email Verification</h2>
        <p class="auth-note">Verification tokens are single-use and expire. This static page is the public shell; the isolated auth service determines the result state.</p>
        <div class="pill ok status-pill">VERIFICATION_RESULT_PENDING_SERVICE_CHECK</div>
        """,
    )


def render_onboarding_page() -> str:
    return _page_shell(
        title="SYNTH Onboarding",
        body_html="""
        <h2>Onboarding</h2>
        <p class="auth-note">A verified website profile can exist before any exchange mapping is provisioned.</p>
        <div class="pill warn status-pill">NO_EXCHANGE_ACCOUNT_CONNECTED</div>
        """,
    )


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root)
    pages = {
        "register.html": render_register_page(),
        "login.html": render_login_page(),
        "verify-result.html": render_verify_result_page(),
        "onboarding.html": render_onboarding_page(),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    for filename, html in pages.items():
        (output_root / filename).write_text(html, encoding="utf-8")
    if args.output == "summary":
        print(f"output_root={output_root}")
        for filename in pages:
            print(f"page={output_root / filename}")
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
