from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.execution.live_prerequisites_v1 import (
    LiveExecutionPrerequisitesUnavailable,
)
from src.executor.executor_v1 import execute_plan_paper
from src.executor.models import ExecutionPlanRow
from src.executor.paper_contract_v1 import PaperExecutorContractError


def _plan(**overrides: object) -> ExecutionPlanRow:
    values: dict[str, object] = {
        "execution_plan_id": 41,
        "account_id": 7,
        "trading_account_id": 19,
        "asset_id": 3,
        "asset_symbol": "BTC",
        "sleeve_code": "CORE",
        "venue": "bitvavo",
        "market": "BTC-EUR",
        "side": "BUY",
        "desired_action": "SPREAD_CAPTURE_PASSIVE",
        "execution_intent": "PLACE_PASSIVE_LIMIT",
        "action_type": "PLACE_ORDER",
        "requested_side": "BUY",
        "execution_mode": "PAPER",
        "plan_ts_utc": datetime(2026, 7, 21, 12, 0, 0),
        "valid_until_ts_utc": None,
        "target_fraction": Decimal("0.1"),
        "max_notional_eur": Decimal("25"),
        "reference_price_eur": Decimal("100"),
        "passive_price_eur": None,
        "urgent_limit_price_eur": None,
        "max_reprices": 2,
        "max_wait_seconds": 60,
        "max_chase_bps": Decimal("10"),
        "min_spread_bps_for_capture": Decimal("1"),
        "escalation_to_urgent_limit": False,
        "abort_if_signal_invalidates": True,
        "plan_state": "IDLE",
        "notes": "test",
    }
    values.update(overrides)
    return ExecutionPlanRow(**values)  # type: ignore[arg-type]


class BoundaryRepository:
    def __init__(self) -> None:
        self.calls = {
            "fetch_symbol": 0,
            "fetch_latest_price_eur": 0,
            "fill_passive_plan_paper": 0,
            "fill_close_position_market_paper": 0,
        }

    def fetch_symbol(self, _asset_id: int) -> str:
        self.calls["fetch_symbol"] += 1
        return "BTC"

    def fetch_latest_price_eur(self, **_kwargs: object) -> Decimal:
        self.calls["fetch_latest_price_eur"] += 1
        return Decimal("100")

    def fill_passive_plan_paper(self, **_kwargs: object) -> tuple[Decimal, bool]:
        self.calls["fill_passive_plan_paper"] += 1
        return Decimal("0.25"), True

    def fill_close_position_market_paper(
        self, **_kwargs: object
    ) -> tuple[Decimal, Decimal, bool]:
        self.calls["fill_close_position_market_paper"] += 1
        return Decimal("0.25"), Decimal("1"), True


@pytest.mark.parametrize("requested_side", ["BUY", "SELL"])
def test_live_direct_call_fails_before_every_repository_boundary(
    requested_side: str,
) -> None:
    plan = _plan(
        execution_mode="LIVE",
        requested_side=requested_side,
        side=requested_side,
    )
    repo = BoundaryRepository()

    with pytest.raises(LiveExecutionPrerequisitesUnavailable) as exc_info:
        execute_plan_paper(plan, repo)  # type: ignore[arg-type]

    assert str(exc_info.value) == (
        "LIVE_EXECUTION_PREREQUISITES_UNAVAILABLE:"
        "CANONICAL_DECISION_GATE_PERMISSION_PRODUCER_REQUIRED,"
        "ACCOUNT_BOUND_TRADE_CREDENTIAL_BINDING_REQUIRED,"
        "LIVE_EXECUTOR_ACTIVATION_REQUIRED"
    )
    assert repo.calls == {
        "fetch_symbol": 0,
        "fetch_latest_price_eur": 0,
        "fill_passive_plan_paper": 0,
        "fill_close_position_market_paper": 0,
    }


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"execution_mode": None}, "PAPER_EXECUTOR_PLAN_MODE_NOT_CANONICAL"),
        ({"execution_mode": ""}, "PAPER_EXECUTOR_PLAN_MODE_NOT_CANONICAL"),
        ({"execution_mode": "paper"}, "PAPER_EXECUTOR_PLAN_MODE_NOT_CANONICAL"),
        ({"execution_mode": "Paper"}, "PAPER_EXECUTOR_PLAN_MODE_NOT_CANONICAL"),
        ({"execution_mode": "live"}, "PAPER_EXECUTOR_PLAN_MODE_NOT_CANONICAL"),
        ({"execution_mode": "Live"}, "PAPER_EXECUTOR_PLAN_MODE_NOT_CANONICAL"),
        ({"execution_mode": "unknown"}, "PAPER_EXECUTOR_PLAN_MODE_NOT_CANONICAL"),
        (
            {"trading_account_id": None},
            "PAPER_EXECUTOR_TRADING_ACCOUNT_ID_NOT_CANONICAL",
        ),
        (
            {"trading_account_id": 0},
            "PAPER_EXECUTOR_TRADING_ACCOUNT_ID_NOT_CANONICAL",
        ),
        ({"venue": "BITVAVO"}, "PAPER_EXECUTOR_VENUE_NOT_CANONICAL"),
        ({"market": None}, "PAPER_EXECUTOR_MARKET_NOT_CANONICAL"),
        ({"market": "btc-eur"}, "PAPER_EXECUTOR_MARKET_NOT_CANONICAL"),
        ({"market": "Btc-Eur"}, "PAPER_EXECUTOR_MARKET_NOT_CANONICAL"),
        (
            {"asset_symbol": "btc", "market": "btc-EUR"},
            "PAPER_EXECUTOR_ASSET_SYMBOL_NOT_CANONICAL",
        ),
        (
            {"action_type": "place_order"},
            "PAPER_EXECUTOR_ACTION_TYPE_NOT_CANONICAL",
        ),
        (
            {"action_type": "Place_Order"},
            "PAPER_EXECUTOR_ACTION_TYPE_NOT_CANONICAL",
        ),
        (
            {"requested_side": "buy", "side": "buy"},
            "PAPER_EXECUTOR_REQUESTED_SIDE_NOT_CANONICAL",
        ),
        (
            {"requested_side": "Buy", "side": "Buy"},
            "PAPER_EXECUTOR_REQUESTED_SIDE_NOT_CANONICAL",
        ),
        ({"side": "SELL"}, "PAPER_EXECUTOR_SIDE_MISMATCH"),
        (
            {"execution_intent": "place_passive_limit"},
            "PAPER_EXECUTOR_INTENT_ACTION_MAPPING_NOT_CANONICAL",
        ),
        (
            {"execution_intent": "Place_Passive_Limit"},
            "PAPER_EXECUTOR_INTENT_ACTION_MAPPING_NOT_CANONICAL",
        ),
        (
            {"execution_intent": "CLOSE_POSITION_MARKET_PAPER"},
            "PAPER_EXECUTOR_INTENT_ACTION_MAPPING_NOT_CANONICAL",
        ),
        (
            {"desired_action": "ENTER"},
            "PAPER_EXECUTOR_INTENT_ACTION_MAPPING_NOT_CANONICAL",
        ),
        (
            {"desired_action": "ENTER_LONG"},
            "PAPER_EXECUTOR_INTENT_ACTION_MAPPING_NOT_CANONICAL",
        ),
        (
            {"desired_action": "PREPARE_PLAN", "execution_intent": "PREPARE_PLAN"},
            "PAPER_EXECUTOR_INTENT_ACTION_MAPPING_NOT_CANONICAL",
        ),
        ({"plan_state": "FILLED"}, "PAPER_EXECUTOR_PLAN_STATE_NOT_ACTIONABLE"),
    ],
)
def test_malformed_direct_call_fails_before_every_repository_boundary(
    overrides: dict[str, object],
    code: str,
) -> None:
    repo = BoundaryRepository()

    with pytest.raises(PaperExecutorContractError, match=f"^{code}$"):
        execute_plan_paper(_plan(**overrides), repo)  # type: ignore[arg-type]

    assert not any(repo.calls.values())


def test_supported_buy_passive_mapping_reaches_only_expected_fill() -> None:
    passive_repo = BoundaryRepository()
    passive_result = execute_plan_paper(
        _plan(), passive_repo  # type: ignore[arg-type]
    )
    assert passive_result.event_type == "PAPER_FILL_PASSIVE"
    assert passive_repo.calls["fetch_latest_price_eur"] == 1
    assert passive_repo.calls["fill_passive_plan_paper"] == 1
    assert passive_repo.calls["fill_close_position_market_paper"] == 0

    close_plan = replace(
        _plan(),
        requested_side="SELL",
        side="SELL",
        desired_action="CLOSE_POSITION_MARKET_PAPER",
        execution_intent="CLOSE_POSITION_MARKET_PAPER",
    )
    close_repo = BoundaryRepository()
    with pytest.raises(
        PaperExecutorContractError,
        match="^PAPER_EXECUTOR_SELL_REQUIRES_MANUAL_AUTHORITY$",
    ):
        execute_plan_paper(close_plan, close_repo)  # type: ignore[arg-type]
    assert not any(close_repo.calls.values())


def test_close_mapping_rejects_buy_before_repository_boundary() -> None:
    repo = BoundaryRepository()
    plan = _plan(
        desired_action="CLOSE_POSITION_MARKET_PAPER",
        execution_intent="CLOSE_POSITION_MARKET_PAPER",
    )
    with pytest.raises(
        PaperExecutorContractError,
        match="^PAPER_EXECUTOR_INTENT_ACTION_MAPPING_NOT_CANONICAL$",
    ):
        execute_plan_paper(plan, repo)  # type: ignore[arg-type]
    assert not any(repo.calls.values())


def test_public_paper_runner_uses_only_canonical_repository_executor_boundary() -> None:
    source = Path("src/execution/run_paper_execution_runner_v1.py").read_text(
        encoding="utf-8"
    )
    assert "repo.fetch_open_plans" in source
    assert "execute_plan_paper(plan, repo)" in source
    assert "FROM execution_plan" not in source
    assert "INSERT INTO" not in source
    assert "UPDATE execution_plan" not in source
