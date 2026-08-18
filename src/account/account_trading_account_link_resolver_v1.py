from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor

    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    if isinstance(db_obj, tuple):
        return db_obj[1]
    return db_obj


class UnmappedAccountIdError(ValueError):
    """Raised when a legacy account_id has no explicit trading_account_id mapping."""


class AccountTradingAccountMismatchError(ValueError):
    """Raised when a caller-supplied (account_id, trading_account_id) pair does not
    match the explicit account_trading_account_link mapping."""


@dataclass
class AccountTradingAccountLinkResolver:
    """Resolves/verifies legacy account_id against trading_account_id via the
    explicit account_trading_account_link mapping table (F6 / Issue #319).

    decision_gate and execution_planner repository call sites must use this
    instead of trusting a caller-supplied account_id as an unchecked value.
    """

    cursor_factory: Callable[..., Any] = field(
        default=_legacy_db_cursor,
        repr=False,
        compare=False,
    )

    def resolve_account_id(self, account_id: int) -> int:
        """Confirm account_id has an explicit trading_account_id mapping.

        Returns the same account_id on success; raises UnmappedAccountIdError
        if no mapping row exists (fail-closed).
        """
        sql = """
        SELECT account_id
        FROM account_trading_account_link
        WHERE account_id = %(account_id)s
        LIMIT 1
        """

        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(sql, {"account_id": account_id})
            row = cursor.fetchone()

        if not row:
            raise UnmappedAccountIdError(
                f"account_id={account_id} has no explicit trading_account_id "
                "mapping in account_trading_account_link"
            )

        return int(row["account_id"])

    def verify_account_trading_account_pair(
        self,
        account_id: int,
        trading_account_id: int,
    ) -> None:
        """Verify account_id and trading_account_id are the same explicitly
        mapped pair. Raises UnmappedAccountIdError if account_id is not
        mapped, or AccountTradingAccountMismatchError if it is mapped to a
        different trading_account_id.
        """
        sql = """
        SELECT trading_account_id
        FROM account_trading_account_link
        WHERE account_id = %(account_id)s
        LIMIT 1
        """

        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(sql, {"account_id": account_id})
            row = cursor.fetchone()

        if not row:
            raise UnmappedAccountIdError(
                f"account_id={account_id} has no explicit trading_account_id "
                "mapping in account_trading_account_link"
            )

        mapped_trading_account_id = int(row["trading_account_id"])
        if mapped_trading_account_id != trading_account_id:
            raise AccountTradingAccountMismatchError(
                f"account_id={account_id} is mapped to "
                f"trading_account_id={mapped_trading_account_id}, not "
                f"trading_account_id={trading_account_id}"
            )
