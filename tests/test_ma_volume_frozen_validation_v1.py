from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from src.research.ma_volume_frozen_validation_v1 import (
    PINNED_POPULATION_SHA256,
    attach_outcome,
    build_candidate_observation,
    has_contiguous_final_history,
    select_population_rows,
    validate_outcome_coverage,
)
from src.research.run_ma_volume_frozen_validation_v1 import (
    fetch_candles_for_asof,
    fetch_unique_market_map,
    load_checkpointed_rows,
    scope_identity,
)


def _contract() -> dict:
    return {
        "feature_contract": {
            "model_id": "ma_volume_candidate_features",
            "model_version": "1.0",
            "slope_bars": 6,
            "required_history_bars": 206,
            "query_history_bars": 240,
            "candidate_columns": [
                "close_vs_sma50_pct",
                "close_vs_sma150_pct",
                "close_vs_sma200_pct",
                "sma50_slope_pct_6b",
                "sma150_slope_pct_6b",
                "sma200_slope_pct_6b",
                "bullish_ma_stack",
                "volume_ratio_20",
            ],
        },
        "source_outcomes": {
            "required_status": "COMPLETE",
            "outcome_field": "forward_return_pct",
            "horizons": ["1h", "4h", "24h"],
        },
        "source_population": {"row_count": 3},
        "baseline_contract": {
            "identity": "baseline",
            "columns": ["selection_score", "trade_quality_score"],
        },
        "output": {
            "candidate_rows": "candidate_observations.jsonl",
            "report_prefix": "validation_report_",
            "manifest": "manifest.json",
        },
    }


def _observation(
    *,
    observation_id: str = "obs-1",
    asset_id: int = 1,
    asof: datetime | None = None,
    split: str = "discovery",
) -> dict:
    asof = asof or datetime(2026, 8, 1, tzinfo=UTC)
    return {
        "observation_id": observation_id,
        "asset_id": asset_id,
        "symbol": "BTC",
        "venue": "bitvavo",
        "asof_ts_utc": asof.isoformat(),
        "split": split,
        "selection_score": 70.0,
        "trade_quality_score": 60.0,
    }


def _candles(
    *,
    count: int = 210,
    asof: datetime | None = None,
    gap_index: int | None = None,
) -> pd.DataFrame:
    asof = asof or datetime(2026, 8, 1, tzinfo=UTC)
    first_end = asof - timedelta(hours=4 * (count - 1))
    rows = []
    extra_shift = timedelta(0)
    for index in range(count):
        if gap_index is not None and index == gap_index:
            extra_shift += timedelta(hours=4)
        end_ts = first_end + timedelta(hours=4 * index) + extra_shift
        close = 100.0 + index * 0.25
        rows.append(
            {
                "market": "BTC-EUR",
                "interval": "4h",
                "start_ts": end_ts - timedelta(hours=4),
                "end_ts": end_ts,
                "open": close - 0.1,
                "high": close + 0.3,
                "low": close - 0.3,
                "close": close,
                "volume": 1000.0 + index,
                "is_final": True,
            }
        )
    return pd.DataFrame(rows)


def test_candidate_observation_builds_only_from_exact_contiguous_asof_history() -> None:
    asof = datetime(2026, 8, 1, tzinfo=UTC)
    result = build_candidate_observation(
        _observation(asof=asof),
        candle_frame=_candles(asof=asof),
        market="BTC-EUR",
        contract=_contract(),
    )
    assert result["candidate_status"] == "AVAILABLE"
    assert result["split"] == "DISCOVERY"
    assert result["bullish_ma_stack"] == 1
    assert result["close_vs_sma200_pct"] is not None
    assert result["sma200_slope_pct_6b"] is not None
    assert result["volume_ratio_20"] is not None


def test_candidate_observation_fails_closed_on_gap_or_missing_exact_asof() -> None:
    asof = datetime(2026, 8, 1, tzinfo=UTC)
    gapped = _candles(asof=asof, gap_index=100)
    result = build_candidate_observation(
        _observation(asof=asof),
        candle_frame=gapped,
        market="BTC-EUR",
        contract=_contract(),
    )
    assert result["candidate_status"] in {
        "MISSING_EXACT_ASOF_CANDLE",
        "NONCONTIGUOUS_CANDLE_HISTORY",
    }

    stale = _candles(asof=asof)
    stale["start_ts"] = stale["start_ts"] - pd.Timedelta(hours=4)
    stale["end_ts"] = stale["end_ts"] - pd.Timedelta(hours=4)
    result = build_candidate_observation(
        _observation(asof=asof),
        candle_frame=stale,
        market="BTC-EUR",
        contract=_contract(),
    )
    assert result["candidate_status"] == "MISSING_EXACT_ASOF_CANDLE"


def test_contiguous_history_requires_exact_four_hour_grid() -> None:
    asof = datetime(2026, 8, 1, tzinfo=UTC)
    assert has_contiguous_final_history(
        _candles(count=206, asof=asof),
        asof_ts_utc=asof,
        required_history_bars=206,
    )
    frame = _candles(count=206, asof=asof)
    frame.loc[100, "end_ts"] = frame.loc[100, "end_ts"] + timedelta(hours=1)
    assert not has_contiguous_final_history(
        frame,
        asof_ts_utc=asof,
        required_history_bars=206,
    )


def test_attach_outcome_preserves_identity_and_complete_only_value() -> None:
    asof = datetime(2026, 8, 1, tzinfo=UTC)
    candidate = build_candidate_observation(
        _observation(asof=asof),
        candle_frame=_candles(asof=asof),
        market="BTC-EUR",
        contract=_contract(),
    )
    complete = {
        "observation_id": "obs-1",
        "asset_id": 1,
        "venue": "bitvavo",
        "observation_asof_ts_utc": asof.isoformat(),
        "split": "discovery",
        "horizon": "4h",
        "status": "COMPLETE",
        "forward_return_pct": "1.25",
        "population_sha256": PINNED_POPULATION_SHA256,
    }
    result = attach_outcome(
        candidate,
        horizon="4h",
        outcome_by_key={("obs-1", "4h"): complete},
        contract=_contract(),
    )
    assert result["forward_return_pct"] == 1.25
    assert result["outcome_status"] == "COMPLETE"

    incomplete = dict(complete, status="INSUFFICIENT_FUTURE_CANDLES", forward_return_pct="9.9")
    result = attach_outcome(
        candidate,
        horizon="4h",
        outcome_by_key={("obs-1", "4h"): incomplete},
        contract=_contract(),
    )
    assert result["forward_return_pct"] is None

    bad = dict(complete, asset_id=2)
    with pytest.raises(ValueError, match="asset identity"):
        attach_outcome(
            candidate,
            horizon="4h",
            outcome_by_key={("obs-1", "4h"): bad},
            contract=_contract(),
        )


def test_select_population_rows_uses_frozen_asof_then_asset_bounds() -> None:
    first = datetime(2026, 7, 18, tzinfo=UTC)
    second = first + timedelta(days=1)
    rows = [
        _observation(observation_id="a", asset_id=1, asof=first),
        _observation(observation_id="b", asset_id=2, asof=first),
        _observation(observation_id="c", asset_id=1, asof=second),
    ]
    selected = select_population_rows(
        rows,
        asof_index=2,
        asset_id=1,
        limit_observations=None,
    )
    assert [row["observation_id"] for row in selected] == ["c"]


def test_outcome_coverage_requires_every_observation_horizon_pair() -> None:
    population = [
        _observation(observation_id="a", asset_id=1),
        _observation(observation_id="b", asset_id=2),
    ]
    outcomes = {
        (observation_id, horizon): {}
        for observation_id in ("a", "b")
        for horizon in ("1h", "4h", "24h")
    }
    validate_outcome_coverage(population, outcomes, ("1h", "4h", "24h"))
    outcomes.pop(("b", "24h"))
    with pytest.raises(ValueError, match="coverage mismatch"):
        validate_outcome_coverage(population, outcomes, ("1h", "4h", "24h"))


class _Cursor:
    def __init__(self, rows, capture):
        self.rows = rows
        self.capture = capture

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        self.capture.append((sql, params))

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, row_batches):
        self.row_batches = list(row_batches)
        self.capture = []

    def cursor(self):
        return _Cursor(self.row_batches.pop(0), self.capture)


def test_market_resolution_fails_closed_for_ambiguous_assets() -> None:
    conn = _Conn(
        [[
            {"asset_id": 1, "market": "BTC-EUR"},
            {"asset_id": 2, "market": "AAA-EUR"},
            {"asset_id": 2, "market": "AAA-USDC"},
        ]]
    )
    result = fetch_unique_market_map(conn, venue="bitvavo", asset_ids=[1, 2])
    assert result == {1: "BTC-EUR"}


def test_candle_query_is_bounded_before_asof_and_maps_canonical_market() -> None:
    asof = datetime(2026, 8, 1, tzinfo=UTC)
    close_ts = asof.replace(tzinfo=None)
    conn = _Conn(
        [[{
            "asset_id": 1,
            "close_ts_utc": close_ts,
            "open_price": 100,
            "high_price": 102,
            "low_price": 99,
            "close_price": 101,
            "volume_base": 10,
        }]]
    )
    result = fetch_candles_for_asof(
        conn,
        venue="bitvavo",
        asof_ts_utc=asof,
        asset_ids=[1],
        market_by_asset={1: "BTC-EUR"},
        query_history_bars=240,
    )
    assert result[1].iloc[0]["market"] == "BTC-EUR"
    sql, params = conn.capture[0]
    assert "close_ts_utc>%s" in sql
    assert "close_ts_utc<=%s" in sql
    assert params[2] == (asof - timedelta(hours=960)).replace(tzinfo=None)
    assert params[3] == asof.replace(tzinfo=None)


def test_resume_loader_truncates_uncheckpointed_tail(tmp_path: Path) -> None:
    path = tmp_path / "candidate_observations.jsonl"
    path.write_text(
        json.dumps({"observation_id": "a"}) + "\n"
        + json.dumps({"observation_id": "uncheckpointed"}) + "\n",
        encoding="utf-8",
    )
    rows = load_checkpointed_rows(path, 1)
    assert rows == [{"observation_id": "a"}]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_scope_identity_binds_exact_selected_observation_ids() -> None:
    args = argparse.Namespace(
        venue="bitvavo",
        asof_index=None,
        asset_id=None,
        limit_observations=None,
    )
    rows = [
        _observation(observation_id="a", asset_id=1),
        _observation(observation_id="b", asset_id=2),
    ]
    identity = scope_identity(
        args,
        selected=rows,
        asofs=[datetime(2026, 8, 1, tzinfo=UTC)],
    )
    changed = scope_identity(
        args,
        selected=list(reversed(rows)),
        asofs=[datetime(2026, 8, 1, tzinfo=UTC)],
    )
    assert identity["selected_observations"] == 2
    assert identity["selected_observation_ids_sha256"] != changed["selected_observation_ids_sha256"]
