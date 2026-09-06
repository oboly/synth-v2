from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.research.execution_offset_replay_v1 import (
    ExecutionOffsetEpisodeV1,
    ExecutionOffsetPolicyV1,
    ExecutionOffsetReplayRowV1,
    POLICY_EXACT_LEVEL,
    POLICY_STATIC_BUFFER,
    POLICY_VOLATILITY_SCALED_BUFFER,
    ReplayCandle,
    SIDE_SELL,
)
from src.research.execution_offset_replay_report_v1 import (
    CONFIDENCE_INSUFFICIENT,
    CONFIDENCE_SUFFICIENT,
    DATASET_SCHEMA_VERSION,
    ExecutionOffsetReportError,
    UNKNOWN_REGIME_KEY,
    build_replay_dataset,
    build_report,
    export_dataset,
    render_report_json,
    summarize_baseline,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def make_episode(
    episode_id: str,
    symbol: str,
    regime: str | None,
    level: str = "100",
) -> ExecutionOffsetEpisodeV1:
    return ExecutionOffsetEpisodeV1(
        episode_id=episode_id,
        symbol=symbol,
        venue="bitvavo",
        horizon="4h",
        side=SIDE_SELL,
        fib_level_id="F1.618",
        canonical_level=Decimal(level),
        issued_ts_utc=T0,
        valid_until_ts_utc=T0 + timedelta(hours=4),
        invalidation_price=Decimal("110"),
        atr_at_issue=Decimal("4"),
        regime_state=regime,
        source_map_id=f"map-{episode_id}",
    )


def make_candles() -> list[ReplayCandle]:
    return [
        ReplayCandle(
            T0,
            T0 + timedelta(hours=1),
            Decimal("101"),
            Decimal("99"),
            Decimal("100"),
        ),
        ReplayCandle(
            T0 + timedelta(hours=1),
            T0 + timedelta(hours=2),
            Decimal("100"),
            Decimal("97"),
            Decimal("98"),
        ),
    ]


EXACT = ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1")
STATIC = ExecutionOffsetPolicyV1(
    POLICY_STATIC_BUFFER,
    "v1",
    buffer_pct=Decimal("0.01"),
)
VOLATILITY = ExecutionOffsetPolicyV1(
    POLICY_VOLATILITY_SCALED_BUFFER,
    "v1",
    atr_multiple=Decimal("0.25"),
)


def fixture_inputs():
    episodes = [
        make_episode("ep-1", "PROM", "RANGE"),
        make_episode("ep-2", "BTC", "TREND"),
        make_episode("ep-3", "PROM", "RANGE"),
    ]
    candles = {episode.episode_id: make_candles() for episode in episodes}
    policies = [EXACT, STATIC, VOLATILITY]
    return episodes, candles, policies


def episode_map(episodes: list[ExecutionOffsetEpisodeV1]):
    return {episode.episode_id: episode for episode in episodes}


def test_report_is_byte_deterministic_regardless_of_input_iteration_order() -> None:
    episodes, candles, policies = fixture_inputs()
    forward = render_report_json(build_report(episodes, candles, policies))
    backward = render_report_json(
        build_report(list(reversed(episodes)), candles, list(reversed(policies)))
    )
    assert forward == backward


def test_export_is_self_contained_and_decimal_safe() -> None:
    episodes, candles, policies = fixture_inputs()
    rows = build_replay_dataset(episodes, candles, policies)
    exported = export_dataset(rows, episode_map(episodes))

    assert exported["schema_version"] == DATASET_SCHEMA_VERSION
    assert exported["row_count"] == len(episodes) * len(policies)
    assert len(exported["dataset_fingerprint"]) == 64

    first = exported["rows"][0]
    assert set(first) == {"episode", "replay"}
    assert first["episode"]["symbol"] in {"BTC", "PROM"}
    assert first["episode"]["venue"] == "bitvavo"
    assert first["episode"]["horizon"] == "4h"
    assert first["episode"]["fib_level_id"] == "F1.618"
    assert first["episode"]["source_map_id"].startswith("map-ep-")
    assert first["episode"]["issued_ts_utc"] == "2026-01-01T00:00:00+00:00"
    assert first["episode"]["canonical_level"] == "100"
    assert isinstance(first["episode"]["atr_at_issue"], str)
    assert isinstance(first["replay"]["execution_price"], str)


def test_dataset_fingerprint_changes_when_episode_provenance_changes() -> None:
    episodes, candles, policies = fixture_inputs()
    rows = build_replay_dataset(episodes, candles, [EXACT])
    original = export_dataset(rows, episode_map(episodes))["dataset_fingerprint"]

    changed = [replace(episodes[0], regime_state="BREAKOUT"), *episodes[1:]]
    revised = export_dataset(rows, episode_map(changed))["dataset_fingerprint"]
    assert revised != original


def test_canonical_level_is_not_mutated() -> None:
    episodes, candles, policies = fixture_inputs()
    original_levels = [episode.canonical_level for episode in episodes]
    rows = build_replay_dataset(episodes, candles, policies)

    assert [episode.canonical_level for episode in episodes] == original_levels
    assert all(row.canonical_level == Decimal("100") for row in rows)


def test_baseline_has_overall_policy_symbol_and_regime_segments() -> None:
    episodes, candles, policies = fixture_inputs()
    rows = build_replay_dataset(episodes, candles, policies)
    summary = summarize_baseline(rows, episode_map(episodes), min_sample_threshold=1)

    assert summary["overall"]["sample_count"] == len(rows)
    assert {segment["policy_id"] for segment in summary["policy"]} == {
        POLICY_EXACT_LEVEL,
        POLICY_STATIC_BUFFER,
        POLICY_VOLATILITY_SCALED_BUFFER,
    }
    assert {segment["symbol"] for segment in summary["policy_symbol"]} == {
        "PROM",
        "BTC",
    }
    assert {segment["regime_state"] for segment in summary["policy_regime"]} == {
        "RANGE",
        "TREND",
    }


def test_unknown_regime_is_explicit() -> None:
    episodes = [make_episode("ep-1", "PROM", None)]
    rows = build_replay_dataset(episodes, {"ep-1": make_candles()}, [EXACT])
    summary = summarize_baseline(rows, episode_map(episodes), min_sample_threshold=1)
    assert summary["policy_regime"][0]["regime_state"] == UNKNOWN_REGIME_KEY


def test_min_sample_threshold_controls_confidence_state() -> None:
    episodes, candles, _policies = fixture_inputs()
    rows = build_replay_dataset(episodes, candles, [EXACT])

    below = summarize_baseline(
        rows,
        episode_map(episodes),
        min_sample_threshold=len(rows) + 1,
    )
    at = summarize_baseline(
        rows,
        episode_map(episodes),
        min_sample_threshold=len(rows),
    )
    assert below["overall"]["confidence_state"] == CONFIDENCE_INSUFFICIENT
    assert at["overall"]["confidence_state"] == CONFIDENCE_SUFFICIENT


@pytest.mark.parametrize("threshold", [0, -1, False, 0.5, Decimal("1.5"), "30", None])
def test_invalid_min_sample_threshold_fails_closed(threshold: object) -> None:
    episodes, candles, _policies = fixture_inputs()
    rows = build_replay_dataset(episodes, candles, [EXACT])
    with pytest.raises(ExecutionOffsetReportError, match="INVALID_MIN_SAMPLE_THRESHOLD"):
        summarize_baseline(rows, episode_map(episodes), min_sample_threshold=threshold)


def test_duplicate_episode_identity_fails_closed() -> None:
    episode = make_episode("ep-1", "PROM", "RANGE")
    with pytest.raises(ExecutionOffsetReportError, match="DUPLICATE_EPISODE_IDENTITY"):
        build_replay_dataset(
            [episode, episode],
            {"ep-1": make_candles()},
            [EXACT],
        )


def test_duplicate_policy_fingerprint_fails_closed() -> None:
    episode = make_episode("ep-1", "PROM", "RANGE")
    with pytest.raises(ExecutionOffsetReportError, match="DUPLICATE_POLICY_FINGERPRINT"):
        build_replay_dataset(
            [episode],
            {"ep-1": make_candles()},
            [EXACT, EXACT],
        )


def test_missing_candles_for_episode_fails_closed() -> None:
    episode = make_episode("ep-1", "PROM", "RANGE")
    with pytest.raises(ExecutionOffsetReportError, match="MISSING_CANDLES_FOR_EPISODE"):
        build_replay_dataset([episode], {}, [EXACT])


def test_no_episodes_fails_closed() -> None:
    with pytest.raises(ExecutionOffsetReportError, match="NO_EPISODES_SUPPLIED"):
        build_replay_dataset([], {}, [EXACT])


def test_no_policies_fails_closed() -> None:
    episode = make_episode("ep-1", "PROM", "RANGE")
    with pytest.raises(ExecutionOffsetReportError, match="NO_POLICIES_SUPPLIED"):
        build_replay_dataset([episode], {"ep-1": make_candles()}, [])


def test_export_fails_closed_on_missing_episode_for_row() -> None:
    episodes, candles, _policies = fixture_inputs()
    rows = build_replay_dataset(episodes, candles, [EXACT])
    with pytest.raises(ExecutionOffsetReportError, match="MISSING_EPISODE_FOR_ROW"):
        export_dataset(rows, {})


def test_export_fails_closed_on_canonical_level_conflict() -> None:
    episodes, candles, _policies = fixture_inputs()
    rows = build_replay_dataset(episodes, candles, [EXACT])
    conflicting = dict(episode_map(episodes))
    conflicting["ep-1"] = replace(episodes[0], canonical_level=Decimal("101"))
    with pytest.raises(ExecutionOffsetReportError, match="CANONICAL_LEVEL_CONFLICT"):
        export_dataset(rows, conflicting)


def test_export_rejects_duplicate_row_identity() -> None:
    episodes, candles, _policies = fixture_inputs()
    rows = build_replay_dataset(episodes, candles, [EXACT])
    duplicate: list[ExecutionOffsetReplayRowV1] = [rows[0], rows[0]]
    with pytest.raises(ExecutionOffsetReportError, match="DUPLICATE_ROW_IDENTITY"):
        export_dataset(duplicate, episode_map(episodes))
