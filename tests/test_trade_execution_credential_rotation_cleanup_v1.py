from __future__ import annotations

from src.account_provisioning.trade_execution_credential_rotation_v1 import (
    CHECK_BLOCKED,
    check_trade_execution_credential_rotation_v1,
)


class FailingCleanupConnection:
    def __init__(self, *, fail_rollback: bool = False, fail_close: bool = False) -> None:
        self.fail_rollback = fail_rollback
        self.fail_close = fail_close
        self.rollbacks = 0
        self.closes = 0

    def rollback(self) -> None:
        self.rollbacks += 1
        if self.fail_rollback:
            raise RuntimeError("rollback failed")

    def close(self) -> None:
        self.closes += 1
        if self.fail_close:
            raise RuntimeError("close failed")


class ExplodingRepository:
    def load_credential(self, *, trading_account_credential_id: int):
        raise RuntimeError("query failed")


def test_check_failing_rollback_returns_deterministic_blocked_result() -> None:
    conn = FailingCleanupConnection(fail_rollback=True)

    result = check_trade_execution_credential_rotation_v1(
        trading_account_id=5,
        trading_account_credential_id=5,
        venue="bitvavo",
        conn_factory=lambda: conn,
        repository_factory=lambda _: ExplodingRepository(),
    )

    assert result.check_state == CHECK_BLOCKED
    assert result.safe_error_code == "CHECK_FAILED"
    assert result.credential_mutations == 0
    assert result.binding_mutations == 0
    assert result.broker_private_calls == 0
    assert result.broker_writes == 0
    assert result.order_submission == 0
    assert result.live_orders == 0
    assert conn.rollbacks == 1
    assert conn.closes == 1


def test_check_failing_close_does_not_escape() -> None:
    conn = FailingCleanupConnection(fail_close=True)

    result = check_trade_execution_credential_rotation_v1(
        trading_account_id=5,
        trading_account_credential_id=5,
        venue="bitvavo",
        conn_factory=lambda: conn,
        repository_factory=lambda _: ExplodingRepository(),
    )

    assert result.check_state == CHECK_BLOCKED
    assert result.safe_error_code == "CHECK_FAILED"
    assert conn.rollbacks == 1
    assert conn.closes == 1
