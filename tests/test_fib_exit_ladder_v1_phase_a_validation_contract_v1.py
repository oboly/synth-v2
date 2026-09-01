"""Tests for Issue #270 Phase A frozen validation contract.

Covers: frozen bucket/target-family definitions, deterministic and
repeatable core logic against synthetic (non-DB) candle input, the anchor
detector's actual (future-aware) look-ahead semantics, the contract/findings
docs labeling that correctly, promotion-eligibility gating for future-aware
evidence, deterministic fail-closed baseline-reproduction-failure
disposition, no account-awareness, no production-layer imports, and
rejection of non-read SQL. Does not require DB access; the actual Phase A
run against real historical data is BLOCKED per
docs/research/fib_exit_ladder_v1_phase_a_validation_findings_v1.md.
"""
from __future__ import annotations

import ast
import re
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.research import fib_exit_ladder_v1_phase_a_disposition_v1 as disposition
from src.research import run_fib_exit_ladder_backtest_v1 as ladder_bt
from src.research import run_fib_exit_ladder_scoreboard_v1 as ladder_sb

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKTEST_MODULE_PATH = REPO_ROOT / "src/research/run_fib_exit_ladder_backtest_v1.py"
SCOREBOARD_MODULE_PATH = REPO_ROOT / "src/research/run_fib_exit_ladder_scoreboard_v1.py"
CONTRACT_DOC_PATH = REPO_ROOT / "docs/research/fib_exit_ladder_v1_phase_a_validation_contract_v1.md"
FINDINGS_DOC_PATH = REPO_ROOT / "docs/research/fib_exit_ladder_v1_phase_a_validation_findings_v1.md"

FORBIDDEN_IMPORT_PREFIXES = (
    "src.decision_gate",
    "src.execution_planner",
    "src.executor",
    "src.selection",
    "src.exit_policy",
)


def _candle(days: int, open_price: str, high: str, low: str, close: str) -> ladder_bt.Candle:
    base = datetime(2020, 1, 1)
    return ladder_bt.Candle(
        open_ts_utc=base + timedelta(days=days),
        open_price=Decimal(open_price),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
    )


def _synthetic_candles() -> list[ladder_bt.Candle]:
    """Deterministic anchor_low -> wave1_high -> wave2_low -> breakout series."""
    candles = [_candle(0, "1.00", "1.00", "0.90", "0.95")]
    # Rally from anchor low (0.90) to wave1 high (>= 2x, so >= 1.80).
    for day in range(1, 20):
        price = Decimal("0.90") + (Decimal("1.00") * day / Decimal("19"))
        candles.append(_candle(day, str(price), str(price + Decimal("0.02")), str(price - Decimal("0.02")), str(price)))
    # wave1 high candle, well above 1.80, at day 20.
    candles.append(_candle(20, "1.90", "2.00", "1.85", "1.95"))
    # Pull back for wave2 low (retrace within 0.236-0.886 of wave1_range) a few days later.
    for day in range(21, 25):
        candles.append(_candle(day, "1.60", "1.65", "1.55", "1.58"))
    candles.append(_candle(25, "1.30", "1.35", "1.20", "1.25"))  # wave2 low candidate
    # Future expansion above wave1 high, giving a valid future_high.
    for day in range(26, 60):
        price = Decimal("1.25") + (Decimal("3.00") * (day - 25) / Decimal("34"))
        candles.append(_candle(day, str(price), str(price + Decimal("0.05")), str(price - Decimal("0.05")), str(price)))
    return candles


def test_target_families_are_frozen() -> None:
    assert set(ladder_bt.TARGET_FAMILIES) == {
        "FIB_STANDARD",
        "PRO_3X4X",
        "SUPERCYCLE",
        "EXPLOSIVE_SUPERCYCLE",
    }

    multipliers, fractions = ladder_bt.TARGET_FAMILIES["PRO_3X4X"]
    assert multipliers == [Decimal("2.000"), Decimal("2.618"), Decimal("3.000"), Decimal("4.000"), Decimal("4.236")]
    assert fractions == [Decimal("0.20"), Decimal("0.25"), Decimal("0.25"), Decimal("0.20"), Decimal("0.10")]

    multipliers, fractions = ladder_bt.TARGET_FAMILIES["SUPERCYCLE"]
    assert multipliers == [Decimal("2.618"), Decimal("4.236"), Decimal("6.854"), Decimal("11.090")]
    assert fractions == [Decimal("0.25"), Decimal("0.35"), Decimal("0.25"), Decimal("0.15")]

    multipliers, fractions = ladder_bt.TARGET_FAMILIES["EXPLOSIVE_SUPERCYCLE"]
    assert multipliers == [Decimal("4.236"), Decimal("6.854"), Decimal("11.090"), Decimal("17.944")]
    assert fractions == [Decimal("0.20"), Decimal("0.30"), Decimal("0.30"), Decimal("0.20")]


def test_original_asset_bucket_mapping_is_frozen() -> None:
    assert ladder_sb.exit_archetype_for_family("PRO_3X4X") == "EXIT_PROFILE_CONTROLLED_3X4X"
    assert ladder_sb.exit_archetype_for_family("SUPERCYCLE") == "EXIT_PROFILE_SUPERCYCLE_BALANCED"
    assert ladder_sb.exit_archetype_for_family("EXPLOSIVE_SUPERCYCLE") == "EXIT_PROFILE_EXPLOSIVE_MOONBAG"


def test_evaluate_symbol_is_deterministic_and_repeatable() -> None:
    candles = _synthetic_candles()
    kwargs = dict(
        symbol="SYNTH",
        candles=candles,
        target_family="PRO_3X4X",
        max_ladder_sell_fraction=Decimal("0.80"),
        pivot_threshold_pct=Decimal("0.25"),
        min_wave1_gain_pct=Decimal("1.00"),
        min_wave1_days=14,
        min_wave2_days_after_high=3,
        wave2_min_retrace=Decimal("0.236"),
        wave2_max_retrace=Decimal("0.886"),
        target_zone_low_pct=Decimal("0.04"),
        target_zone_high_pct=Decimal("0.04"),
        front_run_pct=Decimal("0.08"),
        end_pct_of_zone_high=Decimal("0.98"),
        rungs_per_target=5,
        distribution="front_loaded",
    )

    first = ladder_bt.evaluate_symbol(**kwargs)
    second = ladder_bt.evaluate_symbol(**kwargs)

    assert first.status == "OK"
    assert first.status == second.status
    assert first.anchor == second.anchor
    assert first.total_return_pct_with_remaining == second.total_return_pct_with_remaining
    assert first.hold_return_pct == second.hold_return_pct
    assert [f.limit_price for f in first.fills] == [f.limit_price for f in second.fills]


def test_anchor_detector_requires_future_data_after_its_own_entry_point() -> None:
    """The frozen anchor detector is FUTURE_AWARE_RESEARCH, not
    point-in-time-safe: `find_anchor_set` scores/admits a candidate entry
    (wave2_low) only if `future_high` — the max high of candles strictly
    *after* that entry — exceeds wave1_high. Truncating the series to end
    exactly at the entry point (no data after it) must therefore make the
    same anchor undetectable, proving the entry decision depends on data
    unavailable at the entry point itself."""
    full = _synthetic_candles()

    anchor_full = ladder_bt.find_anchor_set(
        candles=full,
        pivot_threshold_pct=Decimal("0.25"),
        min_wave1_gain_pct=Decimal("1.00"),
        min_wave1_days=14,
        min_wave2_days_after_high=3,
        wave2_min_retrace=Decimal("0.236"),
        wave2_max_retrace=Decimal("0.886"),
    )
    assert anchor_full is not None

    entry_ts = anchor_full.wave2_low_ts
    truncated_at_entry = [c for c in full if c.open_ts_utc <= entry_ts]
    anchor_truncated = ladder_bt.find_anchor_set(
        candles=truncated_at_entry,
        pivot_threshold_pct=Decimal("0.25"),
        min_wave1_gain_pct=Decimal("1.00"),
        min_wave1_days=14,
        min_wave2_days_after_high=3,
        wave2_min_retrace=Decimal("0.236"),
        wave2_max_retrace=Decimal("0.886"),
    )
    assert anchor_truncated is None, (
        "find_anchor_set found an anchor using only data up to and including "
        "the entry point; the frozen detector is documented as future-aware "
        "specifically because it cannot do this, so this would mean the "
        "FUTURE_AWARE_RESEARCH classification no longer matches the code."
    )


def test_contract_and_findings_label_methodology_future_aware() -> None:
    contract_text = CONTRACT_DOC_PATH.read_text(encoding="utf-8")
    findings_text = FINDINGS_DOC_PATH.read_text(encoding="utf-8")

    for text in (contract_text, findings_text):
        assert "FUTURE_AWARE_RESEARCH" in text
        assert "methodology_promotion_grade=0" in text or "methodology_promotion_grade = 0" in text

    assert "point-in-time-safe" in contract_text
    assert "#657" in contract_text and "promotion" in contract_text.lower()


def test_future_aware_evidence_is_never_promotion_eligible() -> None:
    for outcome in (
        disposition.OUTCOME_VALIDATED,
        disposition.OUTCOME_REVISED,
        disposition.OUTCOME_REJECTED,
        disposition.OUTCOME_INSUFFICIENT_DATA,
        disposition.OUTCOME_BLOCKED,
    ):
        assert disposition.is_promotion_eligible(
            disposition_outcome=outcome, methodology_future_aware=True
        ) is False

    # Sanity check: the gate is specifically about future-awareness, not a
    # blanket False — a hypothetical point-in-time-safe VALIDATED result
    # would be eligible, confirming the False above is caused by the
    # future-aware flag and not by the gate always returning False.
    assert disposition.is_promotion_eligible(
        disposition_outcome=disposition.OUTCOME_VALIDATED, methodology_future_aware=False
    ) is True

    # The module-level default must itself reflect the current frozen
    # methodology's actual (future-aware) classification.
    assert disposition.METHODOLOGY_FUTURE_AWARE is True
    assert disposition.is_promotion_eligible(disposition_outcome=disposition.OUTCOME_VALIDATED) is False


def test_baseline_reproduction_failure_is_deterministic_and_fail_closed() -> None:
    result = disposition.classify_asset_disposition(
        symbol="LINK",
        baseline_evaluable=True,
        baseline_reproduced=False,
        has_original_bucket=True,
        validation_windows_ok=2,
        validation_windows_total=2,
        alpha_positive_ok_window_count=2,
        bucket_sign_agreement=True,
        bucket_rank_agreement_all_ok_windows=True,
    )
    assert result.outcome == disposition.OUTCOME_REJECTED
    assert result.reason == disposition.REASON_BASELINE_REPRODUCTION_FAILED

    # Repeatable: identical inputs must yield an identical disposition.
    repeat = disposition.classify_asset_disposition(
        symbol="LINK",
        baseline_evaluable=True,
        baseline_reproduced=False,
        has_original_bucket=True,
        validation_windows_ok=2,
        validation_windows_total=2,
        alpha_positive_ok_window_count=2,
        bucket_sign_agreement=True,
        bucket_rank_agreement_all_ok_windows=True,
    )
    assert repeat == result

    # Fail-closed: even validation windows that would otherwise score
    # VALIDATED (sign + rank agreement both hold) must not override a
    # baseline-reproduction failure.
    assert result.outcome != disposition.OUTCOME_VALIDATED
    assert result.outcome != disposition.OUTCOME_REVISED

    # overall_disposition requires the complete five-asset universe; pair
    # this one REJECTED/BASELINE_REPRODUCTION_FAILED asset with the other
    # four as VALIDATED to prove the failure forces overall REJECTED
    # regardless of how favorably the rest score.
    others = [
        disposition.AssetDisposition(symbol, disposition.OUTCOME_VALIDATED, None)
        for symbol in disposition.REQUIRED_ASSET_UNIVERSE
        if symbol != result.symbol
    ]
    overall = disposition.overall_disposition([result] + others)
    assert overall == disposition.OUTCOME_REJECTED


def test_baseline_not_evaluable_is_insufficient_data_not_rejected() -> None:
    """A non-evaluable baseline (rule 0) is a distinct disposition path from
    an evaluable-but-unreproduced baseline (rule 1): there is no baseline to
    compare against at all, so this must not be reported as REJECTED."""
    result = disposition.classify_asset_disposition(
        symbol="HOT",
        baseline_evaluable=False,
        baseline_reproduced=None,
        has_original_bucket=True,
        validation_windows_ok=0,
        validation_windows_total=2,
        alpha_positive_ok_window_count=0,
        bucket_sign_agreement=None,
        bucket_rank_agreement_all_ok_windows=None,
    )
    assert result.outcome == disposition.OUTCOME_INSUFFICIENT_DATA
    assert result.reason is None


def test_mixed_validation_window_alpha_is_not_validated() -> None:
    """One OK window with alpha_vs_hold_pct > 0 and another OK window with
    alpha_vs_hold_pct <= 0 must NOT resolve to VALIDATED, even when
    bucket_rank_agreement_all_ok_windows is True (rank agreement in the
    positive window alone is not sufficient — contract rule 3 requires
    alpha > 0 in *every* OK window)."""
    mixed = disposition.classify_asset_disposition(
        symbol="XLM",
        baseline_evaluable=True,
        baseline_reproduced=True,
        has_original_bucket=True,
        validation_windows_ok=2,
        validation_windows_total=2,
        alpha_positive_ok_window_count=1,  # one window positive, one non-positive
        bucket_sign_agreement=True,
        bucket_rank_agreement_all_ok_windows=True,
    )
    assert mixed.outcome != disposition.OUTCOME_VALIDATED
    # Existing frozen categories only: routed to REVISED per rule 4 because
    # majority sign agreement still holds across the 3 windows.
    assert mixed.outcome == disposition.OUTCOME_REVISED
    assert mixed.reason is None

    # Same mixed alpha split, but majority sign agreement does NOT hold:
    # must be REJECTED (reproduction succeeded), not REVISED and not
    # VALIDATED, and distinguishable from a BASELINE_REPRODUCTION_FAILED
    # REJECTED by its absent reason.
    mixed_sign_disagreement = disposition.classify_asset_disposition(
        symbol="XLM",
        baseline_evaluable=True,
        baseline_reproduced=True,
        has_original_bucket=True,
        validation_windows_ok=2,
        validation_windows_total=2,
        alpha_positive_ok_window_count=1,
        bucket_sign_agreement=False,
        bucket_rank_agreement_all_ok_windows=True,
    )
    assert mixed_sign_disagreement.outcome == disposition.OUTCOME_REJECTED
    assert mixed_sign_disagreement.reason is None
    assert mixed_sign_disagreement.reason != disposition.REASON_BASELINE_REPRODUCTION_FAILED

    # Repeatable: identical mixed input yields an identical disposition.
    repeat = disposition.classify_asset_disposition(
        symbol="XLM",
        baseline_evaluable=True,
        baseline_reproduced=True,
        has_original_bucket=True,
        validation_windows_ok=2,
        validation_windows_total=2,
        alpha_positive_ok_window_count=1,
        bucket_sign_agreement=True,
        bucket_rank_agreement_all_ok_windows=True,
    )
    assert repeat == mixed


def test_ambiguous_rank_agreement_never_yields_validated_or_revised() -> None:
    """Every OK window alpha-positive, but bucket_rank_agreement_all_ok_windows
    is None (unevaluated, not a known False disagreement): this is missing
    evidence, so it must fail closed to INSUFFICIENT_DATA, never VALIDATED
    (rank agreement was never confirmed True) and never REVISED (an
    unevaluated rank check must not be silently treated as a known
    disagreement, since that's a different, stronger claim than 'unknown')."""
    result = disposition.classify_asset_disposition(
        symbol="XRP",
        baseline_evaluable=True,
        baseline_reproduced=True,
        has_original_bucket=True,
        validation_windows_ok=2,
        validation_windows_total=2,
        alpha_positive_ok_window_count=2,  # every OK window positive
        bucket_sign_agreement=True,
        bucket_rank_agreement_all_ok_windows=None,  # ambiguous
    )
    assert result.outcome not in (disposition.OUTCOME_VALIDATED, disposition.OUTCOME_REVISED)
    assert result.outcome == disposition.OUTCOME_INSUFFICIENT_DATA
    assert result.reason is None


def test_ambiguous_sign_agreement_never_yields_validated_or_revised() -> None:
    """Mixed OK-window alpha set with bucket_sign_agreement None (unevaluated):
    must fail closed to INSUFFICIENT_DATA, never VALIDATED and never
    REVISED, since REVISED specifically requires sign agreement to be known
    True."""
    result = disposition.classify_asset_disposition(
        symbol="XRP",
        baseline_evaluable=True,
        baseline_reproduced=True,
        has_original_bucket=True,
        validation_windows_ok=2,
        validation_windows_total=2,
        alpha_positive_ok_window_count=1,  # mixed
        bucket_sign_agreement=None,  # ambiguous
        bucket_rank_agreement_all_ok_windows=True,
    )
    assert result.outcome not in (disposition.OUTCOME_VALIDATED, disposition.OUTCOME_REVISED)
    assert result.outcome == disposition.OUTCOME_INSUFFICIENT_DATA
    assert result.reason is None

    # Also ambiguous when every OK window is positive but rank agreement is
    # known False (falls through to the same sign-agreement routing).
    result_rank_false = disposition.classify_asset_disposition(
        symbol="XRP",
        baseline_evaluable=True,
        baseline_reproduced=True,
        has_original_bucket=True,
        validation_windows_ok=2,
        validation_windows_total=2,
        alpha_positive_ok_window_count=2,
        bucket_sign_agreement=None,  # ambiguous
        bucket_rank_agreement_all_ok_windows=False,
    )
    assert result_rank_false.outcome not in (disposition.OUTCOME_VALIDATED, disposition.OUTCOME_REVISED)
    assert result_rank_false.outcome == disposition.OUTCOME_INSUFFICIENT_DATA


def test_all_ok_windows_non_positive_is_rejected_without_reason() -> None:
    """Every OK validation window alpha <= 0: REJECTED from a successful
    reproduction, regardless of bucket_sign_agreement/rank_agreement, and
    distinct from BASELINE_REPRODUCTION_FAILED."""
    result = disposition.classify_asset_disposition(
        symbol="SOL",
        baseline_evaluable=True,
        baseline_reproduced=True,
        has_original_bucket=True,
        validation_windows_ok=2,
        validation_windows_total=2,
        alpha_positive_ok_window_count=0,
        bucket_sign_agreement=False,
        bucket_rank_agreement_all_ok_windows=False,
    )
    assert result.outcome == disposition.OUTCOME_REJECTED
    assert result.reason is None


def _kwargs_with_windows(validation_windows_ok: int, validation_windows_total: int) -> dict[str, object]:
    return dict(
        symbol="LINK",
        baseline_evaluable=True,
        baseline_reproduced=True,
        has_original_bucket=True,
        validation_windows_ok=validation_windows_ok,
        validation_windows_total=validation_windows_total,
        alpha_positive_ok_window_count=0,
        bucket_sign_agreement=True,
        bucket_rank_agreement_all_ok_windows=True,
    )


@pytest.mark.parametrize("validation_windows_total", [0, 1, 3, 5])
def test_validation_windows_total_other_than_two_fails_closed(validation_windows_total: int) -> None:
    """The frozen contract always defines exactly 2 validation windows
    (§ New validation window(s)); any other total is malformed caller input
    and must raise rather than silently resolving to any disposition,
    VALIDATED included."""
    with pytest.raises(ValueError):
        disposition.classify_asset_disposition(
            **_kwargs_with_windows(validation_windows_ok=0, validation_windows_total=validation_windows_total)
        )


def test_validation_windows_ok_negative_fails_closed() -> None:
    with pytest.raises(ValueError):
        disposition.classify_asset_disposition(
            **_kwargs_with_windows(validation_windows_ok=-1, validation_windows_total=2)
        )


def test_validation_windows_ok_exceeds_total_fails_closed() -> None:
    with pytest.raises(ValueError):
        disposition.classify_asset_disposition(
            **_kwargs_with_windows(validation_windows_ok=3, validation_windows_total=2)
        )


@pytest.mark.parametrize("validation_windows_ok", [0, 1, 2])
def test_validation_windows_ok_within_bounds_does_not_raise(validation_windows_ok: int) -> None:
    """total == 2 with ok in {0, 1, 2} is exactly the valid input range; none
    of these must raise, and none of them may be silently miscounted."""
    result = disposition.classify_asset_disposition(
        **_kwargs_with_windows(validation_windows_ok=validation_windows_ok, validation_windows_total=2)
    )
    assert isinstance(result, disposition.AssetDisposition)
    if validation_windows_ok == 0:
        assert result.outcome == disposition.OUTCOME_INSUFFICIENT_DATA


def _all_validated() -> list[disposition.AssetDisposition]:
    return [
        disposition.AssetDisposition(symbol, disposition.OUTCOME_VALIDATED, None)
        for symbol in disposition.REQUIRED_ASSET_UNIVERSE
    ]


def test_overall_disposition_complete_universe_all_validated() -> None:
    assert disposition.overall_disposition(_all_validated()) == disposition.OUTCOME_VALIDATED


def test_overall_disposition_complete_universe_one_non_validated_asset() -> None:
    entries = _all_validated()
    entries[0] = disposition.AssetDisposition("LINK", disposition.OUTCOME_REVISED, None)
    assert disposition.overall_disposition(entries) == disposition.OUTCOME_REVISED

    entries[1] = disposition.AssetDisposition(
        "XLM", disposition.OUTCOME_REJECTED, disposition.REASON_BASELINE_REPRODUCTION_FAILED
    )
    assert disposition.overall_disposition(entries) == disposition.OUTCOME_REJECTED


def test_overall_disposition_one_asset_missing_is_never_validated() -> None:
    entries = _all_validated()[:-1]  # drop HOT
    assert disposition.overall_disposition(entries) == disposition.OUTCOME_INSUFFICIENT_DATA
    assert disposition.overall_disposition(entries) != disposition.OUTCOME_VALIDATED


def test_overall_disposition_multiple_assets_missing_is_never_validated() -> None:
    entries = _all_validated()[:2]  # only LINK, XLM present
    assert disposition.overall_disposition(entries) == disposition.OUTCOME_INSUFFICIENT_DATA
    assert disposition.overall_disposition(entries) != disposition.OUTCOME_VALIDATED

    assert disposition.overall_disposition([]) == disposition.OUTCOME_INSUFFICIENT_DATA


def test_overall_disposition_duplicate_asset_fails_closed() -> None:
    entries = _all_validated() + [
        disposition.AssetDisposition("LINK", disposition.OUTCOME_VALIDATED, None)
    ]
    with pytest.raises(ValueError):
        disposition.overall_disposition(entries)


def test_overall_disposition_unexpected_asset_fails_closed() -> None:
    entries = _all_validated()[:-1] + [
        disposition.AssetDisposition("SUI", disposition.OUTCOME_VALIDATED, None)
    ]
    with pytest.raises(ValueError):
        disposition.overall_disposition(entries)

    # A substitute that overlaps neither the five required assets nor a
    # legitimate research symbol must fail the same way, never VALIDATED.
    substitute_entries = _all_validated()[:-1] + [
        disposition.AssetDisposition("DOGE", disposition.OUTCOME_VALIDATED, None)
    ]
    with pytest.raises(ValueError):
        disposition.overall_disposition(substitute_entries)


def test_read_only_guard_rejects_non_select_sql() -> None:
    for forbidden in ("INSERT INTO x VALUES (1)", "update x set y=1", "DELETE FROM x", "DROP TABLE x"):
        with pytest.raises(RuntimeError):
            ladder_bt.assert_read_only_sql(forbidden)

    ladder_bt.assert_read_only_sql("SELECT 1")  # must not raise


@pytest.mark.parametrize("module_path", [BACKTEST_MODULE_PATH, SCOREBOARD_MODULE_PATH])
def test_no_production_layer_or_account_aware_imports(module_path: Path) -> None:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)

    for name in imported_names:
        assert not any(name.startswith(prefix) for prefix in FORBIDDEN_IMPORT_PREFIXES), (
            f"{module_path} imports forbidden module {name}"
        )

    source = module_path.read_text(encoding="utf-8")
    assert "trading_account_id" not in source
    assert not re.search(r"\baccount_balance\b|\bbalance\b(?!d)", source.lower())
