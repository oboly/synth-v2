from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.account.account_portfolio_member_backfill_v1 import (
    ROW_ACTION_ALREADY_MEMBER,
    ROW_ACTION_SEED,
    ROW_ACTION_SKIP_NO_ACCOUNT_ASSET,
    compute_and_apply_portfolio_member_backfill,
)


BACKFILL_SOURCE_PATH = Path("src/account/account_portfolio_member_backfill_v1.py")

# Matches any reference to the global asset table's publication-cohort column
# (historically "is_portfolio") while explicitly allowing the legitimate
# account_asset.is_portfolio_member column this issue implements.
_GLOBAL_ASSET_IS_PORTFOLIO_RE = re.compile(r"(?<!account_)asset\.is_portfolio\b(?!_member)")


class FakeBackfillRepo:
    def __init__(self):
        # (trading_account_id, venue) -> list[{"currency_code", "total_amount"}]
        self.balances: dict[tuple[int, str], list[dict[str, Any]]] = {}
        # (venue, market) -> venue_market_id
        self.venue_markets: dict[tuple[str, str], int] = {}
        # (trading_account_id, venue_market_id) -> {"is_portfolio_member": int}
        self.account_assets: dict[tuple[int, int], dict[str, Any]] = {}

    def fetch_latest_positive_balances(self, *, trading_account_id: int, venue: str) -> list[dict[str, Any]]:
        return list(self.balances.get((trading_account_id, venue), []))

    def fetch_venue_market_id(self, *, venue: str, market: str) -> int | None:
        return self.venue_markets.get((venue, market))

    def fetch_account_asset(self, *, trading_account_id: int, venue_market_id: int) -> dict[str, Any] | None:
        row = self.account_assets.get((trading_account_id, venue_market_id))
        return None if row is None else dict(row)

    def set_portfolio_member(self, *, trading_account_id: int, venue_market_id: int) -> None:
        self.account_assets[(trading_account_id, venue_market_id)]["is_portfolio_member"] = 1


VENUE = "bitvavo"


def make_repo() -> FakeBackfillRepo:
    repo = FakeBackfillRepo()
    repo.venue_markets[(VENUE, "FET-EUR")] = 10
    repo.venue_markets[(VENUE, "WLD-EUR")] = 11
    # NOTREAL-EUR intentionally has no venue_market row (unresolved identity case)
    return repo


def test_backfill_seeds_only_positive_holdings_for_requested_account():
    repo = make_repo()
    repo.account_assets[(1, 10)] = {"is_portfolio_member": 0}
    repo.balances[(1, VENUE)] = [
        {"currency_code": "FET", "total_amount": Decimal("5")},
    ]

    result = compute_and_apply_portfolio_member_backfill(
        repo, trading_account_id=1, venue=VENUE, dry_run=False
    )

    assert result.seeded == 1
    assert repo.account_assets[(1, 10)]["is_portfolio_member"] == 1
    assert result.rows[0].row_action == ROW_ACTION_SEED


def test_backfill_does_not_leak_account_b_holdings_into_account_a():
    repo = make_repo()
    repo.account_assets[(1, 10)] = {"is_portfolio_member": 0}
    repo.account_assets[(2, 10)] = {"is_portfolio_member": 0}
    # Only account B (trading_account_id=2) holds FET-EUR.
    repo.balances[(2, VENUE)] = [
        {"currency_code": "FET", "total_amount": Decimal("5")},
    ]

    result = compute_and_apply_portfolio_member_backfill(
        repo, trading_account_id=1, venue=VENUE, dry_run=False
    )

    assert result.seeded == 0
    assert repo.account_assets[(1, 10)]["is_portfolio_member"] == 0
    assert repo.account_assets[(2, 10)]["is_portfolio_member"] == 0  # untouched: different account requested


def test_backfill_never_touches_other_account_when_backfilling_one():
    repo = make_repo()
    repo.account_assets[(1, 10)] = {"is_portfolio_member": 0}
    repo.account_assets[(2, 10)] = {"is_portfolio_member": 0}
    repo.balances[(1, VENUE)] = [{"currency_code": "FET", "total_amount": Decimal("5")}]
    repo.balances[(2, VENUE)] = [{"currency_code": "FET", "total_amount": Decimal("7")}]

    compute_and_apply_portfolio_member_backfill(repo, trading_account_id=1, venue=VENUE, dry_run=False)

    assert repo.account_assets[(1, 10)]["is_portfolio_member"] == 1
    assert repo.account_assets[(2, 10)]["is_portfolio_member"] == 0


def test_backfill_does_not_seed_zero_balance_assets():
    repo = make_repo()
    repo.account_assets[(1, 10)] = {"is_portfolio_member": 0}
    repo.balances[(1, VENUE)] = [
        {"currency_code": "FET", "total_amount": Decimal("0")},
    ]

    result = compute_and_apply_portfolio_member_backfill(
        repo, trading_account_id=1, venue=VENUE, dry_run=False
    )

    assert result.seeded == 0
    assert repo.account_assets[(1, 10)]["is_portfolio_member"] == 0


def test_backfill_does_not_clear_existing_membership_on_zero_balance():
    repo = make_repo()
    # Existing membership declared by operator action, balance now zero.
    repo.account_assets[(1, 10)] = {"is_portfolio_member": 1}
    repo.balances[(1, VENUE)] = []  # no positive holdings at all

    result = compute_and_apply_portfolio_member_backfill(
        repo, trading_account_id=1, venue=VENUE, dry_run=False
    )

    assert result.seeded == 0
    assert repo.account_assets[(1, 10)]["is_portfolio_member"] == 1


def test_backfill_skips_holding_with_no_account_asset_identity_instead_of_creating_row():
    repo = make_repo()
    repo.balances[(1, VENUE)] = [
        {"currency_code": "NOTREAL", "total_amount": Decimal("3")},
    ]

    result = compute_and_apply_portfolio_member_backfill(
        repo, trading_account_id=1, venue=VENUE, dry_run=False
    )

    assert result.seeded == 0
    assert result.skipped_no_account_asset == 1
    assert result.rows[0].row_action == ROW_ACTION_SKIP_NO_ACCOUNT_ASSET
    assert (1, 12) not in repo.account_assets  # no row silently created


def test_backfill_skips_holding_resolved_to_venue_market_without_account_asset_row():
    repo = make_repo()
    # venue_market exists (WLD-EUR) but no account_asset row was ever created for this account.
    repo.balances[(1, VENUE)] = [
        {"currency_code": "WLD", "total_amount": Decimal("2")},
    ]

    result = compute_and_apply_portfolio_member_backfill(
        repo, trading_account_id=1, venue=VENUE, dry_run=False
    )

    assert result.seeded == 0
    assert result.skipped_no_account_asset == 1
    assert (1, 11) not in repo.account_assets


def test_backfill_is_idempotent():
    repo = make_repo()
    repo.account_assets[(1, 10)] = {"is_portfolio_member": 0}
    repo.balances[(1, VENUE)] = [{"currency_code": "FET", "total_amount": Decimal("5")}]

    first = compute_and_apply_portfolio_member_backfill(repo, trading_account_id=1, venue=VENUE, dry_run=False)
    second = compute_and_apply_portfolio_member_backfill(repo, trading_account_id=1, venue=VENUE, dry_run=False)

    assert first.seeded == 1
    assert second.seeded == 0
    assert second.already_member == 1
    assert second.rows[0].row_action == ROW_ACTION_ALREADY_MEMBER
    assert repo.account_assets[(1, 10)]["is_portfolio_member"] == 1


def test_backfill_dry_run_does_not_write():
    repo = make_repo()
    repo.account_assets[(1, 10)] = {"is_portfolio_member": 0}
    repo.balances[(1, VENUE)] = [{"currency_code": "FET", "total_amount": Decimal("5")}]

    result = compute_and_apply_portfolio_member_backfill(repo, trading_account_id=1, venue=VENUE, dry_run=True)

    assert result.seeded == 1  # plan says it would seed
    assert repo.account_assets[(1, 10)]["is_portfolio_member"] == 0  # but nothing written


def test_backfill_source_file_never_references_global_asset_publication_cohort_column():
    src = BACKFILL_SOURCE_PATH.read_text()
    match = _GLOBAL_ASSET_IS_PORTFOLIO_RE.search(src)
    assert match is None, f"unexpected global asset.is_portfolio reference: {match}"
    # Also assert the file never joins/selects from the global `asset` table at all,
    # since this backfill has no legitimate reason to touch it.
    assert not re.search(r"\b(from|join)\s+asset\b", src, flags=re.IGNORECASE)


def test_backfill_source_file_no_broker_or_execution_layer_coupling():
    src = BACKFILL_SOURCE_PATH.read_text()
    assert "place_order" not in src
    assert "cancel_order" not in src
    for forbidden_import in (
        "import src.decision_gate",
        "from src.decision_gate",
        "import src.execution_planner",
        "from src.execution_planner",
        "import src.executor",
        "from src.executor",
        "import src.selection",
        "from src.selection",
    ):
        assert forbidden_import not in src


def main():
    test_backfill_seeds_only_positive_holdings_for_requested_account()
    test_backfill_does_not_leak_account_b_holdings_into_account_a()
    test_backfill_never_touches_other_account_when_backfilling_one()
    test_backfill_does_not_seed_zero_balance_assets()
    test_backfill_does_not_clear_existing_membership_on_zero_balance()
    test_backfill_skips_holding_with_no_account_asset_identity_instead_of_creating_row()
    test_backfill_skips_holding_resolved_to_venue_market_without_account_asset_row()
    test_backfill_is_idempotent()
    test_backfill_dry_run_does_not_write()
    test_backfill_source_file_never_references_global_asset_publication_cohort_column()
    test_backfill_source_file_no_broker_or_execution_layer_coupling()
    print("ok")


if __name__ == "__main__":
    main()
