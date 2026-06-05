from __future__ import annotations

import ast
import csv
import json
import tempfile
from pathlib import Path

import src.research.run_fib_reaction_consistency_score_v1 as runner


def write_fixture_input(base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    manifest = {
        "report_name": "multi_horizon_fib_backtest_v1",
        "analysis_version": "1.0",
        "algorithm_version": "1.0",
        "symbols": ["WLD"],
        "horizons": ["SHORT", "LONG"],
        "safety_markers": {
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "decision_gate": "none",
            "execution_planner": "none",
            "executor": "none",
            "db_writes": 0,
            "account_tables_used": False,
            "research_only": True,
        },
    }
    (base / "manifest_v1.json").write_text(json.dumps(manifest), encoding="utf-8")
    rows = [
        {
            "event_id": "e1",
            "symbol": "WLD",
            "venue": "bitvavo",
            "quote": "EUR",
            "fib_trading_horizon": "SHORT",
            "interval_code": "4h",
            "interval_role": "PRIMARY",
            "market_regime": "RISK_ON",
            "symbol_regime": "REL_STRENGTH",
            "breath_phase": "EXPANSION",
            "breath_alignment": "ALIGNED",
            "touch_count": "1",
            "reaction_success_count": "1",
            "fakeout_count": "0",
            "invalidation_count": "0",
            "next_extension_hit_count": "1",
        },
        {
            "event_id": "e2",
            "symbol": "WLD",
            "venue": "bitvavo",
            "quote": "EUR",
            "fib_trading_horizon": "SHORT",
            "interval_code": "4h",
            "interval_role": "PRIMARY",
            "market_regime": "RISK_ON",
            "symbol_regime": "REL_STRENGTH",
            "breath_phase": "EXPANSION",
            "breath_alignment": "ALIGNED",
            "touch_count": "1",
            "reaction_success_count": "0",
            "fakeout_count": "1",
            "invalidation_count": "0",
            "next_extension_hit_count": "0",
        },
        {
            "event_id": "e3",
            "symbol": "WLD",
            "venue": "bitvavo",
            "quote": "EUR",
            "fib_trading_horizon": "SHORT",
            "interval_code": "4h",
            "interval_role": "PRIMARY",
            "market_regime": "RISK_OFF",
            "symbol_regime": "REL_STRENGTH",
            "breath_phase": "POST_SPIKE",
            "breath_alignment": "LATE",
            "touch_count": "1",
            "reaction_success_count": "0",
            "fakeout_count": "0",
            "invalidation_count": "1",
            "next_extension_hit_count": "0",
        },
        {
            "event_id": "e4",
            "symbol": "WLD",
            "venue": "bitvavo",
            "quote": "EUR",
            "fib_trading_horizon": "SHORT",
            "interval_code": "4h",
            "interval_role": "PRIMARY",
            "market_regime": "UNKNOWN",
            "symbol_regime": "UNKNOWN",
            "breath_phase": "UNKNOWN",
            "breath_alignment": "UNKNOWN",
            "touch_count": "0",
            "reaction_success_count": "0",
            "fakeout_count": "0",
            "invalidation_count": "0",
            "next_extension_hit_count": "0",
        },
        {
            "event_id": "e5",
            "symbol": "WLD",
            "venue": "bitvavo",
            "quote": "EUR",
            "fib_trading_horizon": "SHORT",
            "interval_code": "4h",
            "interval_role": "PRIMARY",
            "market_regime": "RISK_ON",
            "symbol_regime": "REL_STRENGTH",
            "breath_phase": "EXPANSION",
            "breath_alignment": "ALIGNED",
            "touch_count": "1",
            "reaction_success_count": "1",
            "fakeout_count": "0",
            "invalidation_count": "0",
            "next_extension_hit_count": "1",
        },
        {
            "event_id": "e6",
            "symbol": "WLD",
            "venue": "bitvavo",
            "quote": "EUR",
            "fib_trading_horizon": "LONG",
            "interval_code": "1w",
            "interval_role": "PRIMARY",
            "market_regime": "UNKNOWN",
            "symbol_regime": "UNKNOWN",
            "breath_phase": "UNKNOWN",
            "breath_alignment": "UNKNOWN",
            "touch_count": "1",
            "reaction_success_count": "1",
            "fakeout_count": "0",
            "invalidation_count": "0",
            "next_extension_hit_count": "1",
        },
        {
            "event_id": "e7",
            "symbol": "WLD",
            "venue": "bitvavo",
            "quote": "EUR",
            "fib_trading_horizon": "LONG",
            "interval_code": "1w",
            "interval_role": "PRIMARY",
            "market_regime": "UNKNOWN",
            "symbol_regime": "UNKNOWN",
            "breath_phase": "UNKNOWN",
            "breath_alignment": "UNKNOWN",
            "touch_count": "1",
            "reaction_success_count": "0",
            "fakeout_count": "0",
            "invalidation_count": "1",
            "next_extension_hit_count": "0",
        },
    ]
    with (base / "fib_level_outcomes_v1.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_formula_is_deterministic_and_bounded() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        output_dir = Path(tmpdir) / "output"
        write_fixture_input(input_dir)
        first = runner.run_score(
            input_dir=input_dir,
            output_dir=output_dir,
            symbols=None,
            horizons={"SHORT"},
            heartbeat_seconds=999.0,
            min_valid_sample_count=3,
            min_stability_bucket_sample=2,
            write_files=True,
            control=runner.RunControl(),
        )
        second = runner.run_score(
            input_dir=input_dir,
            output_dir=output_dir,
            symbols=None,
            horizons={"SHORT"},
            heartbeat_seconds=999.0,
            min_valid_sample_count=3,
            min_stability_bucket_sample=2,
            write_files=False,
            control=runner.RunControl(),
        )
        assert first["rows"] == second["rows"]
        row = first["rows"][0]
        score = float(row["fib_reaction_consistency_score"])
        assert 0.0 <= score <= 100.0


def test_invalid_sample_returns_insufficient_sample() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        write_fixture_input(input_dir)
        result = runner.run_score(
            input_dir=input_dir,
            output_dir=Path(tmpdir) / "output",
            symbols=None,
            horizons={"LONG"},
            heartbeat_seconds=999.0,
            min_valid_sample_count=3,
            min_stability_bucket_sample=2,
            write_files=False,
            control=runner.RunControl(),
        )
        long_row = result["rows"][0]
        assert long_row["fib_reaction_consistency_status"] == runner.STATUS_INSUFFICIENT_SAMPLE
        assert long_row["fib_reaction_consistency_score"] == ""


def test_score_components_visible_and_no_class_or_generic_quality_score() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        write_fixture_input(input_dir)
        result = runner.run_score(
            input_dir=input_dir,
            output_dir=Path(tmpdir) / "output",
            symbols=None,
            horizons={"SHORT"},
            heartbeat_seconds=999.0,
            min_valid_sample_count=3,
            min_stability_bucket_sample=2,
            write_files=False,
            control=runner.RunControl(),
        )
        row = result["rows"][0]
        for field in (
            "sample_count",
            "touch_rate",
            "reaction_success_rate",
            "fakeout_rate",
            "invalidation_rate",
            "next_extension_hit_rate",
            "regime_stability",
            "breath_stability",
            "weight_touch_rate",
            "weight_reaction_success_rate",
            "weight_fakeout_rate_complement",
            "weight_invalidation_rate_complement",
            "weight_next_extension_hit_rate",
            "weight_regime_stability",
            "weight_breath_stability",
        ):
            assert field in row
        for forbidden in runner.FORBIDDEN_OUTPUT_FIELDS:
            assert forbidden not in row


def test_unknown_context_preserved_and_context_fallback_visible() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        output_dir = Path(tmpdir) / "output"
        write_fixture_input(input_dir)
        result = runner.run_score(
            input_dir=input_dir,
            output_dir=output_dir,
            symbols=None,
            horizons={"SHORT"},
            heartbeat_seconds=999.0,
            min_valid_sample_count=3,
            min_stability_bucket_sample=2,
            write_files=True,
            control=runner.RunControl(),
        )
        unknown_row = next(row for row in result["context_rows"] if row["market_regime"] == "UNKNOWN")
        assert unknown_row["market_regime"] == "UNKNOWN"
        assert unknown_row["symbol_regime"] == "UNKNOWN"
        assert unknown_row["breath_phase"] == "UNKNOWN"
        assert unknown_row["breath_alignment"] == "UNKNOWN"
        fallback_row = next(row for row in result["context_rows"] if row["market_regime"] == "RISK_OFF")
        assert fallback_row["resolved_context_tier"] in {
            runner.TIER_SYMBOL_HORIZON,
            runner.TIER_HORIZON_BASELINE,
        }
        written_rows = load_csv(output_dir / "fib_reaction_consistency_context_rows_v1.csv")
        assert any(row["market_regime"] == "RISK_OFF" for row in written_rows)


def test_distribution_file_and_manifest_written() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        output_dir = Path(tmpdir) / "output"
        write_fixture_input(input_dir)
        runner.run_score(
            input_dir=input_dir,
            output_dir=output_dir,
            symbols=None,
            horizons=None,
            heartbeat_seconds=999.0,
            min_valid_sample_count=3,
            min_stability_bucket_sample=2,
            write_files=True,
            control=runner.RunControl(),
        )
        distribution_rows = load_csv(output_dir / "score_component_distribution_v1.csv")
        assert any(row["component_name"] == "fib_reaction_consistency_score" for row in distribution_rows)
        manifest = json.loads((output_dir / "manifest_v1.json").read_text(encoding="utf-8"))
        assert manifest["score_formula"]["weights"]["reaction_success_rate"] == runner.WEIGHTS["reaction_success_rate"]


def test_runner_has_no_forbidden_imports_or_strings() -> None:
    source = Path("src/research/run_fib_reaction_consistency_score_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {"decision_gate", "execution_planner", "executor", "broker", "account"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for name in forbidden_imports:
                assert name not in module
        if isinstance(node, ast.Import):
            for alias in node.names:
                for name in forbidden_imports:
                    assert name not in alias.name
    for forbidden in ("placeOrder", "cancelOrder", "create order"):
        assert forbidden not in source


def main() -> None:
    test_formula_is_deterministic_and_bounded()
    test_invalid_sample_returns_insufficient_sample()
    test_score_components_visible_and_no_class_or_generic_quality_score()
    test_unknown_context_preserved_and_context_fallback_visible()
    test_distribution_file_and_manifest_written()
    test_runner_has_no_forbidden_imports_or_strings()


if __name__ == "__main__":
    main()
