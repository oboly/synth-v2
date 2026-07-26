from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection, Mapping

from src.execution.live_prerequisites_v1 import LiveExecutionPrerequisitesUnavailable


CANONICAL_PAPER_VENUE = "bitvavo"
CANONICAL_PAPER_QUOTE = "EUR"
CANONICAL_PAPER_ACTION_TYPE = "PLACE_ORDER"
CANONICAL_PAPER_PLAN_STATES = frozenset({"IDLE", "PLANNED"})


@dataclass(frozen=True)
class PaperExecutionMapping:
    desired_action: str
    execution_intent: str
    requested_sides: tuple[str, ...]


PAPER_EXECUTION_MAPPINGS = (
    PaperExecutionMapping(
        desired_action="SPREAD_CAPTURE_PASSIVE",
        execution_intent="PLACE_PASSIVE_LIMIT",
        requested_sides=("BUY",),
    ),
)


class PaperExecutorContractError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _field(plan: object | Mapping[str, Any], name: str) -> Any:
    if isinstance(plan, Mapping):
        return plan.get(name)
    return getattr(plan, name, None)


def canonical_paper_mapping_sql(alias: str) -> tuple[str, list[str]]:
    predicates: list[str] = []
    params: list[str] = []
    for mapping in PAPER_EXECUTION_MAPPINGS:
        for requested_side in mapping.requested_sides:
            predicates.append(
                "("
                f"BINARY {alias}.desired_action = BINARY %s AND "
                f"BINARY {alias}.execution_intent = BINARY %s AND "
                f"BINARY {alias}.requested_side = BINARY %s"
                ")"
            )
            params.extend(
                [mapping.desired_action, mapping.execution_intent, requested_side]
            )
    return "(" + " OR ".join(predicates) + ")", params


def validate_canonical_paper_contract(
    plan: object | Mapping[str, Any],
    *,
    canonical_symbol: str,
    actionable_states: Collection[str] | None = None,
) -> None:
    execution_mode = _field(plan, "execution_mode")
    if execution_mode == "LIVE":
        raise LiveExecutionPrerequisitesUnavailable()
    if execution_mode != "PAPER":
        raise PaperExecutorContractError("PAPER_EXECUTOR_PLAN_MODE_NOT_CANONICAL")

    trading_account_id = _field(plan, "trading_account_id")
    if type(trading_account_id) is not int or trading_account_id <= 0:
        raise PaperExecutorContractError(
            "PAPER_EXECUTOR_TRADING_ACCOUNT_ID_NOT_CANONICAL"
        )

    if _field(plan, "venue") != CANONICAL_PAPER_VENUE:
        raise PaperExecutorContractError("PAPER_EXECUTOR_VENUE_NOT_CANONICAL")

    if (
        not isinstance(canonical_symbol, str)
        or not canonical_symbol
        or canonical_symbol != canonical_symbol.strip()
        or canonical_symbol != canonical_symbol.upper()
    ):
        raise PaperExecutorContractError("PAPER_EXECUTOR_ASSET_SYMBOL_NOT_CANONICAL")
    canonical_market = f"{canonical_symbol}-{CANONICAL_PAPER_QUOTE}"
    if _field(plan, "market") != canonical_market:
        raise PaperExecutorContractError("PAPER_EXECUTOR_MARKET_NOT_CANONICAL")

    if _field(plan, "action_type") != CANONICAL_PAPER_ACTION_TYPE:
        raise PaperExecutorContractError("PAPER_EXECUTOR_ACTION_TYPE_NOT_CANONICAL")

    requested_side = _field(plan, "requested_side")
    if requested_side == "SELL":
        raise PaperExecutorContractError(
            "PAPER_EXECUTOR_SELL_REQUIRES_MANUAL_AUTHORITY"
        )
    if requested_side not in {"BUY", "SELL"}:
        raise PaperExecutorContractError("PAPER_EXECUTOR_REQUESTED_SIDE_NOT_CANONICAL")
    if _field(plan, "side") != requested_side:
        raise PaperExecutorContractError("PAPER_EXECUTOR_SIDE_MISMATCH")

    desired_action = _field(plan, "desired_action")
    execution_intent = _field(plan, "execution_intent")
    mapping_supported = any(
        desired_action == mapping.desired_action
        and execution_intent == mapping.execution_intent
        and requested_side in mapping.requested_sides
        for mapping in PAPER_EXECUTION_MAPPINGS
    )
    if not mapping_supported:
        raise PaperExecutorContractError(
            "PAPER_EXECUTOR_INTENT_ACTION_MAPPING_NOT_CANONICAL"
        )

    if (
        actionable_states is not None
        and _field(plan, "plan_state") not in actionable_states
    ):
        raise PaperExecutorContractError("PAPER_EXECUTOR_PLAN_STATE_NOT_ACTIONABLE")
