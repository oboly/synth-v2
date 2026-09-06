from __future__ import annotations

"""Read-only execution-offset preview and paper-validation core for issue #317.

Research-only, market-only, account-agnostic. This module consumes the canonical
#224 execution-offset episode/policy contract. It never grants permission,
creates planner intent, submits orders, or mutates runtime/database state.
"""

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from typing import Any, Final, Iterable, Mapping, Sequence

from src.market_rules.price_tick_normalization_v1 import (
    NORM_STATUS_APPLIED,
    PRICE_ROLE_REENTRY_BUY,
    PRICE_ROLE_TARGET_SELL,
    TickRule,
    normalize_price_to_tick,
)
from src.research.execution_offset_replay_v1 import (
    ExecutionOffsetEpisodeV1,
    ExecutionOffsetPolicyV1,
    ExecutionOffsetReplayError,
    ExecutionOffsetReplayRowV1,
    POLICY_EXACT_LEVEL,
    POLICY_STATIC_BUFFER,
    POLICY_VOLATILITY_SCALED_BUFFER,
    ReplayCandle,
    SIDE_BUY,
    SIDE_SELL,
    execution_price_for_policy,
    policy_fingerprint,
    replay_episode,
)

VERSION: Final[str] = "execution_offset_preview_paper_validation_v1"
STATE_PREVIEW: Final[str] = "PREVIEW"
STATE_NON_ACTIONABLE: Final[str] = "NON_ACTIONABLE"
REASON_OK: Final[str] = "OK"
REASON_MISSING_TICK_RULE: Final[str] = "MISSING_TICK_RULE"
REASON_POLICY_ERROR: Final[str] = "POLICY_ERROR"
REASON_INVALID_INVALIDATION_GEOMETRY: Final[str] = "INVALID_INVALIDATION_GEOMETRY"
UNKNOWN_REGIME: Final[str] = "UNKNOWN_REGIME"
CONFIDENCE_SUFFICIENT: Final[str] = "SUFFICIENT_SAMPLE"
CONFIDENCE_INSUFFICIENT: Final[str] = "INSUFFICIENT_SAMPLE"
OUTCOME_NOT_AVAILABLE: Final[str] = "NOT_AVAILABLE"
OUTCOME_NONE: Final[str] = "NONE"
OUTCOME_TARGET: Final[str] = "TARGET"
OUTCOME_INVALIDATION: Final[str] = "INVALIDATION"
OUTCOME_AMBIGUOUS: Final[str] = "AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE"


class ExecutionOffsetValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ExecutionOffsetPreviewV1:
    state: str
    reason_code: str
    episode_id: str
    symbol: str
    venue: str
    horizon: str
    regime_state: str
    side: str
    ideal_market_level: Decimal
    raw_policy_execution_price: Decimal | None
    execution_price: Decimal | None
    execution_offset_pct: Decimal | None
    offset_policy_id: str
    offset_policy_version: str
    policy_fingerprint: str | None
    source_map_id: str
    tick_size: Decimal | None
    tick_rule_source: str
    tick_rule_status: str
    preview_only: bool = True
    decision_permission: bool = False
    execution_intent: bool = False


@dataclass(frozen=True)
class PaperOutcomeContextV1:
    episode_id: str
    profit_target_price: Decimal | None = None


@dataclass(frozen=True)
class PaperCostAssumptionsV1:
    fee_bps_per_side: Decimal
    slippage_bps_per_fill: Decimal


@dataclass(frozen=True)
class PaperValidationInputV1:
    episode: ExecutionOffsetEpisodeV1
    candles: tuple[ReplayCandle, ...]
    tick_rule: TickRule
    outcome_context: PaperOutcomeContextV1 | None = None


@dataclass(frozen=True)
class PaperValidationRowV1:
    episode_id: str
    symbol: str
    regime_state: str
    policy_id: str
    policy_version: str
    policy_fingerprint: str
    canonical_level: Decimal
    execution_price: Decimal
    filled: bool
    near_miss: bool
    near_miss_distance_pct: Decimal | None
    execution_price_degradation_pct: Decimal
    max_favorable_excursion_pct: Decimal | None
    max_adverse_excursion_pct: Decimal | None
    time_to_fill_seconds: int | None
    invalidated_before_fill: bool
    same_candle_fill_invalidation_ambiguous: bool
    post_fill_outcome: str
    post_fill_target_available: bool
    post_fill_invalidation_available: bool
    post_fill_target_hit: bool | None
    post_fill_invalidation_hit: bool | None
    fee_slippage_cost_pct: Decimal
    fee_slippage_adjusted_mfe_proxy_pct: Decimal | None


def _regime(value: str | None) -> str:
    return value if value and value.strip() else UNKNOWN_REGIME


def build_execution_offset_preview(
    *,
    episode: ExecutionOffsetEpisodeV1,
    policy: ExecutionOffsetPolicyV1,
    tick_rule: TickRule,
) -> ExecutionOffsetPreviewV1:
    """Return evidence-only proposed execution price alongside canonical level."""
    regime = _regime(episode.regime_state)
    base = dict(
        episode_id=episode.episode_id,
        symbol=episode.symbol,
        venue=episode.venue,
        horizon=episode.horizon,
        regime_state=regime,
        side=episode.side,
        ideal_market_level=episode.canonical_level,
        offset_policy_id=policy.policy_id,
        offset_policy_version=policy.version,
        source_map_id=episode.source_map_id,
        tick_rule_source=tick_rule.source,
    )
    try:
        raw = execution_price_for_policy(episode, policy)
        fingerprint = policy_fingerprint(policy)
    except ExecutionOffsetReplayError:
        return ExecutionOffsetPreviewV1(
            **base,
            state=STATE_NON_ACTIONABLE,
            reason_code=REASON_POLICY_ERROR,
            raw_policy_execution_price=None,
            execution_price=None,
            execution_offset_pct=None,
            policy_fingerprint=None,
            tick_size=None if tick_rule.tick_size <= 0 else tick_rule.tick_size,
            tick_rule_status=REASON_POLICY_ERROR,
        )

    price_role = PRICE_ROLE_REENTRY_BUY if episode.side == SIDE_BUY else PRICE_ROLE_TARGET_SELL
    normalized = normalize_price_to_tick(raw, tick_rule, price_role)
    if normalized.price_rule_status != NORM_STATUS_APPLIED:
        return ExecutionOffsetPreviewV1(
            **base,
            state=STATE_NON_ACTIONABLE,
            reason_code=REASON_MISSING_TICK_RULE,
            raw_policy_execution_price=raw,
            execution_price=None,
            execution_offset_pct=(raw - episode.canonical_level) / episode.canonical_level * Decimal("100"),
            policy_fingerprint=fingerprint,
            tick_size=normalized.tick_size,
            tick_rule_status=normalized.price_rule_status,
        )

    if episode.invalidation_price is not None:
        canonical_delta = episode.canonical_level - episode.invalidation_price
        execution_delta = normalized.normalized_price - episode.invalidation_price
        if canonical_delta == 0 or execution_delta == 0 or canonical_delta * execution_delta < 0:
            return ExecutionOffsetPreviewV1(
                **base,
                state=STATE_NON_ACTIONABLE,
                reason_code=REASON_INVALID_INVALIDATION_GEOMETRY,
                raw_policy_execution_price=raw,
                execution_price=None,
                execution_offset_pct=(raw - episode.canonical_level) / episode.canonical_level * Decimal("100"),
                policy_fingerprint=fingerprint,
                tick_size=normalized.tick_size,
                tick_rule_status=REASON_INVALID_INVALIDATION_GEOMETRY,
            )

    return ExecutionOffsetPreviewV1(
        **base,
        state=STATE_PREVIEW,
        reason_code=REASON_OK,
        raw_policy_execution_price=raw,
        execution_price=normalized.normalized_price,
        execution_offset_pct=(normalized.normalized_price - episode.canonical_level) / episode.canonical_level * Decimal("100"),
        policy_fingerprint=fingerprint,
        tick_size=normalized.tick_size,
        tick_rule_status=normalized.price_rule_status,
    )


def _validate_costs(costs: PaperCostAssumptionsV1) -> None:
    if costs.fee_bps_per_side < 0 or costs.slippage_bps_per_fill < 0:
        raise ExecutionOffsetValidationError("NEGATIVE_FEE_OR_SLIPPAGE")


def _validate_threshold(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ExecutionOffsetValidationError("INVALID_MIN_SAMPLE_THRESHOLD")


def _validate_policy_set(policies: Sequence[ExecutionOffsetPolicyV1]) -> None:
    if not policies:
        raise ExecutionOffsetValidationError("NO_POLICIES")
    ids = {policy.policy_id for policy in policies}
    required = {POLICY_EXACT_LEVEL, POLICY_STATIC_BUFFER, POLICY_VOLATILITY_SCALED_BUFFER}
    if not required.issubset(ids):
        raise ExecutionOffsetValidationError("REQUIRED_POLICY_FAMILIES_MISSING")
    fps = [policy_fingerprint(policy) for policy in policies]
    if len(fps) != len(set(fps)):
        raise ExecutionOffsetValidationError("DUPLICATE_POLICY_FINGERPRINT")


def _price_degradation_pct(episode: ExecutionOffsetEpisodeV1, execution_price: Decimal) -> Decimal:
    if episode.side == SIDE_BUY:
        return (execution_price - episode.canonical_level) / episode.canonical_level * Decimal("100")
    if episode.side == SIDE_SELL:
        return (episode.canonical_level - execution_price) / episode.canonical_level * Decimal("100")
    raise ExecutionOffsetValidationError("UNSUPPORTED_SIDE")


def _post_fill_outcome(
    *,
    episode: ExecutionOffsetEpisodeV1,
    replay: ExecutionOffsetReplayRowV1,
    candles: Sequence[ReplayCandle],
    context: PaperOutcomeContextV1 | None,
) -> tuple[str, bool, bool, bool | None, bool | None]:
    if context is not None and context.episode_id != episode.episode_id:
        raise ExecutionOffsetValidationError("OUTCOME_CONTEXT_IDENTITY_CONFLICT")
    target = None if context is None else context.profit_target_price
    invalidation = episode.invalidation_price
    target_available = target is not None
    invalidation_available = invalidation is not None
    if target is not None and target <= 0:
        raise ExecutionOffsetValidationError("INVALID_PROFIT_TARGET_PRICE")
    if invalidation is not None and invalidation <= 0:
        raise ExecutionOffsetValidationError("INVALID_OUTCOME_GEOMETRY")
    if target is not None and target == replay.execution_price:
        raise ExecutionOffsetValidationError("INVALID_OUTCOME_GEOMETRY")
    if invalidation is not None and invalidation == replay.execution_price:
        raise ExecutionOffsetValidationError("INVALID_OUTCOME_GEOMETRY")
    if target is not None and invalidation is not None:
        target_delta = target - replay.execution_price
        invalidation_delta = invalidation - replay.execution_price
        if target_delta * invalidation_delta >= 0:
            raise ExecutionOffsetValidationError("INVALID_OUTCOME_GEOMETRY")
    if not target_available and not invalidation_available:
        return OUTCOME_NOT_AVAILABLE, False, False, None, None
    if not replay.filled or replay.time_to_fill_seconds is None:
        return OUTCOME_NONE, target_available, invalidation_available, False if target_available else None, False if invalidation_available else None

    fill_ts = episode.issued_ts_utc + timedelta(seconds=replay.time_to_fill_seconds)
    future = sorted(
        (
            c
            for c in candles
            if episode.issued_ts_utc <= c.open_ts_utc
            and c.close_ts_utc <= episode.valid_until_ts_utc
            and c.close_ts_utc > fill_ts
        ),
        key=lambda c: c.close_ts_utc,
    )
    for candle in future:
        target_hit = False
        if target is not None:
            target_hit = candle.high_price >= target if target > replay.execution_price else candle.low_price <= target
        invalidation_hit = False
        if invalidation is not None:
            invalidation_hit = candle.high_price >= invalidation if invalidation > replay.execution_price else candle.low_price <= invalidation
        if target is not None and invalidation is not None and target_hit and invalidation_hit:
            return OUTCOME_AMBIGUOUS, True, True, None, None
        if target_hit:
            return OUTCOME_TARGET, target_available, invalidation_available, True, False if invalidation_available else None
        if invalidation_hit:
            return OUTCOME_INVALIDATION, target_available, invalidation_available, False if target_available else None, True
    return OUTCOME_NONE, target_available, invalidation_available, False if target_available else None, False if invalidation_available else None


def _paper_row(
    *,
    item: PaperValidationInputV1,
    policy: ExecutionOffsetPolicyV1,
    costs: PaperCostAssumptionsV1,
) -> PaperValidationRowV1:
    # Paper replay must use the same tick-valid price surfaced by preview, not
    # the pre-rounding theoretical policy price. We still delegate ALL fill /
    # near-miss / MFE / MAE semantics to #224: a derived immutable episode
    # pins its canonical level to the tick-rounded preview price and is replayed
    # with EXACT_LEVEL. Output identity remains the caller's original policy.
    preview = build_execution_offset_preview(
        episode=item.episode, policy=policy, tick_rule=item.tick_rule
    )
    if preview.state != STATE_PREVIEW or preview.execution_price is None:
        raise ExecutionOffsetValidationError(
            f"PAPER_PREVIEW_NON_ACTIONABLE:{preview.reason_code}"
        )
    rounded_episode = replace(item.episode, canonical_level=preview.execution_price)
    replay = replay_episode(
        rounded_episode,
        item.candles,
        ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "paper-tick-rounded-v1"),
    )
    # Preserve original policy identity and original canonical market truth in
    # the paper evidence while retaining #224-computed replay measurements.
    original_fingerprint = policy_fingerprint(policy)
    outcome, target_available, invalidation_available, target_hit, invalidation_hit = _post_fill_outcome(
        episode=item.episode,
        replay=replay,
        candles=item.candles,
        context=item.outcome_context,
    )
    # Round-trip research cost: fee + slippage on entry and exit, expressed in percentage points.
    cost_pct = (
        Decimal("2") * costs.fee_bps_per_side
        + Decimal("2") * costs.slippage_bps_per_fill
    ) / Decimal("100")
    adjusted_mfe = (
        None
        if replay.max_favorable_excursion_pct is None
        else replay.max_favorable_excursion_pct - cost_pct
    )
    return PaperValidationRowV1(
        episode_id=item.episode.episode_id,
        symbol=item.episode.symbol,
        regime_state=_regime(item.episode.regime_state),
        policy_id=policy.policy_id,
        policy_version=policy.version,
        policy_fingerprint=original_fingerprint,
        canonical_level=item.episode.canonical_level,
        execution_price=replay.execution_price,
        filled=replay.filled,
        near_miss=(not replay.filled and replay.near_miss_distance_pct is not None),
        near_miss_distance_pct=replay.near_miss_distance_pct,
        execution_price_degradation_pct=_price_degradation_pct(item.episode, replay.execution_price),
        max_favorable_excursion_pct=replay.max_favorable_excursion_pct,
        max_adverse_excursion_pct=replay.max_adverse_excursion_pct,
        time_to_fill_seconds=replay.time_to_fill_seconds,
        invalidated_before_fill=replay.invalidated_before_fill,
        same_candle_fill_invalidation_ambiguous=replay.same_candle_fill_invalidation_ambiguous,
        post_fill_outcome=outcome,
        post_fill_target_available=target_available,
        post_fill_invalidation_available=invalidation_available,
        post_fill_target_hit=target_hit,
        post_fill_invalidation_hit=invalidation_hit,
        fee_slippage_cost_pct=cost_pct,
        fee_slippage_adjusted_mfe_proxy_pct=adjusted_mfe,
    )


def _avg(values: Sequence[Decimal]) -> Decimal | None:
    return None if not values else sum(values, Decimal("0")) / Decimal(len(values))


def _rate(count: int, total: int) -> Decimal | None:
    return None if total == 0 else Decimal(count) / Decimal(total) * Decimal("100")


def _summary(rows: Sequence[PaperValidationRowV1], threshold: int) -> dict[str, Any]:
    filled = [row for row in rows if row.filled]
    near = [row for row in rows if row.near_miss]
    target_eligible = [row for row in filled if row.post_fill_target_available]
    invalidation_eligible = [row for row in filled if row.post_fill_invalidation_available]
    target_hits = [row for row in target_eligible if row.post_fill_target_hit is True]
    invalidation_hits = [row for row in invalidation_eligible if row.post_fill_invalidation_hit is True]
    outcome_ambiguous = [row for row in filled if row.post_fill_outcome == OUTCOME_AMBIGUOUS]
    return {
        "sample_count": len(rows),
        "min_sample_threshold": threshold,
        "confidence_state": CONFIDENCE_SUFFICIENT if len(rows) >= threshold else CONFIDENCE_INSUFFICIENT,
        "fill_rate_pct": _rate(len(filled), len(rows)),
        "near_miss_rate_pct": _rate(len(near), len(rows)),
        "avg_execution_price_degradation_pct": _avg([row.execution_price_degradation_pct for row in rows]),
        "avg_mfe_pct": _avg([row.max_favorable_excursion_pct for row in filled if row.max_favorable_excursion_pct is not None]),
        "avg_mae_pct": _avg([row.max_adverse_excursion_pct for row in filled if row.max_adverse_excursion_pct is not None]),
        "avg_time_to_fill_seconds": _avg([Decimal(row.time_to_fill_seconds) for row in filled if row.time_to_fill_seconds is not None]),
        "invalidated_before_fill_rate_pct": _rate(sum(row.invalidated_before_fill for row in rows), len(rows)),
        "same_candle_fill_invalidation_ambiguity_rate_pct": _rate(sum(row.same_candle_fill_invalidation_ambiguous for row in rows), len(rows)),
        "post_fill_target_eligible_count": len(target_eligible),
        "post_fill_target_hit_rate_pct": _rate(len(target_hits), len(target_eligible)),
        "post_fill_invalidation_eligible_count": len(invalidation_eligible),
        "post_fill_invalidation_hit_rate_pct": _rate(len(invalidation_hits), len(invalidation_eligible)),
        "post_fill_outcome_ambiguity_rate_pct": _rate(len(outcome_ambiguous), len(filled)),
        "avg_fee_slippage_adjusted_mfe_proxy_pct": _avg([
            row.fee_slippage_adjusted_mfe_proxy_pct
            for row in filled
            if row.fee_slippage_adjusted_mfe_proxy_pct is not None
        ]),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "__dict__"):
        return _json_safe(value.__dict__)
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def build_paper_validation_report(
    inputs: Iterable[PaperValidationInputV1],
    policies: Sequence[ExecutionOffsetPolicyV1],
    *,
    costs: PaperCostAssumptionsV1,
    min_sample_threshold: int = 30,
) -> dict[str, Any]:
    _validate_costs(costs)
    _validate_threshold(min_sample_threshold)
    _validate_policy_set(policies)
    items = sorted(list(inputs), key=lambda item: item.episode.episode_id)
    if not items:
        raise ExecutionOffsetValidationError("NO_VALIDATION_INPUTS")
    ids = [item.episode.episode_id for item in items]
    if len(ids) != len(set(ids)):
        raise ExecutionOffsetValidationError("DUPLICATE_EPISODE_IDENTITY")

    policy_order = sorted(policies, key=policy_fingerprint)
    # Batch semantics are deliberately fail-fast: one non-actionable preview
    # means the requested comparison cohort is not homogeneous/fully usable.
    # Callers must fix or explicitly split the cohort; this function never
    # silently excludes an episode and changes denominators.
    rows = [
        _paper_row(item=item, policy=policy, costs=costs)
        for item in items
        for policy in policy_order
    ]
    rows.sort(key=lambda row: (row.policy_fingerprint, row.episode_id))

    overall: list[dict[str, Any]] = []
    by_policy: dict[str, list[PaperValidationRowV1]] = {}
    for row in rows:
        by_policy.setdefault(row.policy_fingerprint, []).append(row)
    for fingerprint in sorted(by_policy):
        group = by_policy[fingerprint]
        first = group[0]
        overall.append({
            "policy_id": first.policy_id,
            "policy_version": first.policy_version,
            "policy_fingerprint": fingerprint,
            **_summary(group, min_sample_threshold),
        })

    segments: dict[str, list[dict[str, Any]]] = {"symbol": [], "regime": []}
    for dimension in ("symbol", "regime"):
        values = sorted({row.symbol if dimension == "symbol" else row.regime_state for row in rows})
        for value in values:
            segment_rows = [row for row in rows if (row.symbol if dimension == "symbol" else row.regime_state) == value]
            for fingerprint in sorted({row.policy_fingerprint for row in segment_rows}):
                group = [row for row in segment_rows if row.policy_fingerprint == fingerprint]
                first = group[0]
                segments[dimension].append({
                    "segment_value": value,
                    "policy_id": first.policy_id,
                    "policy_version": first.policy_version,
                    "policy_fingerprint": fingerprint,
                    **_summary(group, min_sample_threshold),
                })

    report: dict[str, Any] = {
        "version": VERSION,
        "research_only": True,
        "account_awareness": False,
        "decision_permission": False,
        "execution_intent": False,
        "fee_bps_per_side": costs.fee_bps_per_side,
        "slippage_bps_per_fill": costs.slippage_bps_per_fill,
        "overall": overall,
        "segments": segments,
        "rows": rows,
    }
    report["report_fingerprint"] = hashlib.sha256(_canonical_json(report).encode("utf-8")).hexdigest()
    return report


def render_paper_validation_report_json(report: Mapping[str, Any]) -> str:
    return json.dumps(_json_safe(dict(report)), sort_keys=True, indent=2, ensure_ascii=True) + "\n"
