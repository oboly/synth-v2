from __future__ import annotations

"""
Synth v2 - Paper Candidate Contract V1.

LAYER:
research / paper-candidate boundary contract

BOUNDARY:
Allowed:
- define a transport-safe research candidate shape
- validate market-only candidate payloads
- reject account-aware or execution-aware fields
- serialize deterministic preview candidates for later adapters

Forbidden:
- account balances
- live positions
- open orders
- execution plans
- broker/order actions
- decision_gate writes
- execution_intent writes
- execution_plan writes

Purpose:
Provide a strict boundary object between research preview runners and a future
decision_gate adapter. This module does not decide trades and does not execute.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


CONTRACT_VERSION = "paper_candidate_contract_v1"

ALLOWED_CANDIDATE_STATES = frozenset(
    {
        "RESEARCH_PAPER_CANDIDATE_PREVIEW",
        "RESEARCH_PROMOTION_CANDIDATE",
    }
)

ALLOWED_SLEEVE_CODES = frozenset(
    {
        "CORE_STRUCTURAL",
        "SWING_STRUCTURAL",
        "TACTICAL_PULSE",
        "EXPERIMENTAL",
    }
)

FORBIDDEN_ACCOUNT_OR_EXECUTION_FIELDS = frozenset(
    {
        "account_id",
        "portfolio_id",
        "wallet_id",
        "balance",
        "available_balance",
        "cash_balance",
        "position_id",
        "position_qty",
        "open_position",
        "open_order",
        "order_id",
        "execution_plan_id",
        "execution_intent_id",
        "decision_state_id",
        "broker_order_id",
        "exchange_order_id",
        "filled_qty",
        "fill_price",
        "live_trade",
    }
)


@dataclass(frozen=True)
class ValidationIssue:
    field_name: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True)
class ResearchPaperCandidateV1:
    contract_version: str
    policy_name: str
    policy_version: str
    candidate_state: str

    asset_id: int
    symbol: str
    venue: str
    asof_ts_utc: datetime

    selection_state: str
    priority_rank: int
    selection_score: Decimal | None
    btc_prior_24h: Decimal | None

    rotation_bucket: str
    classification_code: str
    sleeve_fit_code: str

    simulated_horizon_hours: int
    simulated_net_return: Decimal | None

    source_table: str
    source_replay_id: int | None
    notes: str | None = None

    def to_transport_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["asof_ts_utc"] = self.asof_ts_utc.isoformat(sep=" ")
        for key, value in list(row.items()):
            if isinstance(value, Decimal):
                row[key] = str(value)
        return row


def validate_no_forbidden_fields(payload: dict[str, Any]) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []

    for field_name in sorted(FORBIDDEN_ACCOUNT_OR_EXECUTION_FIELDS):
        if field_name in payload:
            issues.append(
                ValidationIssue(
                    field_name=field_name,
                    message="Forbidden account-aware or execution-aware field in research candidate payload.",
                )
            )

    return tuple(issues)


def validate_candidate(candidate: ResearchPaperCandidateV1) -> ValidationResult:
    issues: list[ValidationIssue] = []

    if candidate.contract_version != CONTRACT_VERSION:
        issues.append(
            ValidationIssue(
                field_name="contract_version",
                message=f"Expected {CONTRACT_VERSION}.",
            )
        )

    if not candidate.policy_name:
        issues.append(ValidationIssue(field_name="policy_name", message="Policy name is required."))

    if not candidate.policy_version:
        issues.append(ValidationIssue(field_name="policy_version", message="Policy version is required."))

    if candidate.candidate_state not in ALLOWED_CANDIDATE_STATES:
        issues.append(
            ValidationIssue(
                field_name="candidate_state",
                message="Candidate state is not allowed by paper candidate contract.",
            )
        )

    if candidate.asset_id <= 0:
        issues.append(ValidationIssue(field_name="asset_id", message="Asset id must be positive."))

    if not candidate.symbol:
        issues.append(ValidationIssue(field_name="symbol", message="Symbol is required."))

    if not candidate.venue:
        issues.append(ValidationIssue(field_name="venue", message="Venue is required."))

    if candidate.priority_rank <= 0:
        issues.append(ValidationIssue(field_name="priority_rank", message="Priority rank must be positive."))

    if candidate.sleeve_fit_code not in ALLOWED_SLEEVE_CODES:
        issues.append(
            ValidationIssue(
                field_name="sleeve_fit_code",
                message="Sleeve fit code is not allowed.",
            )
        )

    if candidate.simulated_horizon_hours not in {4, 24}:
        issues.append(
            ValidationIssue(
                field_name="simulated_horizon_hours",
                message="Only 4h and 24h simulated horizons are currently supported.",
            )
        )

    issues.extend(validate_no_forbidden_fields(candidate.to_transport_dict()))

    return ValidationResult(is_valid=len(issues) == 0, issues=tuple(issues))


def require_valid_candidate(candidate: ResearchPaperCandidateV1) -> None:
    result = validate_candidate(candidate)

    if result.is_valid:
        return

    rendered = "; ".join(f"{issue.field_name}: {issue.message}" for issue in result.issues)
    raise ValueError(f"Invalid research paper candidate: {rendered}")
