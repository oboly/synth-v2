"""
Tests for #555 historical PIT Fib/map episode substrate.

Pure Python — no DB, no broker, no network. Synthetic candle series only.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.market_data import fib_navigation_map_v1 as canonical_geometry
from src.research import historical_fib_map_episode_substrate_v1 as substrate
from src.research import run_historical_fib_map_episode_substrate_v1 as runner
from src.research.historical_fib_map_episode_substrate_v1 import (
    DIRECTION_BULLISH,
    LIFECYCLE_REASON_FORWARD_WINDOW_EXHAUSTED,
    LIFECYCLE_REASON_INVALIDATION_BREACHED,
    LIFECYCLE_REASON_SOURCE_DATA_EXHAUSTED,
    LIFECYCLE_REASON_TARGET1_REACHED,
    LIFECYCLE_REASON_TARGET2_REACHED,
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
    for _ in range(60):
        price += (200 - 90) / 60
        path.append(price)
    for _ in range(5):
        price -= 3
        path.append(price)
    for _ in range(60):
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
        min_candles=10,
        lookback_candles=180,
        forward_max_candles=200,
        ema_fast_span=5,
        ema_slow_span=10,
    )


def _first_admitted_feature(candles: list[HistoricalCandle], cfg: EpisodeConfig) -> tuple[int, EpisodeFeaturePayload]:
    for i in range(cfg.min_candles - 1, len(candles)):
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
        window = [_candle(t + timedelta(hours=i), 100, 101, 99, 100) for i in range(cfg.min_candles)]
        # Inject a candle timestamped after the nominal as-of (last element).
        window[3] = _candle(t + timedelta(hours=999), 100, 101, 99, 100)
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


class TestCanonicalGeometryReuse:
    def test_same_function_object_used_for_1h_and_4h(self) -> None:
        assert substrate.build_fib_navigation_map is canonical_geometry.build_fib_navigation_map
        cfg_1h = resolve_config("1h")
        cfg_4h = resolve_config("4h")
        assert cfg_1h.interval_code == "1h"
        assert cfg_4h.interval_code == "4h"
        # Both configs are consumed by the exact same builder function; there
        # is exactly one geometry engine reference in the module.
        assert substrate.GEOMETRY_ENGINE_MODULE == "src.market_data.fib_navigation_map_v1"
        assert substrate.GEOMETRY_ENGINE_FUNCTION == "build_fib_navigation_map"

    def test_no_second_fib_implementation_in_substrate_module(self) -> None:
        source = inspect.getsource(substrate)
        # The substrate module must not define its own level-price computation;
        # it may only look up labels already computed by the canonical engine.
        assert "def _build_levels" not in source
        assert "RETRACE_LEVELS" not in source
        assert "EXTENSION_LEVELS" not in source

    def test_feature_levels_match_direct_canonical_call(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        cfg = _small_cfg()
        candles = _synthetic_bullish_series(start)
        i, feature = _first_admitted_feature(candles, cfg)
        window = candles[max(0, i - cfg.lookback_candles + 1) : i + 1]
        fib_candles = [c.to_fib_nav_candle() for c in window]
        direct_map = canonical_geometry.build_fib_navigation_map(
            candles=fib_candles,
            current_price=window[-1].close_price,
            now_utc=window[-1].close_ts_utc,
            prior=None,
            direction=DIRECTION_BULLISH,
            pivot_span=cfg.pivot_span,
            min_candles=cfg.min_candles,
            stale_after=cfg.stale_after,
        )
        assert feature.anchor_low_price == direct_map.anchor_low
        assert feature.anchor_high_price == direct_map.anchor_high


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
            geometry_engine_module=substrate.GEOMETRY_ENGINE_MODULE,
            geometry_engine_function=substrate.GEOMETRY_ENGINE_FUNCTION,
            trend_engine_name="test",
            trend_engine_version="0",
            map_creation_ts_utc=ts,
            source_candle_first_ts_utc=ts,
            source_candle_last_ts_utc=ts,
            source_candle_count=10,
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
        )

    def _forward(self, prices: list[float], *, feature: EpisodeFeaturePayload) -> list[HistoricalCandle]:
        t = feature.map_creation_ts_utc
        candles = []
        for p in prices:
            t += timedelta(hours=1)
            candles.append(_candle(t, p, p + 0.5, p - 0.5, p))
        return candles

    def test_target1_reached(self) -> None:
        feature = self._feature()
        forward = self._forward([100, 105, 113], feature=feature)
        labels = build_episode_labels(feature=feature, forward_candles=forward, cfg=_small_cfg())
        assert labels.lifecycle_transition_reason == LIFECYCLE_REASON_TARGET1_REACHED
        assert labels.target1_ts_utc == forward[2].close_ts_utc

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
            venue="bitvavo",
            symbol="TST",
            timeframe="1h",
            from_ts="2026-01-01",
            to_ts="2026-01-02",
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
