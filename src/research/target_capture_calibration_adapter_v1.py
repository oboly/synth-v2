from __future__ import annotations

"""Phase A adapter/audit for issue #559.

Pure, deterministic, market-only. No DB access, no wall-clock dependence,
no Fib geometry, no replay/policy logic.

Maps #555 (`historical_fib_map_episode_substrate_v1`) `EpisodeRecord`
target roles T1/T2 into #224 (`execution_offset_replay_v1`)
`ExecutionOffsetEpisodeV1` + `ReplayCandle` inputs, so #559 expected-return
calibration can reuse the #224 replay substrate against #555's historical
Fib/map targets without either module depending on the other's internals.

This module does not reimplement:

- Fib/map geometry, anchor selection, or target/invalidation projection
  (owned by `src.market_data.canonical_fib_zone_map_v1.build_row`, consumed
  here only via #555's already-built `EpisodeFeaturePayload`)
- execution-offset replay/policy semantics (owned by
  `src.research.execution_offset_replay_v1`)

It adds only:

- a deterministic target-episode identity per (source map, target role)
- role -> canonical Fib level id / side mapping
- a deterministic `valid_until_ts_utc` derived from #555's own forward-scan
  terminal evidence (`EpisodeOutcomeLabels.terminal_ts_utc`)
- the #224 full-interval PIT candle filter, applied to #555's
  `HistoricalCandle` input so the caller does not have to duplicate it
- a minimal, schema-free analysis context (`TargetEpisodeAnalysisContextV1`)
  carrying #555 `reference_price` / `direction` forward for #559's later
  expected-return economics, without adding fields to the #224 episode
  contract

Scope boundary (issue #559 Phase A):
- This module owns the #555 -> #224 adapter/audit slice only.
- It does not compute expected-return quantiles, candidate-buffer
  calibration, or recommendations (later #559 phases).
- It does not touch the DB, a runner, runtime, selection_engine,
  decision_gate, execution_planner, executor, or broker.

Safety markers:
research_only=1 market_only=1 account_awareness=0 decision_permission=0
execution_intent=0 broker_calls=0 broker_writes=0 orders=0 db_writes=0
production_profile_writes=0 runtime_activation=0
"""

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from src.market_data.fib_navigation_map_v1 import DIRECTION_BEARISH, DIRECTION_BULLISH
from src.research.execution_offset_replay_v1 import (
    ExecutionOffsetEpisodeV1,
    ReplayCandle,
    SIDE_BUY,
    SIDE_SELL,
)
from src.research.historical_fib_map_episode_substrate_v1 import (
    EpisodeFeaturePayload,
    EpisodeRecord,
    HistoricalCandle,
)

BUILDER_NAME = "target_capture_calibration_adapter_v1"
BUILDER_VERSION = "1.0.0"

TARGET_ROLE_T1 = "T1"
TARGET_ROLE_T2 = "T2"
TARGET_ROLES = (TARGET_ROLE_T1, TARGET_ROLE_T2)

# Canonical Fib level identifiers for the two roles this adapter maps, per
# the existing #224 episode contract convention (see
# tests/test_execution_offset_replay_v1.py / test_execution_offset_replay_report_v1.py
# use of "F1.618"). These name the SAME extension levels #555's
# EpisodeFeaturePayload.target_t1 / target_t2 already carry
# (canonical_fib_zone_map_v1.build_row's "ext_1272" / "ext_1618"); this
# module does not recompute or re-derive them.
FIB_LEVEL_ID_T1 = "F1.272"
FIB_LEVEL_ID_T2 = "F1.618"

_FIB_LEVEL_ID_BY_ROLE = {
    TARGET_ROLE_T1: FIB_LEVEL_ID_T1,
    TARGET_ROLE_T2: FIB_LEVEL_ID_T2,
}

# Fib/exit-profile rule (AGENTS.md): a bullish map's targets sit above the
# current structure and are harvested by SELLING into them; a bearish map's
# targets sit below and are harvested by BUYING into them. This adapter
# treats target roles strictly as candidate exit metadata, never as order
# instructions -- see canonical_level / regime_state handling below.
_SIDE_BY_DIRECTION = {
    DIRECTION_BULLISH: SIDE_SELL,
    DIRECTION_BEARISH: SIDE_BUY,
}


class TargetCaptureAdapterError(ValueError):
    pass


@dataclass(frozen=True)
class TargetEpisodeAnalysisContextV1:
    """Minimal analysis context retained alongside a mapped #224 episode.

    Deliberately NOT merged into `ExecutionOffsetEpisodeV1` -- the #224
    episode schema is owned by issue #224 and is not modified here. This
    context carries only what #559's later expected-return economics needs
    that the #224 contract has no field for: the #555 reference price the
    target distance was measured from, and the #555 map direction.
    """

    episode_id: str
    source_map_id: str
    target_role: str
    reference_price: Decimal
    direction: str


def compute_target_episode_id(
    *,
    source_map_id: str,
    target_role: str,
    symbol: str,
    venue: str,
    fib_level_id: str,
) -> str:
    """Deterministic, unique episode_id per (source map, target role).

    Same construction discipline as #555's own `compute_episode_id`: a
    stable pipe-joined payload hashed with SHA-256. Distinct target roles
    for the same source map always produce distinct ids because
    `target_role` (and its resulting `fib_level_id`) is part of the payload.
    """
    if not source_map_id.strip():
        raise TargetCaptureAdapterError("SOURCE_MAP_ID_REQUIRED")
    if target_role not in TARGET_ROLES:
        raise TargetCaptureAdapterError("UNSUPPORTED_TARGET_ROLE")
    payload = "|".join(
        [
            BUILDER_NAME,
            BUILDER_VERSION,
            source_map_id,
            target_role,
            symbol,
            venue,
            fib_level_id,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolve_side(direction: str) -> str:
    try:
        return _SIDE_BY_DIRECTION[direction]
    except KeyError as exc:
        raise TargetCaptureAdapterError(f"UNSUPPORTED_DIRECTION:{direction}") from exc


def _resolve_canonical_level(feature: EpisodeFeaturePayload, target_role: str) -> Decimal:
    if target_role == TARGET_ROLE_T1:
        return feature.target_t1
    return feature.target_t2


def map_target_episode(
    record: EpisodeRecord,
    *,
    target_role: str,
) -> tuple[ExecutionOffsetEpisodeV1, TargetEpisodeAnalysisContextV1]:
    """Map one #555 `EpisodeRecord` target role to a #224 episode + context.

    Fails closed (`TargetCaptureAdapterError`) rather than silently
    excluding when the mapping cannot be resolved deterministically:

    - `VALIDITY_WINDOW_UNRESOLVED`: #555's own forward-scan produced no
      terminal evidence strictly after `map_creation_ts_utc`
      (`labels.terminal_ts_utc <= feature.map_creation_ts_utc`, which
      happens when the episode has zero forward candles). #224's
      `ExecutionOffsetEpisodeV1` requires `valid_until_ts_utc >
      issued_ts_utc`; this adapter never invents a validity window that
      #555's own lifecycle evidence does not support.
    - `UNSUPPORTED_DIRECTION`: `feature.direction` is neither
      `DIRECTION_BULLISH` nor `DIRECTION_BEARISH` (should not occur for a
      #555 record, which only ever emits those two, but this adapter does
      not assume it).

    `valid_until_ts_utc` is `labels.terminal_ts_utc` -- #555's own
    forward-scan terminal evidence (T2 reached, invalidation breached,
    same-candle ambiguity, or forward/source exhaustion; see
    `historical_fib_map_episode_substrate_v1.py`'s lifecycle-reason
    constants). This is deterministic and reuses #555's already-computed
    lifecycle boundary rather than inventing a new validity rule.

    `regime_state` is always `None`: #555's `map_state`/`map_confidence`
    describe Fib/map lifecycle and geometry quality, not market regime, and
    must not be reinterpreted as one (AGENTS.md instruction file ownership /
    state-model discipline). A genuine market-regime source may populate
    this field in a later phase; this adapter never fabricates one.
    """
    if target_role not in TARGET_ROLES:
        raise TargetCaptureAdapterError("UNSUPPORTED_TARGET_ROLE")

    feature = record.feature
    labels = record.labels

    if labels.episode_id != feature.episode_id:
        raise TargetCaptureAdapterError("SOURCE_EPISODE_IDENTITY_CONFLICT")
    if labels.terminal_ts_utc <= feature.map_creation_ts_utc:
        raise TargetCaptureAdapterError("VALIDITY_WINDOW_UNRESOLVED")

    side = _resolve_side(feature.direction)
    fib_level_id = _FIB_LEVEL_ID_BY_ROLE[target_role]
    canonical_level = _resolve_canonical_level(feature, target_role)

    episode_id = compute_target_episode_id(
        source_map_id=feature.episode_id,
        target_role=target_role,
        symbol=feature.symbol,
        venue=feature.venue,
        fib_level_id=fib_level_id,
    )

    atr_at_issue = feature.atr_value if feature.atr_value > 0 else None

    episode = ExecutionOffsetEpisodeV1(
        episode_id=episode_id,
        symbol=feature.symbol,
        venue=feature.venue,
        horizon=feature.source_timeframe,
        side=side,
        fib_level_id=fib_level_id,
        canonical_level=canonical_level,
        issued_ts_utc=feature.map_creation_ts_utc,
        valid_until_ts_utc=labels.terminal_ts_utc,
        invalidation_price=feature.invalidation_level,
        atr_at_issue=atr_at_issue,
        regime_state=None,
        source_map_id=feature.episode_id,
    )
    context = TargetEpisodeAnalysisContextV1(
        episode_id=episode_id,
        source_map_id=feature.episode_id,
        target_role=target_role,
        reference_price=feature.reference_price,
        direction=feature.direction,
    )
    return episode, context


@dataclass(frozen=True)
class TargetEpisodeExclusionV1:
    """Explicit, non-silent record of an unmappable (record, target_role)."""

    source_map_id: str
    target_role: str
    reason: str


def map_episode_records(
    records: Sequence[EpisodeRecord],
    *,
    target_roles: Sequence[str] = TARGET_ROLES,
) -> tuple[
    list[tuple[ExecutionOffsetEpisodeV1, TargetEpisodeAnalysisContextV1]],
    list[TargetEpisodeExclusionV1],
]:
    """Batch-map #555 records with deterministic, input-order-independent output.

    Every (record, target_role) pair either produces exactly one mapped entry
    or exactly one explicit exclusion. Duplicate source-map identities or
    duplicate/empty target-role requests fail closed before any mapping so a
    caller can never create duplicate target episode identities accidentally.
    """
    role_list = list(target_roles)
    if not role_list:
        raise TargetCaptureAdapterError("NO_TARGET_ROLES_SUPPLIED")
    if len(set(role_list)) != len(role_list):
        raise TargetCaptureAdapterError("DUPLICATE_TARGET_ROLE")
    unsupported = [role for role in role_list if role not in TARGET_ROLES]
    if unsupported:
        raise TargetCaptureAdapterError(f"UNSUPPORTED_TARGET_ROLE:{unsupported[0]}")

    record_list = list(records)
    source_ids = [record.feature.episode_id for record in record_list]
    if len(set(source_ids)) != len(source_ids):
        raise TargetCaptureAdapterError("DUPLICATE_SOURCE_MAP_ID")

    role_rank = {role: index for index, role in enumerate(TARGET_ROLES)}
    ordered_records = sorted(record_list, key=lambda record: record.feature.episode_id)
    ordered_roles = sorted(role_list, key=lambda role: role_rank[role])

    mapped: list[tuple[ExecutionOffsetEpisodeV1, TargetEpisodeAnalysisContextV1]] = []
    excluded: list[TargetEpisodeExclusionV1] = []
    for record in ordered_records:
        for role in ordered_roles:
            try:
                mapped.append(map_target_episode(record, target_role=role))
            except TargetCaptureAdapterError as exc:
                excluded.append(
                    TargetEpisodeExclusionV1(
                        source_map_id=record.feature.episode_id,
                        target_role=role,
                        reason=str(exc),
                    )
                )
    return mapped, excluded


def convert_forward_candles(
    candles: Sequence[HistoricalCandle],
    *,
    issued_ts_utc,
    valid_until_ts_utc,
) -> list[ReplayCandle]:
    """Convert #555 `HistoricalCandle`s to #224 `ReplayCandle`s, PIT-filtered.

    Applies the exact #224 full-interval PIT rule documented in
    `docs/research/execution_offset_replay_v1.md` and enforced by
    `execution_offset_replay_v1.replay_episode`'s own forward-candle filter:
    a candle's full interval must start at or after `issued_ts_utc` and
    close no later than `valid_until_ts_utc`. A candle that opens before
    issuance is excluded even if it closes later. This is a boundary
    filter, not Fib/replay geometry, so mirroring it here (rather than
    passing every candle through and relying solely on `replay_episode`'s
    internal filter) lets a caller inspect exactly which candles this
    adapter considered in-window before replay ever runs.

    Candles are returned in ascending `close_ts_utc` order; `replay_episode`
    re-sorts and re-validates its own input independently, so this
    function's ordering is a determinism/audit convenience, not a
    correctness dependency.
    """
    if valid_until_ts_utc <= issued_ts_utc:
        raise TargetCaptureAdapterError("INVALID_VALIDITY_WINDOW")

    in_window = [
        c
        for c in candles
        if issued_ts_utc <= c.open_ts_utc and c.close_ts_utc <= valid_until_ts_utc
    ]
    in_window.sort(key=lambda c: c.close_ts_utc)
    return [
        ReplayCandle(
            open_ts_utc=c.open_ts_utc,
            close_ts_utc=c.close_ts_utc,
            high_price=c.high_price,
            low_price=c.low_price,
            close_price=c.close_price,
        )
        for c in in_window
    ]
