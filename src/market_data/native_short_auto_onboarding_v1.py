from __future__ import annotations

"""Automatic, market-only Native SHORT scope onboarding."""

from dataclasses import dataclass
from datetime import UTC, datetime
import uuid
from typing import Any, Callable

from src.market_data.native_short_multi_asset_audit_v1 import run_audit
from src.market_data.native_short_scope_administration_v1 import (
    NativeShortScopeAdministrationActorType,
    NativeShortScopeAdministrationKey,
    NativeShortScopeAdministrationOperationType,
    NativeShortScopeAdministrationProvenance,
    NativeShortScopeAdministrationRequest,
    NativeShortScopeAdministrationTriggerType,
)
from src.market_data.native_short_scope_administration_transaction_v1 import (
    execute_scope_administration,
)

RUNNER_NAME = "native_short_auto_onboarding_v1"
READY = "READY"
NOT_READY = "NOT_READY"
SUPPORTED = "SUPPORTED"


@dataclass(frozen=True)
class OnboardingResult:
    symbol: str
    state: str
    detail: str


def reconcile_ready_scopes(
    conn: Any,
    *,
    as_of_utc: datetime,
    repository_commit_sha: str,
    authorization: Any,
    execute: Callable[..., Any] = execute_scope_administration,
) -> tuple[OnboardingResult, ...]:
    """Persist every independently READY canonical market as SUPPORTED.

    Historic rollout fields from ``run_audit`` are deliberately ignored. A
    malformed canonical transition raises (hard stop); an ordinary NOT_READY
    market records its reason and cannot suppress another READY market.
    """
    report = run_audit(conn, as_of_utc=as_of_utc)
    results: list[OnboardingResult] = []
    for candidate in sorted(report.results, key=lambda item: item.canonical_key.symbol):
        symbol = candidate.canonical_key.symbol
        if candidate.scope_states == (SUPPORTED,):
            results.append(OnboardingResult(symbol, SUPPORTED, "ALREADY_SUPPORTED"))
            continue
        if (
            candidate.market_readiness_status != "MARKET_READY"
            or candidate.ledger_readiness_status != "LEDGER_READY"
        ):
            reasons = candidate.market_reason_codes or candidate.ledger_reason_codes
            results.append(OnboardingResult(symbol, NOT_READY, ",".join(reasons) or "CONTEXT_UNAVAILABLE"))
            continue
        request = NativeShortScopeAdministrationRequest(
            operation_type=NativeShortScopeAdministrationOperationType.AUTO_ONBOARD_SCOPE,
            scope_key=NativeShortScopeAdministrationKey(
                venue="bitvavo", symbol=symbol, quote_currency="EUR",
                fib_trading_horizon="SHORT", primary_interval="4h", supporting_interval="1h",
            ),
            provenance=NativeShortScopeAdministrationProvenance(
                operation_uuid=str(uuid.uuid4()),
                actor_type=NativeShortScopeAdministrationActorType.SERVICE_PRINCIPAL,
                actor_id=RUNNER_NAME,
                trigger_type=NativeShortScopeAdministrationTriggerType.AUTOMATION,
                request_source=RUNNER_NAME,
                reason="canonical market-data readiness satisfied",
                requested_at_utc=as_of_utc.astimezone(UTC),
                repository_sha=repository_commit_sha,
                schema_version="native_short_auto_onboarding_v1",
            ),
            canonical_metadata={
                "readiness_state": READY,
                "market_reasons": list(candidate.market_reason_codes),
                "ledger_reasons": list(candidate.ledger_reason_codes),
            },
        )
        outcome = execute(conn, request, authorization=authorization, now_utc=as_of_utc)
        if str(outcome.result.result_class) not in {"SUCCESS", "IDEMPOTENT_SUCCESS"}:
            raise RuntimeError(
                f"AUTO_ONBOARD_FAILED symbol={symbol} result={outcome.result.result_code}"
            )
        results.append(OnboardingResult(symbol, SUPPORTED, str(outcome.result.result_code)))
    return tuple(results)
