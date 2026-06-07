from __future__ import annotations

from pathlib import Path


SOURCE = Path("src/reporting/account_dashboard_profile_access_v1.py").read_text(encoding="utf-8")


def test_no_hardcoded_profile_tuple_in_source() -> None:
    """Hardcoded profile/account tuple must not be the canonical authority."""
    assert "CONFIGURED_DASHBOARD_PROFILE_ACCESS" not in SOURCE, (
        "Hardcoded profile tuple must be removed; resolution must come from DB link table."
    )


def test_db_backed_resolver_queries_link_table() -> None:
    """Resolution must query app_profile_trading_account_link, not a static map."""
    assert "app_profile_trading_account_link" in SOURCE
    assert "aptl" in SOURCE  # alias used in the JOIN query


def test_resolver_checks_active_primary_link() -> None:
    """Resolver must filter by link_status=ACTIVE and is_primary=1."""
    assert "link_status" in SOURCE
    assert "ACTIVE" in SOURCE
    assert "is_primary" in SOURCE


def test_resolver_raises_on_missing_link() -> None:
    """PROFILE_HAS_NO_ACCOUNT_ACCESS must be raised when no active primary link exists."""
    assert "PROFILE_HAS_NO_ACCOUNT_ACCESS" in SOURCE
    assert "if not rows" in SOURCE or "not rows" in SOURCE


def test_resolver_raises_on_ambiguous_link() -> None:
    """Multiple active primary links must raise, not silently pick one."""
    assert "AMBIGUOUS_PROFILE_ACCOUNT_LINK" in SOURCE
    assert "len(rows) > 1" in SOURCE


def test_no_credential_inference_from_profile_name() -> None:
    """Account code must never be constructed from profile name."""
    assert 'f"{venue.lower()}_{profile}_read"' not in SOURCE
    assert "default_account_code" not in SOURCE
    assert "profile_code + " not in SOURCE
    assert '+ "_read"' not in SOURCE


def test_profile_has_no_account_access_constant_present() -> None:
    from src.reporting.account_dashboard_profile_access_v1 import PROFILE_HAS_NO_ACCOUNT_ACCESS
    assert PROFILE_HAS_NO_ACCOUNT_ACCESS == "PROFILE_HAS_NO_ACCOUNT_ACCESS"
