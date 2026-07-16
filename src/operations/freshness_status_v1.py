from __future__ import annotations

"""Pure freshness-status authority for Lane C P2-B.

This module is the single, deterministic evaluator for the P2-B absolute
freshness contract.  Given an absolute UTC observation timestamp, a reference
``now``, and a staleness threshold, it classifies a source into exactly one of:

``FRESH | STALE | MISSING | UNAVAILABLE``.

It is intentionally free of side effects:

- no database access
- no broker calls
- no account mutation
- no rendering / HTML / JSON emission
- no implicit wall-clock reads (``now`` is always injected)

Because ``now`` and every observation timestamp are injected, a stopped static
renderer cannot fabricate freshness: a frozen ``dashboard_generated_ts_utc`` ages
against an advancing ``now`` and deterministically becomes ``STALE``.  Freshness
is computed from UTC source timestamps only, independent of any display timezone
(``docs/architecture/dashboard_time_display_policy_v1.md``).

Consumers:

- ``decision_gate`` may consume this pure evaluator (or persisted freshness
  authority) to gate account-aware permission; it must never consume renderer
  HTML/JSON.
- reporting may display the resulting statuses but must not invent authority.

Placed in ``src/operations`` so both ``decision_gate`` and ``reporting`` can
import it without either layer depending on the other.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Mapping, Sequence

# --- Canonical freshness statuses (P2-B authority classes) -------------------

FRESH = "FRESH"
STALE = "STALE"
MISSING = "MISSING"
UNAVAILABLE = "UNAVAILABLE"

FRESHNESS_STATUSES: tuple[str, ...] = (FRESH, STALE, MISSING, UNAVAILABLE)

# Severity ordering used to reduce many per-class statuses to one overall
# status.  A larger rank is "worse".  FRESH is the only non-degraded state.
_STATUS_SEVERITY: dict[str, int] = {
    FRESH: 0,
    STALE: 1,
    MISSING: 2,
    UNAVAILABLE: 3,
}

# --- Reasons (stable machine codes; display text lives elsewhere) ------------

REASON_SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
REASON_NO_OBSERVATION = "NO_OBSERVATION"
REASON_WITHIN_THRESHOLD = "WITHIN_THRESHOLD"
REASON_EXCEEDS_THRESHOLD = "EXCEEDS_THRESHOLD"
REASON_FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"

# --- Canonical P2-B observation class keys -----------------------------------

MARKET_PRICE = "market_price_observed_ts_utc"
WALLET = "wallet_observed_ts_utc"
POSITION = "position_observed_ts_utc"
OPEN_ORDERS = "open_orders_observed_ts_utc"
DASHBOARD_GENERATED = "dashboard_generated_ts_utc"

OBSERVATION_CLASS_KEYS: tuple[str, ...] = (
    MARKET_PRICE,
    WALLET,
    POSITION,
    OPEN_ORDERS,
    DASHBOARD_GENERATED,
)

# Account-specific classes.  When any of these is not FRESH, account-specific
# action / ladder claims must be suppressed (P2-B rule).
ACCOUNT_OBSERVATION_CLASS_KEYS: tuple[str, ...] = (
    WALLET,
    POSITION,
    OPEN_ORDERS,
)


def _normalize_utc(value: datetime) -> datetime:
    """Return ``value`` as a timezone-aware UTC datetime.

    Naive datetimes are assumed to be UTC because the system stores, queries,
    and transports timestamps in UTC (dashboard time-display policy).  This
    keeps freshness math deterministic and independent of the display timezone.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class FreshnessResult:
    """Deterministic classification of a single source's freshness."""

    status: str
    reason: str
    observed_ts_utc: datetime | None
    age_seconds: float | None
    stale_after_seconds: float

    @property
    def is_fresh(self) -> bool:
        return self.status == FRESH


def evaluate_freshness(
    observed_ts: datetime | None,
    now: datetime,
    stale_after: timedelta,
    *,
    source_available: bool = True,
    max_future_skew: timedelta = timedelta(seconds=0),
) -> FreshnessResult:
    """Classify one source into ``FRESH | STALE | MISSING | UNAVAILABLE``.

    Rules (fail-closed):

    - ``source_available=False`` -> ``UNAVAILABLE`` (source structurally absent
      / not configured for this profile or context).
    - ``observed_ts is None`` -> ``MISSING`` (source applies but no observation
      exists yet).
    - observation in the future beyond ``max_future_skew`` -> ``STALE`` (an
      untrustworthy clock must never read as fresh).
    - ``now - observed_ts <= stale_after`` -> ``FRESH``; otherwise ``STALE``.

    ``now`` is injected; this function never reads wall-clock time.
    """

    if stale_after < timedelta(0):
        raise ValueError("stale_after must be non-negative")
    if max_future_skew < timedelta(0):
        raise ValueError("max_future_skew must be non-negative")

    stale_after_seconds = stale_after.total_seconds()

    if not source_available:
        return FreshnessResult(
            status=UNAVAILABLE,
            reason=REASON_SOURCE_UNAVAILABLE,
            observed_ts_utc=None,
            age_seconds=None,
            stale_after_seconds=stale_after_seconds,
        )

    if observed_ts is None:
        return FreshnessResult(
            status=MISSING,
            reason=REASON_NO_OBSERVATION,
            observed_ts_utc=None,
            age_seconds=None,
            stale_after_seconds=stale_after_seconds,
        )

    observed_utc = _normalize_utc(observed_ts)
    now_utc = _normalize_utc(now)
    age_seconds = (now_utc - observed_utc).total_seconds()

    if age_seconds < -max_future_skew.total_seconds():
        # Observation is in the future beyond tolerated skew -> untrustworthy.
        return FreshnessResult(
            status=STALE,
            reason=REASON_FUTURE_TIMESTAMP,
            observed_ts_utc=observed_utc,
            age_seconds=age_seconds,
            stale_after_seconds=stale_after_seconds,
        )

    # Clamp small negative ages (within skew) to zero for reporting.
    effective_age = max(age_seconds, 0.0)
    if effective_age <= stale_after_seconds:
        return FreshnessResult(
            status=FRESH,
            reason=REASON_WITHIN_THRESHOLD,
            observed_ts_utc=observed_utc,
            age_seconds=age_seconds,
            stale_after_seconds=stale_after_seconds,
        )

    return FreshnessResult(
        status=STALE,
        reason=REASON_EXCEEDS_THRESHOLD,
        observed_ts_utc=observed_utc,
        age_seconds=age_seconds,
        stale_after_seconds=stale_after_seconds,
    )


# --- Observation-class level evaluation --------------------------------------

# Named default thresholds (module-level constants, not magic numbers).
DEFAULT_MARKET_PRICE_STALE_AFTER = timedelta(minutes=15)
DEFAULT_WALLET_STALE_AFTER = timedelta(minutes=15)
DEFAULT_POSITION_STALE_AFTER = timedelta(minutes=15)
DEFAULT_OPEN_ORDERS_STALE_AFTER = timedelta(minutes=15)
DEFAULT_DASHBOARD_GENERATED_STALE_AFTER = timedelta(minutes=15)


@dataclass(frozen=True)
class ObservationClassSpec:
    """Threshold + gating role for one P2-B observation class."""

    key: str
    stale_after: timedelta
    # When True this class participates in the overall status reduction.  A
    # non-required class is still classified and reported but does not drag the
    # overall status down (e.g. an absent optional source is UNAVAILABLE-but-ok).
    required: bool = True


DEFAULT_OBSERVATION_CLASS_SPECS: tuple[ObservationClassSpec, ...] = (
    ObservationClassSpec(MARKET_PRICE, DEFAULT_MARKET_PRICE_STALE_AFTER),
    ObservationClassSpec(WALLET, DEFAULT_WALLET_STALE_AFTER),
    ObservationClassSpec(POSITION, DEFAULT_POSITION_STALE_AFTER),
    ObservationClassSpec(OPEN_ORDERS, DEFAULT_OPEN_ORDERS_STALE_AFTER),
    ObservationClassSpec(
        DASHBOARD_GENERATED, DEFAULT_DASHBOARD_GENERATED_STALE_AFTER
    ),
)


@dataclass(frozen=True)
class ObservationFreshnessReport:
    """Per-class freshness results plus a deterministic overall status."""

    overall_status: str
    account_action_permitted: bool
    results: dict[str, FreshnessResult] = field(default_factory=dict)

    def status_of(self, key: str) -> str:
        return self.results[key].status


def _worst_status(statuses: Sequence[str]) -> str:
    worst = FRESH
    for status in statuses:
        if _STATUS_SEVERITY[status] > _STATUS_SEVERITY[worst]:
            worst = status
    return worst


def evaluate_observation_classes(
    observed: Mapping[str, datetime | None],
    now: datetime,
    specs: Sequence[ObservationClassSpec] = DEFAULT_OBSERVATION_CLASS_SPECS,
    *,
    source_available: Mapping[str, bool] | None = None,
    max_future_skew: timedelta = timedelta(seconds=0),
) -> ObservationFreshnessReport:
    """Evaluate every configured observation class deterministically.

    ``overall_status`` is the worst status among *required* classes.  A
    non-required class is reported but never worsens the overall status.

    ``account_action_permitted`` is True only when every account observation
    class present in ``specs`` is ``FRESH`` (P2-B: stale account truth suppresses
    account-specific ladder / action claims).
    """

    availability = source_available or {}
    results: dict[str, FreshnessResult] = {}
    required_statuses: list[str] = []
    account_statuses: list[str] = []

    for spec in specs:
        result = evaluate_freshness(
            observed.get(spec.key),
            now,
            spec.stale_after,
            source_available=availability.get(spec.key, True),
            max_future_skew=max_future_skew,
        )
        results[spec.key] = result
        if spec.required:
            required_statuses.append(result.status)
        if spec.key in ACCOUNT_OBSERVATION_CLASS_KEYS:
            account_statuses.append(result.status)

    overall_status = _worst_status(required_statuses) if required_statuses else FRESH
    account_permitted = bool(account_statuses) and all(
        status == FRESH for status in account_statuses
    )

    return ObservationFreshnessReport(
        overall_status=overall_status,
        account_action_permitted=account_permitted,
        results=results,
    )
