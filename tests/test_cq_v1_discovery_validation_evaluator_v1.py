from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.research import cq_v1_discovery_validation_evaluator_v1 as core
from src.research import run_cq_v1_discovery_validation_evaluator_v1 as runner


def _population_row(
    *,
    observation_id: str,
    asset_id: int,
    asof: str,
    split: str,
    cq_v0: str | None,
    trade_quality_score: str,
    selection_score: str,
    market_score: float | None,
) -> dict:
    mrp_aggregate = None if market_score is None else {"market_score": market_score, "model_version": "1.0"}
    return {
        "observation_id": observation_id,
        "asset_id": asset_id,
        "venue": "bitvavo",
        "asof_ts_utc": asof,
        "split": split,
        "symbol": f"A{asset_id}",
        "trade_quality_score": trade_quality_score,
        "selection_score": selection_score,
        "cq_v0": cq_v0,
        "mrp_aggregate": mrp_aggregate,
    }


def _outcome_row(
    *,
    observation: dict,
    horizon: str,
    status: str = "COMPLETE",
    forward_return_pct: str | None = "1.0",
    mfe_pct: str | None = "2.0",
    mae_pct: str | None = "-1.0",
) -> dict:
    return {
        "outcome_id": f"{observation['observation_id']}:{horizon}",
        "observation_id": observation["observation_id"],
        "asset_id": observation["asset_id"],
        "venue": observation["venue"],
        "split": observation["split"],
        "horizon": horizon,
        "status": status,
        "forward_return_pct": forward_return_pct,
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
    }


def _build_dataset() -> tuple[list[dict], list[dict]]:
    population: list[dict] = []
    outcomes: list[dict] = []

    asof_d = "2026-01-01T00:00:00+00:00"
    for i in range(1, 11):
        obs = _population_row(
            observation_id=f"obs-d-{i}",
            asset_id=i,
            asof=asof_d,
            split="discovery",
            cq_v0=f"{i / 10:.6f}",
            trade_quality_score=f"{i / 10:.6f}",
            selection_score=f"{i / 10:.6f}",
            market_score=None if i == 10 else -100 + (i - 1) * (200 / 9),
        )
        population.append(obs)
        for h_idx, horizon in enumerate(core.HORIZONS):
            outcomes.append(
                _outcome_row(
                    observation=obs,
                    horizon=horizon,
                    forward_return_pct=str(i + h_idx),
                    mfe_pct=str(i + h_idx + 0.5),
                    mae_pct=str(-(i + h_idx)),
                )
            )

    asof_v = "2026-01-02T00:00:00+00:00"
    for i in range(1, 5):
        obs = _population_row(
            observation_id=f"obs-v-{i}",
            asset_id=100 + i,
            asof=asof_v,
            split="validation",
            cq_v0=f"{i / 10:.6f}",
            trade_quality_score=f"{i / 10:.6f}",
            selection_score=f"{i / 10:.6f}",
            market_score=float(i * 5),
        )
        population.append(obs)
        for horizon in core.HORIZONS:
            if i == 4:
                outcomes.append(
                    _outcome_row(
                        observation=obs,
                        horizon=horizon,
                        status="INSUFFICIENT_BASE_PRICE",
                        forward_return_pct=None,
                        mfe_pct=None,
                        mae_pct=None,
                    )
                )
            else:
                outcomes.append(
                    _outcome_row(
                        observation=obs,
                        horizon=horizon,
                        forward_return_pct=str(i),
                        mfe_pct=str(i + 1),
                        mae_pct=str(-i),
                    )
                )

    asof_h = "2026-01-03T00:00:00+00:00"
    for i in range(1, 3):
        obs = _population_row(
            observation_id=f"obs-h-{i}",
            asset_id=200 + i,
            asof=asof_h,
            split="holdout",
            cq_v0="0.900000",
            trade_quality_score="0.900000",
            selection_score="0.900000",
            market_score=50.0,
        )
        population.append(obs)
        for horizon in core.HORIZONS:
            outcomes.append(
                _outcome_row(
                    observation=obs,
                    horizon=horizon,
                    forward_return_pct="999",
                    mfe_pct="999",
                    mae_pct="-999",
                )
            )

    return population, outcomes


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _write_fixture(tmp_path: Path) -> tuple[Path, Path, list[dict], list[dict]]:
    population, outcomes = _build_dataset()
    population_path = tmp_path / "population.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    _write_jsonl(population_path, population)
    _write_jsonl(outcomes_path, outcomes)
    return population_path, outcomes_path, population, outcomes


def _patch_pinned(monkeypatch, population_path: Path, outcomes_path: Path, population: list[dict]) -> None:
    split_counts: dict[str, int] = {}
    for row in population:
        split_counts[row["split"]] = split_counts.get(row["split"], 0) + 1
    monkeypatch.setattr(core, "PINNED_POPULATION_SHA256", core._sha256_path(population_path))
    monkeypatch.setattr(core, "PINNED_POPULATION_ROW_COUNT", len(population))
    monkeypatch.setattr(core, "PINNED_POPULATION_UNIQUE_ASOFS", len({row["asof_ts_utc"] for row in population}))
    monkeypatch.setattr(core, "PINNED_POPULATION_UNIQUE_ASSETS", len({row["asset_id"] for row in population}))
    monkeypatch.setattr(core, "PINNED_OUTCOMES_SHA256", core._sha256_path(outcomes_path))
    monkeypatch.setattr(core, "PINNED_OUTCOMES_ROW_COUNT", len(population) * 3)
    monkeypatch.setattr(
        core,
        "PINNED_SPLIT_OUTCOME_ROW_COUNTS",
        {split: count * 3 for split, count in split_counts.items()},
    )


# 1. SHA mismatch rejected


def test_population_sha_mismatch_rejected(tmp_path) -> None:
    path = tmp_path / "population.jsonl"
    path.write_text(json.dumps({"observation_id": "x"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="population SHA256 mismatch"):
        core.load_population(path)


def test_outcomes_sha_mismatch_rejected(tmp_path) -> None:
    path = tmp_path / "outcomes.jsonl"
    path.write_text(json.dumps({"outcome_id": "x"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="outcomes SHA256 mismatch"):
        core.load_outcomes(path)


# 2. outcome identity mismatch rejected


def test_outcome_identity_mismatch_rejected(tmp_path, monkeypatch) -> None:
    population_path, outcomes_path, population, outcomes = _write_fixture(tmp_path)
    _patch_pinned(monkeypatch, population_path, outcomes_path, population)
    loaded_population = core.load_population(population_path)
    loaded_outcomes = core.load_outcomes(outcomes_path)
    loaded_outcomes[0] = {**loaded_outcomes[0], "observation_id": "does-not-exist"}
    with pytest.raises(ValueError, match="unknown observation_id"):
        core.validate_identity(loaded_population, loaded_outcomes)


# 3. unexpected horizon rejected


def test_unexpected_horizon_rejected(tmp_path, monkeypatch) -> None:
    population_path, outcomes_path, population, outcomes = _write_fixture(tmp_path)
    bad_outcomes = list(outcomes)
    bad_outcomes[0] = {**bad_outcomes[0], "horizon": "2h"}
    _write_jsonl(outcomes_path, bad_outcomes)
    _patch_pinned(monkeypatch, population_path, outcomes_path, population)
    with pytest.raises(ValueError, match="exactly horizons"):
        core.load_outcomes(outcomes_path)


# 4/5. holdout / all split CLI rejected


def test_holdout_split_cli_rejected() -> None:
    with pytest.raises(SystemExit):
        runner.parse_args(
            ["--population", "p.jsonl", "--outcomes", "o.jsonl", "--output-dir", "out", "--split", "holdout"]
        )


def test_all_split_cli_rejected() -> None:
    with pytest.raises(SystemExit):
        runner.parse_args(
            ["--population", "p.jsonl", "--outcomes", "o.jsonl", "--output-dir", "out", "--split", "all"]
        )


# 6. holdout analytical values never enter metric functions


def test_holdout_analytical_values_never_enter_metric_functions(tmp_path, monkeypatch) -> None:
    population_path, outcomes_path, population, outcomes = _write_fixture(tmp_path)
    _patch_pinned(monkeypatch, population_path, outcomes_path, population)
    loaded_population = core.load_population(population_path)
    loaded_outcomes = core.load_outcomes(outcomes_path)
    core.validate_identity(loaded_population, loaded_outcomes)

    eval_splits = core.resolve_eval_splits("discovery_validation")
    safe_population, safe_outcomes = core.filter_safe_rows(loaded_population, loaded_outcomes, eval_splits)

    assert all(row["split"] != "holdout" for row in safe_population)
    assert all(row["split"] != "holdout" for row in safe_outcomes)
    assert not any(row["forward_return_pct"] == "999" for row in safe_outcomes)

    evaluation = core.evaluate(safe_population, safe_outcomes, eval_splits)
    assert "holdout" not in evaluation["metrics"]
    assert "holdout" not in evaluation["pairwise"]


def test_resolve_eval_splits_rejects_holdout_and_all() -> None:
    with pytest.raises(ValueError):
        core.resolve_eval_splits("holdout")
    with pytest.raises(ValueError):
        core.resolve_eval_splits("all")


# 7. candidate formulas exact


def test_candidate_formulas_exact() -> None:
    row = {"cq_v0": "0.8", "mrp_aggregate": {"market_score": 20}}
    scores = core.compute_candidate_scores(row)
    assert scores[core.CQ_V1_BALANCED] == pytest.approx(0.70)
    assert scores[core.CQ_V1_ANCHOR] == pytest.approx(0.75)


# 8. missing candidate input => unavailable, no renormalization


def test_missing_mrp_aggregate_makes_candidates_unavailable_not_renormalized() -> None:
    row = {"cq_v0": "0.8", "mrp_aggregate": None}
    scores = core.compute_candidate_scores(row)
    assert scores[core.CQ_V1_BALANCED] is None
    assert scores[core.CQ_V1_ANCHOR] is None


def test_missing_cq_v0_makes_candidates_unavailable() -> None:
    row = {"cq_v0": None, "mrp_aggregate": {"market_score": 20}}
    scores = core.compute_candidate_scores(row)
    assert scores[core.CQ_V1_BALANCED] is None
    assert scores[core.CQ_V1_ANCHOR] is None


# 9. COMPLETE-only metric eligibility


def test_eligible_rows_excludes_non_complete_status() -> None:
    rows = [
        {"status": "COMPLETE", "scores": {"cq_v0": 0.5}, "forward_return_pct": "1.0"},
        {"status": "INSUFFICIENT_BASE_PRICE", "scores": {"cq_v0": 0.5}, "forward_return_pct": "1.0"},
    ]
    eligible = core.eligible_rows(rows, "cq_v0", "forward_return_pct")
    assert len(eligible) == 1
    assert eligible[0]["status"] == "COMPLETE"


# 10. identical eligible sample pairwise comparison


def test_pairwise_comparison_uses_identical_eligible_sample() -> None:
    rows = [
        {
            "observation_id": f"obs-{i}",
            "status": "COMPLETE",
            "scores": {"cq_v0": 0.1 * i, "cq_v1_balanced": None if i == 5 else 0.1 * i},
            "forward_return_pct": str(i),
            "mfe_pct": str(i),
            "mae_pct": str(-i),
        }
        for i in range(1, 11)
    ]
    result = core.pairwise_comparison(rows, core.CQ_V1_BALANCED, core.CQ_V0)
    for outcome_metric in core.OUTCOME_METRICS:
        assert result[outcome_metric]["n"] == 9


# 11. deterministic bucket assignment/ties


def test_bucket_assignment_deterministic_with_ties() -> None:
    rows = [
        {
            "observation_id": f"obs-{i}",
            "scores": {"cq_v0": 0.5},
            "status": "COMPLETE",
            "forward_return_pct": str(i),
            "mfe_pct": str(i),
            "mae_pct": str(-i),
        }
        for i in range(6)
    ]
    first = core.build_buckets(rows, "cq_v0")
    second = core.build_buckets(list(reversed(rows)), "cq_v0")
    assert first == second
    assert sum(bucket["n"] for bucket in first) == len(rows)


# 12/13. output determinism + immutable output-dir protection


def test_output_determinism_and_immutable_output_dir(tmp_path, monkeypatch) -> None:
    population_path, outcomes_path, population, outcomes = _write_fixture(tmp_path)
    _patch_pinned(monkeypatch, population_path, outcomes_path, population)

    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    args1 = runner.parse_args(
        ["--population", str(population_path), "--outcomes", str(outcomes_path), "--output-dir", str(out1)]
    )
    args2 = runner.parse_args(
        ["--population", str(population_path), "--outcomes", str(outcomes_path), "--output-dir", str(out2)]
    )
    runner.run(args1)
    runner.run(args2)

    eval1 = json.loads((out1 / runner.OUTPUT_EVALUATION).read_text(encoding="utf-8"))
    eval2 = json.loads((out2 / runner.OUTPUT_EVALUATION).read_text(encoding="utf-8"))
    assert eval1 == eval2

    with pytest.raises(ValueError, match="already exists"):
        runner.run(args1)


# 14. no DB access/write path


def test_no_db_access_in_evaluator_source() -> None:
    core_source = Path(core.__file__).read_text(encoding="utf-8")
    runner_source = Path(runner.__file__).read_text(encoding="utf-8")
    for source in (core_source, runner_source):
        assert "get_db_connection" not in source
        assert "src.common.db" not in source
        assert "import pymysql" not in source


# 15. technical outputs contain no BUY/SELL or production recommendation


def test_outputs_contain_no_buy_sell_language(tmp_path, monkeypatch) -> None:
    population_path, outcomes_path, population, outcomes = _write_fixture(tmp_path)
    _patch_pinned(monkeypatch, population_path, outcomes_path, population)
    out_dir = tmp_path / "out"
    args = runner.parse_args(
        ["--population", str(population_path), "--outcomes", str(outcomes_path), "--output-dir", str(out_dir)]
    )
    runner.run(args)
    for path in out_dir.iterdir():
        text = path.read_text(encoding="utf-8")
        assert "BUY" not in text
        assert "SELL" not in text
