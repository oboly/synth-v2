from __future__ import annotations

"""Research-only evaluator for Issue #593 multi-horizon Rotation validation.

Consumes already replayed, point-in-time-safe rows. It does not fetch market data,
write database state, alter production ranking, or emit trading permission.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from math import atanh, erf, exp, isfinite, sqrt
from statistics import mean
from typing import Iterable, Mapping, Sequence


MIN_PAIRED_N = 4
CI_Z = 1.959963984540054
SAMPLE_INTERVAL = timedelta(minutes=15)
FORWARD_FIELDS = {
    "15m": "forward_15m",
    "1h": "forward_1h",
    "4h": "forward_4h",
    "24h": "forward_24h",
}
CANDIDATE_IDS = ("C1", "C2", "C3")


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


def is_on_15m_grid(value: datetime) -> bool:
    value = ensure_utc(value)
    return value.minute % 15 == 0 and value.second == 0 and value.microsecond == 0


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


def _correlation_result(
    *,
    sample_count: int,
    correlation: float | None,
    controlled_variables: int = 0,
) -> CorrelationResult:
    if correlation is None or sample_count <= controlled_variables + 3:
        return CorrelationResult(sample_count, None, None, None, None)
    clipped = max(-0.999999999999, min(0.999999999999, correlation))
    z = atanh(clipped)
    effective_n = sample_count - controlled_variables - 3
    se = 1.0 / sqrt(effective_n)
    lo_z = z - CI_Z * se
    hi_z = z + CI_Z * se
    lo = (exp(2 * lo_z) - 1) / (exp(2 * lo_z) + 1)
    hi = (exp(2 * hi_z) - 1) / (exp(2 * hi_z) + 1)
    z_null = abs(z) * sqrt(effective_n)
    p_approx = 2.0 * (1.0 - 0.5 * (1.0 + erf(z_null / sqrt(2.0))))
    return CorrelationResult(
        sample_count,
        correlation,
        lo,
        hi,
        max(0.0, min(1.0, p_approx)),
    )


def correlation_with_fisher_ci(
    xs: Iterable[float | None], ys: Iterable[float | None]
) -> CorrelationResult:
    paired_x, paired_y = _paired(xs, ys)
    return _correlation_result(
        sample_count=len(paired_x),
        correlation=pearson(paired_x, paired_y),
        controlled_variables=0,
    )


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
    n = len(triples)
    if n <= 4:
        return CorrelationResult(n, None, None, None, None)
    cs = [row[0] for row in triples]
    ys = [row[1] for row in triples]
    bs = [row[2] for row in triples]
    c_resid = residualize(cs, bs)
    y_resid = residualize(ys, bs)
    if c_resid is None or y_resid is None:
        return CorrelationResult(n, None, None, None, None)
    return _correlation_result(
        sample_count=n,
        correlation=pearson(c_resid, y_resid),
        controlled_variables=1,
    )


def holm_bonferroni(p_values: Mapping[str, float | None], *, alpha: float = 0.05) -> dict[str, bool | None]:
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    for value in p_values.values():
        if value is not None and not 0 <= float(value) <= 1:
            raise ValueError("p-values must be in [0,1]")
    valid = sorted(
        ((key, value) for key, value in p_values.items() if value is not None),
        key=lambda item: (float(item[1]), item[0]),
    )
    out: dict[str, bool | None] = {key: None for key in p_values}
    family_size = len(p_values)
    reject_chain = True
    for index, (key, p_value) in enumerate(valid):
        threshold = alpha / (family_size - index)
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
    if reversion_window_samples < 1:
        raise ValueError("reversion_window_samples must be positive")
    by_asset: dict[int, list[ValidationRow]] = {}
    for row in sorted(rows, key=lambda item: (item.asset_id, ensure_utc(item.asof_ts))):
        by_asset.setdefault(row.asset_id, []).append(row)

    run_lengths: list[int] = []
    flips = 0
    chop_reversions = 0
    for asset_rows in by_asset.values():
        current_state: int | None = None
        run = 0
        previous_ts: datetime | None = None
        for row in asset_rows:
            ts = ensure_utc(row.asof_ts)
            state = _state(row.candidate_score)
            contiguous = previous_ts is None or ts - previous_ts == SAMPLE_INTERVAL
            if state is None or not contiguous:
                if run:
                    run_lengths.append(run)
                current_state = None
                run = 0
            if state is not None:
                if current_state is None:
                    current_state = state
                    run = 1
                elif state == current_state:
                    run += 1
                else:
                    run_lengths.append(run)
                    flips += 1
                    current_state = state
                    run = 1
            previous_ts = ts
        if run:
            run_lengths.append(run)

        for idx in range(1, len(asset_rows)):
            previous_row = asset_rows[idx - 1]
            changed_row = asset_rows[idx]
            previous_state = _state(previous_row.candidate_score)
            changed_state = _state(changed_row.candidate_score)
            if previous_state is None or changed_state is None or changed_state == previous_state:
                continue
            if ensure_utc(changed_row.asof_ts) - ensure_utc(previous_row.asof_ts) != SAMPLE_INTERVAL:
                continue
            for future_idx in range(idx + 1, min(len(asset_rows), idx + reversion_window_samples + 1)):
                prior = asset_rows[future_idx - 1]
                future = asset_rows[future_idx]
                if ensure_utc(future.asof_ts) - ensure_utc(prior.asof_ts) != SAMPLE_INTERVAL:
                    break
                future_state = _state(future.candidate_score)
                if future_state is None:
                    break
                if future_state == previous_state:
                    chop_reversions += 1
                    break

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
    candidate_ids = {row.candidate_id for row in rows}
    if len(candidate_ids) > 1:
        raise ValueError("candidate_summary requires exactly one candidate_id")
    sample_count = len(rows)
    complete_count = sum(row.candidate_score is not None for row in rows)
    coverage = complete_count / sample_count if sample_count else 0.0
    forward_ic: dict[str, CorrelationResult] = {}
    incremental_b0: dict[str, CorrelationResult] = {}
    incremental_b1: dict[str, CorrelationResult] = {}
    for label, field in FORWARD_FIELDS.items():
        outcomes = [getattr(row, field) for row in rows]
        candidate = [row.candidate_score for row in rows]
        forward_ic[label] = correlation_with_fisher_ci(candidate, outcomes)
        incremental_b0[label] = partial_correlation(candidate, outcomes, [row.b0_score for row in rows])
        incremental_b1[label] = partial_correlation(candidate, outcomes, [row.b1_return for row in rows])

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


def validation_summary(rows: Sequence[ValidationRow]) -> dict[str, object]:
    unknown = sorted({row.candidate_id for row in rows} - set(CANDIDATE_IDS))
    if unknown:
        raise ValueError(f"unknown candidate ids: {','.join(unknown)}")
    by_candidate = {
        candidate_id: [row for row in rows if row.candidate_id == candidate_id]
        for candidate_id in CANDIDATE_IDS
    }
    summaries = {
        candidate_id: candidate_summary(candidate_rows)
        for candidate_id, candidate_rows in by_candidate.items()
    }
    family_p_values: dict[str, float | None] = {}
    for candidate_id, summary in summaries.items():
        forward_ic = summary["forward_ic"]
        assert isinstance(forward_ic, dict)
        for horizon, result in forward_ic.items():
            assert isinstance(result, CorrelationResult)
            family_p_values[f"{candidate_id}:{horizon}"] = result.p_value_approx
    return {
        "candidate_summaries": summaries,
        "cross_horizon_correlation": cross_horizon_correlations(rows),
        "holm_bonferroni_family": holm_bonferroni(family_p_values),
        "holm_family_size": len(family_p_values),
        "b2_status": "UNAVAILABLE_NO_REPLAY_SAFE_CANONICAL_SOURCE",
    }


def serializable_validation_summary(rows: Sequence[ValidationRow]) -> dict[str, object]:
    def convert(value: object) -> object:
        if hasattr(value, "__dataclass_fields__"):
            return {key: convert(item) for key, item in asdict(value).items()}
        if isinstance(value, dict):
            return {str(key): convert(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [convert(item) for item in value]
        return value

    converted = convert(validation_summary(rows))
    assert isinstance(converted, dict)
    return converted


def derive_chronological_split(
    *, start: datetime, end: datetime, discovery_fraction: float = 0.60, validation_fraction: float = 0.20
) -> dict[str, tuple[datetime, datetime]]:
    start_utc = ensure_utc(start)
    end_utc = ensure_utc(end)
    if not is_on_15m_grid(start_utc) or not is_on_15m_grid(end_utc):
        raise ValueError("split span boundaries must be on the 15m grid")
    if end_utc <= start_utc:
        raise ValueError("end must be after start")
    if discovery_fraction <= 0 or validation_fraction <= 0 or discovery_fraction + validation_fraction >= 1:
        raise ValueError("invalid split fractions")
    total_steps = int((end_utc - start_utc).total_seconds()) // int(SAMPLE_INTERVAL.total_seconds())
    if total_steps < 5:
        raise ValueError("insufficient replay-safe span")
    discovery_steps = int(total_steps * discovery_fraction)
    validation_steps = int(total_steps * validation_fraction)
    if discovery_steps <= 0 or validation_steps <= 0 or discovery_steps + validation_steps >= total_steps:
        raise ValueError("split phases must each contain at least one 15m step")
    discovery_end = start_utc + SAMPLE_INTERVAL * discovery_steps
    validation_end = discovery_end + SAMPLE_INTERVAL * validation_steps
    return {
        "discovery": (start_utc, discovery_end),
        "validation": (discovery_end, validation_end),
        "final_holdout": (validation_end, end_utc),
    }
