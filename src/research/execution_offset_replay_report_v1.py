from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Iterable, Mapping

from src.research.execution_offset_replay_v1 import (
    ExecutionOffsetEpisodeV1,
    ExecutionOffsetPolicyV1,
    ExecutionOffsetReplayRowV1,
    ReplayCandle,
    policy_fingerprint,
    replay_episode,
)

VERSION: Final[str] = "execution_offset_replay_report_v1"
DATASET_SCHEMA_VERSION: Final[str] = "execution_offset_replay_dataset_v1"
MIN_SAMPLE_THRESHOLD: Final[int] = 30
CONFIDENCE_SUFFICIENT: Final[str] = "SUFFICIENT_SAMPLE"
CONFIDENCE_INSUFFICIENT: Final[str] = "INSUFFICIENT_SAMPLE"
UNKNOWN_REGIME_KEY: Final[str] = "UNKNOWN_REGIME"
SEGMENT_OVERALL: Final[str] = "OVERALL"
SEGMENT_POLICY: Final[str] = "POLICY"
SEGMENT_POLICY_SYMBOL: Final[str] = "POLICY_SYMBOL"
SEGMENT_POLICY_REGIME: Final[str] = "POLICY_REGIME"


class ExecutionOffsetReportError(ValueError):
    pass


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _json_safe(val)
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        _json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _row_identity(row: ExecutionOffsetReplayRowV1) -> tuple[str, str]:
    return (row.episode_id, row.policy_fingerprint)


def _ordered_rows(
    rows: Iterable[ExecutionOffsetReplayRowV1],
) -> list[ExecutionOffsetReplayRowV1]:
    ordered = sorted(rows, key=_row_identity)
    identities = [_row_identity(row) for row in ordered]
    if len(set(identities)) != len(identities):
        raise ExecutionOffsetReportError("DUPLICATE_ROW_IDENTITY")
    return ordered


def _episode_for_row(
    row: ExecutionOffsetReplayRowV1,
    episodes_by_id: Mapping[str, ExecutionOffsetEpisodeV1],
) -> ExecutionOffsetEpisodeV1:
    episode = episodes_by_id.get(row.episode_id)
    if episode is None:
        raise ExecutionOffsetReportError("MISSING_EPISODE_FOR_ROW")
    if episode.episode_id != row.episode_id:
        raise ExecutionOffsetReportError("EPISODE_IDENTITY_CONFLICT")
    if episode.canonical_level != row.canonical_level:
        raise ExecutionOffsetReportError("CANONICAL_LEVEL_CONFLICT")
    return episode


def serialize_dataset_row(
    row: ExecutionOffsetReplayRowV1,
    episode: ExecutionOffsetEpisodeV1,
) -> dict[str, Any]:
    if row.episode_id != episode.episode_id:
        raise ExecutionOffsetReportError("EPISODE_IDENTITY_CONFLICT")
    if row.canonical_level != episode.canonical_level:
        raise ExecutionOffsetReportError("CANONICAL_LEVEL_CONFLICT")
    return _json_safe(
        {
            "episode": dataclasses.asdict(episode),
            "replay": dataclasses.asdict(row),
        }
    )


def _serialized_dataset_rows(
    rows: Iterable[ExecutionOffsetReplayRowV1],
    episodes_by_id: Mapping[str, ExecutionOffsetEpisodeV1],
) -> list[dict[str, Any]]:
    return [
        serialize_dataset_row(row, _episode_for_row(row, episodes_by_id))
        for row in _ordered_rows(rows)
    ]


def dataset_fingerprint(
    rows: Iterable[ExecutionOffsetReplayRowV1],
    episodes_by_id: Mapping[str, ExecutionOffsetEpisodeV1],
) -> str:
    serialized = _serialized_dataset_rows(rows, episodes_by_id)
    return hashlib.sha256(_canonical_json(serialized).encode("utf-8")).hexdigest()


def build_replay_dataset(
    episodes: Iterable[ExecutionOffsetEpisodeV1],
    candles_by_episode_id: Mapping[str, Iterable[ReplayCandle]],
    policies: Iterable[ExecutionOffsetPolicyV1],
) -> list[ExecutionOffsetReplayRowV1]:
    episode_list = list(episodes)
    policy_list = list(policies)

    if not episode_list:
        raise ExecutionOffsetReportError("NO_EPISODES_SUPPLIED")
    if not policy_list:
        raise ExecutionOffsetReportError("NO_POLICIES_SUPPLIED")

    seen_episode_ids: set[str] = set()
    for episode in episode_list:
        if episode.episode_id in seen_episode_ids:
            raise ExecutionOffsetReportError("DUPLICATE_EPISODE_IDENTITY")
        seen_episode_ids.add(episode.episode_id)

    seen_policy_fingerprints: set[str] = set()
    fingerprinted_policies: list[ExecutionOffsetPolicyV1] = []
    for policy in policy_list:
        fingerprint = policy_fingerprint(policy)
        if fingerprint in seen_policy_fingerprints:
            raise ExecutionOffsetReportError("DUPLICATE_POLICY_FINGERPRINT")
        seen_policy_fingerprints.add(fingerprint)
        fingerprinted_policies.append(policy)

    rows: list[ExecutionOffsetReplayRowV1] = []
    for episode in episode_list:
        if episode.episode_id not in candles_by_episode_id:
            raise ExecutionOffsetReportError("MISSING_CANDLES_FOR_EPISODE")
        candles = list(candles_by_episode_id[episode.episode_id])
        for policy in fingerprinted_policies:
            rows.append(replay_episode(episode, candles, policy))

    return _ordered_rows(rows)


def export_dataset(
    rows: Iterable[ExecutionOffsetReplayRowV1],
    episodes_by_id: Mapping[str, ExecutionOffsetEpisodeV1],
) -> dict[str, Any]:
    serialized_rows = _serialized_dataset_rows(rows, episodes_by_id)
    return {
        "schema_version": DATASET_SCHEMA_VERSION,
        "row_count": len(serialized_rows),
        "dataset_fingerprint": hashlib.sha256(
            _canonical_json(serialized_rows).encode("utf-8")
        ).hexdigest(),
        "rows": serialized_rows,
    }


def _decimal_avg(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def _rate_pct(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return Decimal(numerator) / Decimal(denominator) * Decimal("100")


def _validate_min_sample_threshold(min_sample_threshold: int) -> None:
    if isinstance(min_sample_threshold, bool) or min_sample_threshold <= 0:
        raise ExecutionOffsetReportError("INVALID_MIN_SAMPLE_THRESHOLD")


def _summarize_rows(
    rows: list[ExecutionOffsetReplayRowV1],
    min_sample_threshold: int,
) -> dict[str, Any]:
    sample_count = len(rows)
    confidence_state = (
        CONFIDENCE_SUFFICIENT
        if sample_count >= min_sample_threshold
        else CONFIDENCE_INSUFFICIENT
    )
    filled_count = sum(1 for row in rows if row.filled)
    touched_count = sum(1 for row in rows if row.touched)
    canonical_touched_count = sum(1 for row in rows if row.canonical_level_touched)
    invalidated_count = sum(1 for row in rows if row.invalidated_before_fill)
    ambiguous_count = sum(
        1 for row in rows if row.same_candle_fill_invalidation_ambiguous
    )

    near_miss_values = [
        row.near_miss_distance_pct
        for row in rows
        if row.near_miss_distance_pct is not None
    ]
    fill_time_values = [
        Decimal(row.time_to_fill_seconds)
        for row in rows
        if row.time_to_fill_seconds is not None
    ]
    mfe_values = [
        row.max_favorable_excursion_pct
        for row in rows
        if row.max_favorable_excursion_pct is not None
    ]
    mae_values = [
        row.max_adverse_excursion_pct
        for row in rows
        if row.max_adverse_excursion_pct is not None
    ]

    return {
        "sample_count": sample_count,
        "min_sample_threshold": min_sample_threshold,
        "confidence_state": confidence_state,
        "fill_rate_pct": _rate_pct(filled_count, sample_count),
        "touched_rate_pct": _rate_pct(touched_count, sample_count),
        "canonical_level_touched_rate_pct": _rate_pct(
            canonical_touched_count, sample_count
        ),
        "invalidated_before_fill_rate_pct": _rate_pct(
            invalidated_count, sample_count
        ),
        "ambiguous_rate_pct": _rate_pct(ambiguous_count, sample_count),
        "avg_near_miss_distance_pct": _decimal_avg(near_miss_values),
        "avg_time_to_fill_seconds": _decimal_avg(fill_time_values),
        "avg_max_favorable_excursion_pct": _decimal_avg(mfe_values),
        "avg_max_adverse_excursion_pct": _decimal_avg(mae_values),
    }


def summarize_baseline(
    rows: Iterable[ExecutionOffsetReplayRowV1],
    episodes_by_id: Mapping[str, ExecutionOffsetEpisodeV1],
    min_sample_threshold: int = MIN_SAMPLE_THRESHOLD,
) -> dict[str, Any]:
    _validate_min_sample_threshold(min_sample_threshold)
    ordered = _ordered_rows(rows)
    for row in ordered:
        _episode_for_row(row, episodes_by_id)

    overall = _summarize_rows(ordered, min_sample_threshold)

    by_policy: dict[str, list[ExecutionOffsetReplayRowV1]] = {}
    for row in ordered:
        by_policy.setdefault(row.policy_fingerprint, []).append(row)

    policy_segments: list[dict[str, Any]] = []
    policy_symbol_segments: list[dict[str, Any]] = []
    policy_regime_segments: list[dict[str, Any]] = []

    for fingerprint in sorted(by_policy):
        policy_rows = by_policy[fingerprint]
        sample_row = policy_rows[0]
        policy_segments.append(
            {
                "segment_type": SEGMENT_POLICY,
                "policy_id": sample_row.policy_id,
                "policy_version": sample_row.policy_version,
                "policy_fingerprint": fingerprint,
                "policy_buffer_pct": sample_row.policy_buffer_pct,
                "policy_atr_multiple": sample_row.policy_atr_multiple,
                **_summarize_rows(policy_rows, min_sample_threshold),
            }
        )

        by_symbol: dict[str, list[ExecutionOffsetReplayRowV1]] = {}
        by_regime: dict[str, list[ExecutionOffsetReplayRowV1]] = {}
        for row in policy_rows:
            episode = _episode_for_row(row, episodes_by_id)
            by_symbol.setdefault(episode.symbol, []).append(row)
            regime_key = episode.regime_state or UNKNOWN_REGIME_KEY
            by_regime.setdefault(regime_key, []).append(row)

        for symbol in sorted(by_symbol):
            policy_symbol_segments.append(
                {
                    "segment_type": SEGMENT_POLICY_SYMBOL,
                    "policy_id": sample_row.policy_id,
                    "policy_version": sample_row.policy_version,
                    "policy_fingerprint": fingerprint,
                    "symbol": symbol,
                    **_summarize_rows(by_symbol[symbol], min_sample_threshold),
                }
            )

        for regime_key in sorted(by_regime):
            policy_regime_segments.append(
                {
                    "segment_type": SEGMENT_POLICY_REGIME,
                    "policy_id": sample_row.policy_id,
                    "policy_version": sample_row.policy_version,
                    "policy_fingerprint": fingerprint,
                    "regime_state": regime_key,
                    **_summarize_rows(by_regime[regime_key], min_sample_threshold),
                }
            )

    return {
        "version": VERSION,
        "min_sample_threshold": min_sample_threshold,
        "overall": {"segment_type": SEGMENT_OVERALL, **overall},
        "policy": policy_segments,
        "policy_symbol": policy_symbol_segments,
        "policy_regime": policy_regime_segments,
    }


def build_report(
    episodes: Iterable[ExecutionOffsetEpisodeV1],
    candles_by_episode_id: Mapping[str, Iterable[ReplayCandle]],
    policies: Iterable[ExecutionOffsetPolicyV1],
    min_sample_threshold: int = MIN_SAMPLE_THRESHOLD,
) -> dict[str, Any]:
    _validate_min_sample_threshold(min_sample_threshold)
    episode_list = list(episodes)
    episodes_by_id = {episode.episode_id: episode for episode in episode_list}
    rows = build_replay_dataset(episode_list, candles_by_episode_id, policies)
    return {
        "version": VERSION,
        "dataset": export_dataset(rows, episodes_by_id),
        "baseline_summary": summarize_baseline(
            rows, episodes_by_id, min_sample_threshold
        ),
    }


def render_report_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    ) + "\n"
