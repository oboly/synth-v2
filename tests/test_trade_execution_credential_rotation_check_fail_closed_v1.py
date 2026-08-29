from __future__ import annotations

from src.account_provisioning.trade_execution_credential_rotation_v1 import (
    CHECK_BLOCKED,
    check_trade_execution_credential_rotation_v1,
)


class FakeConnection:
    def __init__(self) -> None:
        self.rollbacks = 0
        self.closed = 0

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed += 1


class FailingRepository:
    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn

    def load_credential(self, *, trading_account_credential_id: int):
        raise RuntimeError("simulated query failure")


def test_check_repository_exception_fails_closed_and_rolls_back() -> None:
    conn = FakeConnection()

    result = check_trade_execution_credential_rotation_v1(
        trading_account_id=5,
        trading_account_credential_id=5,
        venue="bitvavo",
        conn_factory=lambda: conn,
        repository_factory=FailingRepository,
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
    assert conn.closed == 1
