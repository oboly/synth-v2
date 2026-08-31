from __future__ import annotations

"""Research-only evaluator for Issue #593 multi-horizon Rotation validation.

Consumes already replayed, point-in-time-safe rows. It does not fetch market data,
write database state, alter production ranking, or emit trading permission.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import atanh, erf, exp, isfinite, sqrt
from statistics import mean
from typing import Iterable, Mapping, Sequence


MIN_PAIRED_N = 4
CI_Z = 1.959963984540054


@dataclass(frozen=True)
class ValidationRow:
    venue: str
    asset_id: int
    asof_ts: datetime
    candidate_id: str
    candidate_score: float | None
    b0_score: float | None
    b0_pressure_state: str | None
    b1_return: float | None
    forward_15m: float | None
    forward_1h: float | None
    forward_4h: float | None
    forward_24h: float | None


@dataclass(frozen=True)
class CorrelationResult:
    sample_count: int
    correlation: float | None
    ci_low: float | None
    ci_high: float | None
    p_value_approx: float | None


@dataclass(frozen=True)
class PersistenceResult:
    run_count: int
    mean_run_samples: float | None
    median_run_samples: float | None
    max_run_samples: int | None
    sign_flip_count: int
    chop_reversion_count: int
    chop_rate: float | None


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _paired(xs: Iterable[float | None], ys: Iterable[float | None]) -> tuple[list[float], list[float]]:
    left: list[float] = []
    right: list[float] = []
    for x, y in zip(xs, ys, strict=True):
        if x is None or y is None:
            continue
        if not isfinite(x) or not isfinite(y):
            continue
        left.append(float(x))
        right.append(float(y))
    return left, right


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < MIN_PAIRED_N:
        return None
    mx = mean(xs)
    my = mean(ys)
    dx = [value - mx for value in xs]
    dy = [value - my for value in ys]
    sx2 = sum(value * value for value in dx)
    sy2 = sum(value * value for value in dy)
    if sx2 <= 0 or sy2 <= 0:
        return None
    result = sum(a * b for a, b in zip(dx, dy, strict=True)) / sqrt(sx2 * sy2)
    return max(-1.0, min(1.0, result))


def correlation_with_fisher_ci(
    xs: Iterable[float | None], ys: Iterable[float | None]
) -> CorrelationResult:
    paired_x, paired_y = _paired(xs, ys)
    n = len(paired_x)
    r = pearson(paired_x, paired_y)
    if r is None:
        return CorrelationResult(n, None, None, None, None)
    clipped = max(-0.999999999999, min(0.999999999999, r))
    z = atanh(clipped)
    se = 1.0 / sqrt(n - 3)
    lo_z = z - CI_Z * se
    hi_z = z + CI_Z * se
    lo = (exp(2 * lo_z) - 1) / (exp(2 * lo_z) + 1)
    hi = (exp(2 * hi_z) - 1) / (exp(2 * hi_z) + 1)
    z_null = abs(z) * sqrt(n - 3)
    p_approx = 2.0 * (1.0 - 0.5 * (1.0 + erf(z_null / sqrt(2.0))))
    return CorrelationResult(n, r, lo, hi, max(0.0, min(1.0, p_approx)))


def residualize(values: Sequence[float], baseline: Sequence[float]) -> list[float] | None:
    if len(values) != len(baseline) or len(values) < MIN_PAIRED_N:
        return None
    mb = mean(baseline)
    mv = mean(values)
    bdev = [value - mb for value in baseline]
    denom = sum(value * value for value in bdev)
    if denom <= 0:
        return None
    beta = sum((value - mv) * b for value, b in zip(values, bdev, strict=True)) / denom
    alpha = mv - beta * mb
    return [value - (alpha + beta * b) for value, b in zip(values, baseline, strict=True)]


def partial_correlation(
    candidate: Iterable[float | None],
    outcome: Iterable[float | None],
    baseline: Iterable[float | None],
) -> CorrelationResult:
    triples: list[tuple[float, float, float]] = []
    for c, y, b in zip(candidate, outcome, baseline, strict=True):
        if c is None or y is None or b is None:
            continue
        if not all(isfinite(float(value)) for value in (c, y, b)):
            continue
        triples.append((float(c), float(y), float(b)))
    if len(triples) < MIN_PAIRED_N:
        return CorrelationResult(len(triples), None, None, None, None)
    cs = [row[0] for row in triples]
    ys = [row[1] for row in triples]
    bs = [row[2] for row in triples]
    c_resid = residualize(cs, bs)
    y_resid = residualize(ys, bs)
    if c_resid is None or y_resid is None:
        return CorrelationResult(len(triples), None, None, None, None)
    return correlation_with_fisher_ci(c_resid, y_resid)


def holm_bonferroni(p_values: Mapping[str, float | None], *, alpha: float = 0.05) -> dict[str, bool | None]:
    valid = sorted(
        ((key, value) for key, value in p_values.items() if value is not None),
        key=lambda item: (float(item[1]), item[0]),
    )
    out: dict[str, bool | None] = {key: None for key in p_values}
    m = len(valid)
    reject_chain = True
    for index, (key, p_value) in enumerate(valid):
        threshold = alpha / (m - index)
        reject = reject_chain and float(p_value) <= threshold
        out[key] = reject
        if not reject:
            reject_chain = False
    return out


def _state(score: float | None) -> int | None:
    if score is None or not isfinite(score):
        return None
    if score > 0:
        return 1
    if score < 0:
        return -1
    return 0


def _median_numeric(values: Sequence[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def persistence_and_chop(rows: Sequence[ValidationRow], *, reversion_window_samples: int = 4) -> PersistenceResult:
    ordered = sorted(rows, key=lambda row: (ensure_utc(row.asof_ts), row.asset_id))
    by_asset: dict[int, list[ValidationRow]] = {}
    for row in ordered:
        by_asset.setdefault(row.asset_id, []).append(row)

    run_lengths: list[int] = []
    flips = 0
    chop_reversions = 0
    for asset_rows in by_asset.values():
        states = [_state(row.candidate_score) for row in asset_rows]
        states = [state for state in states if state is not None]
        if not states:
            continue
        current = states[0]
        run = 1
        for state in states[1:]:
            if state == current:
                run += 1
            else:
                run_lengths.append(run)
                flips += 1
                current = state
                run = 1
        run_lengths.append(run)

        for idx in range(1, len(states)):
            previous = states[idx - 1]
            changed = states[idx]
            if changed == previous:
                continue
            end = min(len(states), idx + reversion_window_samples + 1)
            if any(states[future_idx] == previous for future_idx in range(idx + 1, end)):
                chop_reversions += 1

    return PersistenceResult(
        run_count=len(run_lengths),
        mean_run_samples=(mean(run_lengths) if run_lengths else None),
        median_run_samples=_median_numeric(run_lengths),
        max_run_samples=(max(run_lengths) if run_lengths else None),
        sign_flip_count=flips,
        chop_reversion_count=chop_reversions,
        chop_rate=(chop_reversions / flips if flips else None),
    )


def candidate_summary(rows: Sequence[ValidationRow]) -> dict[str, object]:
    sample_count = len(rows)
    complete_count = sum(row.candidate_score is not None for row in rows)
    coverage = complete_count / sample_count if sample_count else 0.0
    forward_fields = {
        "15m": "forward_15m",
        "1h": "forward_1h",
        "4h": "forward_4h",
        "24h": "forward_24h",
    }
    forward_ic: dict[str, CorrelationResult] = {}
    incremental_b0: dict[str, CorrelationResult] = {}
    incremental_b1: dict[str, CorrelationResult] = {}
    for label, field in forward_fields.items():
        outcomes = [getattr(row, field) for row in rows]
        candidate = [row.candidate_score for row in rows]
        forward_ic[label] = correlation_with_fisher_ci(candidate, outcomes)
        incremental_b0[label] = partial_correlation(candidate, outcomes, [row.b0_score for row in rows])
        incremental_b1[label] = partial_correlation(candidate, outcomes, [row.b1_return for row in rows])

    p_values = {label: result.p_value_approx for label, result in forward_ic.items()}
    return {
        "sample_count": sample_count,
        "complete_count": complete_count,
        "coverage": coverage,
        "correlation_vs_b0": correlation_with_fisher_ci(
            [row.candidate_score for row in rows], [row.b0_score for row in rows]
        ),
        "correlation_vs_b1": correlation_with_fisher_ci(
            [row.candidate_score for row in rows], [row.b1_return for row in rows]
        ),
        "forward_ic": forward_ic,
        "incremental_vs_b0": incremental_b0,
        "incremental_vs_b1": incremental_b1,
        "holm_reject_forward_ic": holm_bonferroni(p_values),
        "persistence": persistence_and_chop(rows),
        "b2_status": "UNAVAILABLE_NO_REPLAY_SAFE_CANONICAL_SOURCE",
    }


def cross_horizon_correlations(rows: Sequence[ValidationRow]) -> dict[str, CorrelationResult]:
    by_key: dict[tuple[str, int, datetime], dict[str, float | None]] = {}
    for row in rows:
        key = (row.venue, row.asset_id, ensure_utc(row.asof_ts))
        by_key.setdefault(key, {})[row.candidate_id] = row.candidate_score
    pairs = (("C1", "C2"), ("C1", "C3"), ("C2", "C3"))
    out: dict[str, CorrelationResult] = {}
    for left, right in pairs:
        matched = [values for values in by_key.values() if left in values and right in values]
        out[f"{left}:{right}"] = correlation_with_fisher_ci(
            [values[left] for values in matched], [values[right] for values in matched]
        )
    return out


def derive_chronological_split(
    *, start: datetime, end: datetime, discovery_fraction: float = 0.60, validation_fraction: float = 0.20
) -> dict[str, tuple[datetime, datetime]]:
    start_utc = ensure_utc(start)
    end_utc = ensure_utc(end)
    if end_utc <= start_utc:
        raise ValueError("end must be after start")
    if discovery_fraction <= 0 or validation_fraction <= 0 or discovery_fraction + validation_fraction >= 1:
        raise ValueError("invalid split fractions")
    total_seconds = int((end_utc - start_utc).total_seconds())
    grid_seconds = 15 * 60
    total_steps = total_seconds // grid_seconds
    if total_steps < 5:
        raise ValueError("insufficient replay-safe span")
    discovery_steps = int(total_steps * discovery_fraction)
    validation_steps = int(total_steps * validation_fraction)
    discovery_end = start_utc + timedelta(seconds=discovery_steps * grid_seconds)
    validation_end = discovery_end + timedelta(seconds=validation_steps * grid_seconds)
    return {
        "discovery": (start_utc, discovery_end),
        "validation": (discovery_end, validation_end),
        "final_holdout": (validation_end, end_utc),
    }
