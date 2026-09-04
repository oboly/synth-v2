"""Tests for Issue #707 Phase C: the deterministic verifier over committed
raw PIT replay evidence.

Covers the Phase C required test groups for the verifier:
    - verifier reproduces from raw evidence
    - provenance hashes verified
    - promotion grade fails closed if any one criterion is false
    - no forbidden architecture imports/writes

Builds synthetic evidence directories via
run_fib_exit_ladder_v1_pit_replay_v1.write_evidence (the same function the
real runner uses), so these tests exercise the actual writer/verifier
round-trip rather than a hand-typed second JSON schema.
"""
from __future__ import annotations

import ast
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.research import fib_exit_ladder_v1_pit_replay_engine_v1 as engine
from src.research import fib_exit_ladder_v1_pit_replay_verifier_v1 as verifier
from src.research import run_fib_exit_ladder_v1_pit_replay_v1 as runner

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = REPO_ROOT / "src/research/fib_exit_ladder_v1_pit_replay_verifier_v1.py"

FORBIDDEN_IMPORT_SUBSTRINGS = (
    "decision_gate",
    "execution_planner",
    "executor",
    "account",
    "broker",
    "order",
)

ASSETS = ("LINK", "XLM", "SOL", "XRP", "HOT")


def _ok_result(symbol, window, family, fraction, total_return, hold_return):
    return engine.PitSymbolResult(
        symbol=symbol,
        window=window,
        target_family=family,
        max_ladder_sell_fraction=fraction,
        status="OK",
        anchor_low_ts=datetime(2020, 1, 1),
        wave1_high_ts=datetime(2020, 2, 1),
        wave2_low_ts=datetime(2020, 2, 15),
        confirmation_ts=datetime(2020, 3, 1),
        entry_ts=datetime(2020, 3, 2),
        entry_price=Decimal("1.00"),
        total_return_pct_with_remaining=Decimal(str(total_return)),
        hold_return_pct=Decimal(str(hold_return)),
        alpha_vs_hold_pct=Decimal(str(total_return)) - Decimal(str(hold_return)),
        filled_rung_count=2,
        sample_count=1,
        peak_oracle_return_pct=Decimal("5.00"),
        top_capture_ratio=Decimal("0.50"),
        fills=(),
    )


def _empty_result(symbol, window, family, fraction, status="INSUFFICIENT_CANDLES"):
    return engine._empty_pit_result(symbol, window, family, fraction, status)


def _all_validated_universe() -> dict[str, engine.PitSymbolReplayResult]:
    """Every one of the five required assets: one grid row wins clearly on
    SELECTION_WINDOW (PRO_3X4X/0.40), and both OOS windows are positive
    alpha -> every asset should classify VALIDATED."""
    results: dict[str, engine.PitSymbolReplayResult] = {}
    for symbol in ASSETS:
        grid_results = {}
        for family in engine.CANDIDATE_FAMILIES:
            for fraction in engine.SELL_FRACTION_GRID:
                if family == "PRO_3X4X" and fraction == Decimal("0.40"):
                    grid_results[(family, fraction)] = _ok_result(
                        symbol, "SELECTION_WINDOW", family, fraction, "20.00", "5.00"
                    )
                else:
                    grid_results[(family, fraction)] = _ok_result(
                        symbol, "SELECTION_WINDOW", family, fraction, "10.00", "5.00"
                    )

        selected = engine.SelectedPolicy(
            symbol=symbol,
            target_family="PRO_3X4X",
            max_ladder_sell_fraction=Decimal("0.40"),
            selection_metric_value=Decimal("20.00"),
            selection_sample_count=1,
        )
        results[symbol] = engine.PitSymbolReplayResult(
            symbol=symbol,
            selected_policy=selected,
            selection_grid_results=grid_results,
            oos_window_1_result=_ok_result(symbol, "OOS_WINDOW_1", "PRO_3X4X", Decimal("0.40"), "8.00", "3.00"),
            oos_window_2_result=_ok_result(symbol, "OOS_WINDOW_2", "PRO_3X4X", Decimal("0.40"), "6.00", "2.00"),
        )
    return results


def _row_counts() -> dict[str, dict[str, int]]:
    return {symbol: {"SELECTION_WINDOW": 500, "OOS_WINDOW_1": 500, "OOS_WINDOW_2": 700} for symbol in ASSETS}


def _write(tmp_path: Path, results: dict[str, engine.PitSymbolReplayResult]) -> Path:
    evidence_dir = tmp_path / "evidence"
    runner.write_evidence(evidence_dir, results, _row_counts())
    return evidence_dir


# ---------------------------------------------------------------------------
# Verifier reproduces from raw evidence.
# ---------------------------------------------------------------------------


def test_verifier_reproduces_all_validated_universe(tmp_path):
    evidence_dir = _write(tmp_path, _all_validated_universe())
    report = verifier.verify(evidence_dir)

    assert report.overall == verifier.DISPOSITION_VALIDATED
    for symbol in ASSETS:
        assert report.per_asset_disposition[symbol] == verifier.DISPOSITION_VALIDATED
        assert report.per_asset_selected[symbol]["target_family"] == "PRO_3X4X"
        assert report.per_asset_selected[symbol]["max_ladder_sell_fraction"] == "0.40"
    assert report.methodology_promotion_grade == 1
    assert report.promotion_eligible is True
    assert report.mismatches == []


def test_verifier_reproduces_mixed_universe_worst_case_overall(tmp_path):
    results = _all_validated_universe()

    # HOT: both OOS windows non-positive alpha -> REJECTED.
    results["HOT"] = engine.PitSymbolReplayResult(
        symbol="HOT",
        selected_policy=results["HOT"].selected_policy,
        selection_grid_results=results["HOT"].selection_grid_results,
        oos_window_1_result=_ok_result("HOT", "OOS_WINDOW_1", "PRO_3X4X", Decimal("0.40"), "-5.00", "3.00"),
        oos_window_2_result=_ok_result("HOT", "OOS_WINDOW_2", "PRO_3X4X", Decimal("0.40"), "-2.00", "2.00"),
    )

    # XRP: no PIT anchor confirmed in SELECTION_WINDOW -> INSUFFICIENT_DATA.
    empty_grid = {
        (family, fraction): _empty_result("XRP", "SELECTION_WINDOW", family, fraction, "NO_ANCHOR_SET_FOUND")
        for family in engine.CANDIDATE_FAMILIES
        for fraction in engine.SELL_FRACTION_GRID
    }
    results["XRP"] = engine.PitSymbolReplayResult(
        symbol="XRP",
        selected_policy=None,
        selection_grid_results=empty_grid,
        oos_window_1_result=None,
        oos_window_2_result=None,
    )

    evidence_dir = _write(tmp_path, results)
    report = verifier.verify(evidence_dir)

    assert report.per_asset_disposition["HOT"] == verifier.DISPOSITION_REJECTED
    assert report.per_asset_disposition["XRP"] == verifier.DISPOSITION_INSUFFICIENT_DATA
    assert report.per_asset_disposition["LINK"] == verifier.DISPOSITION_VALIDATED
    # Overall is the least favorable across the required universe.
    assert report.overall == verifier.DISPOSITION_INSUFFICIENT_DATA
    assert report.methodology_promotion_grade == 0
    assert report.promotion_eligible is False


def test_missing_required_asset_treated_as_insufficient_data(tmp_path):
    results = _all_validated_universe()
    del results["SOL"]
    evidence_dir = _write(tmp_path, results)
    report = verifier.verify(evidence_dir)

    assert "SOL" not in report.per_asset_disposition
    assert report.overall == verifier.DISPOSITION_INSUFFICIENT_DATA
    assert report.methodology_promotion_grade == 0


# ---------------------------------------------------------------------------
# Provenance hashes verified.
# ---------------------------------------------------------------------------


def test_tampered_raw_file_fails_hash_verification(tmp_path):
    evidence_dir = _write(tmp_path, _all_validated_universe())
    tampered_path = evidence_dir / "raw" / "selection_grid_results_v1.json"
    payload = json.loads(tampered_path.read_text(encoding="utf-8"))
    payload["rows"][0]["total_return_pct_with_remaining"] = "999999.00"
    tampered_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(verifier.VerifierError):
        verifier.verify(evidence_dir)


def test_missing_raw_file_fails_closed(tmp_path):
    evidence_dir = _write(tmp_path, _all_validated_universe())
    (evidence_dir / "raw" / "oos_evaluation_results_v1.json").unlink()

    with pytest.raises(verifier.VerifierError):
        verifier.verify(evidence_dir)


# ---------------------------------------------------------------------------
# Promotion grade fails closed if any one criterion is false; retuning
# detection.
# ---------------------------------------------------------------------------


def test_retuned_oos_row_fails_disjoint_selection_oos_criterion(tmp_path):
    results = _all_validated_universe()
    # Mutate LINK's OOS_WINDOW_1 evidence to a different (family, fraction)
    # than its frozen SELECTION_WINDOW-selected policy -- simulated retuning.
    retuned = results["LINK"].oos_window_1_result
    results["LINK"] = engine.PitSymbolReplayResult(
        symbol="LINK",
        selected_policy=results["LINK"].selected_policy,
        selection_grid_results=results["LINK"].selection_grid_results,
        oos_window_1_result=engine.PitSymbolResult(
            **{**retuned.__dict__, "target_family": "SUPERCYCLE", "max_ladder_sell_fraction": Decimal("0.80")}
        ),
        oos_window_2_result=results["LINK"].oos_window_2_result,
    )
    evidence_dir = _write(tmp_path, results)
    report = verifier.verify(evidence_dir)

    assert report.criteria["disjoint_selection_oos"] is False
    assert report.methodology_promotion_grade == 0
    assert report.promotion_eligible is False
    assert any("retuning" in mismatch for mismatch in report.mismatches)


def test_promotion_grade_zero_when_one_asset_below_validated(tmp_path):
    results = _all_validated_universe()
    results["XLM"] = engine.PitSymbolReplayResult(
        symbol="XLM",
        selected_policy=results["XLM"].selected_policy,
        selection_grid_results=results["XLM"].selection_grid_results,
        oos_window_1_result=_ok_result("XLM", "OOS_WINDOW_1", "PRO_3X4X", Decimal("0.40"), "-1.00", "1.00"),
        oos_window_2_result=_ok_result("XLM", "OOS_WINDOW_2", "PRO_3X4X", Decimal("0.40"), "-1.00", "1.00"),
    )
    evidence_dir = _write(tmp_path, results)
    report = verifier.verify(evidence_dir)

    assert report.criteria["positive_oos_alpha"] is False
    # Every other criterion may still hold, but any one False fails closed.
    assert report.methodology_promotion_grade == 0
    assert report.promotion_eligible is False


def test_evaluate_promotion_grade_rejects_incomplete_criteria_mapping():
    from src.research import fib_exit_ladder_v1_pit_replay_contract_v1 as pit_contract

    incomplete = {name: True for name in pit_contract.PROMOTION_GRADE_CRITERIA if name != "sufficient_sample_count"}
    assert pit_contract.evaluate_promotion_grade(incomplete) is False


# ---------------------------------------------------------------------------
# Architecture boundary.
# ---------------------------------------------------------------------------


def test_verifier_module_has_no_forbidden_imports():
    source = ast.parse(VERIFIER_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(source):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            lowered = name.lower()
            for forbidden in FORBIDDEN_IMPORT_SUBSTRINGS:
                assert forbidden not in lowered, f"forbidden import {name!r} in verifier module"


def test_verifier_module_never_opens_a_db_connection():
    text = VERIFIER_PATH.read_text(encoding="utf-8")
    assert "pymysql" not in text
    assert "connect(" not in text


# ---------------------------------------------------------------------------
# Real committed Phase C evidence (docs/research/fib_exit_ladder_v1_pit_replay_phase_c_v1/raw).
# Asserts the verifier's output against the actual committed evidence, not a
# synthetic fixture, so a future change to that evidence or to this module's
# derivation logic that silently changes the reported result is caught.
# ---------------------------------------------------------------------------

REAL_EVIDENCE_DIR = REPO_ROOT / "docs/research/fib_exit_ladder_v1_pit_replay_phase_c_v1"

EXPECTED_REAL_SELECTED_POLICIES = {
    "LINK": ("PRO_3X4X", "0.80"),
    "XLM": ("PRO_3X4X", "0.80"),
    "SOL": ("SUPERCYCLE", "0.80"),
    "XRP": ("PRO_3X4X", "0.80"),
    "HOT": ("EXPLOSIVE_SUPERCYCLE", "0.40"),
}


def test_verifier_reproduces_actual_committed_phase_c_evidence():
    report = verifier.verify(REAL_EVIDENCE_DIR)

    assert report.mismatches == []
    for symbol, (family, fraction) in EXPECTED_REAL_SELECTED_POLICIES.items():
        assert report.per_asset_selected[symbol]["target_family"] == family
        assert report.per_asset_selected[symbol]["max_ladder_sell_fraction"] == fraction

    assert report.per_asset_disposition == {symbol: verifier.DISPOSITION_REJECTED for symbol in ASSETS}
    assert report.overall == verifier.DISPOSITION_REJECTED
    assert report.criteria["positive_oos_alpha"] is False
    assert report.criteria["immutable_raw_evidence"] is True
    assert report.criteria["deterministic_replay"] is True
    assert report.criteria["stable_reproducible"] is True
    assert report.methodology_promotion_grade == 0
    assert report.promotion_eligible is False


def test_real_committed_manifest_hashes_match_actual_files():
    raw_dir = REAL_EVIDENCE_DIR / "raw"
    manifest = verifier.load_json(raw_dir / "manifest_v1.json")
    for filename, recorded in manifest["files"].items():
        file_path = raw_dir / filename
        assert verifier.sha256_of_file(file_path) == recorded["sha256"]
        assert file_path.stat().st_size == recorded["byte_size"]


def test_real_committed_selected_policies_reconstructible_from_selection_grid():
    evidence = verifier.load_evidence(REAL_EVIDENCE_DIR)
    rows_by_symbol: dict[str, list] = {}
    for row in evidence.selection_grid_rows:
        rows_by_symbol.setdefault(row["symbol"], []).append(row)

    for symbol, (family, fraction) in EXPECTED_REAL_SELECTED_POLICIES.items():
        derived = verifier.rerank_selection_grid(rows_by_symbol[symbol])
        assert derived is not None
        assert derived["target_family"] == family
        assert derived["max_ladder_sell_fraction"] == fraction


def test_real_committed_oos_policy_identity_equals_frozen_selected_policy():
    evidence = verifier.load_evidence(REAL_EVIDENCE_DIR)
    selected_by_symbol = {row["symbol"]: row for row in evidence.selected_policy_rows}
    assert evidence.oos_rows, "expected non-empty committed OOS evidence"
    for row in evidence.oos_rows:
        selected = selected_by_symbol[row["symbol"]]
        assert row["target_family"] == selected["target_family"]
        assert row["max_ladder_sell_fraction"] == selected["max_ladder_sell_fraction"]


def test_real_committed_no_alternate_oos_ranking_exists():
    """The committed OOS evidence contains exactly one (family, fraction) per
    symbol per OOS window -- i.e. no alternate candidate was ever evaluated
    out-of-sample, so there is no ranking step for the verifier to reproduce
    there (only the frozen SELECTION_WINDOW-chosen policy is present)."""
    evidence = verifier.load_evidence(REAL_EVIDENCE_DIR)
    seen: dict[tuple[str, str], set] = {}
    for row in evidence.oos_rows:
        key = (row["symbol"], row["window"])
        assert key not in seen, f"duplicate OOS row for {key}"
        seen[key] = {(row["target_family"], row["max_ladder_sell_fraction"])}
    assert len(seen) == len(ASSETS) * 2


def test_real_committed_evidence_sufficient_to_reproduce_findings():
    """The four raw evidence files plus the manifest are sufficient on their
    own (no other file/DB access) to reproduce every reported finding."""
    report = verifier.verify(REAL_EVIDENCE_DIR)
    assert set(report.per_asset_selected) == set(ASSETS)
    assert set(report.per_asset_disposition) == set(ASSETS)
    assert report.overall in verifier.DISPOSITION_ORDER
    assert set(report.criteria) == {
        "true_pit_eligibility",
        "no_look_ahead",
        "disjoint_selection_oos",
        "deterministic_replay",
        "sufficient_sample_count",
        "positive_oos_alpha",
        "stable_reproducible",
        "immutable_raw_evidence",
        "verifier_reproduces",
    }
