from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

import src.research.cq_v1_temporal_population_v1 as mod
import src.research.run_cq_v1_temporal_population_v1 as runner
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


def test_runner_import_and_default_cli_contract() -> None:
    args = runner.parse_args([])
    assert args.venue == "bitvavo"
    assert args.selection_config == "configs/selection_engine_v2.yaml"
    assert args.output_dir == "data/research/cq_v1_temporal_population_v1"
    assert args.resume is False
    assert runner.parse_args(["--resume"]).resume is True


def test_selection_config_is_pinned_by_path_and_sha() -> None:
    path, digest = runner._validate_selection_config(runner.DEFAULT_SELECTION_CONFIG)
    assert str(path) == runner.DEFAULT_SELECTION_CONFIG
    assert digest == runner.PINNED_SELECTION_CONFIG_SHA256
    with pytest.raises(ValueError, match="selection config path must be pinned"):
        runner._validate_selection_config("configs/other.yaml")


def test_resume_identity_rejects_changed_config_hash() -> None:
    identity = runner._identity(
        venue="bitvavo",
        contract_sha="contract-sha",
        selection_config_sha="config-sha",
    )
    checkpoint = dict(identity)
    checkpoint["selection_config_sha256"] = "different"
    with pytest.raises(ValueError, match="selection_config_sha256"):
        runner._validate_resume_checkpoint(checkpoint, identity)


def test_selection_config_hash_is_bound_into_observation_identity() -> None:
    base = {
        "asset_id": 7,
        "venue": "bitvavo",
        "asof_ts_utc": "2026-07-18T00:00:00+00:00",
        "evidence_key": "evidence",
        "cq_model_version": "cq_shadow_v1",
        "model_family_version": MODEL_FAMILY_VERSION,
        "coverage_artifact_sha256": COVERAGE_ARTIFACT_SHA256,
        "observation_id": "old",
    }
    first = runner._bind_selection_config_provenance([dict(base)], "config-a")[0]
    second = runner._bind_selection_config_provenance([dict(base)], "config-b")[0]
    assert first["selection_config_sha256"] == "config-a"
    assert second["selection_config_sha256"] == "config-b"
    assert first["observation_id"] != second["observation_id"]


def test_checkpointed_rows_truncate_uncommitted_tail(tmp_path) -> None:
    path = tmp_path / "population.jsonl"
    rows = [
        {"observation_id": "one", "asset_id": 1},
        {"observation_id": "two", "asset_id": 2},
        {"observation_id": "uncheckpointed", "asset_id": 3},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    loaded = runner._load_checkpointed_rows(path, rows_written=2)
    assert loaded == rows[:2]
    persisted = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert persisted == rows[:2]


def test_checkpointed_rows_atomic_replace_preserves_original_on_interrupt(monkeypatch, tmp_path) -> None:
    path = tmp_path / "population.jsonl"
    rows = [
        {"observation_id": "one", "asset_id": 1},
        {"observation_id": "two", "asset_id": 2},
        {"observation_id": "uncheckpointed", "asset_id": 3},
    ]
    original = "".join(json.dumps(row) + "\n" for row in rows)
    path.write_text(original, encoding="utf-8")

    def interrupt_replace(_src, _dst):
        raise runner._Interrupted(15)

    monkeypatch.setattr(runner.os, "replace", interrupt_replace)
    with pytest.raises(runner._Interrupted):
        runner._load_checkpointed_rows(path, rows_written=2)
    assert path.read_text(encoding="utf-8") == original


def test_interrupted_state_is_explicit_and_resumable(tmp_path) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    summary_path = tmp_path / "summary.json"
    population_path = tmp_path / "population.jsonl"
    population_path.write_text('{"observation_id":"one"}\n', encoding="utf-8")
    identity = runner._identity(
        venue="bitvavo",
        contract_sha="contract-sha",
        selection_config_sha="config-sha",
    )
    runner._atomic_json(
        checkpoint_path,
        {
            **identity,
            "terminal_state": "RUNNING",
            "asofs_completed": 3,
            "rows_written": 1,
            "last_asof_ts_utc": "2026-07-20T00:00:00+00:00",
        },
    )
    runner._write_interrupted_state(
        checkpoint_path=checkpoint_path,
        summary_path=summary_path,
        population_path=population_path,
        identity=identity,
        signum=15,
    )
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert checkpoint["terminal_state"] == "INTERRUPTED"
    assert summary["terminal_state"] == "INTERRUPTED"
    assert summary["resumable"] == 1
    assert summary["asofs_completed"] == 3
    assert summary["rows_written"] == 1
    assert summary["selection_config_sha256"] == "config-sha"
    runner._validate_resume_checkpoint(checkpoint, identity)


def test_selection_source_query_is_point_in_time_and_not_current_max() -> None:
    cursor = FakeCursor([])
    asof = datetime(2026, 8, 14, tzinfo=UTC)
    candidates, evidence = mod.fetch_selection_candidates_asof(
        FakeConn(cursor), venue="bitvavo", asof_ts_utc=asof
    )
    assert candidates == []
    assert evidence == {}
    query, params = cursor.executed[0]
    assert "asset_interval_quality" in query
    assert "signal_engine_state" in query
    assert "asof_ts_utc <= %s" in query
    assert "signal_ts_utc <= %s" in query
    assert params.count(asof) == 2


def test_selection_universe_does_not_depend_on_mutable_current_asset_flags() -> None:
    cursor = FakeCursor([])
    asof = datetime(2026, 8, 14, tzinfo=UTC)
    mod.fetch_selection_candidates_asof(FakeConn(cursor), venue="bitvavo", asof_ts_utc=asof)
    query, _ = cursor.executed[0]
    normalized = query.lower()
    assert "is_enabled" not in normalized
    assert "is_tradeable" not in normalized
    assert "q1d.asset_id is not null" in normalized
    assert "s1h.asset_id is not null" in normalized


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
        asset_id=7,
        symbol="TEST",
        venue="bitvavo",
        quality_status_1d="TRUSTED",
        quality_status_4h="TRUSTED",
        quality_status_1h="TRUSTED",
        trend_score_1d=Decimal("0.6"),
        setup_score_1d=Decimal("0.6"),
        signal_confidence_1d=Decimal("0.6"),
        risk_score_1d=Decimal("0.2"),
        volume_score_4h=Decimal("0.6"),
        compass_score_4h=Decimal("0.6"),
        setup_score_4h=Decimal("0.6"),
        relative_score_4h=Decimal("0.6"),
        signal_confidence_4h=Decimal("0.6"),
        expansion_position_score_4h=Decimal("0.6"),
        pullback_quality_score_4h=Decimal("0.6"),
        risk_score_4h=Decimal("0.2"),
        setup_score_1h=Decimal("0.6"),
        signal_confidence_1h=Decimal("0.6"),
        risk_score_1h=Decimal("0.2"),
    )


def _selection() -> SelectionRow:
    return SelectionRow(
        asset_id=7,
        symbol="TEST",
        venue="bitvavo",
        asof_ts_utc=None,
        advice_ts_1h_utc=None,
        advice_ts_4h_utc=None,
        quality_status_1d="TRUSTED",
        quality_status_4h="TRUSTED",
        quality_status_1h="TRUSTED",
        selection_state="BUY_READY",
        selection_bias="BULLISH",
        selection_score=Decimal("0.63"),
        priority_rank=1,
        allow_trade_flag=1,
        allowed_sleeves="",
        blocked_reason=None,
        summary="",
        trade_quality_score=Decimal("0.61"),
        relative_rank_score=Decimal("0.6"),
        timing_refinement_score=Decimal("0.03"),
        quality_penalty=Decimal("0"),
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
    monkeypatch.setattr(
        mod,
        "fetch_selection_candidates_asof",
        lambda *a, **k: ([_candidate()], {7: evidence}),
    )
    monkeypatch.setattr(mod, "rank_candidates", lambda *a, **k: [_selection()])
    monkeypatch.setattr(
        mod,
        "fetch_mrp_aggregate_asof",
        lambda *a, **k: {"model_version": "1.0", "market_score": Decimal("10")},
    )
    monkeypatch.setattr(
        mod,
        "fetch_mrp_assets_asof",
        lambda *a, **k: {7: {"model_version": "1.0", "asset_id": 7}},
    )
    rows = mod.build_asof_population(
        object(), contract=contract, asof_ts_utc=asof, venue="bitvavo", selection_config={}
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["split"] == "discovery"
    assert row["universe_provenance_status"] == "HISTORICAL_CORE_SOURCE_OBSERVED_AT_OR_BEFORE_ASOF"
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
        {
            "asset_id": 1,
            "asof_ts_utc": "2026-07-18T00:00:00+00:00",
            "mrp_aggregate_status": "AVAILABLE",
            "mrp_asset_status": "AVAILABLE",
            "cq_v0": Decimal("0.5"),
        },
        {
            "asset_id": 1,
            "asof_ts_utc": "2026-07-19T00:00:00+00:00",
            "mrp_aggregate_status": "AVAILABLE",
            "mrp_asset_status": "UNAVAILABLE_MRP_ASSET",
            "cq_v0": None,
        },
    ]
    summary = mod.summarize_population(rows)
    assert summary["row_count"] == 2
    assert summary["unique_asset_count"] == 1
    assert summary["unique_asof_count"] == 2
    assert summary["mrp_asset_unavailable_count"] == 1
    assert summary["cq_v0_unavailable_count"] == 1
