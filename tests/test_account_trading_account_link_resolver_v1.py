"""
Tests for src/account/account_trading_account_link_resolver_v1.py.

Uses an in-memory fake DB (no real MariaDB, no network) that implements just
the query shape the resolver issues against account_trading_account_link.
"""
from __future__ import annotations

import pytest

from src.account.account_trading_account_link_resolver_v1 import (
    AccountTradingAccountLinkResolver,
    AccountTradingAccountMismatchError,
    UnmappedAccountIdError,
)


class _FakeCursor:
    def __init__(self, table: list[dict]) -> None:
        self._table = table
        self._result: list[dict] | None = None

    def execute(self, sql: str, params: dict) -> None:
        sql_norm = " ".join(sql.split())
        assert sql_norm.startswith(
            "SELECT account_id FROM account_trading_account_link"
        ) or sql_norm.startswith(
            "SELECT trading_account_id FROM account_trading_account_link"
        )
        account_id = params["account_id"]
        self._result = [dict(r) for r in self._table if r["account_id"] == account_id]

    def fetchone(self):
        return self._result[0] if self._result else None


class _FakeDbContext:
    def __init__(self, table: list[dict]) -> None:
        self._cursor = _FakeCursor(table)

    def __enter__(self):
        return self._cursor

    def __exit__(self, *exc_info) -> bool:
        return False


def _make_resolver(table: list[dict]) -> AccountTradingAccountLinkResolver:
    def factory(*, commit: bool = False, database: str | None = None):
        return _FakeDbContext(table)

    return AccountTradingAccountLinkResolver(cursor_factory=factory)


def test_resolve_account_id_returns_mapped_account_id() -> None:
    resolver = _make_resolver([{"account_id": 1, "trading_account_id": 17}])
    assert resolver.resolve_account_id(1) == 1


def test_resolve_account_id_fails_closed_when_unmapped() -> None:
    resolver = _make_resolver([])
    with pytest.raises(UnmappedAccountIdError):
        resolver.resolve_account_id(1)


def test_verify_pair_passes_for_matching_mapping() -> None:
    resolver = _make_resolver([{"account_id": 1, "trading_account_id": 17}])
    resolver.verify_account_trading_account_pair(1, 17)


def test_verify_pair_fails_closed_when_account_id_unmapped() -> None:
    resolver = _make_resolver([])
    with pytest.raises(UnmappedAccountIdError):
        resolver.verify_account_trading_account_pair(1, 17)


def test_verify_pair_rejects_mismatched_trading_account_id() -> None:
    resolver = _make_resolver([{"account_id": 1, "trading_account_id": 17}])
    with pytest.raises(AccountTradingAccountMismatchError):
        resolver.verify_account_trading_account_pair(1, 99)
