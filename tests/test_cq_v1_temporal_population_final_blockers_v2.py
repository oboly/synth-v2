from __future__ import annotations

import copy
import json

import pytest

import src.research.cq_v1_temporal_population_v1 as population
import src.research.run_cq_v1_temporal_population_v1 as runner


def test_frozen_temporal_contract_hash_is_exact() -> None:
    contract = population.load_temporal_contract()
    assert population.canonical_json_sha256(contract) == population.PINNED_TEMPORAL_CONTRACT_SHA256


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("sampling", "cadence"), "12h"),
        (("sampling", "first_asof_ts_utc"), "2026-07-19T00:00:00Z"),
        (("sampling", "last_asof_ts_utc"), "2026-09-01T00:00:00Z"),
        (("chronological_split", "discovery", "last_asof_ts_utc"), "2026-08-12T00:00:00Z"),
        (("chronological_split", "validation", "first_asof_ts_utc"), "2026-08-15T00:00:00Z"),
        (("chronological_split", "holdout", "first_asof_ts_utc"), "2026-08-24T00:00:00Z"),
    ],
)
def test_frozen_temporal_contract_rejects_sampling_or_split_mutation(tmp_path, path, value) -> None:
    payload = copy.deepcopy(population.load_temporal_contract())
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    mutated = tmp_path / "mutated_contract.json"
    mutated.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="temporal contract SHA256 mismatch"):
        population.load_temporal_contract(mutated)


def test_selection_config_hash_changes_observation_identity() -> None:
    base = {
        "asset_id": 7,
        "venue": "bitvavo",
        "asof_ts_utc": "2026-07-18T00:00:00+00:00",
        "evidence_key": "evidence",
        "cq_model_version": "cq_shadow_v1",
        "model_family_version": "1.0.0",
        "coverage_artifact_sha256": "coverage",
        "observation_id": "old",
    }
    first = runner._bind_selection_config_provenance([dict(base)], "config-a")[0]
    second = runner._bind_selection_config_provenance([dict(base)], "config-b")[0]
    assert first["selection_config_sha256"] == "config-a"
    assert second["selection_config_sha256"] == "config-b"
    assert first["observation_id"] != second["observation_id"]


def test_resume_prefix_rewrite_is_atomic_on_interrupt(tmp_path, monkeypatch) -> None:
    path = tmp_path / "population.jsonl"
    committed = {"observation_id": "committed", "asset_id": 1}
    tail = {"observation_id": "tail", "asset_id": 2}
    original = json.dumps(committed) + "\n" + json.dumps(tail) + "\n"
    path.write_text(original, encoding="utf-8")

    def interrupted_replace(_src, _dst):
        raise runner._Interrupted(15)

    monkeypatch.setattr(runner.os, "replace", interrupted_replace)
    with pytest.raises(runner._Interrupted):
        runner._load_checkpointed_rows(path, rows_written=1)
    assert path.read_text(encoding="utf-8") == original


def test_interrupted_state_omits_uncheckpointed_hash_and_remains_resumable(tmp_path) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    summary_path = tmp_path / "summary.json"
    population_path = tmp_path / "population.jsonl"
    committed = {"observation_id": "committed", "asset_id": 1}
    tail = {"observation_id": "tail", "asset_id": 2}
    population_path.write_text(json.dumps(committed) + "\n" + json.dumps(tail) + "\n", encoding="utf-8")
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
            "asofs_completed": 1,
            "rows_written": 1,
            "last_asof_ts_utc": "2026-07-18T00:00:00+00:00",
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
    assert checkpoint["resumable"] == 1
    assert checkpoint["rows_written"] == 1
    assert "population_sha256" not in checkpoint
    assert "population_sha256" not in summary
    runner._validate_resume_checkpoint(checkpoint, identity)
    loaded = runner._load_checkpointed_rows(population_path, rows_written=1)
    assert loaded == [committed]
