from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.decision_gate.automatic_buy_account_permission_contract_v1 import (
    AutomaticBuyAccountPermissionContractError,
    AutomaticBuyAccountPermissionRevocationV1,
    AutomaticBuyAccountPermissionV1,
    resolve_automatic_buy_account_permission_v1,
)

TS = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _permission(**overrides: object) -> AutomaticBuyAccountPermissionV1:
    base = dict(
        permission_id=1,
        trading_account_id=7,
        execution_enabled=True,
        effective_from_ts_utc=TS - timedelta(days=1),
        effective_until_ts_utc=None,
        permission_version="1",
        source_provenance="manual_review",
    )
    base.update(overrides)
    return AutomaticBuyAccountPermissionV1(**base)  # type: ignore[arg-type]


def test_no_row_resolves_to_none_default_denied() -> None:
    assert resolve_automatic_buy_account_permission_v1((), (), trading_account_id=7, at=TS) is None


def test_active_row_resolves_execution_enabled() -> None:
    resolved = resolve_automatic_buy_account_permission_v1((_permission(),), (), trading_account_id=7, at=TS)
    assert resolved is not None
    assert resolved.execution_enabled is True


def test_disabled_row_resolves_execution_disabled() -> None:
    resolved = resolve_automatic_buy_account_permission_v1(
        (_permission(execution_enabled=False),), (), trading_account_id=7, at=TS,
    )
    assert resolved is not None
    assert resolved.execution_enabled is False


def test_ambiguous_overlapping_rows_fail_closed() -> None:
    rows = (_permission(permission_id=1), _permission(permission_id=2))
    with pytest.raises(AutomaticBuyAccountPermissionContractError):
        resolve_automatic_buy_account_permission_v1(rows, (), trading_account_id=7, at=TS)


def test_revoked_row_no_longer_resolves() -> None:
    rows = (_permission(permission_id=1),)
    revocation = AutomaticBuyAccountPermissionRevocationV1(
        revocation_id=1, permission_id=1, trading_account_id=7, revocation_version="1",
        effective_ts_utc=TS - timedelta(hours=1), actor="operator-v1", reason="superseded",
    )
    assert resolve_automatic_buy_account_permission_v1(rows, (revocation,), trading_account_id=7, at=TS) is None


def test_other_account_rows_are_ignored() -> None:
    rows = (_permission(permission_id=1, trading_account_id=3),)
    assert resolve_automatic_buy_account_permission_v1(rows, (), trading_account_id=7, at=TS) is None


def test_expired_row_no_longer_resolves() -> None:
    rows = (_permission(effective_until_ts_utc=TS - timedelta(hours=1)),)
    assert resolve_automatic_buy_account_permission_v1(rows, (), trading_account_id=7, at=TS) is None


def test_invalid_lookup_raises() -> None:
    with pytest.raises(AutomaticBuyAccountPermissionContractError):
        resolve_automatic_buy_account_permission_v1((), (), trading_account_id=0, at=TS)
