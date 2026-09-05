from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.features.evidence_contract_v1 import (
    EffectiveHorizon,
    EvidenceStatus,
    FreshnessState,
    SignalHorizonV1Evidence,
    UNMEASURED_LIFECYCLE,
)
from src.features.eth_btc_leadership_snapshot_v1 import EthBtcLeadershipSnapshot
from src.features.ma_breadth_snapshot_v1 import MABreadthSnapshot
from src.features.momentum_evidence_snapshot_v1 import MomentumEvidenceSnapshot
from src.reporting.regime_evidence_matrix_v1 import (
    FAMILY_BREADTH,
    FAMILY_ETH_BTC_LEADERSHIP,
    FAMILY_MACRO_LIQUIDITY,
    FAMILY_MOMENTUM,
    FAMILY_VOLATILITY,
    REASON_NO_CANONICAL_OWNER,
    STATUS_INSUFFICIENT_DATA,
    RegimeEvidenceCellV1,
    build_matrix,
    from_eth_btc_leadership,
    from_ma_breadth,
    from_momentum,
    from_signal_horizon,
    unavailable_cell,
)


ASOF = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
EVALUATED = datetime(2026, 9, 5, 0, 30, tzinfo=UTC)


def _rotation_evidence(asset_id: int) -> SignalHorizonV1Evidence:
    return SignalHorizonV1Evidence(
        family="ROTATION",
        component="PER_ASSET_PRESSURE",
        market="asset",
        status=EvidenceStatus.VALID,
        model_id="market_rotation_pressure_v1",
        model_version="1.0",
        input_interval="1h",
        lookback_horizon="24h+168h",
        effective_horizon=EffectiveHorizon.REGIME,
        observed_lifecycle=UNMEASURED_LIFECYCLE,
        asof_ts=ASOF,
        freshness=FreshnessState.FRESH,
        provenance={"venue": "bitvavo", "asset_id": asset_id},
        raw={"score_total": Decimal("12.5"), "pressure_state": "ROTATION_IN"},
        reason_codes=("UPSTREAM_REASON",),
    )


def test_signal_horizon_fields_are_copied_verbatim() -> None:
    evidence = _rotation_evidence(1)

    cell = from_signal_horizon(evidence)

    assert cell.status == evidence.status
    assert cell.freshness == evidence.freshness
    assert cell.raw == evidence.raw
    assert cell.reason_codes == evidence.reason_codes
    assert cell.effective_horizon == evidence.effective_horizon
    assert cell.observed_lifecycle == evidence.observed_lifecycle
    assert cell.scope_key == "venue=bitvavo;asset_id=1"


def test_signal_horizon_generic_asset_market_supports_multiple_assets() -> None:
    btc = from_signal_horizon(_rotation_evidence(1))
    eth = from_signal_horizon(_rotation_evidence(2))

    matrix = build_matrix(evaluated_at=EVALUATED, cells=[eth, btc])

    assert len(matrix.cells) == 2
    assert tuple(cell.scope_key for cell in matrix.cells) == (
        "venue=bitvavo;asset_id=1",
        "venue=bitvavo;asset_id=2",
    )


def test_momentum_exposes_raw_values_without_categorical_state() -> None:
    snapshot = MomentumEvidenceSnapshot(
        venue="bitvavo",
        market="BTC-EUR",
        asset_id=1,
        asof_ts=ASOF,
        input_interval="4h",
        lookback_horizon="35 bars @ 4h",
        effective_horizon=EffectiveHorizon.UNKNOWN,
        observed_lifecycle_status="UNMEASURED",
        fast_ema_period=12,
        slow_ema_period=26,
        signal_ema_period=9,
        macd_value=Decimal("1.1"),
        signal_value=Decimal("0.9"),
        histogram_value=Decimal("0.2"),
        histogram_delta=Decimal("0.05"),
        freshness=FreshnessState.UNKNOWN,
        data_quality="OK",
        model_id="momentum_evidence_snapshot",
        model_version="1.0",
        status=EvidenceStatus.INSUFFICIENT_DATA,
        reason_codes=("FRESHNESS_NOT_OWNER_DEFINED", "UNMAPPED_HORIZON"),
        provenance={"venue": "bitvavo", "asset_id": 1},
    )

    cell = from_momentum(snapshot)

    assert cell.family == FAMILY_MOMENTUM
    assert cell.status == snapshot.status
    assert cell.observed_lifecycle == snapshot.observed_lifecycle_status
    assert cell.raw["macd_value"] == Decimal("1.1")
    assert cell.raw["histogram_delta"] == Decimal("0.05")
    assert "state" not in cell.raw
    assert "EARLY_UP" not in repr(cell)
    assert "MOMENTUM_REVERSAL" not in repr(cell)


def test_breadth_unknown_horizon_and_freshness_are_not_upgraded() -> None:
    snapshot = MABreadthSnapshot(
        asof_ts_utc=ASOF,
        venue="bitvavo",
        universe_id="publication_cohort",
        universe_version="v1",
        universe_hash="abc",
        input_interval="4h",
        lookback_horizon="50 bars @ 4h",
        effective_horizon="UNKNOWN",
        freshness_status="UNKNOWN",
        model_id="ma_breadth_snapshot",
        model_version="1.0",
        data_status="AVAILABLE",
        eligible_count=100,
        evaluated_count=90,
        insufficient_history_count=5,
        stale_constituent_count=5,
        coverage_pct=Decimal("90"),
        universe_above_sma50_count=54,
        universe_above_sma50_pct=Decimal("60"),
    )

    cell = from_ma_breadth(snapshot)

    assert cell.family == FAMILY_BREADTH
    assert cell.status == "AVAILABLE"
    assert cell.freshness == "UNKNOWN"
    assert cell.effective_horizon == "UNKNOWN"
    assert cell.observed_lifecycle is None
    assert cell.raw["universe_above_sma50_pct"] == Decimal("60")
    assert "EXPANDING" not in repr(cell)


def test_eth_btc_raw_comparison_does_not_infer_leadership_state() -> None:
    snapshot = EthBtcLeadershipSnapshot(
        asof_ts_utc=ASOF,
        venue="bitvavo",
        btc_market="BTC-EUR",
        eth_market="ETH-EUR",
        input_interval="1d",
        lookback_horizon="24h",
        effective_horizon="UNKNOWN",
        model_id="eth_btc_leadership_snapshot",
        model_version="1.0",
        freshness="FRESH",
        data_status="AVAILABLE",
        btc_return_pct=Decimal("1.0"),
        eth_return_pct=Decimal("2.0"),
        eth_minus_btc_return_pct=Decimal("1.0"),
        eth_btc_ratio_start=Decimal("0.05"),
        eth_btc_ratio_end=Decimal("0.0505"),
        eth_btc_ratio_change_pct=Decimal("1.0"),
        reason_codes=("UNMAPPED_HORIZON",),
        provenance={"btc_asset_id": 1, "eth_asset_id": 2},
    )

    cell = from_eth_btc_leadership(snapshot)

    assert cell.family == FAMILY_ETH_BTC_LEADERSHIP
    assert cell.status == "AVAILABLE"
    assert cell.raw["eth_minus_btc_return_pct"] == Decimal("1.0")
    assert "ETH_LED" not in repr(cell)
    assert "BTC_LED" not in repr(cell)


def test_unavailable_family_is_explicit_contract_gap_not_market_state() -> None:
    macro = unavailable_cell(family=FAMILY_MACRO_LIQUIDITY, detail="#305 not promoted")
    volatility = unavailable_cell(family=FAMILY_VOLATILITY)

    assert macro.status == STATUS_INSUFFICIENT_DATA
    assert macro.reason_codes == (REASON_NO_CANONICAL_OWNER,)
    assert macro.raw == {}
    assert macro.provenance["detail"] == "#305 not promoted"
    assert volatility.status == STATUS_INSUFFICIENT_DATA


def test_matrix_order_is_deterministic_and_family_lookup_is_read_only() -> None:
    cells = [
        unavailable_cell(family=FAMILY_VOLATILITY),
        unavailable_cell(family=FAMILY_MACRO_LIQUIDITY),
    ]

    matrix = build_matrix(evaluated_at=EVALUATED, cells=reversed(cells))

    assert tuple(cell.family for cell in matrix.cells) == (
        FAMILY_MACRO_LIQUIDITY,
        FAMILY_VOLATILITY,
    )
    assert matrix.by_family(FAMILY_VOLATILITY) == (matrix.cells[1],)


def _test_cell(*, input_interval: str | None, lookback_horizon: str | None) -> RegimeEvidenceCellV1:
    return RegimeEvidenceCellV1(
        family="TEST",
        component="COMPONENT",
        market="asset",
        scope_key="venue=bitvavo;asset_id=1",
        status="AVAILABLE",
        freshness=None,
        asof_ts=ASOF,
        model_id=None,
        model_version=None,
        input_interval=input_interval,
        lookback_horizon=lookback_horizon,
        effective_horizon=None,
    )


def test_matrix_order_handles_mixed_null_and_string_optional_identity_fields() -> None:
    no_interval = _test_cell(input_interval=None, lookback_horizon=None)
    with_interval = _test_cell(input_interval="1h", lookback_horizon="24h")

    matrix = build_matrix(evaluated_at=EVALUATED, cells=[with_interval, no_interval])

    assert matrix.cells == (no_interval, with_interval)


def test_matrix_order_distinguishes_null_from_empty_string() -> None:
    null_interval = _test_cell(input_interval=None, lookback_horizon=None)
    empty_interval = _test_cell(input_interval="", lookback_horizon="")

    forward = build_matrix(evaluated_at=EVALUATED, cells=[empty_interval, null_interval])
    reverse = build_matrix(evaluated_at=EVALUATED, cells=[null_interval, empty_interval])

    assert forward.cells == (null_interval, empty_interval)
    assert reverse.cells == (null_interval, empty_interval)
    assert null_interval.identity != empty_interval.identity


def test_duplicate_component_identity_fails_closed() -> None:
    cell = unavailable_cell(family=FAMILY_VOLATILITY)

    with pytest.raises(ValueError, match="duplicate regime evidence cell identities"):
        build_matrix(evaluated_at=EVALUATED, cells=[cell, cell])
