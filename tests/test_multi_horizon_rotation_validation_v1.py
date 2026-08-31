from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.research.multi_horizon_rotation_validation_v1 import (
    ValidationRow,
    correlation_with_fisher_ci,
    derive_chronological_split,
    holm_bonferroni,
    partial_correlation,
    persistence_and_chop,
    validation_summary,
)


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _row(
    index: int,
    *,
    score: float | None,
    asset_id: int = 1,
    candidate_id: str = "C1",
) -> ValidationRow:
    value = None if score is None else score / 100.0
    return ValidationRow(
        venue="bitvavo",
        asset_id=asset_id,
        asof_ts=BASE + timedelta(minutes=15 * index),
        candidate_id=candidate_id,
        candidate_score=score,
        b0_score=(None if score is None else score * 0.5),
        b0_pressure_state="ROTATION_IN",
        b1_return=value,
        forward_15m=value,
        forward_1h=value,
        forward_4h=value,
        forward_24h=value,
    )


def test_correlation_uses_only_paired_finite_rows() -> None:
    result = correlation_with_fisher_ci(
        [1.0, 2.0, None, 4.0, 5.0],
        [2.0, 4.0, 6.0, 8.0, 10.0],
    )
    assert result.sample_count == 4
    assert result.correlation is not None
    assert abs(result.correlation - 1.0) < 1e-12
    assert result.ci_low is not None
    assert result.ci_high is not None


def test_partial_correlation_fails_closed_when_baseline_is_degenerate() -> None:
    result = partial_correlation(
        [1.0, 2.0, 3.0, 4.0],
        [2.0, 4.0, 6.0, 8.0],
        [1.0, 1.0, 1.0, 1.0],
    )
    assert result.sample_count == 4
    assert result.correlation is None


def test_holm_bonferroni_is_step_down_and_deterministic_on_ties() -> None:
    result = holm_bonferroni(
        {
            "C2:1h": 0.01,
            "C1:15m": 0.01,
            "C3:4h": 0.20,
        },
        alpha=0.05,
    )
    assert result == {
        "C2:1h": True,
        "C1:15m": True,
        "C3:4h": False,
    }


def test_holm_missing_test_still_counts_in_frozen_family_size() -> None:
    result = holm_bonferroni(
        {
            "available": 0.03,
            "missing": None,
        },
        alpha=0.05,
    )
    assert result["available"] is False
    assert result["missing"] is None


def test_family_wide_holm_contains_all_twelve_candidate_horizon_tests() -> None:
    rows: list[ValidationRow] = []
    for candidate_index, candidate_id in enumerate(("C1", "C2", "C3"), start=1):
        for index in range(8):
            score = float((index + 1) * candidate_index)
            rows.append(
                _row(
                    index,
                    score=score,
                    asset_id=index + 1,
                    candidate_id=candidate_id,
                )
            )
    summary = validation_summary(rows)
    assert summary["holm_family_size"] == 12
    family = summary["holm_bonferroni_family"]
    assert isinstance(family, dict)
    assert set(family) == {
        f"{candidate_id}:{horizon}"
        for candidate_id in ("C1", "C2", "C3")
        for horizon in ("15m", "1h", "4h", "24h")
    }


def test_persistence_counts_flip_reversion_as_chop_within_four_samples() -> None:
    rows = [
        _row(0, score=10),
        _row(1, score=12),
        _row(2, score=-8),
        _row(3, score=-5),
        _row(4, score=7),
    ]
    result = persistence_and_chop(rows, reversion_window_samples=4)
    assert result.sign_flip_count == 2
    assert result.chop_reversion_count == 1
    assert result.chop_rate == 0.5
    assert result.run_count == 3
    assert result.max_run_samples == 2


def test_missing_sample_breaks_persistence_and_chop_chain() -> None:
    rows = [
        _row(0, score=10),
        _row(1, score=None),
        _row(2, score=-10),
        _row(3, score=10),
    ]
    result = persistence_and_chop(rows, reversion_window_samples=4)
    assert result.run_count == 3
    assert result.sign_flip_count == 1
    assert result.chop_reversion_count == 0


def test_timestamp_gap_breaks_persistence_without_counting_flip() -> None:
    rows = [
        _row(0, score=10),
        _row(2, score=-10),
    ]
    result = persistence_and_chop(rows)
    assert result.run_count == 2
    assert result.sign_flip_count == 0
    assert result.chop_reversion_count == 0


def test_zero_is_its_own_frozen_state() -> None:
    rows = [_row(0, score=1), _row(1, score=0), _row(2, score=-1)]
    result = persistence_and_chop(rows)
    assert result.sign_flip_count == 2
    assert result.run_count == 3


def test_chronological_split_is_grid_aligned_and_non_overlapping() -> None:
    end = BASE + timedelta(days=100)
    split = derive_chronological_split(start=BASE, end=end)
    discovery = split["discovery"]
    validation = split["validation"]
    holdout = split["final_holdout"]
    assert discovery[0] == BASE
    assert discovery[1] == validation[0]
    assert validation[1] == holdout[0]
    assert holdout[1] == end
    for boundary in (discovery[1], validation[1]):
        assert boundary.minute % 15 == 0
        assert boundary.second == 0


def test_too_short_split_fails_closed() -> None:
    try:
        derive_chronological_split(start=BASE, end=BASE + timedelta(minutes=60))
    except ValueError as exc:
        assert "insufficient replay-safe span" in str(exc)
    else:
        raise AssertionError("expected too-short split to fail")


def test_missing_candidate_score_reduces_paired_sample_count() -> None:
    rows = [_row(0, score=1), _row(1, score=None), _row(2, score=3), _row(3, score=4)]
    result = correlation_with_fisher_ci(
        [row.candidate_score for row in rows],
        [row.forward_15m for row in rows],
    )
    assert result.sample_count == 3
    assert result.correlation is None
