from __future__ import annotations

from pathlib import Path

from src.reporting.account_dashboard_profile_access_v1 import (
    PROFILE_HAS_NO_ACCOUNT_ACCESS,
    resolve_dashboard_profile_access,
)


def test_configured_joost_profile_resolves_exactly_one_trading_account() -> None:
    access = resolve_dashboard_profile_access(account_profile="joost", venue="bitvavo")
    assert access.account_profile == "joost"
    assert access.venue == "bitvavo"
    assert access.trading_account_stable_ref == "bitvavo_joost_read"


def test_unmapped_hugo_profile_fails_closed() -> None:
    try:
        resolve_dashboard_profile_access(account_profile="hugo", venue="bitvavo")
    except RuntimeError as exc:
        assert PROFILE_HAS_NO_ACCOUNT_ACCESS in str(exc)
        assert "profile=hugo" in str(exc)
    else:
        raise AssertionError("Expected PROFILE_HAS_NO_ACCOUNT_ACCESS for unmapped Hugo profile")


def test_no_credential_like_account_code_is_constructed_from_profile_name() -> None:
    source = Path("src/reporting/account_dashboard_profile_access_v1.py").read_text(encoding="utf-8")
    assert 'f"{venue.lower()}_{profile}_read"' not in source
    assert "default_account_code" not in source


def main() -> None:
    test_configured_joost_profile_resolves_exactly_one_trading_account()
    test_unmapped_hugo_profile_fails_closed()
    test_no_credential_like_account_code_is_constructed_from_profile_name()
    print("ok")


if __name__ == "__main__":
    main()
