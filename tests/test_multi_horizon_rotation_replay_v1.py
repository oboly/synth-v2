from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, getcontext

from src.research.multi_horizon_rotation_replay_v1 import CANDIDATE_SPECS, Candle, evaluate_candidate


ASOF = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _series(asset_id: int, *, drift: Decimal) -> list[Candle]:
    rows: list[Candle] = []
    start = ASOF - timedelta(hours=37)
    price = Decimal("100") + Decimal(asset_id) / Decimal("10")
    ts = start
    step = 0
    while ts <= ASOF:
        step_decimal = Decimal(step)
        acceleration = Decimal(asset_id - 12) * step_decimal * Decimal("0.000000002")
        phase = Decimal((ts.minute // 15) % 4) * Decimal(asset_id % 5 + 1) * Decimal("0.000001")
        price = price * (Decimal("1") + drift + acceleration + phase)
        base_volume = Decimal("1000") + Decimal(asset_id) * Decimal("3")
        volume_trend = Decimal("1") + Decimal(asset_id % 7 + 1) * step_decimal * Decimal("0.0002")
        volume = base_volume * volume_trend
        rows.append(Candle(close_ts_utc=ts, close_price=price, volume_base=volume))
        ts += timedelta(minutes=15)
        step += 1
    return rows


def _cohort() -> dict[int, list[Candle]]:
    return {
        asset_id: _series(
            asset_id,
            drift=Decimal(asset_id - 12) * Decimal("0.000005"),
        )
        for asset_id in range(1, 25)
    }


def test_all_frozen_candidates_produce_bounded_numeric_scores() -> None:
    cohort = _cohort()
    for spec in CANDIDATE_SPECS:
        results = evaluate_candidate(
            candles_by_asset=cohort,
            asof_ts=ASOF,
            spec=spec,
            venue="bitvavo",
        )
        complete = [row for row in results if row.data_quality == "COMPLETE"]
        assert len(complete) == 24
        assert all(row.rotation_score is not None for row in complete)
        assert all(
            Decimal("-100") <= row.rotation_score <= Decimal("100")
            for row in complete
            if row.rotation_score is not None
        )
        assert all(row.cohort_size == 24 for row in complete)
        assert all(row.venue == "bitvavo" for row in complete)
        assert all(row.lookback_horizon == spec.lookback_horizon for row in complete)
        assert all(row.observed_lifecycle == "UNMEASURED" for row in complete)
        assert all(row.freshness == "FRESH" for row in complete)
        assert all(row.provenance.startswith("obs_market_candle:15m:") for row in complete)


def test_decimal_precision_does_not_change_candidate_outputs() -> None:
    original_precision = getcontext().prec
    try:
        cohort = _cohort()
        outputs_by_precision: dict[int, dict[str, list[tuple[int, Decimal | None, Decimal | None, Decimal | None, Decimal | None, str]]]] = {}
        for precision in (12, 28):
            getcontext().prec = precision
            candidate_outputs: dict[str, list[tuple[int, Decimal | None, Decimal | None, Decimal | None, Decimal | None, str]]] = {}
            for spec in CANDIDATE_SPECS:
                rows = evaluate_candidate(
                    candles_by_asset=cohort,
                    asof_ts=ASOF,
                    spec=spec,
                    venue="bitvavo",
                )
                candidate_outputs[spec.candidate_id] = [
                    (
                        row.asset_id,
                        row.relative_return_unit,
                        row.signed_flow_unit,
                        row.relative_acceleration_unit,
                        row.rotation_score,
                        row.data_quality,
                    )
                    for row in rows
                ]
            outputs_by_precision[precision] = candidate_outputs
        assert outputs_by_precision[12] == outputs_by_precision[28]
    finally:
        getcontext().prec = original_precision


def test_off_grid_asof_fails_closed() -> None:
    spec = CANDIDATE_SPECS[0]
    results = evaluate_candidate(
        candles_by_asset=_cohort(),
        asof_ts=ASOF + timedelta(minutes=1),
        spec=spec,
        venue="bitvavo",
    )
    assert results
    assert all(row.data_quality == "INSUFFICIENT_DATA" for row in results)
    assert all(row.freshness == "INSUFFICIENT_DATA" for row in results)
    assert all(row.reason == "ASOF_NOT_ON_15M_CLOSE_GRID" for row in results)


def test_missing_exact_window_boundary_excludes_asset_not_stale_fallback() -> None:
    cohort = _cohort()
    spec = CANDIDATE_SPECS[1]
    missing_boundary = ASOF - timedelta(hours=1)
    cohort[1] = [row for row in cohort[1] if row.close_ts_utc != missing_boundary]

    results = evaluate_candidate(candles_by_asset=cohort, asof_ts=ASOF, spec=spec, venue="bitvavo")
    row1 = next(row for row in results if row.asset_id == 1)
    assert row1.data_quality == "INSUFFICIENT_DATA"
    assert row1.rotation_score is None
    assert row1.reason == "MISSING_OR_DEGENERATE_COMPONENT"
    assert next(row for row in results if row.asset_id == 2).cohort_size == 23


def test_internal_15m_gap_excludes_asset() -> None:
    cohort = _cohort()
    spec = CANDIDATE_SPECS[2]
    gap_ts = ASOF - timedelta(minutes=45)
    cohort[2] = [row for row in cohort[2] if row.close_ts_utc != gap_ts]

    results = evaluate_candidate(candles_by_asset=cohort, asof_ts=ASOF, spec=spec, venue="bitvavo")
    row2 = next(row for row in results if row.asset_id == 2)
    assert row2.data_quality == "INSUFFICIENT_DATA"
    assert row2.rotation_score is None
    assert next(row for row in results if row.asset_id == 3).cohort_size == 23


def test_cohort_below_20_fails_closed() -> None:
    cohort = {asset_id: rows for asset_id, rows in _cohort().items() if asset_id <= 19}
    results = evaluate_candidate(
        candles_by_asset=cohort,
        asof_ts=ASOF,
        spec=CANDIDATE_SPECS[0],
        venue="bitvavo",
    )
    assert len(results) == 19
    assert all(row.data_quality == "INSUFFICIENT_DATA" for row in results)
    assert all(row.reason == "COHORT_BELOW_MINIMUM" for row in results)


def test_future_candles_are_ignored() -> None:
    cohort = _cohort()
    cohort[1].append(
        Candle(
            close_ts_utc=ASOF + timedelta(minutes=15),
            close_price=Decimal("999999"),
            volume_base=Decimal("999999"),
        )
    )
    result_with_future = evaluate_candidate(
        candles_by_asset=cohort,
        asof_ts=ASOF,
        spec=CANDIDATE_SPECS[0],
        venue="bitvavo",
    )
    cohort[1] = [row for row in cohort[1] if row.close_ts_utc <= ASOF]
    result_without_future = evaluate_candidate(
        candles_by_asset=cohort,
        asof_ts=ASOF,
        spec=CANDIDATE_SPECS[0],
        venue="bitvavo",
    )
    scores_with = {row.asset_id: row.rotation_score for row in result_with_future}
    scores_without = {row.asset_id: row.rotation_score for row in result_without_future}
    assert scores_with == scores_without
