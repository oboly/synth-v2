"""Frozen, side-neutral plan identity consumed by the executor."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

CONTRACT_VERSION: Final[str] = "execution_plan_reference_v1"


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} required")
    return value.strip()


def _nonempty_or_none(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("strategy lineage field must be a nonempty string or None")
    return value.strip()


def _positive_decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float) or not isinstance(value, Decimal):
        raise ValueError(f"{name} must be a Decimal")
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{name} must be a finite positive Decimal")
    return value


def _decimal_text(value: Decimal) -> str:
    normalized = format(value.normalize(), "f")
    if "." not in normalized:
        return normalized
    normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


@dataclass(frozen=True)
class ExecutionPlanLegV1:
    leg_index: int
    side: str
    price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        if (
            isinstance(self.leg_index, bool)
            or not isinstance(self.leg_index, int)
            or self.leg_index <= 0
        ):
            raise ValueError("leg index must be a positive integer")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("leg side must be BUY or SELL")
        _positive_decimal(self.price, "price")
        _positive_decimal(self.quantity, "quantity")


@dataclass(frozen=True)
class ApprovedExecutionPlanV1:
    plan_source: str
    plan_reference_id: str
    trading_account_id: int
    venue: str
    market: str
    side: str
    legs: tuple[ExecutionPlanLegV1, ...]
    # Issue #756 Codex block: minimum immutable strategy-ownership lineage,
    # propagated through to executor_execution_handoff so a real fill
    # confirmation can attribute a strategy-owned inventory ledger event
    # (see src/executor/strategy_owned_fill_attribution_v1.py). ``None`` for
    # every non-automatic-buy (e.g. manual execution) plan -- manual
    # execution is unaffected and never sets these. Deliberately excluded
    # from canonical_payload/content_hash: provenance, not order economics,
    # so a manual plan's existing hash is unchanged by this field's addition.
    strategy_bucket_id: str | None = None
    strategy_id: str | None = None
    strategy_version: str | None = None
    setup_id: str | None = None
    contract_version: str = field(default=CONTRACT_VERSION, init=False)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        plan_source = _required_text(self.plan_source, "plan_source")
        plan_reference_id = _required_text(self.plan_reference_id, "plan_reference_id")
        venue = _required_text(self.venue, "venue").lower()
        market = _required_text(self.market, "market").upper()
        if isinstance(self.trading_account_id, bool) or not isinstance(self.trading_account_id, int) or self.trading_account_id <= 0:
            raise ValueError("trading_account_id must be a positive integer")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if not isinstance(self.legs, tuple) or not self.legs:
            raise ValueError("legs must be a nonempty immutable tuple")
        if any(not isinstance(leg, ExecutionPlanLegV1) for leg in self.legs):
            raise ValueError("legs must contain ExecutionPlanLegV1 values")
        indices = tuple(leg.leg_index for leg in self.legs)
        if indices != tuple(sorted(indices)) or len(set(indices)) != len(indices):
            raise ValueError("legs must have unique strictly ordered indices")
        if any(leg.side != self.side for leg in self.legs):
            raise ValueError("every leg side must match plan side")
        lineage_fields = (self.strategy_bucket_id, self.strategy_id, self.strategy_version, self.setup_id)
        lineage_present = tuple(_nonempty_or_none(value) for value in lineage_fields)
        if len(set(value is not None for value in lineage_present)) != 1:
            raise ValueError("strategy lineage fields must be set together or not at all")
        object.__setattr__(self, "plan_source", plan_source)
        object.__setattr__(self, "plan_reference_id", plan_reference_id)
        object.__setattr__(self, "venue", venue)
        object.__setattr__(self, "market", market)
        object.__setattr__(self, "strategy_bucket_id", lineage_present[0])
        object.__setattr__(self, "strategy_id", lineage_present[1])
        object.__setattr__(self, "strategy_version", lineage_present[2])
        object.__setattr__(self, "setup_id", lineage_present[3])
        object.__setattr__(self, "content_hash", hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "contract_version": CONTRACT_VERSION,
            "plan_source": self.plan_source,
            "plan_reference_id": self.plan_reference_id,
            "trading_account_id": self.trading_account_id,
            "venue": self.venue,
            "market": self.market,
            "side": self.side,
            "legs": [
                {
                    "leg_index": leg.leg_index,
                    "side": leg.side,
                    "price": _decimal_text(leg.price),
                    "quantity": _decimal_text(leg.quantity),
                }
                for leg in self.legs
            ],
        }

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
