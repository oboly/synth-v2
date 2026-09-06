from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.market_data.fib_navigation_map_v1 import DIRECTION_BEARISH, DIRECTION_BULLISH
from src.research.execution_offset_replay_v1 import (
    ExecutionOffsetPolicyV1,
    POLICY_EXACT_LEVEL,
    POLICY_STATIC_BUFFER,
    SIDE_BUY,
    SIDE_SELL,
    replay_episode,
)
from src.research.historical_fib_map_episode_substrate_v1 import (
    EpisodeFeaturePayload,
    EpisodeOutcomeLabels,
    EpisodeRecord,
    HistoricalCandle,
)
from src.research.target_capture_calibration_adapter_v1 import (
    FIB_LEVEL_ID_T1,
    FIB_LEVEL_ID_T2,
    TARGET_ROLE_T1,
    TARGET_ROLE_T2,
    TargetCaptureAdapterError,
    compute_target_episode_id,
    convert_forward_candles,
    map_episode_records,
    map_target_episode,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def make_feature(
    *,
    direction: str = DIRECTION_BULLISH,
    episode_id: str = "map-1",
    atr_value: Decimal = Decimal("2"),
) -> EpisodeFeaturePayload:
    return EpisodeFeaturePayload(
        episode_id=episode_id,
        symbol="PROM",
        venue="bitvavo",
        source_timeframe="4h",
        builder_name="historical_fib_map_episode_substrate_v1",
        builder_version="2.0.0",
        contract_version="1.1.0",
        projection_engine_module="src.market_data.canonical_fib_zone_map_v1",
        projection_engine_function="build_row",
        map_version="v1",
        map_creation_ts_utc=T0,
        source_candle_first_ts_utc=T0 - timedelta(hours=180 * 4),
        source_candle_last_ts_utc=T0,
        source_candle_count=180,
        direction=direction,
        anchor_low_price=Decimal("90"),
        anchor_low_ts_utc=T0 - timedelta(hours=40),
        anchor_high_price=Decimal("110"),
        anchor_high_ts_utc=T0 - timedelta(hours=4),
        anchor_span_candles=10,
        anchor_span_elapsed_seconds=36 * 3600,
        swing_amplitude_pct=Decimal("22.22"),
        reference_price=Decimal("100"),
        entry_zone_low=Decimal("98"),
        entry_zone_high=Decimal("102"),
        entry_zone_mid=Decimal("100"),
        target_t1=Decimal("112.72") if direction == DIRECTION_BULLISH else Decimal("87.28"),
        target_t2=Decimal("116.18") if direction == DIRECTION_BULLISH else Decimal("83.82"),
        target_extension=Decimal("120"),
        invalidation_level=Decimal("90") if direction == DIRECTION_BULLISH else Decimal("110"),
        atr_value=atr_value,
        atr_period=14,
        target_t1_distance_pct=Decimal("12.72"),
        target_t2_distance_pct=Decimal("16.18"),
        invalidation_distance_pct=Decimal("10"),
        target_t1_distance_atr=Decimal("6.36"),
        target_t2_distance_atr=Decimal("8.09"),
        invalidation_distance_atr=Decimal("5"),
        map_state="ACTIVE",
        map_confidence="HIGH",
        rebuild_trigger="NONE",
        canonical_provenance_payload={},
    )


def make_labels(
    *,
    episode_id: str = "map-1",
    terminal_ts_utc: datetime = T0 + timedelta(hours=8),
    reason: str = "TARGET2_REACHED",
    forward_candles_scanned: int = 2,
) -> EpisodeOutcomeLabels:
    return EpisodeOutcomeLabels(
        episode_id=episode_id,
        first_entry_ts_utc=None,
        time_to_first_entry_seconds=None,
        target1_ts_utc=T0 + timedelta(hours=4),
        time_to_target1_seconds=4 * 3600,
        target2_ts_utc=T0 + timedelta(hours=8) if reason == "TARGET2_REACHED" else None,
        time_to_target2_seconds=8 * 3600 if reason == "TARGET2_REACHED" else None,
        invalidation_ts_utc=None,
        time_to_invalidation_seconds=None,
        ambiguous_ts_utc=None,
        terminal_ts_utc=terminal_ts_utc,
        map_lifetime_seconds=(terminal_ts_utc - T0).total_seconds(),
        lifecycle_transition_reason=reason,
        num_source_candles_until_terminal=forward_candles_scanned,
        forward_candles_scanned=forward_candles_scanned,
    )


def make_record(**kwargs) -> EpisodeRecord:
    direction = kwargs.pop("direction", DIRECTION_BULLISH)
    terminal_ts_utc = kwargs.pop("terminal_ts_utc", T0 + timedelta(hours=8))
    atr_value = kwargs.pop("atr_value", Decimal("2"))
    episode_id = kwargs.pop("episode_id", "map-1")
    if kwargs:
        raise AssertionError(f"unused fixture kwargs: {sorted(kwargs)}")
    return EpisodeRecord(
        feature=make_feature(direction=direction, episode_id=episode_id, atr_value=atr_value),
        labels=make_labels(episode_id=episode_id, terminal_ts_utc=terminal_ts_utc),
    )


def candle(hours: int, low: str, high: str) -> HistoricalCandle:
    close_ts = T0 + timedelta(hours=hours)
    return HistoricalCandle(
        symbol="PROM",
        venue="bitvavo",
        interval_code="4h",
        open_ts_utc=close_ts - timedelta(hours=4),
        close_ts_utc=close_ts,
        open_price=Decimal("100"),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal("100"),
    )


# ---------------------------------------------------------------------------
# Bullish -> SELL, bearish -> BUY
# ---------------------------------------------------------------------------

def test_bullish_map_produces_sell_target_episodes() -> None:
    record = make_record(direction=DIRECTION_BULLISH)
    episode, context = map_target_episode(record, target_role=TARGET_ROLE_T1)
    assert episode.side == SIDE_SELL
    assert context.direction == DIRECTION_BULLISH


def test_bearish_map_produces_buy_target_episodes() -> None:
    record = make_record(direction=DIRECTION_BEARISH)
    episode, context = map_target_episode(record, target_role=TARGET_ROLE_T1)
    assert episode.side == SIDE_BUY
    assert context.direction == DIRECTION_BEARISH


# ---------------------------------------------------------------------------
# T1/T2 identity, provenance, canonical_level
# ---------------------------------------------------------------------------

def test_t1_t2_map_to_distinct_canonical_fib_levels() -> None:
    record = make_record()
    t1_episode, _ = map_target_episode(record, target_role=TARGET_ROLE_T1)
    t2_episode, _ = map_target_episode(record, target_role=TARGET_ROLE_T2)
    assert t1_episode.fib_level_id == FIB_LEVEL_ID_T1
    assert t2_episode.fib_level_id == FIB_LEVEL_ID_T2
    assert t1_episode.canonical_level == record.feature.target_t1
    assert t2_episode.canonical_level == record.feature.target_t2
    assert t1_episode.episode_id != t2_episode.episode_id


def test_source_map_id_preserved_from_feature_episode_id() -> None:
    record = make_record()
    episode, context = map_target_episode(record, target_role=TARGET_ROLE_T1)
    assert episode.source_map_id == record.feature.episode_id
    assert context.source_map_id == record.feature.episode_id


def test_target_episode_id_deterministic_and_unique_per_role() -> None:
    record = make_record()
    e1a, _ = map_target_episode(record, target_role=TARGET_ROLE_T1)
    e1b, _ = map_target_episode(record, target_role=TARGET_ROLE_T1)
    e2, _ = map_target_episode(record, target_role=TARGET_ROLE_T2)
    assert e1a.episode_id == e1b.episode_id
    assert e1a.episode_id != e2.episode_id
    assert e1a.episode_id == compute_target_episode_id(
        source_map_id=record.feature.episode_id,
        target_role=TARGET_ROLE_T1,
        symbol=record.feature.symbol,
        venue=record.feature.venue,
        fib_level_id=FIB_LEVEL_ID_T1,
    )


def test_invalidation_level_and_reference_context_preserved() -> None:
    record = make_record()
    episode, context = map_target_episode(record, target_role=TARGET_ROLE_T1)
    assert episode.invalidation_price == record.feature.invalidation_level
    assert context.reference_price == record.feature.reference_price


def test_issued_ts_is_map_creation_ts() -> None:
    record = make_record()
    episode, _ = map_target_episode(record, target_role=TARGET_ROLE_T1)
    assert episode.issued_ts_utc == record.feature.map_creation_ts_utc


def test_atr_zero_becomes_none() -> None:
    record = make_record(atr_value=Decimal("0"))
    episode, _ = map_target_episode(record, target_role=TARGET_ROLE_T1)
    assert episode.atr_at_issue is None


def test_atr_positive_is_preserved() -> None:
    record = make_record(atr_value=Decimal("3.5"))
    episode, _ = map_target_episode(record, target_role=TARGET_ROLE_T1)
    assert episode.atr_at_issue == Decimal("3.5")


# ---------------------------------------------------------------------------
# No map_state/map_confidence -> regime_state misuse
# ---------------------------------------------------------------------------

def test_regime_state_is_always_none_not_map_state_or_confidence() -> None:
    record = make_record()
    assert record.feature.map_state == "ACTIVE"
    assert record.feature.map_confidence == "HIGH"
    episode, _ = map_target_episode(record, target_role=TARGET_ROLE_T1)
    assert episode.regime_state is None


# ---------------------------------------------------------------------------
# Candle interval filtering (#224 full-interval PIT rule)
# ---------------------------------------------------------------------------

def test_convert_forward_candles_excludes_candle_opening_before_issuance() -> None:
    issued = T0
    valid_until = T0 + timedelta(hours=8)
    candles = [
        HistoricalCandle(
            symbol="PROM", venue="bitvavo", interval_code="4h",
            open_ts_utc=issued - timedelta(hours=1), close_ts_utc=issued + timedelta(hours=3),
            open_price=Decimal("100"), high_price=Decimal("101"), low_price=Decimal("99"), close_price=Decimal("100"),
        ),
        candle(4, "99", "101"),
        candle(8, "99", "101"),
    ]
    converted = convert_forward_candles(candles, issued_ts_utc=issued, valid_until_ts_utc=valid_until)
    assert [c.close_ts_utc for c in converted] == [T0 + timedelta(hours=4), T0 + timedelta(hours=8)]


def test_convert_forward_candles_excludes_candle_closing_after_valid_until() -> None:
    issued = T0
    valid_until = T0 + timedelta(hours=8)
    candles = [candle(4, "99", "101"), candle(12, "99", "101")]
    converted = convert_forward_candles(candles, issued_ts_utc=issued, valid_until_ts_utc=valid_until)
    assert [c.close_ts_utc for c in converted] == [T0 + timedelta(hours=4)]


def test_convert_forward_candles_deterministic_order_independent_of_input_order() -> None:
    issued = T0
    valid_until = T0 + timedelta(hours=12)
    candles = [candle(8, "99", "101"), candle(4, "99", "101")]
    converted = convert_forward_candles(candles, issued_ts_utc=issued, valid_until_ts_utc=valid_until)
    assert [c.close_ts_utc for c in converted] == [T0 + timedelta(hours=4), T0 + timedelta(hours=8)]


def test_convert_forward_candles_rejects_non_positive_window() -> None:
    with pytest.raises(TargetCaptureAdapterError):
        convert_forward_candles([], issued_ts_utc=T0, valid_until_ts_utc=T0)


# ---------------------------------------------------------------------------
# Exclusion / fail-closed behavior
# ---------------------------------------------------------------------------

def test_zero_forward_candles_raises_validity_window_unresolved() -> None:
    record = make_record(terminal_ts_utc=T0)  # no forward evidence: terminal == issuance
    with pytest.raises(TargetCaptureAdapterError):
        map_target_episode(record, target_role=TARGET_ROLE_T1)


def test_batch_mapping_explicitly_excludes_unmappable_pairs_never_silently_drops() -> None:
    good = make_record()
    bad = make_record(terminal_ts_utc=T0, episode_id="map-2")
    mapped, excluded = map_episode_records([good, bad])
    assert len(mapped) == 2  # good record x (T1, T2)
    assert len(excluded) == 2  # bad record x (T1, T2), each explicitly recorded
    assert {e.source_map_id for e in excluded} == {"map-2"}
    assert all(e.reason == "VALIDITY_WINDOW_UNRESOLVED" for e in excluded)
    total_pairs = (len([good, bad])) * 2
    assert len(mapped) + len(excluded) == total_pairs


def test_unsupported_target_role_fails_closed() -> None:
    record = make_record()
    with pytest.raises(TargetCaptureAdapterError):
        map_target_episode(record, target_role="T3")


def test_unsupported_direction_fails_closed() -> None:
    record = make_record()
    from dataclasses import replace

    bad_feature = replace(record.feature, direction="SIDEWAYS")
    bad_record = EpisodeRecord(feature=bad_feature, labels=record.labels)
    with pytest.raises(TargetCaptureAdapterError):
        map_target_episode(bad_record, target_role=TARGET_ROLE_T1)


def test_source_feature_and_labels_identity_must_match() -> None:
    from dataclasses import replace

    record = make_record(episode_id="map-1")
    bad = EpisodeRecord(feature=record.feature, labels=replace(record.labels, episode_id="map-2"))
    with pytest.raises(TargetCaptureAdapterError, match="SOURCE_EPISODE_IDENTITY_CONFLICT"):
        map_target_episode(bad, target_role=TARGET_ROLE_T1)


def test_batch_mapping_order_is_independent_of_record_and_role_input_order() -> None:
    first = make_record(episode_id="map-a")
    second = make_record(episode_id="map-b")
    mapped_a, excluded_a = map_episode_records([second, first], target_roles=[TARGET_ROLE_T2, TARGET_ROLE_T1])
    mapped_b, excluded_b = map_episode_records([first, second], target_roles=[TARGET_ROLE_T1, TARGET_ROLE_T2])
    assert [episode.episode_id for episode, _ in mapped_a] == [episode.episode_id for episode, _ in mapped_b]
    assert mapped_a == mapped_b
    assert excluded_a == excluded_b == []


@pytest.mark.parametrize(
    ("records", "roles", "error"),
    [
        ([make_record(episode_id="map-a"), make_record(episode_id="map-a")], [TARGET_ROLE_T1], "DUPLICATE_SOURCE_MAP_ID"),
        ([make_record()], [TARGET_ROLE_T1, TARGET_ROLE_T1], "DUPLICATE_TARGET_ROLE"),
        ([make_record()], [], "NO_TARGET_ROLES_SUPPLIED"),
        ([make_record()], ["T3"], "UNSUPPORTED_TARGET_ROLE"),
    ],
)
def test_batch_mapping_invalid_identity_or_role_contract_fails_closed(records, roles, error) -> None:
    with pytest.raises(TargetCaptureAdapterError, match=error):
        map_episode_records(records, target_roles=roles)


def test_bullish_target_adapter_replays_exact_miss_and_static_buffer_fill() -> None:
    record = make_record(direction=DIRECTION_BULLISH)
    episode, _ = map_target_episode(record, target_role=TARGET_ROLE_T1)
    replay_candles = convert_forward_candles(
        [candle(4, "100", "112.50")],
        issued_ts_utc=episode.issued_ts_utc,
        valid_until_ts_utc=episode.valid_until_ts_utc,
    )
    exact = replay_episode(
        episode, replay_candles, ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1")
    )
    buffered = replay_episode(
        episode,
        replay_candles,
        ExecutionOffsetPolicyV1(POLICY_STATIC_BUFFER, "v1", buffer_pct=Decimal("0.01")),
    )
    assert exact.filled is False
    assert buffered.filled is True
    assert buffered.execution_price == Decimal("111.5928")


def test_bearish_target_adapter_replays_exact_miss_and_static_buffer_fill() -> None:
    record = make_record(direction=DIRECTION_BEARISH)
    episode, _ = map_target_episode(record, target_role=TARGET_ROLE_T1)
    replay_candles = convert_forward_candles(
        [candle(4, "87.50", "100")],
        issued_ts_utc=episode.issued_ts_utc,
        valid_until_ts_utc=episode.valid_until_ts_utc,
    )
    exact = replay_episode(
        episode, replay_candles, ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1")
    )
    buffered = replay_episode(
        episode,
        replay_candles,
        ExecutionOffsetPolicyV1(POLICY_STATIC_BUFFER, "v1", buffer_pct=Decimal("0.01")),
    )
    assert exact.filled is False
    assert buffered.filled is True
    assert buffered.execution_price == Decimal("88.1528")
