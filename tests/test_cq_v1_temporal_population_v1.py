from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

import src.research.cq_v1_temporal_population_v1 as mod
from src.research.cq_v1_model_candidate_v1 import COVERAGE_ARTIFACT_SHA256, MODEL_FAMILY_VERSION
from src.selection.selection_engine_v2 import SelectionCandidate, SelectionRow


class FakeCursor:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executed = []

    def execute(self, query, params):
        self.executed.append((" ".join(query.split()), params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def test_contract_is_exact_frozen_45_date_family() -> None:
    contract = mod.load_temporal_contract()
    assert len(mod.derive_asofs(contract)) == 45
    assert contract["frozen_model_family"]["model_family_version"] == MODEL_FAMILY_VERSION
    assert contract["frozen_model_family"]["coverage_artifact_sha256"] == COVERAGE_ARTIFACT_SHA256


def test_selection_source_query_is_point_in_time_and_not_current_max() -> None:
    cursor = FakeCursor([])
    asof = datetime(2026, 8, 14, tzinfo=UTC)
    candidates, evidence = mod.fetch_selection_candidates_asof(FakeConn(cursor), venue="bitvavo", asof_ts_utc=asof)
    assert candidates == []
    assert evidence == {}
    query, params = cursor.executed[0]
    assert "asset_interval_quality" in query
    assert "signal_engine_state" in query
    assert "asof_ts_utc <= %s" in query
    assert "signal_ts_utc <= %s" in query
    assert params.count(asof) == 2


def test_mrp_queries_bound_observation_and_parent_snapshot_to_asof() -> None:
    cursor = FakeCursor([])
    asof = datetime(2026, 8, 14, tzinfo=UTC)
    mod.fetch_mrp_assets_asof(FakeConn(cursor), venue="bitvavo", asof_ts_utc=asof)
    query, params = cursor.executed[0]
    assert "o2.as_of_ts_utc <= %s" in query
    assert "s2.as_of_ts_utc <= %s" in query
    assert "o.as_of_ts_utc <= %s" in query
    assert "s.as_of_ts_utc <= %s" in query
    assert params.count(asof) == 4


def _candidate() -> SelectionCandidate:
    return SelectionCandidate(
        asset_id=7,symbol="TEST",venue="bitvavo",
        quality_status_1d="TRUSTED",quality_status_4h="TRUSTED",quality_status_1h="TRUSTED",
        trend_score_1d=Decimal("0.6"),setup_score_1d=Decimal("0.6"),signal_confidence_1d=Decimal("0.6"),risk_score_1d=Decimal("0.2"),
        volume_score_4h=Decimal("0.6"),compass_score_4h=Decimal("0.6"),setup_score_4h=Decimal("0.6"),relative_score_4h=Decimal("0.6"),signal_confidence_4h=Decimal("0.6"),expansion_position_score_4h=Decimal("0.6"),pullback_quality_score_4h=Decimal("0.6"),risk_score_4h=Decimal("0.2"),
        setup_score_1h=Decimal("0.6"),signal_confidence_1h=Decimal("0.6"),risk_score_1h=Decimal("0.2"),
    )


def _selection() -> SelectionRow:
    return SelectionRow(
        asset_id=7,symbol="TEST",venue="bitvavo",asof_ts_utc=None,advice_ts_1h_utc=None,advice_ts_4h_utc=None,
        quality_status_1d="TRUSTED",quality_status_4h="TRUSTED",quality_status_1h="TRUSTED",
        selection_state="BUY_READY",selection_bias="BULLISH",selection_score=Decimal("0.63"),priority_rank=1,
        allow_trade_flag=1,allowed_sleeves="",blocked_reason=None,summary="",
        trade_quality_score=Decimal("0.61"),relative_rank_score=Decimal("0.6"),timing_refinement_score=Decimal("0.03"),quality_penalty=Decimal("0"),
    )


def test_population_row_preserves_unavailable_sector_and_ppp(monkeypatch) -> None:
    contract = mod.load_temporal_contract()
    asof = mod.derive_asofs(contract)[0]
    evidence = {
        "quality_ts_1d_utc": "2026-07-17T20:00:00+00:00",
        "quality_ts_4h_utc": "2026-07-17T20:00:00+00:00",
        "quality_ts_1h_utc": "2026-07-17T23:00:00+00:00",
        "signal_ts_1d_utc": "2026-07-17T20:00:00+00:00",
        "signal_ts_4h_utc": "2026-07-17T20:00:00+00:00",
        "signal_ts_1h_utc": "2026-07-17T23:00:00+00:00",
    }
    monkeypatch.setattr(mod, "fetch_selection_candidates_asof", lambda *a, **k: ([_candidate()], {7: evidence}))
    monkeypatch.setattr(mod, "rank_candidates", lambda *a, **k: [_selection()])
    monkeypatch.setattr(mod, "fetch_mrp_aggregate_asof", lambda *a, **k: {"model_version": "1.0", "market_score": Decimal("10")})
    monkeypatch.setattr(mod, "fetch_mrp_assets_asof", lambda *a, **k: {7: {"model_version": "1.0", "asset_id": 7}})
    rows = mod.build_asof_population(object(), contract=contract, asof_ts_utc=asof, venue="bitvavo", selection_config={})
    assert len(rows) == 1
    row = rows[0]
    assert row["split"] == "discovery"
    assert row["cq_v0"] == Decimal("0.610000")
    assert row["sector_context_status"] == "UNAVAILABLE_HISTORICAL_MEMBERSHIP"
    assert row["ppp_status"] == "UNAVAILABLE_UNLESS_CANONICAL_PIT_ARTIFACT_SUPPLIED"
    assert row["model_family_version"] == MODEL_FAMILY_VERSION
    assert row["coverage_artifact_sha256"] == COVERAGE_ARTIFACT_SHA256


def test_non_frozen_asof_fails_closed(monkeypatch) -> None:
    contract = mod.load_temporal_contract()
    with pytest.raises(ValueError, match="not a frozen temporal sample"):
        mod.build_asof_population(
            object(),
            contract=contract,
            asof_ts_utc=datetime(2026, 8, 14, 12, tzinfo=UTC),
            venue="bitvavo",
            selection_config={},
        )


def test_summary_reports_temporal_counts() -> None:
    rows = [
        {"asset_id": 1,"asof_ts_utc": "2026-07-18T00:00:00+00:00","mrp_aggregate_status": "AVAILABLE","mrp_asset_status": "AVAILABLE","cq_v0": Decimal("0.5")},
        {"asset_id": 1,"asof_ts_utc": "2026-07-19T00:00:00+00:00","mrp_aggregate_status": "AVAILABLE","mrp_asset_status": "UNAVAILABLE_MRP_ASSET","cq_v0": None},
    ]
    summary = mod.summarize_population(rows)
    assert summary["row_count"] == 2
    assert summary["unique_asset_count"] == 1
    assert summary["unique_asof_count"] == 2
    assert summary["mrp_asset_unavailable_count"] == 1
    assert summary["cq_v0_unavailable_count"] == 1
