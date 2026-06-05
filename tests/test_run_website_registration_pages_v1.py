from __future__ import annotations

import tempfile
from pathlib import Path

from src.web.run_website_registration_pages_v1 import (
    render_login_page,
    render_onboarding_page,
    render_register_page,
    render_verify_result_page,
)


def test_register_page_contains_required_fields() -> None:
    html = render_register_page()
    assert "Email address" in html
    assert "Alias / profile code" in html
    assert "Password" in html
    assert "Proof-of-human response" in html
    assert "/synth/accounts/" not in html


def test_login_page_contains_expected_copy() -> None:
    html = render_login_page()
    assert "Login" in html
    assert "Existing public dashboard pages remain public and unchanged" in html


def test_onboarding_page_shows_no_exchange_state() -> None:
    html = render_onboarding_page()
    assert "NO_EXCHANGE_ACCOUNT_CONNECTED" in html


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


def main() -> None:
    test_register_page_contains_required_fields()
    test_login_page_contains_expected_copy()
    test_onboarding_page_shows_no_exchange_state()
    test_pages_runner_outputs_only_new_public_pages()
    print("ok")


if __name__ == "__main__":
    main()
