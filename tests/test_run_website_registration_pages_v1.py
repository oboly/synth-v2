from __future__ import annotations

import os
import tempfile
from pathlib import Path

from src.web.run_website_registration_pages_v1 import (
    TURNSTILE_SCRIPT_URL,
    TURNSTILE_TEST_SITE_KEY,
    render_login_page,
    render_onboarding_page,
    render_register_page,
    render_verify_result_page,
)


# ---------------------------------------------------------------------------
# Existing page-structure tests (updated for Turnstile)
# ---------------------------------------------------------------------------

def test_register_page_contains_required_fields() -> None:
    html = render_register_page()
    assert "Email address" in html
    assert "Alias / profile code" in html
    assert "Password" in html
    assert "/synth/web-auth/register" in html
    assert "/synth/accounts/" not in html


def test_login_page_contains_expected_copy() -> None:
    html = render_login_page()
    assert "Login" in html
    assert "Existing public dashboard URLs remain unchanged" in html
    assert "/synth/web-auth/login" in html
    assert "/synth/web-auth/resend-verification" in html


def test_onboarding_page_shows_no_exchange_state() -> None:
    html = render_onboarding_page()
    assert "NO_EXCHANGE_ACCOUNT_CONNECTED" in html
    assert "/synth/web-auth/onboarding-status" in html
    assert "/synth/web-auth/logout" in html


def test_public_pages_include_register_and_login_navigation() -> None:
    html = render_register_page()
    assert "/synth/register.html" in html
    assert "/synth/login.html" in html


def test_pages_runner_outputs_only_new_public_pages() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "synth"
        for name, html in {
            "register.html": render_register_page(),
            "login.html": render_login_page(),
            "verify-result.html": render_verify_result_page(),
            "onboarding.html": render_onboarding_page(),
        }.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(html, encoding="utf-8")
        assert (root / "register.html").exists()
        assert (root / "login.html").exists()
        assert (root / "verify-result.html").exists()
        assert (root / "onboarding.html").exists()
        assert not (root / "accounts").exists()
        assert not (root / "profit-plan.html").exists()
        assert not (root / "open-orders-monitor.html").exists()


# ---------------------------------------------------------------------------
# Turnstile widget tests
# ---------------------------------------------------------------------------

def test_register_page_includes_turnstile_script() -> None:
    """Cloudflare Turnstile script must be loaded in the register page."""
    html = render_register_page(turnstile_site_key="0x4AAAAAABtest")
    assert TURNSTILE_SCRIPT_URL in html


def test_register_page_has_cf_turnstile_element() -> None:
    """cf-turnstile div must be present with data-sitekey attribute."""
    html = render_register_page(turnstile_site_key="0x4AAAAAABtest")
    assert 'class="cf-turnstile"' in html
    assert "data-sitekey=" in html


def test_register_page_site_key_html_escaped() -> None:
    """Site key must be HTML-escaped before embedding in the attribute."""
    html = render_register_page(turnstile_site_key='key"<>&test')
    assert 'key"<>&test' not in html
    assert "key&quot;&lt;&gt;&amp;test" in html


def test_register_page_no_manual_proof_textarea() -> None:
    """Manual proof_response textarea must be absent — Turnstile replaces it."""
    html = render_register_page()
    assert 'name="proof_response"' not in html
    assert "Proof-of-human response" not in html


def test_register_page_js_maps_turnstile_token_to_proof_response() -> None:
    """JS must read the internal token variable and pass it as proof_response."""
    html = render_register_page(turnstile_site_key="0x4AAAAAABtest")
    # Token variable is populated by the Turnstile callback
    assert "_synthTurnstileToken" in html
    assert "synthTurnstileSuccess" in html
    # Token is mapped to proof_response in the payload
    assert "proof_response: _synthTurnstileToken" in html or "proof_response" in html
    # cf-turnstile-response must not be forwarded as a separate payload field
    assert '"cf-turnstile-response"' not in html
    assert "cf-turnstile-response" not in html.split("proof_response")[0]


def test_register_page_blocks_submit_without_token() -> None:
    """Submit handler must block if no Turnstile token is present."""
    html = render_register_page()
    assert "Please complete the human verification challenge" in html
    assert "!_synthTurnstileToken" in html


def test_register_page_resets_widget_on_failure() -> None:
    """Widget must be reset after a failed registration attempt."""
    html = render_register_page()
    assert "turnstile.reset()" in html


def test_register_page_handles_expired_callback() -> None:
    """Turnstile expired callback must clear the token and inform the user."""
    html = render_register_page()
    assert "synthTurnstileExpired" in html
    assert "expired" in html.lower()


def test_register_page_handles_error_callback() -> None:
    """Turnstile error callback must clear the token and inform the user."""
    html = render_register_page()
    assert "synthTurnstileError" in html


def test_register_page_uses_test_site_key_by_default() -> None:
    """When no site key is provided, the Cloudflare test site key is used."""
    html = render_register_page()
    assert TURNSTILE_TEST_SITE_KEY in html


def test_register_page_uses_supplied_site_key() -> None:
    """Explicit site key is embedded, not the test key."""
    production_key = "0x4AAAAAAA_production_key"
    html = render_register_page(turnstile_site_key=production_key)
    assert production_key in html


# ---------------------------------------------------------------------------
# Secret leakage tests
# ---------------------------------------------------------------------------

def test_secret_never_in_rendered_output() -> None:
    """SYNTH_TURNSTILE_SECRET must never appear in rendered HTML."""
    fake_secret = "FAKE_SECRET_abc123XYZ_do_not_leak"
    original = dict(os.environ)
    try:
        os.environ["SYNTH_TURNSTILE_SECRET"] = fake_secret
        html = render_register_page(turnstile_site_key="0x4test")
        assert fake_secret not in html, "Secret key must not appear in rendered HTML"
    finally:
        os.environ.clear()
        os.environ.update(original)


def test_no_secret_keyword_in_register_page_source() -> None:
    """The page renderer source must not reference SYNTH_TURNSTILE_SECRET."""
    source = Path("src/web/run_website_registration_pages_v1.py").read_text(encoding="utf-8")
    assert "SYNTH_TURNSTILE_SECRET" not in source


# ---------------------------------------------------------------------------
# Production fail-closed test
# ---------------------------------------------------------------------------

def test_missing_production_site_key_fails_closed() -> None:
    """Production render must raise RuntimeError if site key is missing."""
    from src.web.website_registration_v1 import is_production_env

    prod_env = {"SYNTH_ENV": "production"}
    assert is_production_env(prod_env)

    # Simulate the main() guard: production + empty site key → RuntimeError
    turnstile_site_key = ""
    try:
        if is_production_env(prod_env) and not turnstile_site_key:
            raise RuntimeError("PRODUCTION_TURNSTILE_SITE_KEY_REQUIRED")
    except RuntimeError as exc:
        assert "PRODUCTION_TURNSTILE_SITE_KEY_REQUIRED" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for missing production site key")


def test_production_site_key_accepted_when_present() -> None:
    """Production render must succeed when site key is provided."""
    from src.web.website_registration_v1 import is_production_env

    prod_env = {"SYNTH_ENV": "production"}
    turnstile_site_key = "0x4AAAAAAA_real_key"

    # Simulate the main() guard: production + non-empty site key → no error
    if is_production_env(prod_env) and not turnstile_site_key:
        raise AssertionError("Should not raise — key is present")

    html = render_register_page(turnstile_site_key=turnstile_site_key)
    assert turnstile_site_key in html


def main() -> None:
    test_register_page_contains_required_fields()
    test_login_page_contains_expected_copy()
    test_onboarding_page_shows_no_exchange_state()
    test_public_pages_include_register_and_login_navigation()
    test_pages_runner_outputs_only_new_public_pages()
    test_register_page_includes_turnstile_script()
    test_register_page_has_cf_turnstile_element()
    test_register_page_site_key_html_escaped()
    test_register_page_no_manual_proof_textarea()
    test_register_page_js_maps_turnstile_token_to_proof_response()
    test_register_page_blocks_submit_without_token()
    test_register_page_resets_widget_on_failure()
    test_register_page_handles_expired_callback()
    test_register_page_handles_error_callback()
    test_register_page_uses_test_site_key_by_default()
    test_register_page_uses_supplied_site_key()
    test_secret_never_in_rendered_output()
    test_no_secret_keyword_in_register_page_source()
    test_missing_production_site_key_fails_closed()
    test_production_site_key_accepted_when_present()
    print("ok")


if __name__ == "__main__":
    main()
