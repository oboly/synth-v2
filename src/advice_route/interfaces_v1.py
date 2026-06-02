from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
import re


FORBIDDEN_FIELD_SUBSTRINGS: tuple[str, ...] = (
    "account_balance",
    "available_cash",
    "position_size",
    "current_position_qty",
    "current_qty",
    "live_order_id",
    "broker_order_payload",
    "order_submit",
    "submit_order",
    "cancel_order",
    "replace_order",
    "order_payload",
    "broker_payload",
    "portfolio_allocation_permission",
)

SETUP_ID_RE = re.compile(
    r"^(BUY|SELL|HOLD|ROTATE|WARN)_(SHORT|MID|LONG|MIXED|UNKNOWN)_[A-Z0-9_]+$"
)


class Horizon(str, Enum):
    SHORT = "SHORT"
    MID = "MID"
    LONG = "LONG"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    ROTATE = "ROTATE"
    WARN = "WARN"


class ConfirmationState(str, Enum):
    CONFIRMS = "CONFIRMS"
    CONFLICTS = "CONFLICTS"
    MIXED = "MIXED"
    WEAK = "WEAK"
    UNKNOWN = "UNKNOWN"


class StrengthBucket(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ConfidenceBucket(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class FreshnessState(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_RUNTIME_OWNED = "NOT_RUNTIME_OWNED"


class SourceType(str, Enum):
    PRIMITIVE_SIGNAL = "PRIMITIVE_SIGNAL"
    AGGREGATE_CONTEXT = "AGGREGATE_CONTEXT"
    FRAMEWORK_CONTEXT = "FRAMEWORK_CONTEXT"
    RESEARCH_CONTEXT = "RESEARCH_CONTEXT"
    LEGACY = "LEGACY"
    EXCLUDED = "EXCLUDED"


def validate_forbidden_fields_absent(*dataclass_types: type[object]) -> None:
    for dataclass_type in dataclass_types:
        if not is_dataclass(dataclass_type):
            raise TypeError(f"{dataclass_type!r} is not a dataclass")
        for dataclass_field in fields(dataclass_type):
            normalized = dataclass_field.name.lower()
            for forbidden in FORBIDDEN_FIELD_SUBSTRINGS:
                if forbidden in normalized:
                    raise ValueError(
                        f"{dataclass_type.__name__}.{dataclass_field.name} contains forbidden field substring {forbidden!r}"
                    )


def _validate_setup_id(*, action: Action, horizon: Horizon, setup_id: str) -> None:
    if not SETUP_ID_RE.match(setup_id):
        raise ValueError(
            "setup_id must follow the canonical ACTION_HORIZON_SETUP format, for example SELL_SHORT_SPIKE"
        )
    expected_prefix = f"{action.value}_{horizon.value}_"
    if not setup_id.startswith(expected_prefix):
        raise ValueError(
            f"setup_id={setup_id!r} does not match action={action.value!r} and horizon={horizon.value!r}"
        )


@dataclass(frozen=True)
class FrameworkContext:
    symbol: str
    created_at_utc: datetime
    framework_bias: str
    framework_horizon: Horizon
    map_horizon: Horizon
    source_interval: str
    anchor_interval: str
    target_zone_low: Decimal | None = None
    target_zone_high: Decimal | None = None
    invalidation_level: Decimal | None = None
    framework_confidence_bucket: ConfidenceBucket = ConfidenceBucket.NONE
    research_context_flags: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class SynthConfirmationContext:
    symbol: str
    created_at_utc: datetime
    confirmation_state: ConfirmationState
    confirmation_strength_bucket: StrengthBucket
    freshness_state: FreshnessState
    conflict_flags: tuple[str, ...] = ()
    quality_flags: tuple[str, ...] = ()
    runtime_source_flags: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategyInterpretation:
    symbol: str
    created_at_utc: datetime
    action: Action
    horizon: Horizon
    setup_id: str
    framework_bias: str
    confirmation_state: ConfirmationState
    confirmation_strength_bucket: StrengthBucket
    confidence_bucket: ConfidenceBucket
    notes: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_setup_id(action=self.action, horizon=self.horizon, setup_id=self.setup_id)


@dataclass(frozen=True)
class StrategyProposal:
    proposal_id: str
    symbol: str
    created_at_utc: datetime
    route_version: str
    action: Action
    horizon: Horizon
    setup_id: str
    framework_bias: str
    framework_horizon: Horizon
    confirmation_state: ConfirmationState
    confirmation_strength_bucket: StrengthBucket
    confidence_bucket: ConfidenceBucket
    entry_zone_low: Decimal | None = None
    entry_zone_high: Decimal | None = None
    target_zone_low: Decimal | None = None
    target_zone_high: Decimal | None = None
    invalidation_level: Decimal | None = None
    source_interval: str = ""
    anchor_interval: str = ""
    map_horizon: Horizon = Horizon.UNKNOWN
    wave_degree: str | None = None
    freshness_state: FreshnessState = FreshnessState.UNKNOWN
    quality_flags: tuple[str, ...] = ()
    conflict_flags: tuple[str, ...] = ()
    research_context_flags: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    account_awareness: bool = False
    broker_write_allowed: bool = False
    order_submission: bool = False
    decision_required: bool = True

    def __post_init__(self) -> None:
        _validate_setup_id(action=self.action, horizon=self.horizon, setup_id=self.setup_id)
        if self.account_awareness is not False:
            raise ValueError("StrategyProposal must remain account-agnostic")
        if self.broker_write_allowed is not False:
            raise ValueError("StrategyProposal must fail closed on broker writes")
        if self.order_submission is not False:
            raise ValueError("StrategyProposal must fail closed on order submission")
        if self.decision_required is not True:
            raise ValueError("StrategyProposal must always require downstream decision permission")


validate_forbidden_fields_absent(
    FrameworkContext,
    SynthConfirmationContext,
    StrategyInterpretation,
    StrategyProposal,
)
