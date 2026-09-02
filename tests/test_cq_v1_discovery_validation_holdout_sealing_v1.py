from __future__ import annotations

import json
from pathlib import Path

from src.research import cq_v1_discovery_validation_evaluator_v1 as core
from src.research import run_cq_v1_discovery_validation_evaluator_v1 as runner


def _row(obs: str, asset: int, split: str, horizon: str, metric: str) -> dict:
    return {
        "outcome_id": f"{obs}:{horizon}",
        "observation_id": obs,
        "asset_id": asset,
        "split": split,
        "horizon": horizon,
        "status": "COMPLETE",
        "forward_return_pct": metric,
        "mfe_pct": metric,
        "mae_pct": metric,
    }


def test_holdout_analytical_fields_never_deserialized_during_loading(tmp_path, monkeypatch) -> None:
    rows = []
    for split, obs, asset, metric in (
        ("discovery", "obs-d", 1, "1.0"),
        ("validation", "obs-v", 2, "2.0"),
        ("holdout", "obs-h", 3, "999999.0"),
    ):
        for horizon in core.HORIZONS:
            rows.append(_row(obs, asset, split, horizon, metric))

    path = tmp_path / "outcomes.jsonl"
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")

    monkeypatch.setattr(core, "PINNED_OUTCOMES_SHA256", core._sha256_path(path))
    monkeypatch.setattr(core, "PINNED_OUTCOMES_ROW_COUNT", len(rows))
    monkeypatch.setattr(
        core,
        "PINNED_SPLIT_OUTCOME_ROW_COUNTS",
        {"discovery": 3, "validation": 3, "holdout": 3},
    )

    original_loads = runner.json.loads
    deserialized_inputs: list[str] = []

    def guarded_loads(value, *args, **kwargs):
        if isinstance(value, str):
            deserialized_inputs.append(value)
            assert "999999.0" not in value, "holdout analytical JSON was deserialized"
        return original_loads(value, *args, **kwargs)

    monkeypatch.setattr(runner.json, "loads", guarded_loads)

    loaded = runner._load_outcomes_sealed(path, ("discovery", "validation"))

    assert len(loaded) == 9
    holdout = [row for row in loaded if row["split"] == "holdout"]
    assert len(holdout) == 3
    assert all("forward_return_pct" not in row for row in holdout)
    assert all("mfe_pct" not in row for row in holdout)
    assert all("mae_pct" not in row for row in holdout)
    assert any("1.0" in value for value in deserialized_inputs)
    assert any("2.0" in value for value in deserialized_inputs)
