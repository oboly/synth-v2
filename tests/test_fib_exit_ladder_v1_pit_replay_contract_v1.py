"""Tests for Issue #707 Phase A frozen point-in-time (PIT) replay contract.

Covers: the frozen PIT anchor-eligibility helper's no-future-candle-access
and no-same-candle-leakage guarantees, frozen training/OOS window
disjointness and no-retuning framing, the frozen candidate grid, fail-closed
promotion-grade criteria evaluation, and the contract document's own
required content (confirmation-event semantics, explicit rejection of
future_high-style scoring, immutable-evidence/verifier requirements).

Does not execute a PIT replay, does not access the DB, and does not
compute or inspect any new outcome metric (return/alpha/fill) — this Phase
A only freezes the protocol, per
docs/research/fib_exit_ladder_v1_pit_replay_contract_v1.md.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.research import fib_exit_ladder_v1_pit_replay_contract_v1 as pit
from src.research import run_fib_exit_ladder_backtest_v1 as ladder_bt

REPO_ROOT = Path(__file__).resolve().parents[1]
PIT_CONTRACT_DOC_PATH = REPO_ROOT / "docs/research/fib_exit_ladder_v1_pit_replay_contract_v1.md"


def _candle(days: int, open_price: str, high: str, low: str, close: str) -> ladder_bt.Candle:
    base = datetime(2020, 1, 1)
    return ladder_bt.Candle(
        open_ts_utc=base + timedelta(days=days),
        open_price=Decimal(open_price),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
    )


def _series_with_confirmation_at(confirmation_day: int, has_observable_next: bool) -> list[ladder_bt.Candle]:
    """A minimal candle series where wave2_idx is day 0 (price 1.00, below
    wave1_high=2.00), and the confirmation candle (close > wave1_high)
    occurs at `confirmation_day`. If `has_observable_next` is False, the
    series ends exactly at the confirmation candle (no next candle exists
    to make it observable)."""
    candles = [_candle(0, "1.00", "1.05", "0.95", "1.00")]
    for day in range(1, confirmation_day):
        candles.append(_candle(day, "1.10", "1.20", "1.05", "1.10"))
    candles.append(_candle(confirmation_day, "2.05", "2.10", "2.00", "2.05"))  # confirmation: close > 2.00
    if has_observable_next:
        candles.append(_candle(confirmation_day + 1, "2.06", "2.15", "2.04", "2.10"))
    return candles


# ---------------------------------------------------------------------------
# § 2 / § 5: no same-candle leakage, no future candle access
# ---------------------------------------------------------------------------


def test_visible_candle_indices_excludes_the_decision_candle_itself() -> None:
    """Same-candle leakage guard: a decision made at candles[5]'s own open
    timestamp must never be able to see candles[5]'s own high/low/close."""
    assert list(pit.visible_candle_indices(5)) == [0, 1, 2, 3, 4]
    assert 5 not in pit.visible_candle_indices(5)


def test_visible_candle_indices_rejects_negative_decision_index() -> None:
    with pytest.raises(ValueError):
        pit.visible_candle_indices(-1)


def test_visible_candle_indices_at_zero_is_empty() -> None:
    """The very first candle has no visible history at all yet."""
    assert list(pit.visible_candle_indices(0)) == []


def test_find_confirmation_index_never_reads_before_wave2_idx() -> None:
    """The confirmation scan starts strictly after wave2_idx; a confirming
    close placed at or before wave2_idx must never be picked up."""
    candles = [
        _candle(0, "1.00", "1.05", "0.95", "1.00"),
        _candle(1, "3.00", "3.10", "2.95", "3.00"),  # would "confirm" wave1_high=2.00 if visible
        _candle(2, "1.10", "1.20", "1.05", "1.10"),
        _candle(3, "2.05", "2.10", "2.00", "2.05"),  # actual confirmation, after wave2_idx=1
    ]
    # wave2_idx = 1 (the day-1 candle itself, which if scanned against
    # itself would wrongly "confirm" using its own close).
    result = pit.find_confirmation_index(candles, wave1_high=Decimal("2.00"), wave2_idx=1)
    assert result == 3


def test_find_confirmation_index_returns_none_when_never_confirmed() -> None:
    candles = [_candle(day, "1.00", "1.10", "0.95", "1.00") for day in range(10)]
    assert pit.find_confirmation_index(candles, wave1_high=Decimal("5.00"), wave2_idx=0) is None


def test_find_confirmation_index_rejects_out_of_range_wave2_idx() -> None:
    candles = [_candle(0, "1.00", "1.10", "0.95", "1.00")]
    with pytest.raises(ValueError):
        pit.find_confirmation_index(candles, wave1_high=Decimal("2.00"), wave2_idx=5)
    with pytest.raises(ValueError):
        pit.find_confirmation_index(candles, wave1_high=Decimal("2.00"), wave2_idx=-1)


def test_observable_index_is_one_past_confirmation_and_none_at_series_end() -> None:
    """Contract § 5.2: the confirmation candle's own close is not knowable
    until the *next* candle opens. If the confirmation candle is the last
    one available, the event is not yet observable at all."""
    series_with_next = _series_with_confirmation_at(confirmation_day=3, has_observable_next=True)
    confirmation_idx = pit.find_confirmation_index(
        series_with_next, wave1_high=Decimal("2.00"), wave2_idx=0
    )
    assert confirmation_idx == 3
    observable = pit.observable_index_for_confirmation(series_with_next, confirmation_idx)
    assert observable == 4

    series_without_next = _series_with_confirmation_at(confirmation_day=3, has_observable_next=False)
    confirmation_idx_2 = pit.find_confirmation_index(
        series_without_next, wave1_high=Decimal("2.00"), wave2_idx=0
    )
    assert confirmation_idx_2 == 3
    assert pit.observable_index_for_confirmation(series_without_next, confirmation_idx_2) is None


def test_observable_index_rejects_out_of_range_confirmation_idx() -> None:
    candles = [_candle(0, "1.00", "1.10", "0.95", "1.00")]
    with pytest.raises(ValueError):
        pit.observable_index_for_confirmation(candles, 5)
    with pytest.raises(ValueError):
        pit.observable_index_for_confirmation(candles, -1)


def test_entry_from_confirmation_uses_next_candle_open_not_confirmation_candle_values() -> None:
    """entry_price must be the observable candle's open_price (a genuinely
    future-unknown-at-confirmation-time value is never used); it must not
    be the confirmation candle's own close/high/low, which would be
    same-candle leakage relative to the moment the event becomes known."""
    series = _series_with_confirmation_at(confirmation_day=3, has_observable_next=True)
    confirmation_idx = pit.find_confirmation_index(series, wave1_high=Decimal("2.00"), wave2_idx=0)
    entry = pit.entry_from_confirmation(series, confirmation_idx)

    assert entry is not None
    assert entry.entry_idx == confirmation_idx + 1
    assert entry.entry_ts == series[confirmation_idx + 1].open_ts_utc
    assert entry.entry_price == series[confirmation_idx + 1].open_price
    assert entry.entry_price != series[confirmation_idx].close_price


def test_entry_from_confirmation_is_none_when_not_yet_observable() -> None:
    series = _series_with_confirmation_at(confirmation_day=3, has_observable_next=False)
    confirmation_idx = pit.find_confirmation_index(series, wave1_high=Decimal("2.00"), wave2_idx=0)
    assert pit.entry_from_confirmation(series, confirmation_idx) is None


def test_truncating_series_at_observable_index_still_confirms_same_anchor() -> None:
    """Contract § 5.3 machine-testability claim: truncating the series to
    end exactly at observable_ts (inclusive) must still let the PIT
    detector confirm the identical anchor and fix the identical entry,
    because nothing after observable_ts was used to reach it. This is the
    PIT-safe mirror of the existing #270 test proving the opposite property
    for the future-aware detector
    (test_anchor_detector_requires_future_data_after_its_own_entry_point)."""
    full = _series_with_confirmation_at(confirmation_day=3, has_observable_next=True)
    # Add plenty of extra future candles the PIT rule must not depend on.
    for day in range(5, 40):
        full.append(_candle(day, "9.00", "9.10", "8.90", "9.00"))

    confirmation_idx = pit.find_confirmation_index(full, wave1_high=Decimal("2.00"), wave2_idx=0)
    entry_full = pit.entry_from_confirmation(full, confirmation_idx)
    assert entry_full is not None

    truncated = full[: entry_full.entry_idx + 1]
    confirmation_idx_truncated = pit.find_confirmation_index(
        truncated, wave1_high=Decimal("2.00"), wave2_idx=0
    )
    entry_truncated = pit.entry_from_confirmation(truncated, confirmation_idx_truncated)

    assert confirmation_idx_truncated == confirmation_idx
    assert entry_truncated == entry_full


# ---------------------------------------------------------------------------
# § 4 / § 6: frozen windows and candidate grid
# ---------------------------------------------------------------------------


def test_selection_and_oos_windows_are_frozen_and_disjoint() -> None:
    assert pit.SELECTION_WINDOW == ("2020-01-01 00:00:00", "2022-01-01 00:00:00")
    assert pit.OOS_WINDOW_1 == ("2022-01-01 00:00:00", "2024-01-01 00:00:00")
    assert pit.OOS_WINDOW_2 == ("2024-01-01 00:00:00", "2026-09-01 00:00:00")

    # Disjoint and contiguous, no overlap: each window's end equals the
    # next window's start, never a re-crossed boundary.
    assert pit.SELECTION_WINDOW[1] == pit.OOS_WINDOW_1[0]
    assert pit.OOS_WINDOW_1[1] == pit.OOS_WINDOW_2[0]
    assert pit.SELECTION_WINDOW[0] < pit.SELECTION_WINDOW[1]
    assert pit.OOS_WINDOW_1[0] < pit.OOS_WINDOW_1[1]
    assert pit.OOS_WINDOW_2[0] < pit.OOS_WINDOW_2[1]


def test_required_asset_universe_matches_270_five_asset_universe() -> None:
    from src.research import fib_exit_ladder_v1_phase_a_disposition_v1 as disposition_270

    assert pit.REQUIRED_ASSET_UNIVERSE == disposition_270.REQUIRED_ASSET_UNIVERSE


def test_candidate_families_are_frozen_and_exclude_fib_standard() -> None:
    assert set(pit.CANDIDATE_FAMILIES) == {"PRO_3X4X", "SUPERCYCLE", "EXPLOSIVE_SUPERCYCLE"}
    assert "FIB_STANDARD" not in pit.CANDIDATE_FAMILIES
    # Every frozen candidate family must actually exist in the frozen
    # TARGET_FAMILIES definitions this contract reuses.
    assert set(pit.CANDIDATE_FAMILIES).issubset(set(ladder_bt.TARGET_FAMILIES))


def test_sell_fraction_grid_matches_scoreboard_default_grid() -> None:
    from src.research import run_fib_exit_ladder_scoreboard_v1 as ladder_sb

    expected = tuple(Decimal(part) for part in ladder_sb.DEFAULT_MAX_SELL_FRACTIONS.split(","))
    assert pit.SELL_FRACTION_GRID == expected


# ---------------------------------------------------------------------------
# § 10: fail-closed promotion-grade criteria
# ---------------------------------------------------------------------------


def _all_criteria_true() -> dict[str, bool]:
    return {name: True for name in pit.PROMOTION_GRADE_CRITERIA}


def test_promotion_grade_requires_every_criterion_true() -> None:
    assert pit.evaluate_promotion_grade(_all_criteria_true()) is True


@pytest.mark.parametrize("missing_criterion", pit.PROMOTION_GRADE_CRITERIA)
def test_promotion_grade_fails_closed_when_any_single_criterion_is_false(missing_criterion: str) -> None:
    criteria = _all_criteria_true()
    criteria[missing_criterion] = False
    assert pit.evaluate_promotion_grade(criteria) is False


@pytest.mark.parametrize("missing_criterion", pit.PROMOTION_GRADE_CRITERIA)
def test_promotion_grade_fails_closed_when_any_single_criterion_is_absent(missing_criterion: str) -> None:
    criteria = _all_criteria_true()
    del criteria[missing_criterion]
    assert pit.evaluate_promotion_grade(criteria) is False


def test_promotion_grade_rejects_unexpected_criteria_keys() -> None:
    criteria = _all_criteria_true()
    criteria["some_other_unreviewed_flag"] = True
    with pytest.raises(ValueError):
        pit.evaluate_promotion_grade(criteria)


@pytest.mark.parametrize("non_bool_value", [1, 0, "true", "false", None, [], {}])
def test_promotion_grade_rejects_non_bool_criterion_values(non_bool_value: object) -> None:
    """Mirrors the #270 disposition module's rationale: bool is an int
    subclass, so a naive truthiness check would let 1/0 slip through as if
    they were True/False. Every criterion value must be an actual bool."""
    criteria = _all_criteria_true()
    criteria["true_pit_eligibility"] = non_bool_value  # type: ignore[assignment]
    with pytest.raises(TypeError):
        pit.evaluate_promotion_grade(criteria)


def test_promotion_grade_empty_input_is_not_promotion_grade() -> None:
    assert pit.evaluate_promotion_grade({}) is False


# ---------------------------------------------------------------------------
# Contract document content: confirmation semantics, no-look-ahead framing,
# training/OOS separation, no-retuning, immutable-evidence/verifier
# requirements, promotion-grade fail-closed framing.
# ---------------------------------------------------------------------------


def test_contract_document_rejects_future_high_style_scoring() -> None:
    text = PIT_CONTRACT_DOC_PATH.read_text(encoding="utf-8")

    assert "no `future_high`" in text or "no future_high" in text.lower()
    assert "no scan of candles after the candidate decision timestamp" in text.lower() or (
        "no scan of candles after" in text
    )
    assert "no future-return-derived anchor ranking" in text.lower() or (
        "future-return-derived anchor ranking" in text
    )


def test_contract_document_defines_confirmation_event_and_observable_ts() -> None:
    text = PIT_CONTRACT_DOC_PATH.read_text(encoding="utf-8")

    assert "confirmation_event" in text
    assert "observable_ts" in text
    assert "entry_ts" in text and "entry_price" in text
    assert "no same-candle information leakage" in text.lower() or "same-candle" in text.lower()


def test_contract_document_separates_selection_from_oos_and_forbids_retuning() -> None:
    text = PIT_CONTRACT_DOC_PATH.read_text(encoding="utf-8")

    assert "SELECTION_WINDOW" in text
    assert "OOS_WINDOW_1" in text and "OOS_WINDOW_2" in text
    assert "no retuning" in text.lower()


def test_contract_document_requires_promotion_grade_fail_closed_criteria() -> None:
    text = PIT_CONTRACT_DOC_PATH.read_text(encoding="utf-8")

    assert "promotion_grade = 0" in text or "promotion_grade=0" in text
    for criterion in pit.PROMOTION_GRADE_CRITERIA:
        assert criterion in text, f"§10 criterion {criterion!r} missing from frozen contract doc"


def test_contract_document_requires_immutable_evidence_and_verifier() -> None:
    text = PIT_CONTRACT_DOC_PATH.read_text(encoding="utf-8")

    assert "provenance_hashes" in text
    assert "Deterministic verifier" in text or "deterministic verifier" in text.lower()
    assert "sha256" in text.lower()


def test_contract_document_declares_no_pit_outcome_metrics_inspected() -> None:
    text = PIT_CONTRACT_DOC_PATH.read_text(encoding="utf-8")
    assert "pit_outcome_metrics_inspected=0" in text


def test_contract_document_carries_required_safety_markers() -> None:
    text = PIT_CONTRACT_DOC_PATH.read_text(encoding="utf-8")
    for marker in (
        "account_awareness=0",
        "decision_permission=0",
        "execution_intent=0",
        "order_submission=0",
        "broker_calls=0" if "broker_calls=0" in text else "broker_writes=0",
        "automatic_exit_profile_v1_writes=0",
        "decision_gate_changes=0",
        "execution_planner_changes=0",
        "executor_changes=0",
        "production_promotion=0",
        "methodology_promotion_grade=0",
    ):
        assert marker in text, f"missing safety marker: {marker}"
