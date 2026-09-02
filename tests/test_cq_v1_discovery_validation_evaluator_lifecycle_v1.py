from __future__ import annotations

import csv
import json
import signal
from argparse import Namespace
from pathlib import Path

from src.research import cq_v1_discovery_validation_evaluator_v1 as core
from src.research import run_cq_v1_discovery_validation_evaluator_v1 as runner


def _synthetic_evaluation() -> dict:
    coverage = {
        metric: {
            "jointly_eligible_count": 1,
            "coverage_pct": 100.0,
            "pearson": None,
            "spearman": None,
        }
        for metric in core.OUTCOME_METRICS
    }
    buckets = {}
    for metric in core.OUTCOME_METRICS:
        buckets[metric] = {
            "top_bottom_spread": 0.0,
            "buckets": [
                {
                    "bucket": 1,
                    "n": 1,
                    "score_min": 0.5,
                    "score_max": 0.5,
                    "score_mean": 0.5,
                    metric: {"mean": 1.0, "median": 1.0},
                }
            ],
        }
    pair_metric = {
        "n": 1,
        "pearson": {"left": None, "right": None, "delta": None},
        "spearman": {"left": None, "right": None, "delta": None},
        "top_bottom_spread": {"left": 0.0, "right": 0.0, "delta": 0.0},
    }
    return {
        "metrics": {
            "discovery": {
                "1h": {
                    "cq_v0": {
                        "total_frozen_observations": 1,
                        "complete_outcome_count": 1,
                        "score_available_count": 1,
                        "coverage": coverage,
                        "buckets": buckets,
                    }
                }
            }
        },
        "pairwise": {
            "discovery": {
                "1h": {
                    "cq_v1_balanced_vs_cq_v0": {
                        metric: dict(pair_metric) for metric in core.OUTCOME_METRICS
                    }
                }
            }
        },
    }


def _assert_json_markers(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for key, value in runner.SAFETY_MARKERS.items():
        assert payload[key] == value


def _assert_csv_markers(path: Path) -> None:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    for row in rows:
        for key, value in runner.SAFETY_MARKERS.items():
            assert key in row
            assert row[key] == str(value)


def test_all_output_artifacts_carry_complete_safety_markers(tmp_path, monkeypatch) -> None:
    population = [{"observation_id": "d1", "split": "discovery"}]
    outcomes = [{"observation_id": "d1", "split": "discovery"}]
    evaluation = _synthetic_evaluation()

    monkeypatch.setattr(core, "load_population", lambda _path: population)
    monkeypatch.setattr(core, "load_outcomes", lambda _path: outcomes)
    monkeypatch.setattr(core, "validate_identity", lambda _population, _outcomes: None)
    monkeypatch.setattr(core, "filter_safe_rows", lambda p, o, _splits: (p, o))
    monkeypatch.setattr(core, "evaluate", lambda _p, _o, _splits: evaluation)

    out = tmp_path / "out"
    args = Namespace(
        population=str(tmp_path / "population.jsonl"),
        outcomes=str(tmp_path / "outcomes.jsonl"),
        output_dir=str(out),
        split="discovery",
    )
    runner.run(args)

    _assert_json_markers(out / runner.OUTPUT_EVALUATION)
    _assert_json_markers(out / runner.OUTPUT_MANIFEST)
    _assert_csv_markers(out / runner.OUTPUT_METRICS_CSV)
    _assert_csv_markers(out / runner.OUTPUT_BUCKETS_CSV)
    _assert_csv_markers(out / runner.OUTPUT_PAIRWISE_CSV)

    summary = (out / runner.OUTPUT_SUMMARY_MD).read_text(encoding="utf-8")
    for key, value in runner.SAFETY_MARKERS.items():
        assert f"{key}={value}" in summary


def _success_manifest() -> dict:
    return {
        "splits_evaluated": ["discovery"],
        "population_row_count": 1,
        "outcomes_row_count": 3,
        "safe_outcome_row_count": 3,
        "metrics_row_count": 1,
        "bucket_row_count": 1,
        "pairwise_row_count": 1,
    }


def _argv(tmp_path: Path) -> list[str]:
    return [
        "--population",
        str(tmp_path / "population.jsonl"),
        "--outcomes",
        str(tmp_path / "outcomes.jsonl"),
        "--output-dir",
        str(tmp_path / "out"),
        "--split",
        "discovery",
    ]


def test_success_emits_exactly_one_finished(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(runner, "run", lambda _args: _success_manifest())
    assert runner.main(_argv(tmp_path)) == 0
    output = capsys.readouterr().out
    assert output.count("FINISHED runner=") == 1
    assert "FAILED runner=" not in output
    assert "INTERRUPTED runner=" not in output


def test_work_error_emits_exactly_one_failed_and_returns_one(tmp_path, monkeypatch, capsys) -> None:
    def fail(_args):
        raise ValueError("synthetic-work-error")

    monkeypatch.setattr(runner, "run", fail)
    assert runner.main(_argv(tmp_path)) == 1
    output = capsys.readouterr().out
    assert output.count("FAILED runner=") == 1
    assert "error_type=ValueError" in output
    assert "synthetic-work-error" in output
    assert "FINISHED runner=" not in output
    assert "INTERRUPTED runner=" not in output


def test_sigint_and_sigterm_emit_exactly_one_interrupted_and_return_130(tmp_path, monkeypatch, capsys) -> None:
    for signum in (signal.SIGINT, signal.SIGTERM):
        monkeypatch.setattr(runner, "run", lambda _args, s=signum: (_ for _ in ()).throw(runner._RunnerInterrupted(s)))
        assert runner.main(_argv(tmp_path)) == 130
        output = capsys.readouterr().out
        assert output.count("INTERRUPTED runner=") == 1
        assert f"signal={signum}" in output
        assert "holdout_analytics_read=0" in output
        assert "FINISHED runner=" not in output
        assert "FAILED runner=" not in output


def test_main_restores_original_signal_handlers(tmp_path, monkeypatch) -> None:
    before = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    monkeypatch.setattr(runner, "run", lambda _args: _success_manifest())
    assert runner.main(_argv(tmp_path)) == 0
    after = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    assert after == before


def test_signal_handler_raises_without_reading_holdout_analytics() -> None:
    try:
        runner._signal_handler(signal.SIGINT, None)
    except runner._RunnerInterrupted as exc:
        assert exc.signum == signal.SIGINT
        assert "999" not in str(exc)
    else:
        raise AssertionError("signal handler did not interrupt")
