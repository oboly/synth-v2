from __future__ import annotations

"""Pure freshness-status classifier for Lane C P2-B.

This module is the single, deterministic classifier for the P2-B absolute
freshness contract.  Given an absolute UTC observation timestamp, a reference
``now``, and a caller-supplied staleness threshold, it classifies a source into
exactly one of:

``FRESH | STALE | MISSING | UNAVAILABLE``.

Scope is deliberately narrow — it classifies freshness only.  It does **not**
decide whether any account action, ladder action, order action, or other
permission is allowed; account-aware permission belongs exclusively to
``decision_gate``, which may consume this classifier (or persisted freshness
authority) as an input.

It is intentionally free of side effects and policy:

- no database access
- no broker calls
- no account mutation or account-permission logic
- no rendering / HTML / JSON emission
- no implicit wall-clock reads (``now`` is always injected)
- no built-in staleness thresholds (callers supply them explicitly)

Because ``now`` and every observation timestamp are injected, a stopped static
renderer cannot fabricate freshness: a frozen ``dashboard_generated_ts_utc`` ages
against an advancing ``now`` and deterministically becomes ``STALE``.

Timestamp handling is fail-closed.  Persisted authorities are UTC and the DB
boundary types them as timezone-aware before they enter pure logic
(`docs/architecture/native_short_fib_context_snapshot_contract_v1.md`, DB
boundary), and engine logic must never mix aware/naive timestamps
(`docs/coding_standards.md` §3).  This classifier therefore requires
timezone-aware UTC datetimes and rejects naive datetimes with ``ValueError``
rather than silently attaching UTC and concealing malformed source data.

Placed in ``src/operations`` so both ``decision_gate`` and reporting can import
it without either layer depending on the other.
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
# freshness status.  A larger rank is "worse".  FRESH is the only non-degraded
# state.  This is a freshness reduction only, not a permission decision.
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

# --- Canonical P2-B observation class keys (field names, not policy) ---------

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


def _require_utc(value: datetime, label: str) -> datetime:
    """Return ``value`` as UTC, rejecting naive datetimes (fail-closed).

    Persisted authorities are timezone-aware UTC by the time they reach engine
    logic (DB boundary attaches UTC; `docs/coding_standards.md` §3 forbids
    mixing aware/naive in engine logic).  A naive datetime here indicates
    malformed/unconverted source data and must not be silently coerced.
    """

    if value.tzinfo is None:
        raise ValueError(
            f"{label} must be timezone-aware UTC; received naive datetime"
        )
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

    ``stale_after`` is required and caller-supplied; this module defines no
    staleness policy of its own.

    Rules (fail-closed):

    - ``source_available=False`` -> ``UNAVAILABLE`` (source structurally absent
      / not configured for this profile or context).
    - ``observed_ts is None`` -> ``MISSING`` (source applies but no observation
      exists yet).
    - observation in the future beyond ``max_future_skew`` -> ``STALE`` (an
      untrustworthy clock must never read as fresh).
    - ``now - observed_ts <= stale_after`` -> ``FRESH``; otherwise ``STALE``.

    ``now`` and any present ``observed_ts`` must be timezone-aware UTC; a naive
    datetime raises ``ValueError``.  ``now`` never reads wall-clock time.
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

    observed_utc = _require_utc(observed_ts, "observed_ts")
    now_utc = _require_utc(now, "now")
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


@dataclass(frozen=True)
class ObservationClassSpec:
    """Caller-supplied threshold + reduction role for one observation class.

    ``stale_after`` is required; this module ships no default thresholds because
    no canonical doc defines per-class P2-B freshness limits.  Consumers own the
    policy and must pass explicit specs.
    """

    key: str
    stale_after: timedelta
    # When True this class participates in the overall status reduction.  A
    # non-required class is still classified and reported but never worsens the
    # overall status.
    required: bool = True


@dataclass(frozen=True)
class ObservationFreshnessReport:
    """Per-class freshness results plus a deterministic overall status.

    This is a freshness aggregate only.  It carries no permission decision.
    """

    overall_status: str
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
    specs: Sequence[ObservationClassSpec],
    *,
    source_available: Mapping[str, bool] | None = None,
    max_future_skew: timedelta = timedelta(seconds=0),
) -> ObservationFreshnessReport:
    """Evaluate every caller-supplied observation class deterministically.

    ``specs`` is required; the caller owns which classes and thresholds apply.
    ``overall_status`` is the worst freshness status among *required* classes; a
    non-required class is reported but never worsens the overall status.  No
    permission is computed here.
    """

    availability = source_available or {}
    results: dict[str, FreshnessResult] = {}
    required_statuses: list[str] = []

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

    overall_status = _worst_status(required_statuses) if required_statuses else FRESH

    return ObservationFreshnessReport(
        overall_status=overall_status,
        results=results,
    )
