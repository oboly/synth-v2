from __future__ import annotations

from decimal import Decimal

from src.decision_gate.sell_intent_policy_v1 import (
    SellIntentPolicyInput,
    evaluate_sell_intent_policy_v1,
)


def base_input(**overrides):
    data = {
        "account_enabled": 1,
        "account_live_trading_enabled": 0,
        "broker_write_permission_state": "MISSING",
        "hard_safety_nonzero": False,
        "source_duplicate_symbol_rows": 0,
        "source_negative_quantity_rows": 0,
        "source_missing_mark_price_rows": 0,
        "position_exists": True,
        "position_quantity_base": Decimal("231.301835"),
        "available_quantity_base": Decimal("231.301835"),
        "reserved_quantity_base": Decimal("0"),
        "open_sell_order_remaining_base": Decimal("0"),
        "requested_quantity_base": Decimal("10"),
        "mark_price_exists": True,
    }
    data.update(overrides)
    return SellIntentPolicyInput(**data)


def assert_case(name: str, policy_input: SellIntentPolicyInput, expected_state: str, expected_blockers: tuple[str, ...]) -> None:
    decision = evaluate_sell_intent_policy_v1(policy_input)

    print(
        {
            "case": name,
            "preview_state": decision.preview_state,
            "blocking_reasons": decision.blocking_reasons,
        }
    )

    if decision.preview_state != expected_state:
        raise AssertionError(f"{name}: expected state {expected_state}, got {decision.preview_state}")

    if decision.blocking_reasons != expected_blockers:
        raise AssertionError(
            f"{name}: expected blockers {expected_blockers}, got {decision.blocking_reasons}"
        )


def main() -> int:
    assert_case(
        "xrp_small_sell_preview",
        base_input(),
        "WOULD_APPROVE_SELL_INTENT_PREVIEW",
        (),
    )

    assert_case(
        "tao_reserved_no_available",
        base_input(
            position_quantity_base=Decimal("1.05336588"),
            available_quantity_base=Decimal("0"),
            reserved_quantity_base=Decimal("1.05336588"),
            open_sell_order_remaining_base=Decimal("1.05336588"),
            requested_quantity_base=Decimal("0"),
        ),
        "BLOCKED",
        (
            "NO_AVAILABLE_QUANTITY_RESERVED",
            "REQUESTED_QUANTITY_NOT_POSITIVE",
        ),
    )

    assert_case(
        "xrp_oversized_sell",
        base_input(requested_quantity_base=Decimal("999999")),
        "BLOCKED",
        ("REQUEST_EXCEEDS_AVAILABLE_QUANTITY",),
    )

    assert_case(
        "broker_write_permission_granted",
        base_input(broker_write_permission_state="GRANTED"),
        "BLOCKED",
        ("BROKER_WRITE_PERMISSION_GRANTED",),
    )

    assert_case(
        "stale_source",
        base_input(source_freshness_ok=False),
        "BLOCKED",
        ("SOURCE_STALE",),
    )

    print("[DONE] sell_intent_policy_v1 smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
