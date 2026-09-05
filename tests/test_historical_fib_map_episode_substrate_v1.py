"""
Tests for #555 historical PIT Fib/map episode substrate.

Pure Python — no DB, no broker, no network. Synthetic candle series only.
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import signal
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from src.market_data import canonical_fib_zone_map_v1 as canonical_projection
from src.research import historical_fib_map_episode_substrate_v1 as substrate
from src.research import run_historical_fib_map_episode_substrate_v1 as runner
from src.research.historical_fib_map_episode_substrate_v1 import (
    DIRECTION_BEARISH,
    DIRECTION_BULLISH,
    LIFECYCLE_REASON_AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE,
    LIFECYCLE_REASON_FORWARD_WINDOW_EXHAUSTED,
    LIFECYCLE_REASON_INVALIDATION_BREACHED,
    LIFECYCLE_REASON_SOURCE_DATA_EXHAUSTED,
    LIFECYCLE_REASON_TARGET1_REACHED,
    LIFECYCLE_REASON_TARGET2_REACHED,
    NON_ATTRIBUTABLE_LIFECYCLE_REASONS,
    EpisodeConfig,
    EpisodeFeaturePayload,
    EpisodeSubstrateError,
    HistoricalCandle,
    PitViolationError,
    build_episode_feature,
    build_episode_labels,
    build_episodes,
    compute_episode_id,
    episodes_to_json,
    resolve_config,
    validate_candle_sequence,
)

UTC = timezone.utc


def _candle(ts: datetime, o: float, h: float, l: float, c: float, interval: str = "1h") -> HistoricalCandle:
    return HistoricalCandle(
        symbol="TST",
        venue="bitvavo",
        interval_code=interval,
        open_ts_utc=ts,
        close_ts_utc=ts + timedelta(hours=1 if interval == "1h" else 4),
        open_price=Decimal(str(o)),
        high_price=Decimal(str(h)),
        low_price=Decimal(str(l)),
        close_price=Decimal(str(c)),
        volume=Decimal("1"),
    )


def _synthetic_bullish_series(start: datetime, *, interval: str = "1h") -> list[HistoricalCandle]:
    """Deterministic decline -> swing -> rally -> pullback -> continuation series."""
    price = 100.0
    path: list[float] = []
    for _ in range(10):
        price -= 1.0
        path.append(price)
    for _ in range(120):
        price += (250 - 90) / 120
        path.append(price)
    for _ in range(5):
        price -= 3
        path.append(price)
    for _ in range(80):
        price += 5
        path.append(price)

    step = timedelta(hours=1 if interval == "1h" else 4)
    candles = []
    t = start
    for p in path:
        candles.append(_candle(t, p - 0.2, p + 0.5, p - 0.5, p, interval=interval))
        t += step
    return candles


def _small_cfg(interval: str = "1h") -> EpisodeConfig:
    return EpisodeConfig(
        interval_code=interval,
        interval_seconds=3600 if interval == "1h" else 4 * 3600,
        min_window_candles=50,
        lookback_candles=180,
        forward_max_candles=200,
    )


def _first_admitted_feature(candles: list[HistoricalCandle], cfg: EpisodeConfig) -> tuple[int, EpisodeFeaturePayload]:
    for i in range(cfg.min_window_candles - 1, len(candles)):
        window = candles[max(0, i - cfg.lookback_candles + 1) : i + 1]
        feature = build_episode_feature(symbol="TST", venue="bitvavo", window=window, cfg=cfg)
        if feature is not None and feature.direction == DIRECTION_BULLISH:
            return i, feature
    raise AssertionError("synthetic series produced no admissible bullish episode")


class TestCandleSequenceSafeguards:
    def test_duplicate_candle_rejected(self) -> None:
        t = datetime(2026, 1, 1, tzinfo=UTC)
        candles = [_candle(t, 1, 2, 0.5, 1.5), _candle(t, 1, 2, 0.5, 1.5)]
        with pytest.raises(EpisodeSubstrateError, match="duplicate"):
            validate_candle_sequence(candles)

    def test_non_monotonic_candle_rejected(self) -> None:
        t = datetime(2026, 1, 1, tzinfo=UTC)
        candles = [
            _candle(t + timedelta(hours=2), 1, 2, 0.5, 1.5),
            _candle(t, 1, 2, 0.5, 1.5),
        ]
        with pytest.raises(EpisodeSubstrateError, match="non-monotonic"):
            validate_candle_sequence(candles)

    def test_well_formed_sequence_passes(self) -> None:
        t = datetime(2026, 1, 1, tzinfo=UTC)
        candles = [_candle(t + timedelta(hours=i), 1, 2, 0.5, 1.5) for i in range(5)]
        validate_candle_sequence(candles)  # no raise


class TestPitTripwire:
    def test_feature_construction_rejects_out_of_order_future_candle(self) -> None:
        t = datetime(2026, 1, 1, tzinfo=UTC)
        cfg = _small_cfg()
        window = [_candle(t + timedelta(hours=i), 100, 101, 99, 100) for i in range(cfg.min_window_candles)]
        # Inject a candle timestamped after the nominal as-of (last element).
        window[3] = _candle(t + timedelta(hours=9999), 100, 101, 99, 100)
        with pytest.raises(PitViolationError):
            build_episode_feature(symbol="TST", venue="bitvavo", window=window, cfg=cfg)

    def test_label_construction_rejects_candle_at_or_before_asof(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        cfg = _small_cfg()
        candles = _synthetic_bullish_series(start)
        i, feature = _first_admitted_feature(candles, cfg)
        forward = [candles[i]] + list(candles[i + 1 :])  # includes the as-of candle itself
        with pytest.raises(PitViolationError):
            build_episode_labels(feature=feature, forward_candles=forward, cfg=cfg)


class TestCanonicalProjectionReuse:
    def test_same_function_object_used_for_1h_and_4h(self) -> None:
        assert substrate.build_row is canonical_projection.build_row
        cfg_1h = resolve_config("1h")
        cfg_4h = resolve_config("4h")
        assert cfg_1h.interval_code == "1h"
        assert cfg_4h.interval_code == "4h"
        assert substrate.PROJECTION_ENGINE_MODULE == "src.market_data.canonical_fib_zone_map_v1"
        assert substrate.PROJECTION_ENGINE_FUNCTION == "build_row"

    def test_no_reimplemented_projection_glue_in_substrate_module(self) -> None:
        source = inspect.getsource(substrate)
        # The substrate module must not reselect entry/target/invalidation
        # fields or re-derive anchor timestamps itself; build_row owns that.
        assert "_anchor_times" not in source
        assert "_build_levels" not in source
        assert "RETRACE_LEVELS" not in source
        assert "EXTENSION_LEVELS" not in source
        assert "r_0382" not in source
        assert "ext_1272" not in source

    def test_feature_fields_pass_through_from_direct_canonical_call(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        cfg = _small_cfg()
        candles = _synthetic_bullish_series(start)
        i, feature = _first_admitted_feature(candles, cfg)
        window = candles[max(0, i - cfg.lookback_candles + 1) : i + 1]

        trend_row = substrate._reconstruct_trend_row(window)
        fib_candles = [c.to_fib_nav_candle() for c in window]
        direct_row = canonical_projection.build_row(
            venue="bitvavo",
            symbol="TST",
            interval_code=cfg.interval_code,
            candles=fib_candles,
            now_utc=window[-1].close_ts_utc,
            trend_row=trend_row,
            prior_row=None,
            stale_after=cfg.stale_after,
        )
        assert feature.anchor_low_price == direct_row["anchor_low_price"]
        assert feature.anchor_high_price == direct_row["anchor_high_price"]
        assert feature.target_t1 == direct_row["target_t1"]
        assert feature.target_t2 == direct_row["target_t2"]
        assert feature.invalidation_level == direct_row["invalidation_level"]
        assert feature.entry_zone_low == direct_row["entry_zone_low"]
        assert feature.entry_zone_high == direct_row["entry_zone_high"]
        assert feature.map_version == direct_row["map_version"]


class TestDeterminism:
    def test_episode_id_deterministic_and_sensitive_to_anchor(self) -> None:
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        kwargs = dict(
            symbol="TST",
            venue="bitvavo",
            interval_code="1h",
            contract_version="1.0.0",
            map_creation_ts_utc=ts,
            direction=DIRECTION_BULLISH,
            anchor_low_price=Decimal("90"),
            anchor_high_price=Decimal("100"),
        )
        id_a = compute_episode_id(**kwargs)
        id_b = compute_episode_id(**kwargs)
        assert id_a == id_b

        kwargs_diff = dict(kwargs, anchor_high_price=Decimal("101"))
        id_c = compute_episode_id(**kwargs_diff)
        assert id_c != id_a

    def test_build_episodes_deterministic_across_repeated_runs(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        cfg = _small_cfg()
        candles = _synthetic_bullish_series(start)
        run_a = build_episodes(symbol="TST", venue="bitvavo", candles=candles, cfg=cfg, episode_stride_candles=5)
        run_b = build_episodes(symbol="TST", venue="bitvavo", candles=candles, cfg=cfg, episode_stride_candles=5)
        assert len(run_a) > 0
        assert episodes_to_json(run_a) == episodes_to_json(run_b)

    def test_atr_normalization_deterministic(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        cfg = _small_cfg()
        candles = _synthetic_bullish_series(start)
        i, feature_a = _first_admitted_feature(candles, cfg)
        window = candles[max(0, i - cfg.lookback_candles + 1) : i + 1]
        feature_b = build_episode_feature(symbol="TST", venue="bitvavo", window=window, cfg=cfg)
        assert feature_a.atr_value == feature_b.atr_value
        assert feature_a.target_t1_distance_atr == feature_b.target_t1_distance_atr


class TestLifecycleReasonExactness:
    def _feature(self, *, direction: str = DIRECTION_BULLISH) -> EpisodeFeaturePayload:
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        return EpisodeFeaturePayload(
            episode_id="deadbeef",
            symbol="TST",
            venue="bitvavo",
            source_timeframe="1h",
            builder_name=substrate.BUILDER_NAME,
            builder_version=substrate.BUILDER_VERSION,
            contract_version=substrate.CONTRACT_VERSION,
            projection_engine_module=substrate.PROJECTION_ENGINE_MODULE,
            projection_engine_function=substrate.PROJECTION_ENGINE_FUNCTION,
            map_version="test",
            map_creation_ts_utc=ts,
            source_candle_first_ts_utc=ts,
            source_candle_last_ts_utc=ts,
            source_candle_count=50,
            direction=direction,
            anchor_low_price=Decimal("90"),
            anchor_low_ts_utc=ts,
            anchor_high_price=Decimal("100"),
            anchor_high_ts_utc=ts,
            anchor_span_candles=1,
            anchor_span_elapsed_seconds=0.0,
            swing_amplitude_pct=Decimal("11"),
            reference_price=Decimal("100"),
            entry_zone_low=Decimal("96"),
            entry_zone_high=Decimal("98"),
            entry_zone_mid=Decimal("97"),
            target_t1=Decimal("112.72"),
            target_t2=Decimal("116.18"),
            target_extension=Decimal("126.18"),
            invalidation_level=Decimal("90"),
            atr_value=Decimal("1"),
            atr_period=14,
            target_t1_distance_pct=Decimal("12.72"),
            target_t2_distance_pct=Decimal("16.18"),
            invalidation_distance_pct=Decimal("10"),
            target_t1_distance_atr=Decimal("12.72"),
            target_t2_distance_atr=Decimal("16.18"),
            invalidation_distance_atr=Decimal("10"),
            map_state="FRESH",
            map_confidence="HIGH",
            rebuild_trigger="NONE",
            canonical_provenance_payload={},
        )

    def _bearish_feature(self) -> EpisodeFeaturePayload:
        # Mirror image: invalidation above anchor_high, targets below anchor_low.
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        feature = self._feature(direction=DIRECTION_BEARISH)
        return substrate.EpisodeFeaturePayload(
            **{
                **feature.__dict__,
                "entry_zone_low": Decimal("102"),
                "entry_zone_high": Decimal("104"),
                "entry_zone_mid": Decimal("103"),
                "target_t1": Decimal("87.28"),
                "target_t2": Decimal("83.82"),
                "target_extension": Decimal("73.82"),
                "invalidation_level": Decimal("110"),
                "reference_price": Decimal("100"),
            }
        )

    def _forward(self, prices: list[float], *, feature: EpisodeFeaturePayload) -> list[HistoricalCandle]:
        t = feature.map_creation_ts_utc
        candles = []
        for p in prices:
            t += timedelta(hours=1)
            candles.append(_candle(t, p, p + 0.5, p - 0.5, p))
        return candles

    def _forward_ohlc(
        self, bars: list[tuple[float, float, float, float]], *, feature: EpisodeFeaturePayload
    ) -> list[HistoricalCandle]:
        t = feature.map_creation_ts_utc
        candles = []
        for o, h, l, c in bars:
            t += timedelta(hours=1)
            candles.append(_candle(t, o, h, l, c))
        return candles

    def test_target1_reached_is_recorded_but_not_terminal(self) -> None:
        # T1 must not terminate the episode: with no further T2/invalidation
        # candles the scan runs out of source data, but target1_ts_utc is
        # still recorded from the candle that crossed target_t1.
        feature = self._feature()
        forward = self._forward([100, 105, 113], feature=feature)
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_SOURCE_DATA_EXHAUSTED
        assert labels.target1_ts_utc == forward[2].close_ts_utc
        assert labels.target2_ts_utc is None

    def test_target1_then_target2_later_both_timings_preserved(self) -> None:
        feature = self._feature()
        # T1 (112.72) hit on candle 1, T2 (116.18) only later on candle 3.
        forward = self._forward_ohlc(
            [
                (100, 113, 99.5, 113),
                (113, 113.5, 112.5, 113),
                (113, 117, 112.5, 117),
            ],
            feature=feature,
        )
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_TARGET2_REACHED
        assert labels.target1_ts_utc == forward[0].close_ts_utc
        assert labels.target2_ts_utc == forward[2].close_ts_utc
        assert labels.time_to_target1_seconds == (
            forward[0].close_ts_utc - feature.map_creation_ts_utc
        ).total_seconds()
        assert labels.time_to_target2_seconds == (
            forward[2].close_ts_utc - feature.map_creation_ts_utc
        ).total_seconds()
        assert labels.time_to_target1_seconds < labels.time_to_target2_seconds

    def test_target1_then_invalidation_later_t1_timing_preserved(self) -> None:
        feature = self._feature()
        # T1 (112.72) hit on candle 1, invalidation (90) only later on candle 3.
        forward = self._forward_ohlc(
            [
                (100, 113, 99.5, 113),
                (113, 113.5, 105, 105),
                (105, 106, 89, 89),
            ],
            feature=feature,
        )
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_INVALIDATION_BREACHED
        assert labels.target1_ts_utc == forward[0].close_ts_utc
        assert labels.target2_ts_utc is None
        assert labels.invalidation_ts_utc == forward[2].close_ts_utc

    def test_target1_then_later_same_candle_ambiguity_preserves_target1(self) -> None:
        feature = self._feature()
        # T1 hit cleanly on candle 1. Candle 2 crosses both target2 and
        # invalidation in the same bar -- ambiguous and non-attributable,
        # but the earlier target1_ts_utc must survive.
        forward = self._forward_ohlc(
            [
                (100, 113, 99.5, 113),
                (100, 120, 85, 110),
            ],
            feature=feature,
        )
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE
        assert labels.target1_ts_utc == forward[0].close_ts_utc
        assert labels.target2_ts_utc is None
        assert labels.invalidation_ts_utc is None
        assert labels.ambiguous_ts_utc == forward[1].close_ts_utc

    def test_bearish_target1_then_target2_later_both_timings_preserved(self) -> None:
        feature = self._bearish_feature()
        # Bearish mirror: T1 (87.28) hit on candle 1, T2 (83.82) later.
        forward = self._forward_ohlc(
            [
                (100, 100.5, 87, 87),
                (87, 87.5, 86, 86),
                (86, 86.5, 83, 83),
            ],
            feature=feature,
        )
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_TARGET2_REACHED
        assert labels.target1_ts_utc == forward[0].close_ts_utc
        assert labels.target2_ts_utc == forward[2].close_ts_utc

    def test_bearish_target1_then_invalidation_later_t1_timing_preserved(self) -> None:
        feature = self._bearish_feature()
        # Bearish mirror: T1 (87.28) hit on candle 1, invalidation (110) later.
        forward = self._forward_ohlc(
            [
                (100, 100.5, 87, 87),
                (87, 95, 86, 95),
                (95, 111, 94, 111),
            ],
            feature=feature,
        )
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_INVALIDATION_BREACHED
        assert labels.target1_ts_utc == forward[0].close_ts_utc
        assert labels.target2_ts_utc is None
        assert labels.invalidation_ts_utc == forward[2].close_ts_utc

    def test_target2_reached(self) -> None:
        feature = self._feature()
        # A single candle spanning both target levels: target1 and target2 are
        # hit in the same candle, so target2 (the further/later level) governs
        # the terminal reason rather than an intermediate target1-only step.
        forward = self._forward([100, 117], feature=feature)
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_TARGET2_REACHED

    def test_invalidation_breached(self) -> None:
        feature = self._feature()
        forward = self._forward([100, 95, 89], feature=feature)
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_INVALIDATION_BREACHED

    def test_forward_window_exhausted(self) -> None:
        feature = self._feature()
        cfg = EpisodeConfig(interval_code="1h", interval_seconds=3600, forward_max_candles=2)
        forward = self._forward([100, 100.1, 100.2, 100.3, 100.4], feature=feature)
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=cfg)
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_FORWARD_WINDOW_EXHAUSTED
        assert labels.forward_candles_scanned == 2

    def test_source_data_exhausted(self) -> None:
        feature = self._feature()
        forward = self._forward([100, 100.1], feature=feature)
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_SOURCE_DATA_EXHAUSTED

    def test_bullish_same_candle_target_invalidation_collision_is_ambiguous(self) -> None:
        feature = self._feature()
        # Single candle whose range crosses both invalidation (90) and
        # target1/target2 (112.72 / 116.18): low below invalidation, high
        # above target2. OHLC alone cannot say which was touched first.
        forward = self._forward_ohlc([(100, 120, 85, 110)], feature=feature)
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE
        assert labels.lifecycle_transition_reason in NON_ATTRIBUTABLE_LIFECYCLE_REASONS
        assert labels.ambiguous_ts_utc == forward[0].close_ts_utc
        # Must not be counted as either a target success or an invalidation success.
        assert labels.target1_ts_utc is None
        assert labels.target2_ts_utc is None
        assert labels.invalidation_ts_utc is None
        assert labels.time_to_target1_seconds is None
        assert labels.time_to_target2_seconds is None
        assert labels.time_to_invalidation_seconds is None

    def test_bearish_same_candle_target_invalidation_collision_is_ambiguous(self) -> None:
        feature = self._bearish_feature()
        # Bearish mirror: invalidation is above (110), targets are below
        # (87.28 / 83.82). A single candle whose high crosses invalidation
        # and whose low crosses both targets is ambiguous.
        forward = self._forward_ohlc([(100, 112, 80, 95)], feature=feature)
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE
        assert labels.ambiguous_ts_utc == forward[0].close_ts_utc
        assert labels.target1_ts_utc is None
        assert labels.target2_ts_utc is None
        assert labels.invalidation_ts_utc is None

    def test_ambiguous_collision_does_not_block_prior_entry_label(self) -> None:
        feature = self._feature()
        # Entry zone (96-98) touched on candle 1, ambiguous collision on candle 2.
        forward = self._forward_ohlc(
            [
                (100, 100.5, 96.5, 97),
                (100, 120, 85, 110),
            ],
            feature=feature,
        )
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.first_entry_ts_utc == forward[0].close_ts_utc
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE

    def test_bullish_entry_and_invalidation_same_candle_withholds_entry(self) -> None:
        feature = self._feature()
        # Entry zone (96-98) and invalidation (90) both touched by the same
        # bar's range: OHLC cannot say entry happened before invalidation.
        forward = self._forward_ohlc([(97, 97.5, 89, 89)], feature=feature)
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.first_entry_ts_utc is None
        assert labels.time_to_first_entry_seconds is None
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_INVALIDATION_BREACHED

    def test_bullish_entry_and_target_same_candle_withholds_entry(self) -> None:
        feature = self._feature()
        # Entry zone (96-98) and target1 (112.72) both touched by the same
        # bar's range: OHLC cannot say entry happened before target1.
        forward = self._forward_ohlc([(97, 113, 96.5, 113)], feature=feature)
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.first_entry_ts_utc is None
        assert labels.time_to_first_entry_seconds is None
        assert labels.target1_ts_utc == forward[0].close_ts_utc

    def test_bearish_entry_and_invalidation_same_candle_withholds_entry(self) -> None:
        feature = self._bearish_feature()
        # Entry zone (102-104) and invalidation (110) both touched by the
        # same bar's range.
        forward = self._forward_ohlc([(103, 111, 102.5, 111)], feature=feature)
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.first_entry_ts_utc is None
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_INVALIDATION_BREACHED

    def test_bearish_entry_and_target_same_candle_withholds_entry(self) -> None:
        feature = self._bearish_feature()
        # Entry zone (102-104) and target1 (87.28) both touched by the same
        # bar's range.
        forward = self._forward_ohlc([(103, 103.5, 87, 87)], feature=feature)
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.first_entry_ts_utc is None
        assert labels.target1_ts_utc == forward[0].close_ts_utc

    def test_earlier_entry_preserved_when_later_candle_is_entry_outcome_ambiguous(self) -> None:
        feature = self._feature()
        # Candle 1: clean, unambiguous entry-zone touch only.
        # Candle 2: re-touches entry zone AND hits invalidation in the same
        # bar -- that candle's own attribution must be withheld, but the
        # earlier candle-1 entry timestamp must survive untouched.
        forward = self._forward_ohlc(
            [
                (100, 100.5, 96.5, 97),
                (97, 97.5, 89, 89),
            ],
            feature=feature,
        )
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.first_entry_ts_utc == forward[0].close_ts_utc
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_INVALIDATION_BREACHED

    def test_entry_attributed_from_later_unambiguous_candle_after_earlier_ambiguous_one(self) -> None:
        feature = self._feature()
        # Candle 1 touches entry AND target1 in the same bar -- ambiguous,
        # entry withheld. Candle 2 touches entry zone cleanly (no
        # target/invalidation in that bar) -- entry attributed there instead.
        forward = self._forward_ohlc(
            [
                (97, 113, 96.5, 113),
                (100, 100.5, 96.5, 97),
            ],
            feature=feature,
        )
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.first_entry_ts_utc == forward[1].close_ts_utc


class TestImmutableOutput:
    def test_write_immutable_json_idempotent(self, tmp_path) -> None:
        path = tmp_path / "episodes_v1.json"
        text = '{"a": 1}\n'
        sha_a = runner.write_immutable_json(path, text)
        sha_b = runner.write_immutable_json(path, text)
        assert sha_a == sha_b

    def test_write_immutable_json_refuses_conflicting_overwrite(self, tmp_path) -> None:
        path = tmp_path / "episodes_v1.json"
        runner.write_immutable_json(path, '{"a": 1}\n')
        with pytest.raises(ValueError, match="refusing to overwrite"):
            runner.write_immutable_json(path, '{"a": 2}\n')


class TestAtomicPublication:
    """Regression coverage for the #727 blocker: a final <run_id> directory

    must be either absent or complete (both episodes_v1.json AND
    manifest_v1.json present and mutually consistent) -- never a partial
    directory with only episodes_v1.json, which the prior two-separate-
    write design could leave behind if manifest construction/write failed.
    """

    def _staging_dirs(self, output_dir: Path) -> list[Path]:
        return [
            p for p in output_dir.parent.iterdir() if p.name.startswith(f".{output_dir.name}.stage-")
        ] if output_dir.parent.exists() else []

    def test_successful_publish_both_files_appear_together(self, tmp_path: Any) -> None:
        output_dir = tmp_path / "bitvavo" / "BTC" / "1h" / "runid"
        episodes_sha256, manifest_sha256 = runner.publish_immutable_run(
            output_dir=output_dir,
            episodes_text='{"episodes": true}\n',
            manifest_text='{"manifest": true}\n',
        )
        assert output_dir.exists()
        assert (output_dir / "episodes_v1.json").read_text(encoding="utf-8") == '{"episodes": true}\n'
        assert (output_dir / "manifest_v1.json").read_text(encoding="utf-8") == '{"manifest": true}\n'
        assert episodes_sha256 == runner._sha256_text('{"episodes": true}\n')
        assert manifest_sha256 == runner._sha256_text('{"manifest": true}\n')
        assert self._staging_dirs(output_dir) == []

    def test_identical_rerun_is_idempotent(self, tmp_path: Any) -> None:
        output_dir = tmp_path / "bitvavo" / "BTC" / "1h" / "runid"
        result_a = runner.publish_immutable_run(
            output_dir=output_dir,
            episodes_text='{"episodes": true}\n',
            manifest_text='{"manifest": true}\n',
        )
        result_b = runner.publish_immutable_run(
            output_dir=output_dir,
            episodes_text='{"episodes": true}\n',
            manifest_text='{"manifest": true}\n',
        )
        assert result_a == result_b
        assert (output_dir / "episodes_v1.json").read_text(encoding="utf-8") == '{"episodes": true}\n'
        assert (output_dir / "manifest_v1.json").read_text(encoding="utf-8") == '{"manifest": true}\n'
        assert self._staging_dirs(output_dir) == []

    def test_existing_partial_final_dir_fails_closed_without_repair(self, tmp_path: Any) -> None:
        output_dir = tmp_path / "bitvavo" / "BTC" / "1h" / "runid"
        output_dir.mkdir(parents=True)
        (output_dir / "episodes_v1.json").write_text('{"pre-existing": true}\n', encoding="utf-8")
        # manifest_v1.json deliberately absent -- a partial directory.

        with pytest.raises(ValueError, match="incomplete"):
            runner.publish_immutable_run(
                output_dir=output_dir,
                episodes_text='{"pre-existing": true}\n',
                manifest_text='{"manifest": true}\n',
            )
        # Not "repaired": still exactly the one pre-existing file, untouched.
        assert (output_dir / "episodes_v1.json").read_text(encoding="utf-8") == '{"pre-existing": true}\n'
        assert not (output_dir / "manifest_v1.json").exists()
        assert self._staging_dirs(output_dir) == []

    def test_existing_conflicting_complete_dir_fails_closed(self, tmp_path: Any) -> None:
        output_dir = tmp_path / "bitvavo" / "BTC" / "1h" / "runid"
        output_dir.mkdir(parents=True)
        (output_dir / "episodes_v1.json").write_text('{"episodes": "old"}\n', encoding="utf-8")
        (output_dir / "manifest_v1.json").write_text('{"manifest": "old"}\n', encoding="utf-8")

        with pytest.raises(ValueError, match="refusing to overwrite"):
            runner.publish_immutable_run(
                output_dir=output_dir,
                episodes_text='{"episodes": "new"}\n',
                manifest_text='{"manifest": "old"}\n',
            )
        assert (output_dir / "episodes_v1.json").read_text(encoding="utf-8") == '{"episodes": "old"}\n'
        assert (output_dir / "manifest_v1.json").read_text(encoding="utf-8") == '{"manifest": "old"}\n'
        assert self._staging_dirs(output_dir) == []

    def test_episodes_staged_write_failure_leaves_no_final_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        output_dir = tmp_path / "bitvavo" / "BTC" / "1h" / "runid"
        real_fsync = os.fsync
        call_count = {"n": 0}

        def _flaky_fsync(fd: int) -> None:
            call_count["n"] += 1
            if call_count["n"] == 1:  # episodes_v1.json's fsync (written first)
                raise OSError("simulated disk failure")
            real_fsync(fd)

        monkeypatch.setattr(runner.os, "fsync", _flaky_fsync)

        with pytest.raises(OSError):
            runner.publish_immutable_run(
                output_dir=output_dir,
                episodes_text='{"episodes": true}\n',
                manifest_text='{"manifest": true}\n',
            )
        assert not output_dir.exists()
        assert self._staging_dirs(output_dir) == []

    def test_manifest_staged_write_failure_leaves_no_final_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        output_dir = tmp_path / "bitvavo" / "BTC" / "1h" / "runid"
        real_fsync = os.fsync
        call_count = {"n": 0}

        def _flaky_fsync(fd: int) -> None:
            call_count["n"] += 1
            if call_count["n"] == 2:  # manifest_v1.json's fsync (written second)
                raise OSError("simulated disk failure")
            real_fsync(fd)

        monkeypatch.setattr(runner.os, "fsync", _flaky_fsync)

        with pytest.raises(OSError):
            runner.publish_immutable_run(
                output_dir=output_dir,
                episodes_text='{"episodes": true}\n',
                manifest_text='{"manifest": true}\n',
            )
        assert not output_dir.exists()
        assert self._staging_dirs(output_dir) == []

    def test_manifest_construction_failure_leaves_no_final_dir_full_pipeline(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        candles = _synthetic_bullish_series(start)
        _RunnerHarness.patch_successful_fetch(monkeypatch, candles)

        def _boom(**kw: Any) -> dict[str, Any]:
            raise RuntimeError("simulated manifest construction failure")

        monkeypatch.setattr(runner, "build_manifest", _boom)

        exit_code = runner.main(_RunnerHarness.valid_args(tmp_path))
        out = capsys.readouterr().out
        assert exit_code != 0
        assert out.count("FAILED") == 1
        assert "FAILED reason=output_write_failed" in out
        assert "FINISHED" not in out
        assert list(tmp_path.rglob("*")) == []

    def test_interruption_before_publish_leaves_no_final_run_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        candles = _synthetic_bullish_series(start)
        _RunnerHarness.patch_successful_fetch(monkeypatch, candles)
        monkeypatch.setattr(runner, "DEFAULT_BUILD_PROGRESS_INTERVAL_CANDLES", 1)

        real_build_episodes = substrate.build_episodes

        def _signal_then_build(**kwargs: Any) -> list[Any]:
            os.kill(os.getpid(), signal.SIGINT)
            return real_build_episodes(**kwargs)

        monkeypatch.setattr(runner, "build_episodes", _signal_then_build)

        publish_calls: list[Any] = []
        monkeypatch.setattr(
            runner,
            "publish_immutable_run",
            lambda **kw: publish_calls.append(kw) or ("sha", "sha"),
        )

        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        try:
            exit_code = runner.main(_RunnerHarness.valid_args(tmp_path))
        finally:
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)

        assert exit_code == 130
        assert publish_calls == []
        assert list(tmp_path.rglob("*")) == []
        out = capsys.readouterr().out
        assert out.count("INTERRUPTED") == 1


class TestRunIdentity:
    def _kwargs(self, **overrides: Any) -> dict[str, Any]:
        base = dict(
            venue="bitvavo",
            symbol="BTC",
            timeframe="4h",
            from_ts="2026-01-01 00:00:00",
            to_ts="2026-06-01 00:00:00",
            episode_stride_candles=1,
            max_episodes=None,
            source_input_sha256="a" * 64,
        )
        base.update(overrides)
        return base

    def test_run_id_deterministic_for_identical_inputs(self) -> None:
        id_a = runner.compute_run_id(**self._kwargs())
        id_b = runner.compute_run_id(**self._kwargs())
        assert id_a == id_b

    @pytest.mark.parametrize(
        "override",
        [
            {"from_ts": "2026-01-02 00:00:00"},
            {"to_ts": "2026-06-02 00:00:00"},
            {"episode_stride_candles": 5},
            {"max_episodes": 10},
            {"venue": "other_venue"},
            {"symbol": "ETH"},
            {"timeframe": "1h"},
            {"source_input_sha256": "b" * 64},
        ],
    )
    def test_run_id_changes_when_any_dataset_defining_parameter_changes(self, override) -> None:
        baseline = runner.compute_run_id(**self._kwargs())
        varied = runner.compute_run_id(**self._kwargs(**override))
        assert varied != baseline

    def test_output_path_includes_run_id_and_isolates_conflicting_runs(self, tmp_path) -> None:
        kwargs_a = self._kwargs(max_episodes=5)
        kwargs_b = self._kwargs(max_episodes=50)
        run_id_a = runner.compute_run_id(**kwargs_a)
        run_id_b = runner.compute_run_id(**kwargs_b)
        assert run_id_a != run_id_b

        base_dir = tmp_path / "bitvavo" / "BTC" / "4h"
        path_a = base_dir / run_id_a / "episodes_v1.json"
        path_b = base_dir / run_id_b / "episodes_v1.json"

        runner.write_immutable_json(path_a, '{"episodes": "a"}\n')
        runner.write_immutable_json(path_b, '{"episodes": "b"}\n')  # must not collide with path_a

        assert path_a.read_text(encoding="utf-8") == '{"episodes": "a"}\n'
        assert path_b.read_text(encoding="utf-8") == '{"episodes": "b"}\n'

    def test_manifest_carries_full_run_identity(self) -> None:
        kwargs = self._kwargs()
        run_id = runner.compute_run_id(**kwargs)
        manifest = runner.build_manifest(
            run_id=run_id,
            venue="bitvavo",
            symbol="BTC",
            timeframe="4h",
            from_ts="2026-01-01 00:00:00",
            to_ts="2026-06-01 00:00:00",
            episode_stride_candles=1,
            max_episodes=None,
            candle_count=10,
            episode_count=1,
            episodes_sha256="a" * 64,
            source_input_sha256=kwargs["source_input_sha256"],
        )
        assert manifest["run_id"] == run_id
        assert manifest["builder_version"] == runner.BUILDER_VERSION
        assert manifest["contract_version"] == runner.CONTRACT_VERSION
        assert manifest["venue"] == "bitvavo"
        assert manifest["symbol"] == "BTC"
        assert manifest["timeframe"] == "4h"
        assert manifest["source_from_ts"] == "2026-01-01 00:00:00"
        assert manifest["source_to_ts"] == "2026-06-01 00:00:00"
        assert manifest["episode_stride_candles"] == 1
        assert manifest["max_episodes"] is None
        assert manifest["source_input_sha256"] == kwargs["source_input_sha256"]

        # run_id must be mechanically recomputable from the manifest's own
        # identity fields alone.
        recomputed = runner.compute_run_id(
            venue=manifest["venue"],
            symbol=manifest["symbol"],
            timeframe=manifest["timeframe"],
            from_ts=manifest["source_from_ts"],
            to_ts=manifest["source_to_ts"],
            episode_stride_candles=manifest["episode_stride_candles"],
            max_episodes=manifest["max_episodes"],
            source_input_sha256=manifest["source_input_sha256"],
        )
        assert recomputed == run_id


class TestBoundaryAndSafety:
    def test_fetch_candles_select_only_with_exact_bounds_and_order(self) -> None:
        source = inspect.getsource(runner.fetch_candles)
        assert "SELECT" in source
        assert "INSERT" not in source.upper()
        assert "UPDATE" not in source.upper()
        assert "DELETE" not in source.upper()
        assert "ORDER BY open_ts_utc ASC" in source
        assert "open_ts_utc >= %s" in source
        assert "open_ts_utc < %s" in source

    def test_fetch_forward_tail_candles_select_only_bounded_and_ascending(self) -> None:
        source = inspect.getsource(runner.fetch_forward_tail_candles)
        assert "SELECT" in source
        assert "INSERT" not in source.upper()
        assert "UPDATE" not in source.upper()
        assert "DELETE" not in source.upper()
        assert "ORDER BY open_ts_utc ASC" in source
        assert "open_ts_utc >= %s" in source
        assert "LIMIT %s" in source
        assert "datetime.now" not in source
        assert "utcnow" not in source

    def test_fetch_forward_tail_candles_limit_zero_or_negative_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom() -> Any:
            raise AssertionError("must not query DB when limit <= 0")

        monkeypatch.setattr(runner, "get_connection", _boom)
        assert (
            runner.fetch_forward_tail_candles(
                asset_id=1,
                symbol="TST",
                venue="bitvavo",
                interval_code="1h",
                to_ts="2026-01-01 00:00:00",
                limit=0,
            )
            == []
        )

    def test_no_forbidden_layer_imports(self) -> None:
        for module in (substrate, runner):
            source = inspect.getsource(module)
            import_lines = [
                line.strip()
                for line in source.splitlines()
                if line.strip().startswith(("import ", "from "))
            ]
            for forbidden in ("decision_gate", "execution_planner", "src.executor", "src.broker"):
                offending = [line for line in import_lines if forbidden in line]
                assert not offending, f"{module.__name__} imports forbidden layer {forbidden!r}: {offending}"

    def test_manifest_safety_markers_are_all_zero_except_research_market(self) -> None:
        manifest = runner.build_manifest(
            run_id="deadbeef",
            venue="bitvavo",
            symbol="TST",
            timeframe="1h",
            from_ts="2026-01-01",
            to_ts="2026-01-02",
            episode_stride_candles=1,
            max_episodes=None,
            candle_count=10,
            episode_count=1,
            episodes_sha256="a" * 64,
        )
        markers = manifest["safety_markers"]
        assert markers["research_only"] == 1
        assert markers["market_only"] == 1
        for key in (
            "account_awareness",
            "decision_permission",
            "execution_intent",
            "broker_calls",
            "broker_writes",
            "orders",
            "db_writes",
            "production_profile_writes",
            "runtime_activation",
        ):
            assert markers[key] == 0


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: list[Any]) -> None:
        return None

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._rows)

    def close(self) -> None:
        return None


def _fake_row(ts: datetime) -> dict[str, Any]:
    return {
        "venue": "bitvavo",
        "interval_code": "1h",
        "open_ts_utc": ts,
        "close_ts_utc": ts + timedelta(hours=1),
        "open_price": Decimal("100"),
        "high_price": Decimal("101"),
        "low_price": Decimal("99"),
        "close_price": Decimal("100.5"),
        "volume_base": Decimal("1"),
    }


class TestTimestampNormalization:
    def test_naive_db_datetime_treated_as_utc(self) -> None:
        naive_ts = datetime(2026, 1, 1, 12, 0, 0)  # tzinfo=None, as returned by MariaDB driver
        assert naive_ts.tzinfo is None
        normalized = runner.normalize_db_datetime_to_utc(naive_ts)
        assert normalized.tzinfo is timezone.utc
        assert normalized == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_aware_db_datetime_converted_to_utc(self) -> None:
        aware_ts = datetime(2026, 1, 1, 14, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        normalized = runner.normalize_db_datetime_to_utc(aware_ts)
        assert normalized.tzinfo is timezone.utc
        assert normalized == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_fetch_candles_produces_utc_aware_historical_candles(self, monkeypatch: pytest.MonkeyPatch) -> None:
        naive_ts = datetime(2026, 1, 1, 0, 0, 0)
        rows = [_fake_row(naive_ts), _fake_row(naive_ts + timedelta(hours=1))]
        monkeypatch.setattr(runner, "get_connection", lambda: _FakeConnection(rows))

        candles = runner.fetch_candles(
            asset_id=1,
            symbol="BTC",
            venue="bitvavo",
            interval_code="1h",
            from_ts="2026-01-01 00:00:00",
            to_ts="2026-01-02 00:00:00",
        )

        assert len(candles) == 2
        for candle in candles:
            assert candle.open_ts_utc.tzinfo is timezone.utc
            assert candle.close_ts_utc.tzinfo is timezone.utc

    def test_naive_and_aware_equivalent_db_rows_produce_identical_episode_identity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Same instant, expressed once as a naive datetime (DB storage
        # convention: naive means UTC) and once as an explicitly UTC-aware
        # datetime. Both must normalize to the identical canonical
        # timestamp, independent of any local host timezone assumption.
        naive_ts = datetime(2026, 1, 1, 0, 0, 0)
        aware_ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

        def _episode_id_for(ts: datetime) -> str:
            rows = [_fake_row(ts), _fake_row(ts + timedelta(hours=1))]
            monkeypatch.setattr(runner, "get_connection", lambda: _FakeConnection(rows))
            candles = runner.fetch_candles(
                asset_id=1,
                symbol="BTC",
                venue="bitvavo",
                interval_code="1h",
                from_ts="2026-01-01 00:00:00",
                to_ts="2026-01-02 00:00:00",
            )
            return substrate.compute_episode_id(
                symbol="BTC",
                venue="bitvavo",
                interval_code="1h",
                contract_version=substrate.CONTRACT_VERSION,
                map_creation_ts_utc=candles[-1].close_ts_utc,
                direction=DIRECTION_BULLISH,
                anchor_low_price=Decimal("90"),
                anchor_high_price=Decimal("100"),
            )

        assert _episode_id_for(naive_ts) == _episode_id_for(aware_ts)


class TestOffsetAwareCliTimestampBounds:
    """Regression coverage for the latest #727 blocker: --from-ts/--to-ts

    accept offset-aware ISO timestamps, but every DB query bound must be
    derived from the SAME normalized-UTC datetime build_episodes' emission
    boundary uses (from_ts_dt/to_ts_dt) -- never from the raw CLI string,
    which could carry an explicit non-UTC offset. Without this, an
    offset-aware --from-ts/--to-ts would fetch a different window than the
    declared UTC contract, silently changing episodes/labels.
    """

    def test_format_ts_for_query_normalizes_offset_aware_datetime(self) -> None:
        aware = datetime(2026, 1, 1, 2, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        assert runner.format_ts_for_query(aware) == "2026-01-01 00:00:00"

    def test_format_ts_for_query_matches_naive_utc_equivalent(self) -> None:
        naive_equivalent = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        offset_aware = datetime(2026, 1, 1, 5, 0, 0, tzinfo=timezone(timedelta(hours=5)))
        assert (
            runner.format_ts_for_query(naive_equivalent)
            == runner.format_ts_for_query(offset_aware)
            == "2026-01-01 00:00:00"
        )

    def test_offset_aware_cli_bounds_produce_utc_normalized_db_query_bounds(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        monkeypatch.setattr(runner, "fetch_asset_id", lambda **kw: 1)

        captured: dict[str, dict[str, Any]] = {}

        def _capture_warmup(**kw: Any) -> list[Any]:
            captured["warmup"] = kw
            return []

        def _capture_requested(**kw: Any) -> list[Any]:
            captured["requested"] = kw
            return []

        def _capture_tail(**kw: Any) -> list[Any]:
            captured["tail"] = kw
            return []

        monkeypatch.setattr(runner, "fetch_warmup_candles", _capture_warmup)
        monkeypatch.setattr(runner, "fetch_candles", _capture_requested)
        monkeypatch.setattr(runner, "fetch_forward_tail_candles", _capture_tail)

        # +02:00 offset: 2026-01-01T02:00:00+02:00 == 2026-01-01T00:00:00 UTC,
        # 2026-01-02T02:00:00+02:00 == 2026-01-02T00:00:00 UTC. If the raw
        # CLI string leaked into any DB query, these captured bounds would
        # instead show the literal (wrong) wall-clock digits with no offset
        # stripped, e.g. "2026-01-01 02:00:00".
        exit_code = runner.main(
            [
                "--symbol", "BTC",
                "--timeframe", "1h",
                "--from-ts", "2026-01-01T02:00:00+02:00",
                "--to-ts", "2026-01-02T02:00:00+02:00",
                "--output-dir", str(tmp_path),
            ]
        )
        assert exit_code == 0

        assert captured["warmup"]["before_ts"] == "2026-01-01 00:00:00"
        assert captured["requested"]["from_ts"] == "2026-01-01 00:00:00"
        assert captured["requested"]["to_ts"] == "2026-01-02 00:00:00"
        assert captured["tail"]["to_ts"] == "2026-01-02 00:00:00"

    def test_offset_aware_and_naive_utc_equivalent_bounds_fetch_identical_window(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        # Two CLI invocations naming the SAME UTC instant, one with an
        # explicit +02:00 offset and one already in UTC, must resolve to
        # the identical DB query bound for every fetch phase.
        monkeypatch.setattr(runner, "fetch_asset_id", lambda **kw: 1)

        def _run(from_ts: str, to_ts: str, subdir: str) -> dict[str, Any]:
            captured: dict[str, Any] = {}

            def _capture(**kw: Any) -> list[Any]:
                captured.update(kw)
                return []

            monkeypatch.setattr(runner, "fetch_warmup_candles", _capture)
            monkeypatch.setattr(runner, "fetch_candles", lambda **kw: [])
            monkeypatch.setattr(runner, "fetch_forward_tail_candles", lambda **kw: [])
            exit_code = runner.main(
                [
                    "--symbol", "BTC",
                    "--timeframe", "1h",
                    "--from-ts", from_ts,
                    "--to-ts", to_ts,
                    "--output-dir", str(tmp_path / subdir),
                ]
            )
            assert exit_code == 0
            return captured

        offset_captured = _run("2026-01-01T02:00:00+02:00", "2026-01-02T00:00:00+00:00", "a")
        naive_utc_captured = _run("2026-01-01T00:00:00", "2026-01-02T00:00:00", "b")
        assert (
            offset_captured["before_ts"]
            == naive_utc_captured["before_ts"]
            == "2026-01-01 00:00:00"
        )


# ---------------------------------------------------------------------------
# Fake paginating DB harness for warmup/chunked-retrieval tests.
# ---------------------------------------------------------------------------

def _candle_to_row(candle: HistoricalCandle) -> dict[str, Any]:
    return {
        "venue": candle.venue,
        "interval_code": candle.interval_code,
        "open_ts_utc": candle.open_ts_utc.replace(tzinfo=None),
        "close_ts_utc": candle.close_ts_utc.replace(tzinfo=None),
        "open_price": candle.open_price,
        "high_price": candle.high_price,
        "low_price": candle.low_price,
        "close_price": candle.close_price,
        "volume_base": candle.volume,
    }


def _coerce_utc(value: Any) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return runner.normalize_db_datetime_to_utc(value)


class _PagingFakeCursor:
    """Mimics MariaDB WHERE/ORDER BY/LIMIT semantics over an in-memory row list."""

    def __init__(self, rows: list[dict[str, Any]], conn: "_PagingFakeConnection") -> None:
        self._rows = rows
        self._conn = conn
        self._result: list[dict[str, Any]] = []

    def __enter__(self) -> "_PagingFakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: list[Any]) -> None:
        self._conn.query_count += 1
        normalized = " ".join(sql.split())
        if "DESC" in normalized:
            _asset_id, _venue, _interval_code, before_ts, limit = params
            before = _coerce_utc(before_ts)
            candidates = [r for r in self._rows if _coerce_utc(r["open_ts_utc"]) < before]
            # Mirror the real SQL's ORDER BY open_ts_utc DESC: return the
            # nearest-before-`before_ts` rows in descending order, matching
            # what a real DB would hand back before fetch_warmup_candles
            # itself reverses it to ascending.
            candidates.sort(key=lambda r: r["open_ts_utc"], reverse=True)
            self._result = candidates[:limit]
        elif len(params) == 5:
            # fetch_forward_tail_candles: ORDER BY ASC, only a lower bound
            # (open_ts_utc >= to_ts) plus LIMIT -- no upper bound, so this
            # is distinguished from the requested-window queries by param
            # count (5, not 6) rather than by SQL substring.
            _asset_id, _venue, _interval_code, lower, limit = params
            lower_dt = _coerce_utc(lower)
            candidates = [r for r in self._rows if _coerce_utc(r["open_ts_utc"]) >= lower_dt]
            candidates.sort(key=lambda r: r["open_ts_utc"])
            self._result = candidates[:limit]
        elif "open_ts_utc >= %s" in normalized:
            _asset_id, _venue, _interval_code, lower, upper, limit = params
            lower_dt, upper_dt = _coerce_utc(lower), _coerce_utc(upper)
            candidates = [
                r for r in self._rows if lower_dt <= _coerce_utc(r["open_ts_utc"]) < upper_dt
            ]
            candidates.sort(key=lambda r: r["open_ts_utc"])
            self._result = candidates[:limit]
        else:
            _asset_id, _venue, _interval_code, lower, upper, limit = params
            lower_dt, upper_dt = _coerce_utc(lower), _coerce_utc(upper)
            candidates = [
                r for r in self._rows if lower_dt < _coerce_utc(r["open_ts_utc"]) < upper_dt
            ]
            candidates.sort(key=lambda r: r["open_ts_utc"])
            self._result = candidates[:limit]

    def fetchall(self) -> list[dict[str, Any]]:
        return self._result


class _PagingFakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.query_count = 0

    def cursor(self) -> _PagingFakeCursor:
        return _PagingFakeCursor(self._rows, self)

    def close(self) -> None:
        return None


class TestBoundedChunkedRetrieval:
    def test_fetch_candles_paginates_without_duplicates_or_gaps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        all_candles = _synthetic_bullish_series(start)
        rows = [_candle_to_row(c) for c in all_candles]
        conn = _PagingFakeConnection(rows)
        monkeypatch.setattr(runner, "get_connection", lambda: conn)

        from_ts = start.strftime("%Y-%m-%d %H:%M:%S")
        to_ts = (all_candles[-1].close_ts_utc + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        fetched = runner.fetch_candles(
            asset_id=1,
            symbol="TST",
            venue="bitvavo",
            interval_code="1h",
            from_ts=from_ts,
            to_ts=to_ts,
            chunk_size=20,
        )
        assert len(fetched) == len(all_candles)
        assert conn.query_count > 1  # proves pagination actually occurred
        ts_list = [c.open_ts_utc for c in fetched]
        assert ts_list == sorted(set(ts_list))  # strictly ascending, no duplicates
        assert [c.close_ts_utc for c in fetched] == [c.close_ts_utc for c in all_candles]

    def test_fetch_candles_single_chunk_when_range_smaller_than_chunk_size(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        all_candles = _synthetic_bullish_series(start)
        rows = [_candle_to_row(c) for c in all_candles]
        conn = _PagingFakeConnection(rows)
        monkeypatch.setattr(runner, "get_connection", lambda: conn)

        from_ts = start.strftime("%Y-%m-%d %H:%M:%S")
        to_ts = (all_candles[-1].close_ts_utc + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        fetched = runner.fetch_candles(
            asset_id=1,
            symbol="TST",
            venue="bitvavo",
            interval_code="1h",
            from_ts=from_ts,
            to_ts=to_ts,
            chunk_size=len(all_candles) + 100,
        )
        assert len(fetched) == len(all_candles)
        assert conn.query_count == 1

    def test_fetch_candles_respects_should_stop_between_chunks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        all_candles = _synthetic_bullish_series(start)
        rows = [_candle_to_row(c) for c in all_candles]
        conn = _PagingFakeConnection(rows)
        monkeypatch.setattr(runner, "get_connection", lambda: conn)

        from_ts = start.strftime("%Y-%m-%d %H:%M:%S")
        to_ts = (all_candles[-1].close_ts_utc + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

        progress_calls = {"n": 0}

        def _progress(_count: int) -> None:
            progress_calls["n"] += 1

        def _stop_after_first_chunk() -> bool:
            return progress_calls["n"] > 0

        fetched = runner.fetch_candles(
            asset_id=1,
            symbol="TST",
            venue="bitvavo",
            interval_code="1h",
            from_ts=from_ts,
            to_ts=to_ts,
            chunk_size=20,
            on_progress=_progress,
            should_stop=_stop_after_first_chunk,
        )
        assert 0 < len(fetched) < len(all_candles)
        assert len(fetched) == 20

    def test_fetch_warmup_candles_bounded_and_ascending(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        all_candles = _synthetic_bullish_series(start)
        rows = [_candle_to_row(c) for c in all_candles]
        conn = _PagingFakeConnection(rows)
        monkeypatch.setattr(runner, "get_connection", lambda: conn)

        before_ts = all_candles[100].open_ts_utc.strftime("%Y-%m-%d %H:%M:%S")
        warmup = runner.fetch_warmup_candles(
            asset_id=1,
            symbol="TST",
            venue="bitvavo",
            interval_code="1h",
            before_ts=before_ts,
            limit=30,
        )
        assert len(warmup) == 30
        ts_list = [c.open_ts_utc for c in warmup]
        assert ts_list == sorted(ts_list)
        before_dt = runner.parse_ts_arg(before_ts, name="before_ts")
        assert all(ts < before_dt for ts in ts_list)
        assert warmup[-1].close_ts_utc == all_candles[99].close_ts_utc

    def test_fetch_warmup_candles_limit_zero_or_negative_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom() -> Any:
            raise AssertionError("must not query DB when limit <= 0")

        monkeypatch.setattr(runner, "get_connection", _boom)
        assert (
            runner.fetch_warmup_candles(
                asset_id=1,
                symbol="TST",
                venue="bitvavo",
                interval_code="1h",
                before_ts="2026-01-01 00:00:00",
                limit=0,
            )
            == []
        )

    def test_fetch_forward_tail_candles_bounded_and_ascending_from_to_ts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        all_candles = _synthetic_bullish_series(start)
        rows = [_candle_to_row(c) for c in all_candles]
        conn = _PagingFakeConnection(rows)
        monkeypatch.setattr(runner, "get_connection", lambda: conn)

        to_ts = all_candles[100].open_ts_utc.strftime("%Y-%m-%d %H:%M:%S")
        tail = runner.fetch_forward_tail_candles(
            asset_id=1,
            symbol="TST",
            venue="bitvavo",
            interval_code="1h",
            to_ts=to_ts,
            limit=30,
        )
        assert len(tail) == 30
        ts_list = [c.open_ts_utc for c in tail]
        assert ts_list == sorted(ts_list)
        to_ts_dt = runner.parse_ts_arg(to_ts, name="to_ts")
        assert all(ts >= to_ts_dt for ts in ts_list)
        assert tail[0].open_ts_utc == all_candles[100].open_ts_utc


class TestWarmupInvariance:
    """Regression coverage for the #727 PIT trend-feature warmup blocker."""

    def _cfg(self) -> EpisodeConfig:
        return EpisodeConfig(
            interval_code="1h",
            interval_seconds=3600,
            min_window_candles=50,
            lookback_candles=60,
            forward_max_candles=50,
        )

    def test_same_asof_candle_invariant_to_requested_from_ts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        all_candles = _synthetic_bullish_series(start)
        cfg = self._cfg()
        rows = [_candle_to_row(c) for c in all_candles]

        asof_index = cfg.min_window_candles + cfg.lookback_candles + 10
        asof_ts = all_candles[asof_index].close_ts_utc

        def _feature_for(from_ts: str, to_ts: str) -> EpisodeFeaturePayload:
            monkeypatch.setattr(runner, "get_connection", lambda: _PagingFakeConnection(rows))
            warmup = runner.fetch_warmup_candles(
                asset_id=1,
                symbol="TST",
                venue="bitvavo",
                interval_code="1h",
                before_ts=from_ts,
                limit=cfg.lookback_candles - 1,
            )
            monkeypatch.setattr(runner, "get_connection", lambda: _PagingFakeConnection(rows))
            requested = runner.fetch_candles(
                asset_id=1,
                symbol="TST",
                venue="bitvavo",
                interval_code="1h",
                from_ts=from_ts,
                to_ts=to_ts,
            )
            candles = warmup + requested
            records = build_episodes(
                symbol="TST",
                venue="bitvavo",
                candles=candles,
                cfg=cfg,
                emit_from_ts_utc=runner.parse_ts_arg(from_ts, name="--from-ts"),
                emit_to_ts_utc=runner.parse_ts_arg(to_ts, name="--to-ts"),
            )
            matches = [r for r in records if r.feature.map_creation_ts_utc == asof_ts]
            assert len(matches) == 1, f"expected exactly one episode at {asof_ts}, got {len(matches)}"
            return matches[0].feature

        to_ts = (asof_ts + timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
        from_ts_near = (asof_ts - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
        from_ts_far = (asof_ts - timedelta(hours=40)).strftime("%Y-%m-%d %H:%M:%S")

        feature_near = _feature_for(from_ts_near, to_ts)
        feature_far = _feature_for(from_ts_far, to_ts)

        assert feature_near.direction == feature_far.direction
        assert feature_near.anchor_low_price == feature_far.anchor_low_price
        assert feature_near.anchor_high_price == feature_far.anchor_high_price
        assert feature_near.anchor_low_ts_utc == feature_far.anchor_low_ts_utc
        assert feature_near.anchor_high_ts_utc == feature_far.anchor_high_ts_utc
        assert feature_near.target_t1 == feature_far.target_t1
        assert feature_near.target_t2 == feature_far.target_t2
        assert feature_near.invalidation_level == feature_far.invalidation_level
        assert feature_near.map_state == feature_far.map_state
        assert feature_near.atr_value == feature_far.atr_value
        assert feature_near.episode_id == feature_far.episode_id

    def test_without_warmup_narrow_window_diverges_from_full_history(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Negative control: proves the invariance above is actually exercising
        # the warmup mechanism, not a coincidence of the synthetic series --
        # skipping warmup entirely for the narrow window changes the outcome
        # (fewer candles in the reconstructed window) versus fetching with
        # full prior history from the start of the series.
        start = datetime(2026, 1, 1, tzinfo=UTC)
        all_candles = _synthetic_bullish_series(start)
        cfg = self._cfg()

        asof_index = cfg.min_window_candles + cfg.lookback_candles + 10
        asof_ts = all_candles[asof_index].close_ts_utc

        window_full = all_candles[: asof_index + 1]
        feature_full = build_episode_feature(
            symbol="TST", venue="bitvavo", window=window_full, cfg=cfg
        )
        assert feature_full is not None

        narrow_start = asof_index - 5
        window_narrow = all_candles[narrow_start : asof_index + 1]
        feature_narrow = build_episode_feature(
            symbol="TST", venue="bitvavo", window=window_narrow, cfg=cfg
        )

        # Either admission itself differs (None vs a payload) or, if both
        # admit, the reconstructed geometry differs -- either way this shows
        # the un-warmed-up narrow window is not equivalent to the full one.
        assert feature_narrow is None or feature_narrow.anchor_low_price != feature_full.anchor_low_price or feature_narrow.target_t1 != feature_full.target_t1


class TestForwardTailRetrieval:
    """Regression coverage for the #727 forward-label-tail blocker.

    Without a forward-label tail, an episode emitted near --to-ts whose
    T2/invalidation resolves after --to-ts was mislabeled
    SOURCE_DATA_EXHAUSTED purely because DB retrieval stopped at the
    requested output bound, not because the market itself ran out of data.
    """

    MIN_TERMINAL_OFFSET_HOURS = 10
    MAX_TERMINAL_OFFSET_HOURS = 60  # stays within cfg.forward_max_candles below

    def _cfg(self) -> EpisodeConfig:
        return EpisodeConfig(
            interval_code="1h",
            interval_seconds=3600,
            min_window_candles=50,
            lookback_candles=60,
            forward_max_candles=80,
        )

    def _full_series_and_reference_labels(
        self,
    ) -> tuple[list[HistoricalCandle], EpisodeConfig, list[Any]]:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        all_candles = _synthetic_bullish_series(start)
        cfg = self._cfg()
        records = build_episodes(symbol="BTC", venue="bitvavo", candles=all_candles, cfg=cfg)
        return all_candles, cfg, records

    def _pick_reference(self, records: list[Any], reason: str) -> Any:
        for record in records:
            if record.labels.lifecycle_transition_reason != reason:
                continue
            offset_hours = (
                record.labels.terminal_ts_utc - record.feature.map_creation_ts_utc
            ).total_seconds() / 3600
            if self.MIN_TERMINAL_OFFSET_HOURS <= offset_hours <= self.MAX_TERMINAL_OFFSET_HOURS:
                return record
        raise AssertionError(
            f"synthetic series produced no {reason} candidate with a distant terminal event"
        )

    def test_upper_bound_does_not_falsely_exhaust_target2_labels(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        all_candles, cfg, records = self._full_series_and_reference_labels()
        reference = self._pick_reference(records, LIFECYCLE_REASON_TARGET2_REACHED)

        from_ts_dt = reference.feature.map_creation_ts_utc - timedelta(hours=5)
        to_ts_dt = reference.feature.map_creation_ts_utc + timedelta(hours=1)

        rows = [_candle_to_row(c) for c in all_candles]
        monkeypatch.setattr(runner, "get_connection", lambda: _PagingFakeConnection(rows))
        monkeypatch.setattr(runner, "fetch_asset_id", lambda **kw: 1)
        monkeypatch.setattr(runner, "resolve_config", lambda timeframe: cfg)

        exit_code = runner.main(
            [
                "--symbol", "BTC",
                "--timeframe", "1h",
                "--from-ts", from_ts_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "--to-ts", to_ts_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "--output-dir", str(tmp_path),
            ]
        )
        assert exit_code == 0

        [episodes_path] = list(tmp_path.rglob("episodes_v1.json"))
        [manifest_path] = list(tmp_path.rglob("manifest_v1.json"))
        episodes = json.loads(episodes_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        matches = [e for e in episodes if e["feature"]["episode_id"] == reference.feature.episode_id]
        assert len(matches) == 1
        labels = matches[0]["labels"]
        assert labels["lifecycle_transition_reason"] == LIFECYCLE_REASON_TARGET2_REACHED
        assert labels["lifecycle_transition_reason"] != LIFECYCLE_REASON_SOURCE_DATA_EXHAUSTED
        assert datetime.fromisoformat(labels["target2_ts_utc"]) == reference.labels.target2_ts_utc
        assert manifest["forward_tail_candle_count"] > 0
        assert manifest["forward_tail_max_candles"] == cfg.forward_max_candles

    def test_split_and_concatenated_forward_candles_preserve_invalidation_labels(self) -> None:
        # Cheap substrate-level equivalent of the runner-level T2 case above,
        # for INVALIDATION_BREACHED: the runner builds its final candle input
        # as `warmup + requested_window + forward_tail` -- i.e. it fetches
        # the SAME forward candle series as an unsplit fetch would, just in
        # two pieces joined end to end. Splitting `forward_candles` at an
        # arbitrary boundary (standing in for the requested-window/to_ts
        # cut) and re-concatenating it must be label-identical to a single
        # unsplit fetch; truncating instead of concatenating is exactly the
        # pre-#727-fix bug (SOURCE_DATA_EXHAUSTED for a purely
        # request-bound reason).
        helpers = TestLifecycleReasonExactness()
        feature = helpers._feature()
        # T1 hit candle 1, nothing candle 2, invalidation breached candle 3
        # -- same scenario as test_target1_then_invalidation_later_t1_timing_preserved.
        forward = helpers._forward_ohlc(
            [
                (100, 113, 99.5, 113),
                (113, 113.5, 105, 105),
                (105, 106, 89, 89),
            ],
            feature=feature,
        )
        cfg = _small_cfg()

        full_labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=cfg)
        assert full_labels.lifecycle_transition_reason == LIFECYCLE_REASON_INVALIDATION_BREACHED

        # Pre-fix behavior: DB retrieval stops at the requested-window
        # boundary and no tail is fetched -- the same episode is mislabeled
        # SOURCE_DATA_EXHAUSTED purely because of where the request ended.
        truncated_labels = build_episode_labels(
            feature=feature, forward_candles=forward[:2], cfg=cfg
        )
        assert truncated_labels.lifecycle_transition_reason == LIFECYCLE_REASON_SOURCE_DATA_EXHAUSTED

        # Fixed behavior: requested-window candles + forward-tail candles,
        # fetched separately, concatenated exactly like the runner's
        # `warmup + requested_candles + forward_tail_candles`.
        reconstructed = forward[:2] + forward[2:]
        reconstructed_labels = build_episode_labels(
            feature=feature, forward_candles=reconstructed, cfg=cfg
        )
        assert reconstructed_labels == full_labels
        assert reconstructed_labels.lifecycle_transition_reason == LIFECYCLE_REASON_INVALIDATION_BREACHED

    def test_without_forward_tail_same_episode_is_falsely_exhausted(self) -> None:
        # Negative control proving the fix is load-bearing: replaying the
        # SAME requested window with NO forward tail (the pre-#727-fix
        # behavior) mislabels the identical episode SOURCE_DATA_EXHAUSTED.
        all_candles, cfg, records = self._full_series_and_reference_labels()
        reference = self._pick_reference(records, LIFECYCLE_REASON_TARGET2_REACHED)

        from_ts_dt = reference.feature.map_creation_ts_utc - timedelta(hours=5)
        to_ts_dt = reference.feature.map_creation_ts_utc + timedelta(hours=1)

        requested_only = [c for c in all_candles if from_ts_dt <= c.open_ts_utc < to_ts_dt]
        warmup_pool = [c for c in all_candles if c.open_ts_utc < from_ts_dt]
        warmup_only = warmup_pool[-(cfg.lookback_candles - 1):] if cfg.lookback_candles > 1 else []
        no_tail_candles = warmup_only + requested_only

        no_tail_records = build_episodes(
            symbol="BTC",
            venue="bitvavo",
            candles=no_tail_candles,
            cfg=cfg,
            emit_from_ts_utc=from_ts_dt,
            emit_to_ts_utc=to_ts_dt,
        )
        matches = [r for r in no_tail_records if r.feature.episode_id == reference.feature.episode_id]
        assert len(matches) == 1
        assert matches[0].labels.lifecycle_transition_reason == LIFECYCLE_REASON_SOURCE_DATA_EXHAUSTED

    def test_emission_boundary_unchanged_by_forward_tail(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        # Extending the forward tail must never create a NEW emitted episode
        # outside [from_ts, to_ts) -- only supply outcome evidence for
        # episodes already emitted inside it.
        all_candles, cfg, records = self._full_series_and_reference_labels()
        reference = self._pick_reference(records, LIFECYCLE_REASON_TARGET2_REACHED)

        from_ts_dt = reference.feature.map_creation_ts_utc - timedelta(hours=5)
        to_ts_dt = reference.feature.map_creation_ts_utc + timedelta(hours=1)

        rows = [_candle_to_row(c) for c in all_candles]
        monkeypatch.setattr(runner, "get_connection", lambda: _PagingFakeConnection(rows))
        monkeypatch.setattr(runner, "fetch_asset_id", lambda **kw: 1)
        monkeypatch.setattr(runner, "resolve_config", lambda timeframe: cfg)

        exit_code = runner.main(
            [
                "--symbol", "BTC",
                "--timeframe", "1h",
                "--from-ts", from_ts_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "--to-ts", to_ts_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "--output-dir", str(tmp_path),
            ]
        )
        assert exit_code == 0

        [episodes_path] = list(tmp_path.rglob("episodes_v1.json"))
        episodes = json.loads(episodes_path.read_text(encoding="utf-8"))
        assert len(episodes) > 0
        for episode in episodes:
            map_creation_ts = datetime.fromisoformat(episode["feature"]["map_creation_ts_utc"])
            assert from_ts_dt <= map_creation_ts < to_ts_dt

    def test_upper_bound_invariance_extending_output_window_preserves_earlier_episode(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        all_candles, cfg, records = self._full_series_and_reference_labels()
        reference = self._pick_reference(records, LIFECYCLE_REASON_TARGET2_REACHED)

        from_ts_dt = reference.feature.map_creation_ts_utc - timedelta(hours=5)
        to_ts_near = reference.feature.map_creation_ts_utc + timedelta(hours=1)
        to_ts_far = reference.feature.map_creation_ts_utc + timedelta(hours=20)

        rows = [_candle_to_row(c) for c in all_candles]

        def _run(output_dir: Any, to_ts_dt: datetime) -> list[dict[str, Any]]:
            monkeypatch.setattr(runner, "get_connection", lambda: _PagingFakeConnection(rows))
            monkeypatch.setattr(runner, "fetch_asset_id", lambda **kw: 1)
            monkeypatch.setattr(runner, "resolve_config", lambda timeframe: cfg)
            exit_code = runner.main(
                [
                    "--symbol", "BTC",
                    "--timeframe", "1h",
                    "--from-ts", from_ts_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "--to-ts", to_ts_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "--output-dir", str(output_dir),
                ]
            )
            assert exit_code == 0
            [episodes_path] = list(Path(output_dir).rglob("episodes_v1.json"))
            return json.loads(episodes_path.read_text(encoding="utf-8"))

        episodes_near = _run(tmp_path / "near", to_ts_near)
        episodes_far = _run(tmp_path / "far", to_ts_far)

        [match_near] = [
            e for e in episodes_near if e["feature"]["episode_id"] == reference.feature.episode_id
        ]
        [match_far] = [
            e for e in episodes_far if e["feature"]["episode_id"] == reference.feature.episode_id
        ]

        assert match_near["feature"] == match_far["feature"]
        assert match_near["labels"] == match_far["labels"]


class TestCliValidation:
    def _args(self, **overrides: Any) -> argparse.Namespace:
        base: dict[str, Any] = dict(
            venue="bitvavo",
            symbol="BTC",
            timeframe="1h",
            from_ts="2026-01-01 00:00:00",
            to_ts="2026-01-02 00:00:00",
            episode_stride_candles=1,
            max_episodes=None,
            output_dir=runner.DEFAULT_OUTPUT_DIR,
            chunk_size_candles=runner.DEFAULT_CHUNK_CANDLES,
        )
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_valid_args_pass(self) -> None:
        runner.validate_args(self._args())  # no raise

    def test_non_positive_stride_rejected(self) -> None:
        with pytest.raises(ValueError, match="episode-stride-candles"):
            runner.validate_args(self._args(episode_stride_candles=0))

    def test_negative_stride_rejected(self) -> None:
        with pytest.raises(ValueError, match="episode-stride-candles"):
            runner.validate_args(self._args(episode_stride_candles=-3))

    def test_negative_max_episodes_rejected(self) -> None:
        with pytest.raises(ValueError, match="max-episodes"):
            runner.validate_args(self._args(max_episodes=-1))

    def test_max_episodes_zero_is_valid(self) -> None:
        runner.validate_args(self._args(max_episodes=0))  # no raise

    def test_max_episodes_none_is_valid(self) -> None:
        runner.validate_args(self._args(max_episodes=None))  # no raise

    def test_from_ts_after_to_ts_rejected(self) -> None:
        with pytest.raises(ValueError, match="from-ts"):
            runner.validate_args(
                self._args(from_ts="2026-01-02 00:00:00", to_ts="2026-01-01 00:00:00")
            )

    def test_equal_from_ts_to_ts_rejected(self) -> None:
        with pytest.raises(ValueError, match="from-ts"):
            runner.validate_args(
                self._args(from_ts="2026-01-01 00:00:00", to_ts="2026-01-01 00:00:00")
            )

    def test_non_positive_chunk_size_rejected(self) -> None:
        with pytest.raises(ValueError, match="chunk-size-candles"):
            runner.validate_args(self._args(chunk_size_candles=0))

    def test_invalid_bounds_never_reach_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom() -> Any:
            raise AssertionError("DB helper must not be called for invalid CLI args")

        monkeypatch.setattr(runner, "get_connection", _boom)
        exit_code = runner.main(
            [
                "--symbol", "BTC",
                "--timeframe", "1h",
                "--from-ts", "2026-01-02 00:00:00",
                "--to-ts", "2026-01-01 00:00:00",
            ]
        )
        assert exit_code == 2

    def test_invalid_stride_never_reaches_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom() -> Any:
            raise AssertionError("DB helper must not be called for invalid CLI args")

        monkeypatch.setattr(runner, "get_connection", _boom)
        exit_code = runner.main(
            [
                "--symbol", "BTC",
                "--timeframe", "1h",
                "--from-ts", "2026-01-01 00:00:00",
                "--to-ts", "2026-01-02 00:00:00",
                "--episode-stride-candles", "0",
            ]
        )
        assert exit_code == 2

    def test_invalid_max_episodes_never_reaches_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom() -> Any:
            raise AssertionError("DB helper must not be called for invalid CLI args")

        monkeypatch.setattr(runner, "get_connection", _boom)
        exit_code = runner.main(
            [
                "--symbol", "BTC",
                "--timeframe", "1h",
                "--from-ts", "2026-01-01 00:00:00",
                "--to-ts", "2026-01-02 00:00:00",
                "--max-episodes", "-1",
            ]
        )
        assert exit_code == 2


class TestParserErrorHandling:
    """Regression coverage for the #727 blocker: argparse's own SystemExit(2)

    bypassed the FAILED reason=invalid_arguments terminal contract before
    main() ever reached validate_args(). main() must own the full CLI
    terminal contract for BOTH argparse-level parse failures and
    validate_args()-level semantic failures.
    """

    def test_parse_args_raises_arg_parse_error_not_system_exit(self) -> None:
        with pytest.raises(runner.ArgParseError):
            runner.parse_args(["--timeframe", "1h"])  # missing required --symbol etc.

    def test_missing_symbol_produces_single_failed_line_exit_2(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = runner.main(
            [
                "--timeframe", "1h",
                "--from-ts", "2026-01-01 00:00:00",
                "--to-ts", "2026-01-02 00:00:00",
            ]
        )
        out = capsys.readouterr().out
        assert exit_code == 2
        assert out.count("FAILED") == 1
        assert "FAILED reason=invalid_arguments" in out
        assert "Traceback" not in out
        assert "STARTED" not in out
        assert "FINISHED" not in out

    def test_invalid_timeframe_choice_produces_single_failed_line_exit_2(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = runner.main(
            [
                "--symbol", "BTC",
                "--timeframe", "1d",  # not in choices=["1h", "4h"]
                "--from-ts", "2026-01-01 00:00:00",
                "--to-ts", "2026-01-02 00:00:00",
            ]
        )
        out = capsys.readouterr().out
        assert exit_code == 2
        assert out.count("FAILED") == 1
        assert "FAILED reason=invalid_arguments" in out
        assert "STARTED" not in out
        assert "FINISHED" not in out

    def test_malformed_numeric_argument_produces_single_failed_line_exit_2(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = runner.main(
            [
                "--symbol", "BTC",
                "--timeframe", "1h",
                "--from-ts", "2026-01-01 00:00:00",
                "--to-ts", "2026-01-02 00:00:00",
                "--max-episodes", "not-a-number",
            ]
        )
        out = capsys.readouterr().out
        assert exit_code == 2
        assert out.count("FAILED") == 1
        assert "FAILED reason=invalid_arguments" in out
        assert "STARTED" not in out
        assert "FINISHED" not in out

    def test_parser_failure_never_calls_get_connection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom() -> Any:
            raise AssertionError("DB helper must not be called for a parser failure")

        monkeypatch.setattr(runner, "get_connection", _boom)
        exit_code = runner.main(["--timeframe", "1h"])  # missing required flags
        assert exit_code == 2

    def test_help_exits_zero_and_does_not_produce_failed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc_info:
            runner.main(["--help"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "usage" in out.lower()
        assert "FAILED" not in out
        assert "STARTED" not in out

    def test_help_never_calls_get_connection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom() -> Any:
            raise AssertionError("DB helper must not be called for --help")

        monkeypatch.setattr(runner, "get_connection", _boom)
        with pytest.raises(SystemExit) as exc_info:
            runner.main(["--help"])
        assert exc_info.value.code == 0


class TestMaxEpisodesZero:
    def test_max_episodes_zero_yields_no_episodes(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        cfg = _small_cfg()
        candles = _synthetic_bullish_series(start)
        records = build_episodes(
            symbol="TST",
            venue="bitvavo",
            candles=candles,
            cfg=cfg,
            episode_stride_candles=5,
            max_episodes=0,
        )
        assert records == []

    def test_max_episodes_one_yields_exactly_one_episode(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        cfg = _small_cfg()
        candles = _synthetic_bullish_series(start)
        records = build_episodes(
            symbol="TST",
            venue="bitvavo",
            candles=candles,
            cfg=cfg,
            episode_stride_candles=5,
            max_episodes=1,
        )
        assert len(records) == 1


class TestEmitWindowFilter:
    def test_warmup_region_candles_participate_but_are_not_emitted(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        cfg = _small_cfg()
        candles = _synthetic_bullish_series(start)

        all_records = build_episodes(
            symbol="TST", venue="bitvavo", candles=candles, cfg=cfg, episode_stride_candles=5
        )
        assert len(all_records) > 2

        # Cut the requested window at the midpoint of the unfiltered result
        # set: everything before it becomes "warmup region" (candles that
        # still feed window/EMA/ATR reconstruction for later as-of candles
        # but must not themselves be emitted).
        cutoff = all_records[len(all_records) // 2].feature.map_creation_ts_utc
        emit_to = all_records[-1].feature.map_creation_ts_utc + timedelta(days=3650)

        filtered_records = build_episodes(
            symbol="TST",
            venue="bitvavo",
            candles=candles,
            cfg=cfg,
            episode_stride_candles=5,
            emit_from_ts_utc=cutoff,
            emit_to_ts_utc=emit_to,
        )
        expected = [r for r in all_records if r.feature.map_creation_ts_utc >= cutoff]
        assert 0 < len(filtered_records) < len(all_records)
        assert len(filtered_records) == len(expected)
        assert [r.feature.episode_id for r in filtered_records] == [r.feature.episode_id for r in expected]
        assert all(r.feature.map_creation_ts_utc >= cutoff for r in filtered_records)
        assert all(r.feature.map_creation_ts_utc < emit_to for r in filtered_records)


class TestSignalState:
    def test_signal_state_tracks_signum(self) -> None:
        state = runner._SignalState()
        assert not state.triggered
        assert state.signum is None

        state.handle(signal.SIGINT, None)
        assert state.triggered
        assert state.signum == signal.SIGINT

    def test_signal_state_sigterm(self) -> None:
        state = runner._SignalState()
        state.handle(signal.SIGTERM, None)
        assert state.triggered
        assert state.signum == signal.SIGTERM


class TestRunIdentityExcludesOperationalParams:
    def test_compute_run_id_signature_excludes_chunk_size_and_progress_cadence(self) -> None:
        params = inspect.signature(runner.compute_run_id).parameters
        assert "chunk_size" not in params
        assert "chunk_size_candles" not in params
        assert "progress_interval_candles" not in params
        # source_input_sha256 IS part of identity -- see TestSourceInputFingerprint.
        assert "source_input_sha256" in params

    def test_manifest_carries_warmup_and_chunk_provenance_alongside_shared_run_id(self) -> None:
        # A fixed run_id (computed once, as the runner does) can be reused
        # across manifests whose only difference is provenance-only fields
        # (warmup_candle_count, chunk_size_candles) -- those fields are
        # recorded for observability but are not independently re-derived
        # from run_id, so this does not by itself prove they can vary
        # freely; see TestSourceInputFingerprint for the load-bearing proof
        # that only source *content* (not chunk size / progress cadence)
        # changes source_input_sha256/run_id.
        run_id = runner.compute_run_id(
            venue="bitvavo",
            symbol="BTC",
            timeframe="4h",
            from_ts="2026-01-01 00:00:00",
            to_ts="2026-06-01 00:00:00",
            episode_stride_candles=1,
            max_episodes=None,
            source_input_sha256="a" * 64,
        )
        manifest_a = runner.build_manifest(
            run_id=run_id,
            venue="bitvavo",
            symbol="BTC",
            timeframe="4h",
            from_ts="2026-01-01 00:00:00",
            to_ts="2026-06-01 00:00:00",
            episode_stride_candles=1,
            max_episodes=None,
            candle_count=100,
            episode_count=1,
            episodes_sha256="a" * 64,
            source_input_sha256="a" * 64,
            warmup_candle_count=179,
            chunk_size_candles=1000,
        )
        manifest_b = runner.build_manifest(
            run_id=run_id,
            venue="bitvavo",
            symbol="BTC",
            timeframe="4h",
            from_ts="2026-01-01 00:00:00",
            to_ts="2026-06-01 00:00:00",
            episode_stride_candles=1,
            max_episodes=None,
            candle_count=100,
            episode_count=1,
            episodes_sha256="a" * 64,
            source_input_sha256="a" * 64,
            warmup_candle_count=179,
            chunk_size_candles=5000,
        )
        assert manifest_a["run_id"] == manifest_b["run_id"] == run_id
        assert manifest_a["warmup_candle_count"] == 179
        assert manifest_b["warmup_candle_count"] == 179
        assert manifest_a["chunk_size_candles"] == 1000
        assert manifest_b["chunk_size_candles"] == 5000


class TestSourceInputFingerprint:
    """Regression coverage for the latest #727 blocker: compute_run_id must

    identify the actual PIT source candle content, not just CLI/config
    parameters, so identical CLI arguments with different underlying
    obs_market_candle content can never collide at the same immutable path.
    """

    def _candles(self, start: datetime, n: int) -> list[HistoricalCandle]:
        return [
            _candle(start + timedelta(hours=i), 100 + i, 101 + i, 99 + i, 100.5 + i)
            for i in range(n)
        ]

    def _base_kwargs(self) -> dict[str, Any]:
        return dict(
            venue="bitvavo",
            symbol="BTC",
            timeframe="1h",
            from_ts="2026-01-01 00:00:00",
            to_ts="2026-01-02 00:00:00",
            episode_stride_candles=1,
            max_episodes=None,
        )

    def test_canonical_fingerprint_fields(self) -> None:
        source = inspect.getsource(runner._candle_fingerprint_fields)
        for field in (
            "symbol",
            "venue",
            "interval_code",
            "open_ts_utc",
            "close_ts_utc",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
        ):
            assert f'"{field}"' in source

    def test_identical_cli_and_identical_source_content_same_fingerprint_and_run_id(
        self,
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        warmup = self._candles(start, 5)
        requested = self._candles(start + timedelta(hours=5), 10)
        tail = self._candles(start + timedelta(hours=15), 5)
        candles_a = warmup + requested + tail
        candles_b = self._candles(start, 5) + self._candles(
            start + timedelta(hours=5), 10
        ) + self._candles(start + timedelta(hours=15), 5)

        fp_a = runner.compute_source_input_sha256(candles_a)
        fp_b = runner.compute_source_input_sha256(candles_b)
        assert fp_a == fp_b

        kwargs = self._base_kwargs()
        run_id_a = runner.compute_run_id(**kwargs, source_input_sha256=fp_a)
        run_id_b = runner.compute_run_id(**kwargs, source_input_sha256=fp_b)
        assert run_id_a == run_id_b

    def test_changed_warmup_candle_changes_fingerprint_and_run_id(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        warmup = self._candles(start, 5)
        requested = self._candles(start + timedelta(hours=5), 10)
        tail = self._candles(start + timedelta(hours=15), 5)
        baseline = warmup + requested + tail

        mutated_warmup = list(warmup)
        mutated_warmup[0] = _candle(
            mutated_warmup[0].open_ts_utc, 999, 999.5, 998.5, 999
        )
        mutated = mutated_warmup + requested + tail

        fp_baseline = runner.compute_source_input_sha256(baseline)
        fp_mutated = runner.compute_source_input_sha256(mutated)
        assert fp_baseline != fp_mutated

        kwargs = self._base_kwargs()
        run_id_baseline = runner.compute_run_id(**kwargs, source_input_sha256=fp_baseline)
        run_id_mutated = runner.compute_run_id(**kwargs, source_input_sha256=fp_mutated)
        assert run_id_baseline != run_id_mutated

    def test_changed_requested_window_candle_changes_fingerprint_and_run_id(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        warmup = self._candles(start, 5)
        requested = self._candles(start + timedelta(hours=5), 10)
        tail = self._candles(start + timedelta(hours=15), 5)
        baseline = warmup + requested + tail

        mutated_requested = list(requested)
        mutated_requested[3] = _candle(
            mutated_requested[3].open_ts_utc, 999, 999.5, 998.5, 999
        )
        mutated = warmup + mutated_requested + tail

        fp_baseline = runner.compute_source_input_sha256(baseline)
        fp_mutated = runner.compute_source_input_sha256(mutated)
        assert fp_baseline != fp_mutated

        kwargs = self._base_kwargs()
        run_id_baseline = runner.compute_run_id(**kwargs, source_input_sha256=fp_baseline)
        run_id_mutated = runner.compute_run_id(**kwargs, source_input_sha256=fp_mutated)
        assert run_id_baseline != run_id_mutated

    def test_changed_forward_tail_candle_changes_fingerprint_and_run_id(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        warmup = self._candles(start, 5)
        requested = self._candles(start + timedelta(hours=5), 10)
        tail = self._candles(start + timedelta(hours=15), 5)
        baseline = warmup + requested + tail

        mutated_tail = list(tail)
        mutated_tail[-1] = _candle(
            mutated_tail[-1].open_ts_utc, 999, 999.5, 998.5, 999
        )
        mutated = warmup + requested + mutated_tail

        fp_baseline = runner.compute_source_input_sha256(baseline)
        fp_mutated = runner.compute_source_input_sha256(mutated)
        assert fp_baseline != fp_mutated

        kwargs = self._base_kwargs()
        run_id_baseline = runner.compute_run_id(**kwargs, source_input_sha256=fp_baseline)
        run_id_mutated = runner.compute_run_id(**kwargs, source_input_sha256=fp_mutated)
        assert run_id_baseline != run_id_mutated

    def test_chunk_size_and_progress_cadence_do_not_affect_fingerprint_or_run_id(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        # Same underlying candle content, fetched via the full runner
        # pipeline with two different --chunk-size-candles values (which
        # only change how many DB round trips fetch_candles makes, never
        # which candles it returns) and two different BUILDING progress
        # cadences: source_input_sha256 and run_id must be identical.
        start = datetime(2026, 1, 1, tzinfo=UTC)
        candles = _synthetic_bullish_series(start)
        rows = [_candle_to_row(c) for c in candles]

        def _run(output_dir: Any, chunk_size: int, progress_interval: int) -> dict[str, Any]:
            monkeypatch.setattr(runner, "get_connection", lambda: _PagingFakeConnection(rows))
            monkeypatch.setattr(runner, "fetch_asset_id", lambda **kw: 1)
            monkeypatch.setattr(runner, "DEFAULT_BUILD_PROGRESS_INTERVAL_CANDLES", progress_interval)
            exit_code = runner.main(
                [
                    "--symbol", "BTC",
                    "--timeframe", "1h",
                    "--from-ts", start.strftime("%Y-%m-%d %H:%M:%S"),
                    "--to-ts", (start + timedelta(hours=40)).strftime("%Y-%m-%d %H:%M:%S"),
                    "--output-dir", str(output_dir),
                    "--chunk-size-candles", str(chunk_size),
                ]
            )
            assert exit_code == 0
            [manifest_path] = list(Path(output_dir).rglob("manifest_v1.json"))
            return json.loads(manifest_path.read_text(encoding="utf-8"))

        manifest_a = _run(tmp_path / "a", chunk_size=5, progress_interval=1)
        manifest_b = _run(tmp_path / "b", chunk_size=1000, progress_interval=500)

        assert manifest_a["source_input_sha256"] == manifest_b["source_input_sha256"]
        assert manifest_a["run_id"] == manifest_b["run_id"]
        assert manifest_a["chunk_size_candles"] != manifest_b["chunk_size_candles"]

    def test_fingerprint_stable_across_repeated_calls(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        candles = self._candles(start, 20)
        fingerprints = {runner.compute_source_input_sha256(candles) for _ in range(5)}
        assert len(fingerprints) == 1

    def test_run_id_recomputable_from_manifest_after_full_pipeline_run(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        candles = _synthetic_bullish_series(start)
        rows = [_candle_to_row(c) for c in candles]
        monkeypatch.setattr(runner, "get_connection", lambda: _PagingFakeConnection(rows))
        monkeypatch.setattr(runner, "fetch_asset_id", lambda **kw: 1)

        exit_code = runner.main(
            [
                "--symbol", "BTC",
                "--timeframe", "1h",
                "--from-ts", start.strftime("%Y-%m-%d %H:%M:%S"),
                "--to-ts", (start + timedelta(hours=40)).strftime("%Y-%m-%d %H:%M:%S"),
                "--output-dir", str(tmp_path),
            ]
        )
        assert exit_code == 0
        [manifest_path] = list(tmp_path.rglob("manifest_v1.json"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        recomputed = runner.compute_run_id(
            venue=manifest["venue"],
            symbol=manifest["symbol"],
            timeframe=manifest["timeframe"],
            from_ts=manifest["source_from_ts"],
            to_ts=manifest["source_to_ts"],
            episode_stride_candles=manifest["episode_stride_candles"],
            max_episodes=manifest["max_episodes"],
            source_input_sha256=manifest["source_input_sha256"],
        )
        assert recomputed == manifest["run_id"]


class TestBuildProgressHook:
    """build_episodes' optional deterministic progress/cancellation hooks (#727)."""

    def test_default_hooks_are_none_and_side_effect_free(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        cfg = _small_cfg()
        candles = _synthetic_bullish_series(start)
        records = build_episodes(
            symbol="TST", venue="bitvavo", candles=candles, cfg=cfg, episode_stride_candles=5
        )
        assert len(records) > 0

    def test_on_progress_called_at_configured_interval(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        cfg = _small_cfg()
        candles = _synthetic_bullish_series(start)
        calls: list[tuple[int, int]] = []
        build_episodes(
            symbol="TST",
            venue="bitvavo",
            candles=candles,
            cfg=cfg,
            episode_stride_candles=5,
            on_progress=lambda processed, total: calls.append((processed, total)),
            progress_interval_candles=10,
        )
        assert len(calls) > 0
        assert all(processed % 10 == 0 for processed, _total in calls)
        assert calls == sorted(calls)
        assert all(total == len(candles) for _processed, total in calls)

    def test_should_stop_raises_build_cancelled_at_safe_boundary(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        cfg = _small_cfg()
        candles = _synthetic_bullish_series(start)
        baseline = build_episodes(
            symbol="TST", venue="bitvavo", candles=candles, cfg=cfg, episode_stride_candles=5
        )

        with pytest.raises(substrate.BuildCancelled) as exc_info:
            build_episodes(
                symbol="TST",
                venue="bitvavo",
                candles=candles,
                cfg=cfg,
                episode_stride_candles=5,
                should_stop=lambda: True,
                progress_interval_candles=10,
            )
        assert isinstance(exc_info.value.records, list)
        assert len(exc_info.value.records) < len(baseline)

    def test_should_stop_not_polled_without_progress_interval_elapsed(self) -> None:
        # should_stop() must only be polled at the deterministic cadence, not
        # on every single attempted position -- a should_stop that always
        # returns True but with an interval larger than the series still
        # completes if the cadence boundary is never reached.
        start = datetime(2026, 1, 1, tzinfo=UTC)
        cfg = _small_cfg()
        candles = _synthetic_bullish_series(start)
        attempted_positions = len(candles) - (cfg.min_window_candles - 1)

        records = build_episodes(
            symbol="TST",
            venue="bitvavo",
            candles=candles,
            cfg=cfg,
            episode_stride_candles=5,
            should_stop=lambda: True,
            progress_interval_candles=attempted_positions + 1000,
        )
        assert len(records) > 0

    def test_output_byte_identical_with_and_without_noncancelling_progress_hook(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        cfg = _small_cfg()
        candles = _synthetic_bullish_series(start)
        baseline = build_episodes(
            symbol="TST", venue="bitvavo", candles=candles, cfg=cfg, episode_stride_candles=5
        )
        with_hook = build_episodes(
            symbol="TST",
            venue="bitvavo",
            candles=candles,
            cfg=cfg,
            episode_stride_candles=5,
            on_progress=lambda processed, total: None,
            should_stop=lambda: False,
            progress_interval_candles=7,
        )
        assert episodes_to_json(baseline) == episodes_to_json(with_hook)


class _RunnerHarness:
    """Shared fake-DB/CLI-args scaffolding for full main() integration tests."""

    @staticmethod
    def valid_args(tmp_path: Any) -> list[str]:
        return [
            "--symbol", "BTC",
            "--timeframe", "1h",
            "--from-ts", "2026-01-01 00:00:00",
            "--to-ts", "2026-01-02 00:00:00",
            "--output-dir", str(tmp_path),
        ]

    @staticmethod
    def patch_successful_fetch(
        monkeypatch: pytest.MonkeyPatch, candles: list[HistoricalCandle]
    ) -> None:
        monkeypatch.setattr(runner, "fetch_asset_id", lambda **kw: 1)
        monkeypatch.setattr(runner, "fetch_warmup_candles", lambda **kw: [])
        monkeypatch.setattr(runner, "fetch_candles", lambda **kw: candles)
        monkeypatch.setattr(runner, "fetch_forward_tail_candles", lambda **kw: [])


class TestBuildingCancellationIntegration:
    """Runner-level wiring of build_episodes' should_stop/on_progress hooks."""

    def test_sigint_during_building_stops_before_write(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        candles = _synthetic_bullish_series(start)
        _RunnerHarness.patch_successful_fetch(monkeypatch, candles)
        monkeypatch.setattr(runner, "DEFAULT_BUILD_PROGRESS_INTERVAL_CANDLES", 1)

        real_build_episodes = substrate.build_episodes

        def _signal_then_build(**kwargs: Any) -> list[Any]:
            # Deliver a real SIGINT to this process before delegating to the
            # real build_episodes -- main()'s real signal handler (installed
            # by main() itself) sets _SignalState.signum synchronously, so
            # the `should_stop` closure main() wired in observes it at the
            # very first cadence boundary (progress_interval_candles=1).
            os.kill(os.getpid(), signal.SIGINT)
            return real_build_episodes(**kwargs)

        monkeypatch.setattr(runner, "build_episodes", _signal_then_build)

        write_calls: list[Any] = []
        monkeypatch.setattr(
            runner,
            "publish_immutable_run",
            lambda **kw: write_calls.append(kw) or ("sha", "sha"),
        )

        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        try:
            exit_code = runner.main(_RunnerHarness.valid_args(tmp_path))
        finally:
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)

        assert exit_code == 130
        assert write_calls == []
        assert list(tmp_path.rglob("*")) == []

        out = capsys.readouterr().out
        assert out.count("INTERRUPTED") == 1
        assert "FAILED" not in out
        assert "FINISHED" not in out
        assert f"signal={int(signal.SIGINT)}" in out

    def test_sigterm_during_building_returns_143(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        candles = _synthetic_bullish_series(start)
        _RunnerHarness.patch_successful_fetch(monkeypatch, candles)
        monkeypatch.setattr(runner, "DEFAULT_BUILD_PROGRESS_INTERVAL_CANDLES", 1)

        real_build_episodes = substrate.build_episodes

        def _signal_then_build(**kwargs: Any) -> list[Any]:
            os.kill(os.getpid(), signal.SIGTERM)
            return real_build_episodes(**kwargs)

        monkeypatch.setattr(runner, "build_episodes", _signal_then_build)
        monkeypatch.setattr(runner, "publish_immutable_run", lambda **kw: ("sha", "sha"))

        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        try:
            exit_code = runner.main(_RunnerHarness.valid_args(tmp_path))
        finally:
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)

        assert exit_code == 143
        out = capsys.readouterr().out
        assert out.count("INTERRUPTED") == 1
        assert f"signal={int(signal.SIGTERM)}" in out

    def test_build_episodes_receives_progress_and_stop_hooks(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        candles = _synthetic_bullish_series(start)
        _RunnerHarness.patch_successful_fetch(monkeypatch, candles)

        captured: dict[str, Any] = {}

        def _capturing_build_episodes(**kwargs: Any) -> list[Any]:
            captured.update(kwargs)
            return []

        monkeypatch.setattr(runner, "build_episodes", _capturing_build_episodes)
        monkeypatch.setattr(runner, "publish_immutable_run", lambda **kw: ("sha", "sha"))

        exit_code = runner.main(_RunnerHarness.valid_args(tmp_path))
        assert exit_code == 0
        assert callable(captured["on_progress"])
        assert callable(captured["should_stop"])
        assert captured["progress_interval_candles"] == runner.DEFAULT_BUILD_PROGRESS_INTERVAL_CANDLES
        assert captured["should_stop"]() is False


class TestFailedTerminalSummary:
    """Exactly-one-FAILED-line coverage for each operational failure path (#727)."""

    def test_asset_lookup_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def _boom(**kw: Any) -> int:
            raise ValueError("no asset found for symbol='BTC'")

        monkeypatch.setattr(runner, "fetch_asset_id", _boom)

        exit_code = runner.main(_RunnerHarness.valid_args(tmp_path))
        out = capsys.readouterr().out
        assert exit_code != 0
        assert out.count("FAILED") == 1
        assert "FAILED reason=asset_lookup_failed" in out
        assert "FINISHED" not in out
        assert list(tmp_path.rglob("*")) == []

    def test_source_fetch_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(runner, "fetch_asset_id", lambda **kw: 1)

        def _boom(**kw: Any) -> list[Any]:
            raise RuntimeError("db connection reset")

        monkeypatch.setattr(runner, "fetch_warmup_candles", _boom)

        exit_code = runner.main(_RunnerHarness.valid_args(tmp_path))
        out = capsys.readouterr().out
        assert exit_code != 0
        assert out.count("FAILED") == 1
        assert "FAILED reason=source_fetch_failed" in out
        assert "FINISHED" not in out
        assert list(tmp_path.rglob("*")) == []

    def test_forward_tail_fetch_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        candles = _synthetic_bullish_series(start)
        monkeypatch.setattr(runner, "fetch_asset_id", lambda **kw: 1)
        monkeypatch.setattr(runner, "fetch_warmup_candles", lambda **kw: [])
        monkeypatch.setattr(runner, "fetch_candles", lambda **kw: candles)

        def _boom(**kw: Any) -> list[Any]:
            raise RuntimeError("db connection reset")

        monkeypatch.setattr(runner, "fetch_forward_tail_candles", _boom)

        exit_code = runner.main(_RunnerHarness.valid_args(tmp_path))
        out = capsys.readouterr().out
        assert exit_code != 0
        assert out.count("FAILED") == 1
        assert "FAILED reason=source_fetch_failed" in out
        assert "FINISHED" not in out
        assert list(tmp_path.rglob("*")) == []

    def test_source_validation_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        dup = _candle(start, 1, 2, 0.5, 1.5)
        _RunnerHarness.patch_successful_fetch(monkeypatch, [dup, dup])

        exit_code = runner.main(_RunnerHarness.valid_args(tmp_path))
        out = capsys.readouterr().out
        assert exit_code != 0
        assert out.count("FAILED") == 1
        assert "FAILED reason=source_validation_failed" in out
        assert "FINISHED" not in out
        assert list(tmp_path.rglob("*")) == []

    def test_build_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        candles = _synthetic_bullish_series(start)
        _RunnerHarness.patch_successful_fetch(monkeypatch, candles)

        def _boom(**kw: Any) -> list[Any]:
            raise RuntimeError("unexpected build failure")

        monkeypatch.setattr(runner, "build_episodes", _boom)

        exit_code = runner.main(_RunnerHarness.valid_args(tmp_path))
        out = capsys.readouterr().out
        assert exit_code != 0
        assert out.count("FAILED") == 1
        assert "FAILED reason=build_failed" in out
        assert "FINISHED" not in out
        assert list(tmp_path.rglob("*")) == []

    def test_output_write_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        candles = _synthetic_bullish_series(start)
        _RunnerHarness.patch_successful_fetch(monkeypatch, candles)

        def _boom(*a: Any, **kw: Any) -> tuple[str, str]:
            raise ValueError("refusing to overwrite immutable output")

        monkeypatch.setattr(runner, "publish_immutable_run", _boom)

        exit_code = runner.main(_RunnerHarness.valid_args(tmp_path))
        out = capsys.readouterr().out
        assert exit_code != 0
        assert out.count("FAILED") == 1
        assert "FAILED reason=output_write_failed" in out
        assert "FINISHED" not in out
        assert list(tmp_path.rglob("*")) == []

    def test_output_write_conflict_leaves_existing_file_untouched(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        candles = _synthetic_bullish_series(start)
        _RunnerHarness.patch_successful_fetch(monkeypatch, candles)

        cfg_1h = resolve_config("1h")
        # patch_successful_fetch stubs warmup=[] / requested=candles /
        # forward_tail=[] -- match that exact source content here so the
        # run_id we precompute collides with the one main() computes
        # internally, producing a genuine immutable-path conflict.
        source_input_sha256 = runner.compute_source_input_sha256(candles)
        run_id = runner.compute_run_id(
            venue="bitvavo",
            symbol="BTC",
            timeframe="1h",
            from_ts="2026-01-01 00:00:00",
            to_ts="2026-01-02 00:00:00",
            episode_stride_candles=1,
            max_episodes=None,
            source_input_sha256=source_input_sha256,
        )
        conflict_dir = tmp_path / "bitvavo" / "BTC" / cfg_1h.interval_code / run_id
        conflict_dir.mkdir(parents=True)
        conflict_path = conflict_dir / "episodes_v1.json"
        conflict_path.write_text('{"pre-existing": "conflicting content"}\n', encoding="utf-8")

        exit_code = runner.main(_RunnerHarness.valid_args(tmp_path))
        out = capsys.readouterr().out

        assert exit_code != 0
        assert out.count("FAILED") == 1
        assert "FAILED reason=output_write_failed" in out
        assert "FINISHED" not in out
        # The pre-existing conflicting file must survive untouched, and no
        # manifest must ever be written since the conflict is detected on
        # the first (episodes) write.
        assert conflict_path.read_text(encoding="utf-8") == '{"pre-existing": "conflicting content"}\n'
        assert not (conflict_dir / "manifest_v1.json").exists()

    def test_invalid_arguments_still_single_failed_line(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = runner.main(
            [
                "--symbol", "BTC",
                "--timeframe", "1h",
                "--from-ts", "2026-01-02 00:00:00",
                "--to-ts", "2026-01-01 00:00:00",
            ]
        )
        out = capsys.readouterr().out
        assert exit_code == 2
        assert out.count("FAILED") == 1
        assert "FAILED reason=invalid_arguments" in out
        assert "FINISHED" not in out
