from __future__ import annotations

import argparse
import html as html_module
import os
from pathlib import Path

from src.reporting.dashboard_style_v1 import (
    cockpit_base_css,
    cockpit_nav,
    copy_synth_favicon_assets,
    synth_favicon_head_html,
)
from src.web.website_registration_v1 import is_production_env


DEFAULT_OUTPUT_ROOT = Path("/var/www/html/synth")
REGISTER_ENDPOINT = "/synth/web-auth/register"
VERIFY_ENDPOINT = "/synth/web-auth/verify-email"
LOGIN_ENDPOINT = "/synth/web-auth/login"
LOGOUT_ENDPOINT = "/synth/web-auth/logout"
ONBOARDING_ENDPOINT = "/synth/web-auth/onboarding-status"
RESEND_ENDPOINT = "/synth/web-auth/resend-verification"

TURNSTILE_SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js"
# Cloudflare's published always-pass test site key (public, non-secret).
TURNSTILE_TEST_SITE_KEY = "1x00000000000000000000AA"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render minimal SYNTH registration pages wired to the isolated website auth service. "
            "Static page render only; no dashboard URL changes, no broker calls."
        )
    )
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
    parser.add_argument(
        "--turnstile-site-key",
        default=os.getenv("SYNTH_TURNSTILE_SITE_KEY", ""),
        help="Cloudflare Turnstile public site key (SYNTH_TURNSTILE_SITE_KEY env). "
             "Public value — safe to embed in HTML. Never pass the secret key here.",
    )
    return parser.parse_args()


def _page_shell(*, title: str, body_html: str, script_html: str = "") -> str:
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
      color: var(--text); background: rgba(255,255,255,.05); cursor: pointer;
    }
    .auth-note { color: var(--muted); line-height: 1.55; }
    .status-pill { display: inline-block; margin-top: 8px; }
    .auth-status {
      margin-top: 14px; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--line);
      background: rgba(255,255,255,.03); color: var(--muted); min-height: 46px;
    }
    code { color: var(--warn); }
    """
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  {synth_favicon_head_html().rstrip()}
  <style>{css}</style>
</head>
<body>
  <div class="page auth-wrap">
    <header class="header">
      {cockpit_nav(include_auth_links=True)}
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
  {script_html}
</body>
</html>"""


def _json_fetch_script() -> str:
    return """
<script>
async function synthPostJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    credentials: "same-origin",
    body: JSON.stringify(payload || {})
  });
  const text = await response.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch (_error) {
    data = {"ok": false, "error": {"code": "INVALID_JSON_RESPONSE"}, "raw": text};
  }
  return {response, data};
}
</script>
""".strip()


def render_register_page(turnstile_site_key: str = "") -> str:
    # Escape for safe embedding in HTML attribute. Site key is public — no secret risk.
    safe_site_key = html_module.escape(turnstile_site_key or TURNSTILE_TEST_SITE_KEY)
    body = f"""
        <h2>Register</h2>
        <p class="auth-note">Create a SYNTH website profile. This does not create a trading account and does not collect exchange API credentials.</p>
        <form class="auth-grid" id="register-form">
          <div class="auth-field"><label>Email address</label><input type="email" name="email" autocomplete="email" required></div>
          <div class="auth-field"><label>Alias / profile code</label><input type="text" name="profile_code" autocomplete="username" required></div>
          <div class="auth-field"><label>Password</label><input type="password" name="password" autocomplete="new-password" required></div>
          <div class="cf-turnstile" data-sitekey="{safe_site_key}" data-callback="synthTurnstileSuccess" data-expired-callback="synthTurnstileExpired" data-error-callback="synthTurnstileError"></div>
          <div class="auth-actions">
            <button type="submit">Register</button>
            <a href="/synth/login.html">Already verified? Log in</a>
          </div>
        </form>
        <div id="register-status" class="auth-status" aria-live="polite">Waiting for registration input.</div>
        """
    script = (
        _json_fetch_script()
        + f"""
<script src="{TURNSTILE_SCRIPT_URL}" async defer></script>
<script>
var _synthTurnstileToken = "";
function synthTurnstileSuccess(token) {{ _synthTurnstileToken = token; }}
function synthTurnstileExpired() {{
  _synthTurnstileToken = "";
  var s = document.getElementById("register-status");
  if (s) {{ s.textContent = "Verification expired. Please complete the challenge again."; }}
}}
function synthTurnstileError(code) {{
  _synthTurnstileToken = "";
  var s = document.getElementById("register-status");
  if (s) {{ s.textContent = "Verification error. Please reload and try again."; }}
}}
document.getElementById("register-form").addEventListener("submit", async function(event) {{
  event.preventDefault();
  const form = event.currentTarget;
  const status = document.getElementById("register-status");
  if (!_synthTurnstileToken) {{
    status.textContent = "Please complete the human verification challenge.";
    return;
  }}
  const formData = new FormData(form);
  const payload = {{
    email: formData.get("email") || "",
    profile_code: formData.get("profile_code") || "",
    password: formData.get("password") || "",
    proof_response: _synthTurnstileToken,
  }};
  status.textContent = "Submitting registration...";
  const {{response, data}} = await synthPostJson("{REGISTER_ENDPOINT}", payload);
  if (response.ok && data.ok) {{
    status.textContent = "Registration accepted. Check your email for the verification link.";
  }} else {{
    _synthTurnstileToken = "";
    if (typeof turnstile !== "undefined") {{ turnstile.reset(); }}
    status.textContent = "Registration failed: " + ((data.error && data.error.code) || "UNKNOWN_ERROR");
  }}
}});
</script>
"""
    )
    return _page_shell(title="SYNTH Register", body_html=body, script_html=script)


def render_login_page() -> str:
    body = f"""
        <h2>Login</h2>
        <p class="auth-note">Use your verified email address or profile code. Email verification is required before login is permitted.</p>
        <div id="login-notice" class="auth-status" style="display:none" aria-live="polite"></div>
        <form class="auth-grid" id="login-form">
          <div class="auth-field"><label>Email or profile code</label><input type="text" name="login_value" autocomplete="username" required></div>
          <div class="auth-field"><label>Password</label><input type="password" name="password" autocomplete="current-password" required></div>
          <div class="auth-actions">
            <button type="submit">Login</button>
            <button type="button" id="resend-button">Resend verification email</button>
          </div>
        </form>
        <div id="login-status" class="auth-status" aria-live="polite">Waiting for login input.</div>
        """
    script = (
        _json_fetch_script()
        + f"""
<script>
(function() {{
  const notice = document.getElementById("login-notice");
  const reason = new URLSearchParams(window.location.search).get("reason") || "";
  if (reason === "session_expired") {{
    notice.textContent = "Your session has expired. Please log in again.";
    notice.style.display = "";
  }} else if (reason === "unauthorized") {{
    notice.textContent = "Authentication required to access that page.";
    notice.style.display = "";
  }} else if (reason === "forbidden") {{
    notice.textContent = "You are not authorized to access that profile.";
    notice.style.display = "";
  }}
}})();
const loginForm = document.getElementById("login-form");
const loginStatus = document.getElementById("login-status");
loginForm.addEventListener("submit", async function(event) {{
  event.preventDefault();
  loginStatus.textContent = "Signing in...";
  const payload = Object.fromEntries(new FormData(loginForm).entries());
  const {{response, data}} = await synthPostJson("{LOGIN_ENDPOINT}", payload);
  if (response.ok && data.ok) {{
    loginStatus.textContent = "Login complete. Redirecting...";
    const landingPath = typeof data.landing_path === "string" ? data.landing_path : "";
    if (landingPath && landingPath.startsWith("/synth/")) {{
      window.location.assign(landingPath);
    }} else {{
      window.location.assign("/synth/onboarding.html");
    }}
  }} else {{
    loginStatus.textContent = "Login failed. Check your email/profile code and password and try again.";
  }}
}});
document.getElementById("resend-button").addEventListener("click", async function() {{
  const payload = Object.fromEntries(new FormData(loginForm).entries());
  loginStatus.textContent = "Requesting verification resend...";
  const {{response, data}} = await synthPostJson("{RESEND_ENDPOINT}", {{login_value: payload.login_value || ""}});
  if (response.ok && data.ok) {{
    loginStatus.textContent = "If the profile is pending verification, a new verification email has been queued.";
  }} else {{
    loginStatus.textContent = "Resend failed: " + ((data.error && data.error.code) || "UNKNOWN_ERROR");
  }}
}});
</script>
"""
    )
    return _page_shell(title="SYNTH Login", body_html=body, script_html=script)


def render_verify_result_page() -> str:
    body = """
        <h2>Email Verification</h2>
        <p class="auth-note">Verification tokens are single-use and expire. The verification result is resolved server-side through the isolated website auth service.</p>
        <div id="verify-status" class="auth-status" aria-live="polite">Checking verification token...</div>
        """
    script = (
        _json_fetch_script()
        + f"""
<script>
(async function() {{
  const status = document.getElementById("verify-status");
  const token = new URLSearchParams(window.location.search).get("token") || "";
  if (!token) {{
    status.textContent = "Verification failed: MISSING_VERIFICATION_TOKEN";
    return;
  }}
  const {{response, data}} = await synthPostJson("{VERIFY_ENDPOINT}", {{token}});
  if (response.ok && data.ok) {{
    status.textContent = "Verification complete for profile " + (data.profile_code || "") + ". You can now log in.";
  }} else {{
    status.textContent = "Verification failed: " + ((data.error && data.error.code) || "UNKNOWN_ERROR");
  }}
}})();
</script>
"""
    )
    return _page_shell(title="SYNTH Verification", body_html=body, script_html=script)


def render_onboarding_page() -> str:
    body = f"""
        <h2>Onboarding</h2>
        <p class="auth-note">A verified website profile can exist before any exchange mapping is provisioned.</p>
        <div class="pill warn status-pill">NO_EXCHANGE_ACCOUNT_CONNECTED</div>
        <div id="onboarding-status" class="auth-status" aria-live="polite">Checking onboarding access...</div>
        <div class="auth-actions">
          <button type="button" id="logout-button">Logout</button>
        </div>

        <section class="auth-card" style="margin-top:28px;opacity:.7">
          <h3 style="color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.08em">
            API-account koppelen
            <span style="font-size:10px;border:1px solid var(--line);border-radius:6px;padding:2px 8px;margin-left:8px">Toekomstig</span>
          </h3>
          <p class="auth-note">
            Een exchange API-koppeling wordt later in een aparte stap toegevoegd.
            Wanneer je een API-sleutel koppelt, worden uitsluitend de volgende rechten ondersteund:
          </p>
          <ul class="auth-note" style="padding-left:18px;line-height:2">
            <li>Accountbalans lezen</li>
            <li>Posities lezen</li>
            <li>Openstaande orders lezen</li>
          </ul>
          <p class="auth-note" style="color:var(--warn)">
            <strong>Niet toegestaan:</strong> handelen, orders aanmaken of wijzigen, opnames, overboekingen of adresbeheer.
          </p>
          <p class="auth-note">
            API-sleutels worden later server-side versleuteld opgeslagen.
            Ze worden nooit opgeslagen in HTML, JSON, URL's, logbestanden of browserstorage.
            Er zijn op dit moment geen velden voor inloggegevens beschikbaar.
          </p>
        </section>
        """
    script = (
        _json_fetch_script()
        + f"""
<script>
const onboardingStatus = document.getElementById("onboarding-status");
async function refreshOnboardingStatus() {{
  const {{response, data}} = await synthPostJson("{ONBOARDING_ENDPOINT}", {{}});
  if (response.ok && data.ok) {{
    onboardingStatus.textContent = "Onboarding state: " + (data.onboarding_state || "UNKNOWN");
  }} else if (response.status === 401) {{
    onboardingStatus.textContent = "Session verlopen of niet ingelogd. Doorsturen naar login...";
    setTimeout(function() {{ window.location.assign("/synth/login.html?reason=session_expired"); }}, 1500);
  }} else if (response.status === 403) {{
    onboardingStatus.textContent = "Geen toegang tot dit profiel.";
  }} else {{
    onboardingStatus.textContent = "Onboarding access failed: " + ((data.error && data.error.code) || "UNKNOWN_ERROR");
  }}
}}
document.getElementById("logout-button").addEventListener("click", async function() {{
  await synthPostJson("{LOGOUT_ENDPOINT}", {{}});
  window.location.assign("/synth/login.html");
}});
refreshOnboardingStatus();
</script>
"""
    )
    return _page_shell(title="SYNTH Onboarding", body_html=body, script_html=script)


def main() -> int:
    args = parse_args()
    env = dict(os.environ)
    if is_production_env(env) and not args.turnstile_site_key:
        raise RuntimeError("PRODUCTION_TURNSTILE_SITE_KEY_REQUIRED")
    output_root = Path(args.output_root)
    favicon_outputs = copy_synth_favicon_assets(output_root=output_root)
    pages = {
        "register.html": render_register_page(turnstile_site_key=args.turnstile_site_key),
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
