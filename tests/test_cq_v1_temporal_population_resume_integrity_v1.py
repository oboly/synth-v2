from __future__ import annotations

import json

import src.research.run_cq_v1_temporal_population_v1 as runner


def test_interrupted_state_omits_uncommitted_population_hash_and_resume_truncates(tmp_path) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    summary_path = tmp_path / "summary.json"
    population_path = tmp_path / "population.jsonl"
    committed = {"observation_id": "committed", "asset_id": 1}
    uncommitted = {"observation_id": "uncommitted", "asset_id": 2}
    population_path.write_text(
        json.dumps(committed) + "\n" + json.dumps(uncommitted) + "\n",
        encoding="utf-8",
    )
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
    assert "population_sha256" not in checkpoint
    assert "population_sha256" not in summary
    assert checkpoint["rows_written"] == 1

    loaded = runner._load_checkpointed_rows(population_path, rows_written=1)
    assert loaded == [committed]
    assert [json.loads(line) for line in population_path.read_text(encoding="utf-8").splitlines()] == [committed]
