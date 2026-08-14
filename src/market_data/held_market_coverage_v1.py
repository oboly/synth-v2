"""
held_market_coverage_v1 -- Pure resolution/classification for the
positive-wallet-holding -> canonical market/Fib coverage invariant
(Issue #238 follow-up).

Enforces one invariant, deterministically:

    positive persisted wallet holding
    -> canonical exchange market resolved
    -> enrolled in the account-agnostic market/Fib publication cohort

This module contains no SQL and no DB/broker access. Callers (an enrollment
writer, a read-only health check) fetch rows and pass them in as plain data;
this module only classifies them. Market-only / account-agnostic by
construction: the output never carries account balances forward, only the
account codes that justify enrollment (for audit trail).

Canonical identity is resolved by an exact ``asset.symbol`` match on the
upper-cased held currency code. Display aliases (e.g. "LIT" for "LIGHTER")
are never used as machine identity here -- that is exactly the mismatch this
module exists to avoid. Alias *display* work is tracked separately
(Issue #245) and must not feed this resolution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Mapping, Sequence

SAFETY_MARKERS: dict[str, object] = {
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
}

# Resolution reasons
NON_RESOLVABLE_NO_ASSET = "NO_MATCHING_ASSET_REGISTRY_ROW"
NON_RESOLVABLE_DISABLED = "ASSET_DISABLED_OR_NOT_TRADEABLE"
RESOLVED_ALREADY_ENROLLED = "ALREADY_ENROLLED"
RESOLVED_NEEDS_ENROLLMENT = "NEEDS_ENROLLMENT"

# Coverage-check reasons (read-only, Fib-publication side)
COVERAGE_FRESH = "FRESH_CANONICAL_4H_CONTEXT"
COVERAGE_NOT_RESOLVABLE = "NON_RESOLVABLE_HELD_SYMBOL"
COVERAGE_NOT_ENROLLED = "NOT_ENROLLED_IN_PUBLICATION_COHORT"
COVERAGE_NO_CANDLES = "INSUFFICIENT_CANDLE_HISTORY"
COVERAGE_NOT_PUBLISHED = "ENROLLED_BUT_NOT_YET_PUBLISHED"
COVERAGE_STALE = "CANONICAL_4H_CONTEXT_STALE"
COVERAGE_UNAVAILABLE_MAP_STATUS = "CANONICAL_4H_MAP_STATUS_UNAVAILABLE"


@dataclass(frozen=True)
class AssetRegistryRow:
    asset_id: int
    symbol: str
    is_enabled: bool
    is_tradeable: bool
    is_publication_cohort: bool
    is_core_sensor: bool


@dataclass(frozen=True)
class HeldBalance:
    trading_account_id: int
    account_code: str
    currency_code: str
    total_amount: Decimal


@dataclass(frozen=True)
class HeldMarketResolution:
    currency_code: str
    symbol: str | None
    asset_id: int | None
    market: str | None
    resolvable: bool
    reason: str
    held_by_account_codes: tuple[str, ...]
    needs_enrollment: bool


def resolve_held_markets(
    *,
    held_balances: Sequence[HeldBalance],
    quote_currency: str,
    asset_registry_by_symbol: Mapping[str, AssetRegistryRow],
) -> tuple[HeldMarketResolution, ...]:
    """Deterministically classify every distinct positive held currency code
    across all supplied balances (any number of accounts).

    Zero/negative balances are excluded (not a "positive persisted wallet
    holding"). The quote currency itself is excluded. Output is sorted by
    currency code for deterministic ordering.
    """
    quote = quote_currency.strip().upper()
    grouped: dict[str, list[str]] = {}
    for balance in held_balances:
        if balance.total_amount is None or balance.total_amount <= 0:
            continue
        code = balance.currency_code.strip().upper()
        if not code or code == quote:
            continue
        grouped.setdefault(code, []).append(balance.account_code)

    out: list[HeldMarketResolution] = []
    for code in sorted(grouped):
        accounts = tuple(sorted(set(grouped[code])))
        asset_row = asset_registry_by_symbol.get(code)
        if asset_row is None:
            out.append(
                HeldMarketResolution(
                    currency_code=code,
                    symbol=None,
                    asset_id=None,
                    market=None,
                    resolvable=False,
                    reason=NON_RESOLVABLE_NO_ASSET,
                    held_by_account_codes=accounts,
                    needs_enrollment=False,
                )
            )
            continue
        if not (asset_row.is_enabled and asset_row.is_tradeable):
            out.append(
                HeldMarketResolution(
                    currency_code=code,
                    symbol=asset_row.symbol,
                    asset_id=asset_row.asset_id,
                    market=f"{asset_row.symbol}-{quote}",
                    resolvable=False,
                    reason=NON_RESOLVABLE_DISABLED,
                    held_by_account_codes=accounts,
                    needs_enrollment=False,
                )
            )
            continue
        already_enrolled = bool(asset_row.is_publication_cohort or asset_row.is_core_sensor)
        out.append(
            HeldMarketResolution(
                currency_code=code,
                symbol=asset_row.symbol,
                asset_id=asset_row.asset_id,
                market=f"{asset_row.symbol}-{quote}",
                resolvable=True,
                reason=(RESOLVED_ALREADY_ENROLLED if already_enrolled else RESOLVED_NEEDS_ENROLLMENT),
                held_by_account_codes=accounts,
                needs_enrollment=not already_enrolled,
            )
        )
    return tuple(out)


def resolutions_needing_enrollment(
    resolutions: Sequence[HeldMarketResolution],
) -> tuple[HeldMarketResolution, ...]:
    return tuple(r for r in resolutions if r.resolvable and r.needs_enrollment)


@dataclass(frozen=True)
class HeldCoverageStatus:
    currency_code: str
    symbol: str | None
    market: str | None
    status: str
    reason: str
    held_by_account_codes: tuple[str, ...]
    candle_count: int | None = None
    map_status: str | None = None
    asof_ts_display: str | None = None


def classify_held_coverage(
    resolution: HeldMarketResolution,
    *,
    candle_count_by_symbol: Mapping[str, int],
    canonical_row_by_symbol: Mapping[str, Mapping[str, object]],
    min_required_candles: int,
    available_map_statuses: frozenset[str],
    now_utc: datetime,
    stale_after: timedelta,
) -> HeldCoverageStatus:
    """Classify one held symbol's canonical-4h coverage with a single,
    precise reason. Never returns a generic/ambiguous status.
    """
    if not resolution.resolvable:
        return HeldCoverageStatus(
            currency_code=resolution.currency_code,
            symbol=resolution.symbol,
            market=resolution.market,
            status="GAP",
            reason=COVERAGE_NOT_RESOLVABLE,
            held_by_account_codes=resolution.held_by_account_codes,
        )
    if resolution.needs_enrollment:
        return HeldCoverageStatus(
            currency_code=resolution.currency_code,
            symbol=resolution.symbol,
            market=resolution.market,
            status="GAP",
            reason=COVERAGE_NOT_ENROLLED,
            held_by_account_codes=resolution.held_by_account_codes,
        )
    symbol = resolution.symbol or resolution.currency_code
    candle_count = candle_count_by_symbol.get(symbol, 0)
    if candle_count < min_required_candles:
        return HeldCoverageStatus(
            currency_code=resolution.currency_code,
            symbol=resolution.symbol,
            market=resolution.market,
            status="GAP",
            reason=COVERAGE_NO_CANDLES,
            held_by_account_codes=resolution.held_by_account_codes,
            candle_count=candle_count,
        )
    row = canonical_row_by_symbol.get(symbol)
    if row is None:
        return HeldCoverageStatus(
            currency_code=resolution.currency_code,
            symbol=resolution.symbol,
            market=resolution.market,
            status="GAP",
            reason=COVERAGE_NOT_PUBLISHED,
            held_by_account_codes=resolution.held_by_account_codes,
            candle_count=candle_count,
        )
    map_status = str(row.get("map_status") or "")
    asof_display = row.get("asof_ts_utc")
    asof_ts_utc = row.get("asof_ts_utc")
    if isinstance(asof_ts_utc, datetime):
        compare_now = now_utc if asof_ts_utc.tzinfo is not None else now_utc.replace(tzinfo=None)
        if compare_now - asof_ts_utc > stale_after:
            return HeldCoverageStatus(
                currency_code=resolution.currency_code,
                symbol=resolution.symbol,
                market=resolution.market,
                status="GAP",
                reason=COVERAGE_STALE,
                held_by_account_codes=resolution.held_by_account_codes,
                candle_count=candle_count,
                map_status=map_status,
                asof_ts_display=str(asof_display) if asof_display is not None else None,
            )
    if map_status not in available_map_statuses:
        return HeldCoverageStatus(
            currency_code=resolution.currency_code,
            symbol=resolution.symbol,
            market=resolution.market,
            status="GAP",
            reason=COVERAGE_UNAVAILABLE_MAP_STATUS,
            held_by_account_codes=resolution.held_by_account_codes,
            candle_count=candle_count,
            map_status=map_status,
            asof_ts_display=str(asof_display) if asof_display is not None else None,
        )
    return HeldCoverageStatus(
        currency_code=resolution.currency_code,
        symbol=resolution.symbol,
        market=resolution.market,
        status="OK",
        reason=COVERAGE_FRESH,
        held_by_account_codes=resolution.held_by_account_codes,
        candle_count=candle_count,
        map_status=map_status,
        asof_ts_display=str(asof_display) if asof_display is not None else None,
    )


@dataclass(frozen=True)
class CoverageSummary:
    """Two separate invariants over the same statuses, deliberately not
    conflated (Issue #238 follow-up):

    - enrollment: every resolvable held asset is enrolled in the
      account-agnostic publication cohort (asset.is_publication_cohort
      / is_core_sensor
      set). Does not require a published canonical 4h row yet.
    - publication: every resolvable held asset actually has fresh, published
      canonical 4h context. A known gap (e.g. a map-status-unavailable
      symbol) keeps this failing even after enrollment succeeds -- it must
      never be normalized as acceptable just because enrollment passed.
    """

    enrollment_pass: bool
    enrollment_gaps: tuple[HeldCoverageStatus, ...]
    publication_pass: bool
    publication_gaps: tuple[HeldCoverageStatus, ...]


def summarize_coverage(statuses: Sequence[HeldCoverageStatus]) -> CoverageSummary:
    publication_gaps = tuple(s for s in statuses if s.status == "GAP")
    enrollment_gaps = tuple(s for s in statuses if s.reason == COVERAGE_NOT_ENROLLED)
    return CoverageSummary(
        enrollment_pass=not enrollment_gaps,
        enrollment_gaps=enrollment_gaps,
        publication_pass=not publication_gaps,
        publication_gaps=publication_gaps,
    )


def coverage_check_passes(summary: CoverageSummary, *, check: str) -> bool:
    """``check`` is one of 'enrollment', 'publication', 'all'. 'publication'
    and 'all' are deliberately equivalent: publication is the strict
    superset invariant, so gating the exit code on it is always at least as
    strict as gating on enrollment alone."""
    if check == "enrollment":
        return summary.enrollment_pass
    return summary.publication_pass
