import pytest

from src.executor.execution_client_order_id_v1 import (
    derive_execution_client_order_id,
)


def identity() -> dict[str, object]:
    return {
        "handoff_id": 1,
        "plan_source": "planner-v1",
        "plan_reference_id": "plan-1",
        "plan_content_hash": "a" * 64,
        "leg_index": 1,
        "trading_account_id": 2,
        "venue": "bitvavo",
        "market": "BTC-EUR",
    }


def test_client_order_id_is_deterministic() -> None:
    assert derive_execution_client_order_id(**identity()) == derive_execution_client_order_id(
        **identity()
    )


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    [
        ("handoff_id", 2),
        ("plan_source", "planner-v2"),
        ("plan_reference_id", "plan-2"),
        ("plan_content_hash", "b" * 64),
        ("leg_index", 2),
        ("trading_account_id", 3),
        ("venue", "other"),
        ("market", "ETH-EUR"),
    ],
)
def test_client_order_id_is_bound_to_every_identity_dimension(
    field_name: str, changed_value: object
) -> None:
    baseline = identity()
    changed = baseline | {field_name: changed_value}
    assert derive_execution_client_order_id(**changed) != derive_execution_client_order_id(
        **baseline
    )
