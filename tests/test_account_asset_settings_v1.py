from __future__ import annotations

import ast
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.account.account_asset_settings_v1 import (
    ACTION_ADD_ASSET,
    ACTION_CLEAR_PORTFOLIO_MEMBER,
    ACTION_DISABLE_CANDIDATE,
    ACTION_HIDE_ASSET,
    ACTION_PAUSE_CANDIDATE_24H,
    ACTION_REENABLE_ASSET,
    ACTION_SET_PORTFOLIO_MEMBER,
    DEFAULT_VENUE,
    SOURCE_MANUAL_ADD,
    add_asset_for_account,
    clear_portfolio_member_for_account,
    disable_candidate_for_account,
    dispatch_account_asset_action,
    hide_asset_for_account,
    pause_candidate_for_account,
    reenable_asset_for_account,
    set_portfolio_member_for_account,
)


class FakeRepo:
    def __init__(self):
        self.accounts = {
            ("bitvavo_hugo_read", DEFAULT_VENUE): {
                "trading_account_id": 1,
                "account_code": "bitvavo_hugo_read",
                "venue": DEFAULT_VENUE,
            },
            ("bitvavo_joost_read", DEFAULT_VENUE): {
                "trading_account_id": 2,
                "account_code": "bitvavo_joost_read",
                "venue": DEFAULT_VENUE,
            },
        }
        self.venue_markets = {
            (DEFAULT_VENUE, "FET-EUR"): {
                "venue_market_id": 10,
                "venue": DEFAULT_VENUE,
                "market": "FET-EUR",
                "quote_currency": "EUR",
                "is_tradeable": 1,
                "asset_symbol": "FET",
            },
            (DEFAULT_VENUE, "WLD-EUR"): {
                "venue_market_id": 11,
                "venue": DEFAULT_VENUE,
                "market": "WLD-EUR",
                "quote_currency": "EUR",
                "is_tradeable": 1,
                "asset_symbol": "WLD",
            },
            (DEFAULT_VENUE, "BTC-USDT"): {
                "venue_market_id": 12,
                "venue": DEFAULT_VENUE,
                "market": "BTC-USDT",
                "quote_currency": "USDT",
                "is_tradeable": 1,
                "asset_symbol": "BTC",
            },
        }
        self.account_assets: dict[tuple[int, int], dict[str, Any]] = {}

    def fetch_trading_account(self, *, account_code: str, venue: str) -> dict[str, Any] | None:
        return self.accounts.get((account_code, venue))

    def fetch_venue_market(self, *, venue: str, market: str) -> dict[str, Any] | None:
        return self.venue_markets.get((venue, market))

    def fetch_account_asset(self, *, trading_account_id: int, venue_market_id: int) -> dict[str, Any] | None:
        row = self.account_assets.get((trading_account_id, venue_market_id))
        return None if row is None else dict(row)

    def insert_account_asset(
        self,
        *,
        trading_account_id: int,
        venue_market_id: int,
        source: str,
        now_utc: datetime,
    ) -> None:
        self.account_assets[(trading_account_id, venue_market_id)] = {
            "trading_account_id": trading_account_id,
            "venue_market_id": venue_market_id,
            "is_visible": 1,
            "is_candidate_enabled": 1,
            "is_order_proposal_enabled": 0,
            "is_portfolio_member": 0,
            "is_hidden": 0,
            "disabled_until_utc": None,
            "disabled_reason": None,
            "source": source,
            "first_seen_at_utc": now_utc,
            "last_seen_at_utc": now_utc,
        }

    def update_account_asset(
        self,
        *,
        trading_account_id: int,
        venue_market_id: int,
        updates: dict[str, Any],
    ) -> None:
        current = self.account_assets[(trading_account_id, venue_market_id)]
        current.update(updates)


def test_dependency_check_fails_closed_if_account_asset_foundation_missing():
    repo = FakeRepo()
    repo.venue_markets = {}
    try:
        add_asset_for_account(
            repo,
            account_code="bitvavo_hugo_read",
            venue=DEFAULT_VENUE,
            market="FET-EUR",
            now_utc=datetime(2026, 6, 3, 12, 0, 0),
        )
        raise AssertionError("Expected RuntimeError when venue_market foundation is missing")
    except RuntimeError as exc:
        assert "venue_market not found" in str(exc)


def test_adding_fet_eur_for_hugo_affects_only_hugo():
    repo = FakeRepo()
    add_asset_for_account(
        repo,
        account_code="bitvavo_hugo_read",
        venue=DEFAULT_VENUE,
        market="FET-EUR",
        now_utc=datetime(2026, 6, 3, 12, 0, 0),
    )
    assert (1, 10) in repo.account_assets
    assert (2, 10) not in repo.account_assets


def test_joost_remains_unchanged():
    repo = FakeRepo()
    add_asset_for_account(
        repo,
        account_code="bitvavo_hugo_read",
        venue=DEFAULT_VENUE,
        market="FET-EUR",
        now_utc=datetime(2026, 6, 3, 12, 0, 0),
    )
    assert repo.fetch_account_asset(trading_account_id=2, venue_market_id=10) is None


def test_duplicate_add_is_idempotent():
    repo = FakeRepo()
    first = add_asset_for_account(
        repo,
        account_code="bitvavo_hugo_read",
        venue=DEFAULT_VENUE,
        market="FET-EUR",
        now_utc=datetime(2026, 6, 3, 12, 0, 0),
    )
    second = add_asset_for_account(
        repo,
        account_code="bitvavo_hugo_read",
        venue=DEFAULT_VENUE,
        market="FET-EUR",
        now_utc=datetime(2026, 6, 3, 12, 5, 0),
    )
    assert first.status == "INSERTED"
    assert second.status == "EXISTING"
    assert len(repo.account_assets) == 1


def test_hide_works():
    repo = FakeRepo()
    add_asset_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")
    hide_asset_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")
    row = repo.fetch_account_asset(trading_account_id=1, venue_market_id=10)
    assert row["is_hidden"] == 1
    assert row["is_visible"] == 0


def test_disable_works():
    repo = FakeRepo()
    add_asset_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")
    disable_candidate_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")
    row = repo.fetch_account_asset(trading_account_id=1, venue_market_id=10)
    assert row["is_candidate_enabled"] == 0
    assert row["disabled_reason"] == "MANUAL_DISABLE"


def test_pause_24h_sets_disabled_until_utc():
    repo = FakeRepo()
    now = datetime(2026, 6, 3, 12, 0, 0)
    add_asset_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR", now_utc=now)
    pause_candidate_for_account(
        repo,
        account_code="bitvavo_hugo_read",
        venue=DEFAULT_VENUE,
        market="FET-EUR",
        now_utc=now,
    )
    row = repo.fetch_account_asset(trading_account_id=1, venue_market_id=10)
    assert row["disabled_until_utc"] == now + timedelta(hours=24)


def test_reenable_clears_disabled_flags_reason_as_appropriate():
    repo = FakeRepo()
    now = datetime(2026, 6, 3, 12, 0, 0)
    add_asset_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR", now_utc=now)
    pause_candidate_for_account(
        repo,
        account_code="bitvavo_hugo_read",
        venue=DEFAULT_VENUE,
        market="FET-EUR",
        now_utc=now,
    )
    reenable_asset_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")
    row = repo.fetch_account_asset(trading_account_id=1, venue_market_id=10)
    assert row["is_visible"] == 1
    assert row["is_hidden"] == 0
    assert row["is_candidate_enabled"] == 1
    assert row["disabled_until_utc"] is None
    assert row["disabled_reason"] is None


def test_missing_venue_market_fails_closed():
    repo = FakeRepo()
    try:
        add_asset_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="NOTREAL-EUR")
        raise AssertionError("Expected RuntimeError for missing venue_market")
    except RuntimeError as exc:
        assert "venue_market not found" in str(exc)


def test_default_manual_add_sets_is_order_proposal_enabled_false():
    repo = FakeRepo()
    result = add_asset_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")
    row = repo.fetch_account_asset(trading_account_id=1, venue_market_id=10)
    assert result.source == SOURCE_MANUAL_ADD
    assert row["is_order_proposal_enabled"] == 0


def test_non_eur_market_excluded_by_default_filter():
    repo = FakeRepo()
    try:
        add_asset_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="BTC-USDT")
        raise AssertionError("Expected RuntimeError for non-EUR market")
    except RuntimeError as exc:
        assert "requires EUR market by default" in str(exc)


def test_set_portfolio_member_sets_one_row():
    repo = FakeRepo()
    add_asset_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")
    result = set_portfolio_member_for_account(
        repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR"
    )
    row = repo.fetch_account_asset(trading_account_id=1, venue_market_id=10)
    assert row["is_portfolio_member"] == 1
    assert result.action == ACTION_SET_PORTFOLIO_MEMBER
    assert result.status == "UPDATED"


def test_clear_portfolio_member_clears_one_row():
    repo = FakeRepo()
    add_asset_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")
    set_portfolio_member_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")
    result = clear_portfolio_member_for_account(
        repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR"
    )
    row = repo.fetch_account_asset(trading_account_id=1, venue_market_id=10)
    assert row["is_portfolio_member"] == 0
    assert result.action == ACTION_CLEAR_PORTFOLIO_MEMBER


def test_set_portfolio_member_does_not_affect_other_account():
    repo = FakeRepo()
    add_asset_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")
    add_asset_for_account(repo, account_code="bitvavo_joost_read", venue=DEFAULT_VENUE, market="FET-EUR")
    joost_before = repo.fetch_account_asset(trading_account_id=2, venue_market_id=10)

    set_portfolio_member_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")

    joost_after = repo.fetch_account_asset(trading_account_id=2, venue_market_id=10)
    assert joost_before == joost_after
    assert joost_after["is_portfolio_member"] == 0
    hugo_row = repo.fetch_account_asset(trading_account_id=1, venue_market_id=10)
    assert hugo_row["is_portfolio_member"] == 1


def test_clear_portfolio_member_does_not_affect_other_account():
    repo = FakeRepo()
    add_asset_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")
    add_asset_for_account(repo, account_code="bitvavo_joost_read", venue=DEFAULT_VENUE, market="FET-EUR")
    set_portfolio_member_for_account(repo, account_code="bitvavo_joost_read", venue=DEFAULT_VENUE, market="FET-EUR")
    hugo_before = repo.fetch_account_asset(trading_account_id=1, venue_market_id=10)

    clear_portfolio_member_for_account(repo, account_code="bitvavo_joost_read", venue=DEFAULT_VENUE, market="FET-EUR")

    hugo_after = repo.fetch_account_asset(trading_account_id=1, venue_market_id=10)
    assert hugo_before == hugo_after
    joost_row = repo.fetch_account_asset(trading_account_id=2, venue_market_id=10)
    assert joost_row["is_portfolio_member"] == 0


def test_set_then_clear_portfolio_member_is_idempotent():
    repo = FakeRepo()
    add_asset_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")

    set_portfolio_member_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")
    set_portfolio_member_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")
    row = repo.fetch_account_asset(trading_account_id=1, venue_market_id=10)
    assert row["is_portfolio_member"] == 1

    clear_portfolio_member_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")
    clear_portfolio_member_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")
    row = repo.fetch_account_asset(trading_account_id=1, venue_market_id=10)
    assert row["is_portfolio_member"] == 0


def test_set_portfolio_member_missing_account_asset_fails_closed():
    repo = FakeRepo()
    try:
        set_portfolio_member_for_account(
            repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR"
        )
        raise AssertionError("Expected RuntimeError for missing account_asset row")
    except RuntimeError as exc:
        assert "account_asset not found" in str(exc)


def test_set_portfolio_member_preserves_unrelated_fields():
    repo = FakeRepo()
    add_asset_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")
    before = repo.fetch_account_asset(trading_account_id=1, venue_market_id=10)

    set_portfolio_member_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="FET-EUR")

    after = repo.fetch_account_asset(trading_account_id=1, venue_market_id=10)
    for key in before:
        if key == "is_portfolio_member":
            continue
        assert after[key] == before[key], f"unexpected drift in field {key}"
    assert after["is_portfolio_member"] == 1


def test_dispatch_supports_all_actions():
    repo = FakeRepo()
    add_asset_for_account(repo, account_code="bitvavo_hugo_read", venue=DEFAULT_VENUE, market="WLD-EUR")
    for action in [
        ACTION_ADD_ASSET,
        ACTION_HIDE_ASSET,
        ACTION_DISABLE_CANDIDATE,
        ACTION_PAUSE_CANDIDATE_24H,
        ACTION_REENABLE_ASSET,
        ACTION_SET_PORTFOLIO_MEMBER,
        ACTION_CLEAR_PORTFOLIO_MEMBER,
    ]:
        dispatch_account_asset_action(
            repo,
            action=action,
            account_code="bitvavo_hugo_read",
            venue=DEFAULT_VENUE,
            market="WLD-EUR",
            now_utc=datetime(2026, 6, 3, 12, 0, 0),
        )


def test_source_checks_forbid_broker_writes_order_submission():
    for path in [
        Path("src/account/account_asset_settings_v1.py"),
        Path("src/account/run_account_asset_settings_v1.py"),
    ]:
        src = path.read_text()
        assert "place_order" not in src
        assert "cancel_order" not in src


def test_no_decision_gate_execution_planner_executor_imports():
    for path in [
        Path("src/account/account_asset_settings_v1.py"),
        Path("src/account/run_account_asset_settings_v1.py"),
    ]:
        src = path.read_text()
        assert "import src.decision_gate" not in src
        assert "from src.decision_gate" not in src
        assert "import src.execution_planner" not in src
        assert "from src.execution_planner" not in src
        assert "import src.executor" not in src
        assert "from src.executor" not in src


def test_no_broker_ast_calls():
    src = Path("src/account/account_asset_settings_v1.py").read_text()
    tree = ast.parse(src)
    forbidden = {"place_order", "cancel_order", "create_order"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            raise AssertionError(f"Forbidden broker-like call .{node.attr}() found")


def main():
    test_dependency_check_fails_closed_if_account_asset_foundation_missing()
    test_adding_fet_eur_for_hugo_affects_only_hugo()
    test_joost_remains_unchanged()
    test_duplicate_add_is_idempotent()
    test_hide_works()
    test_disable_works()
    test_pause_24h_sets_disabled_until_utc()
    test_reenable_clears_disabled_flags_reason_as_appropriate()
    test_missing_venue_market_fails_closed()
    test_default_manual_add_sets_is_order_proposal_enabled_false()
    test_non_eur_market_excluded_by_default_filter()
    test_set_portfolio_member_sets_one_row()
    test_clear_portfolio_member_clears_one_row()
    test_set_portfolio_member_does_not_affect_other_account()
    test_clear_portfolio_member_does_not_affect_other_account()
    test_set_then_clear_portfolio_member_is_idempotent()
    test_set_portfolio_member_missing_account_asset_fails_closed()
    test_set_portfolio_member_preserves_unrelated_fields()
    test_dispatch_supports_all_actions()
    test_source_checks_forbid_broker_writes_order_submission()
    test_no_decision_gate_execution_planner_executor_imports()
    test_no_broker_ast_calls()
    print("ok")


if __name__ == "__main__":
    main()
