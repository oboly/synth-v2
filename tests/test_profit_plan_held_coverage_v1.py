from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

from src.reporting.profit_plan_held_coverage_v1 import (
    DATA_UNAVAILABLE,
    audit_profit_plan_held_coverage,
)


ACCOUNT_TS = "2026-08-18T10:00:00Z"


def _row(
    symbol: str,
    *,
    held_amount: str = "2",
    held_eur_value: str = "200",
    current_price: str | None = "100",
    current_price_status: str = "FRESH_CURRENT_PRICE",
    wallet_snapshot_status: str = "FRESH",
    planning_ppp_pct: str | None = "25",
    planning_ppp_unavailable_reason: str | None = None,
    short_context_coverage_status: str = "CONTEXT_INVALID_OR_STALE",
    reload_reentry_zone: list[str] | None = None,
    target_exit_zone: list[str] | None = None,
    invalidation_risk_zone: str | None = None,
    cost_basis_price_eur: str = DATA_UNAVAILABLE,
    position_snapshot_status: str = DATA_UNAVAILABLE,
    price_ts_utc: str = "2026-08-18T10:00:00Z",
    price_freshness_state: str = "FRESH",
    is_wallet_held: bool = True,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "market": f"{symbol}-EUR",
        "is_wallet_held": is_wallet_held,
        "current_price": current_price,
        "current_price_status": current_price_status,
        "short_context_coverage_status": short_context_coverage_status,
        "planning_ppp_pct": planning_ppp_pct,
        "planning_ppp_unavailable_reason": planning_ppp_unavailable_reason,
        "reload_reentry_zone": reload_reentry_zone or [],
        "buy_zone": [],
        "target_exit_zone": target_exit_zone or [],
        "invalidation_risk_zone": invalidation_risk_zone,
        "invalidation_level": None,
        "evidence": {
            "held_amount": held_amount,
            "held_eur_value": held_eur_value,
            "wallet_snapshot_status": wallet_snapshot_status,
            "cost_basis_price_eur": cost_basis_price_eur,
            "position_snapshot_status": position_snapshot_status,
            "price_ts_utc": price_ts_utc,
            "price_freshness_state": price_freshness_state,
        },
    }


def _snapshot(*rows: dict[str, object], held_count: int | None = None) -> dict[str, object]:
    if held_count is None:
        held_count = sum(1 for row in rows if row.get("is_wallet_held") is True)
    return {
        "account_snapshot_ts_utc": ACCOUNT_TS,
        "wallet_held_count": held_count,
        "symbols": list(rows),
    }


def _codes(report: object) -> set[str]:
    return {problem.code for problem in report.problems}


def test_passes_with_no_native_short_context_and_unavailable_cost_basis() -> None:
    """Native SHORT lifecycle and authoritative cost basis are not visibility gates."""
    row = _row(
        "ETH",
        planning_ppp_pct=None,
        planning_ppp_unavailable_reason="No reference target level available (no canonical 4h or native context).",
        short_context_coverage_status="CONTEXT_INVALID_OR_STALE",
        cost_basis_price_eur=DATA_UNAVAILABLE,
        position_snapshot_status=DATA_UNAVAILABLE,
    )
    report = audit_profit_plan_held_coverage(
        snapshot=_snapshot(row),
        held_amount_by_symbol={"ETH": Decimal("2")},
        held_eur_value_by_symbol={"ETH": Decimal("200")},
        expected_account_snapshot_ts_utc=ACCOUNT_TS,
        expected_wallet_snapshot_status="FRESH",
    )
    assert report.ok is True
    assert report.problems == ()


def test_missing_held_card_fails_even_when_wallet_count_claims_complete() -> None:
    report = audit_profit_plan_held_coverage(
        snapshot=_snapshot(held_count=1),
        held_amount_by_symbol={"LIGHTER": Decimal("100")},
        held_eur_value_by_symbol={"LIGHTER": Decimal("50")},
        expected_account_snapshot_ts_utc=ACCOUNT_TS,
        expected_wallet_snapshot_status="FRESH",
    )
    assert "HELD_CARD_MISSING" in _codes(report)


def test_duplicate_held_card_fails() -> None:
    report = audit_profit_plan_held_coverage(
        snapshot=_snapshot(_row("BTC"), _row("BTC"), held_count=1),
        held_amount_by_symbol={"BTC": Decimal("2")},
        held_eur_value_by_symbol={"BTC": Decimal("200")},
    )
    assert "HELD_CARD_DUPLICATE" in _codes(report)


def test_stale_wallet_held_card_after_balance_disappears_fails() -> None:
    report = audit_profit_plan_held_coverage(
        snapshot=_snapshot(_row("BTC"), held_count=1),
        held_amount_by_symbol={},
        held_eur_value_by_symbol={},
    )
    assert "STALE_OR_UNEXPECTED_WALLET_HELD_CARD" in _codes(report)
    assert "WALLET_HELD_COUNT_MISMATCH" in _codes(report)


def test_current_balance_value_and_wallet_freshness_must_match_persisted_truth() -> None:
    report = audit_profit_plan_held_coverage(
        snapshot=_snapshot(_row("BTC", held_amount="1.9", held_eur_value="190", wallet_snapshot_status="STALE")),
        held_amount_by_symbol={"BTC": Decimal("2")},
        held_eur_value_by_symbol={"BTC": Decimal("200")},
        expected_wallet_snapshot_status="FRESH",
    )
    assert {
        "HELD_AMOUNT_MISMATCH",
        "HELD_EUR_VALUE_MISMATCH",
        "WALLET_FRESHNESS_MISMATCH",
    }.issubset(_codes(report))


def test_missing_market_price_keeps_eur_value_unavailable_and_requires_ppp_reason() -> None:
    row = _row(
        "SOL",
        held_eur_value=DATA_UNAVAILABLE,
        current_price=None,
        current_price_status="MISSING_CURRENT_PRICE",
        price_ts_utc=DATA_UNAVAILABLE,
        price_freshness_state="MISSING",
        planning_ppp_pct=None,
        planning_ppp_unavailable_reason="Current price snapshot unavailable.",
    )
    report = audit_profit_plan_held_coverage(
        snapshot=_snapshot(row),
        held_amount_by_symbol={"SOL": Decimal("2")},
        held_eur_value_by_symbol={"SOL": None},
    )
    assert report.ok is True


def test_numeric_price_requires_visible_price_provenance() -> None:
    row = _row(
        "BTC",
        price_ts_utc=DATA_UNAVAILABLE,
        price_freshness_state=DATA_UNAVAILABLE,
    )
    report = audit_profit_plan_held_coverage(
        snapshot=_snapshot(row),
        held_amount_by_symbol={"BTC": Decimal("2")},
        held_eur_value_by_symbol={"BTC": Decimal("200")},
    )
    assert "PRICE_PROVENANCE_INCOMPLETE" in _codes(report)


def test_planning_ppp_requires_numeric_value_or_precise_reason() -> None:
    row = _row("ETH", planning_ppp_pct=None, planning_ppp_unavailable_reason=None)
    report = audit_profit_plan_held_coverage(
        snapshot=_snapshot(row),
        held_amount_by_symbol={"ETH": Decimal("2")},
        held_eur_value_by_symbol={"ETH": Decimal("200")},
    )
    assert "PLANNING_PPP_WITHOUT_REASON" in _codes(report)


def test_canonical_4h_available_requires_exposed_reference_levels() -> None:
    row = _row(
        "LIGHTER",
        short_context_coverage_status="CANONICAL_4H_CONTEXT_AVAILABLE",
        reload_reentry_zone=[],
        target_exit_zone=[],
        invalidation_risk_zone=None,
    )
    report = audit_profit_plan_held_coverage(
        snapshot=_snapshot(row),
        held_amount_by_symbol={"LIGHTER": Decimal("2")},
        held_eur_value_by_symbol={"LIGHTER": Decimal("200")},
    )
    assert {
        "CANONICAL_REENTRY_LEVEL_MISSING",
        "CANONICAL_TARGET_LEVEL_MISSING",
        "CANONICAL_INVALIDATION_LEVEL_MISSING",
    }.issubset(_codes(report))


def test_canonical_4h_available_with_levels_passes_without_native_lifecycle() -> None:
    row = _row(
        "LIGHTER",
        short_context_coverage_status="CANONICAL_4H_CONTEXT_AVAILABLE",
        reload_reentry_zone=["80"],
        target_exit_zone=["125"],
        invalidation_risk_zone="70",
    )
    report = audit_profit_plan_held_coverage(
        snapshot=_snapshot(row),
        held_amount_by_symbol={"LIGHTER": Decimal("2")},
        held_eur_value_by_symbol={"LIGHTER": Decimal("200")},
    )
    assert report.ok is True


def test_cost_basis_unavailable_is_allowed_but_present_basis_needs_position_authority() -> None:
    unavailable = audit_profit_plan_held_coverage(
        snapshot=_snapshot(_row("ETH")),
        held_amount_by_symbol={"ETH": Decimal("2")},
        held_eur_value_by_symbol={"ETH": Decimal("200")},
    )
    assert unavailable.ok is True

    present_without_authority = audit_profit_plan_held_coverage(
        snapshot=_snapshot(_row("ETH", cost_basis_price_eur="75", position_snapshot_status=DATA_UNAVAILABLE)),
        held_amount_by_symbol={"ETH": Decimal("2")},
        held_eur_value_by_symbol={"ETH": Decimal("200")},
    )
    assert "COST_BASIS_PROVENANCE_INCOMPLETE" in _codes(present_without_authority)


def test_account_snapshot_timestamp_mismatch_fails() -> None:
    report = audit_profit_plan_held_coverage(
        snapshot=_snapshot(_row("BTC")),
        held_amount_by_symbol={"BTC": Decimal("2")},
        held_eur_value_by_symbol={"BTC": Decimal("200")},
        expected_account_snapshot_ts_utc="2026-08-18T11:00:00Z",
    )
    assert "ACCOUNT_SNAPSHOT_TS_MISMATCH" in _codes(report)


def test_runner_has_no_decision_execution_or_broker_imports() -> None:
    source_path = Path("src/reporting/run_profit_plan_held_coverage_v1.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    forbidden_prefixes = (
        "src.selection",
        "src.decision_gate",
        "src.execution_planner",
        "src.execution",
        "src.executor",
        "src.broker",
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(forbidden_prefixes), alias.name
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith(forbidden_prefixes), node.module
