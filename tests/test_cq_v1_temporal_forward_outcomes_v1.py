from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.research.entry_quality_forward_validation_v1 import Candle
from src.research import run_cq_v1_temporal_forward_outcomes_v1 as mod


def _observation(asset_id: int, asof: str, observation_id: str) -> dict:
    return {
        "observation_id": observation_id,
        "asset_id": asset_id,
        "symbol": f"A{asset_id}",
        "venue": "bitvavo",
        "asof_ts_utc": asof,
        "split": "discovery",
        "evidence_key": f"e{asset_id}",
        "cq_model_version": "cq_shadow_v1",
        "model_family_version": "1.0.0",
        "trade_quality_score": "0.5",
        "selection_score": "0.4",
        "cq_v0": "0.45",
    }


def _args(**overrides) -> argparse.Namespace:
    values = {
        "asof_index": None,
        "asset_id": None,
        "limit_observations": None,
        "horizon": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_frozen_contract_loads_exact_horizons() -> None:
    contract, horizons = mod.load_contract()
    assert contract["frozen_population"]["population_sha256"] == mod.PINNED_POPULATION_SHA256
    assert [(item.label, int(item.delta.total_seconds() // 60)) for item in horizons] == [
        ("1h", 60),
        ("4h", 240),
        ("24h", 1440),
    ]


def test_load_population_fails_closed_on_hash_mismatch(tmp_path) -> None:
    path = tmp_path / "population.jsonl"
    path.write_text(json.dumps(_observation(1, "2026-07-18T00:00:00+00:00", "x")) + "\n")
    contract, _ = mod.load_contract()
    with pytest.raises(ValueError, match="population SHA256 mismatch"):
        mod.load_population(path, contract)


def test_select_population_rows_applies_asof_asset_and_limit() -> None:
    rows = [
        _observation(2, "2026-07-19T00:00:00+00:00", "b"),
        _observation(1, "2026-07-18T00:00:00+00:00", "a"),
        _observation(2, "2026-07-18T00:00:00+00:00", "c"),
    ]
    selected = mod.select_population_rows(rows, _args(asof_index=1, asset_id=2, limit_observations=1))
    assert [row["observation_id"] for row in selected] == ["c"]


def test_build_outcomes_batches_once_per_asof_and_is_deterministic(monkeypatch) -> None:
    asof = "2026-07-18T00:00:00+00:00"
    observations = [_observation(1, asof, "obs-1"), _observation(2, asof, "obs-2")]
    calls: list[tuple[list[int], datetime]] = []

    def fake_fetch(conn, *, asset_ids, venue, observation_asof, max_horizon):
        calls.append((list(asset_ids), observation_asof))
        out = {}
        for asset_id in asset_ids:
            base = Decimal("100") + Decimal(asset_id)
            out[asset_id] = [
                Candle(datetime(2026, 7, 18, 0, 0, tzinfo=UTC), base, base, base),
                Candle(datetime(2026, 7, 18, 1, 0, tzinfo=UTC), base + 1, base + 2, base - 1),
                Candle(datetime(2026, 7, 18, 4, 0, tzinfo=UTC), base + 2, base + 3, base - 2),
                Candle(datetime(2026, 7, 19, 0, 0, tzinfo=UTC), base + 4, base + 5, base - 3),
            ]
        return out

    monkeypatch.setattr(mod, "fetch_candles_for_asof_assets", fake_fetch)
    _, horizons = mod.load_contract()
    rows1 = mod.build_outcome_rows(object(), observations=observations, venue="bitvavo", horizons=horizons)
    rows2 = mod.build_outcome_rows(object(), observations=observations, venue="bitvavo", horizons=horizons)

    assert len(calls) == 2
    assert calls[0][0] == [1, 2]
    assert len(rows1) == 6
    assert [row["outcome_id"] for row in rows1] == [row["outcome_id"] for row in rows2]
    assert len({row["outcome_id"] for row in rows1}) == 6
    assert {row["status"] for row in rows1} == {"COMPLETE"}
    assert all(row["population_sha256"] == mod.PINNED_POPULATION_SHA256 for row in rows1)
    assert all(row["target_outcome_status"] == "UNAVAILABLE_NO_CANONICAL_TARGET_PRICE" for row in rows1)


def test_single_horizon_remains_one_label_per_observation(monkeypatch) -> None:
    observation = _observation(1, "2026-07-18T00:00:00+00:00", "obs-1")

    def fake_fetch(conn, *, asset_ids, venue, observation_asof, max_horizon):
        return {
            1: [
                Candle(datetime(2026, 7, 18, 0, 0, tzinfo=UTC), Decimal("100"), Decimal("100"), Decimal("100")),
                Candle(datetime(2026, 7, 18, 1, 0, tzinfo=UTC), Decimal("101"), Decimal("102"), Decimal("99")),
            ]
        }

    monkeypatch.setattr(mod, "fetch_candles_for_asof_assets", fake_fetch)
    _, horizons = mod.load_contract()
    one_horizon = [item for item in horizons if item.label == "1h"]
    rows = mod.build_outcome_rows(object(), observations=[observation], venue="bitvavo", horizons=one_horizon)
    assert len(rows) == 1
    assert rows[0]["horizon"] == "1h"
    assert rows[0]["status"] == "COMPLETE"
    assert rows[0]["forward_return_pct"] == Decimal("1.000000")


def test_write_artifacts_contains_only_technical_summary(tmp_path) -> None:
    row = {
        "outcome_id": "o1",
        "horizon": "1h",
        "status": "COMPLETE",
        "forward_return_pct": Decimal("1.0"),
    }
    mod.write_artifacts(tmp_path, [row], observation_count=1)
    summary = json.loads((tmp_path / mod.OUTPUT_SUMMARY).read_text())
    assert summary["observation_count"] == 1
    assert summary["outcome_row_count"] == 1
    assert summary["db_writes"] == 0
    assert "average_forward_return" not in summary
    assert "holdout" not in summary
