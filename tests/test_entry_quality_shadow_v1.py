from decimal import Decimal

from src.research.entry_quality_shadow_v1 import (
    EntryQualityInput,
    compute_entry_quality_shadow,
    compute_entry_strength,
)


def test_entry_quality_evolves_existing_trade_quality_score() -> None:
    result = compute_entry_quality_shadow(
        EntryQualityInput(
            trade_quality_score=Decimal("0.68"),
            timing_refinement_score=Decimal("0.03"),
            quality_penalty=Decimal("0.05"),
            quality_status_1d="TRUSTED",
            quality_status_4h="TRUSTED",
            quality_status_1h="TRUSTED",
        )
    )

    assert result.entry_quality_score == Decimal("0.660000")
    assert result.entry_quality_state == "GOOD"
    assert "EVOLVED_FROM_TRADE_QUALITY_SCORE" in result.reasons
    assert "POSITIVE_1H_TIMING_REFINEMENT" in result.reasons
    assert "DATA_QUALITY_PENALTY_APPLIED" in result.reasons
    assert result.blockers == ()


def test_entry_quality_blocks_on_required_quality() -> None:
    result = compute_entry_quality_shadow(
        EntryQualityInput(
            trade_quality_score=Decimal("0.90"),
            timing_refinement_score=Decimal("0.03"),
            quality_penalty=Decimal("0"),
            quality_status_1d="TRUSTED",
            quality_status_4h="BLOCKED",
            quality_status_1h="TRUSTED",
        )
    )

    assert result.entry_quality_score is None
    assert result.entry_quality_state == "BLOCKED"
    assert result.blockers == ("BLOCKED_4H_QUALITY",)


def test_blocked_1h_only_removes_refinement_not_cq() -> None:
    result = compute_entry_quality_shadow(
        EntryQualityInput(
            trade_quality_score=Decimal("0.50"),
            timing_refinement_score=Decimal("0"),
            quality_penalty=Decimal("0"),
            quality_status_1d="TRUSTED",
            quality_status_4h="TRUSTED",
            quality_status_1h="BLOCKED",
        )
    )

    assert result.entry_quality_score == Decimal("0.500000")
    assert result.entry_quality_state == "WATCH"
    assert "1H_REFINEMENT_UNAVAILABLE" in result.reasons


def test_entry_strength_multiplies_ppp_percentage_points_by_cq() -> None:
    assert compute_entry_strength(
        ppp_pct=Decimal("20.00"),
        entry_quality_score=Decimal("0.75"),
    ) == Decimal("15.000000")


def test_entry_strength_fails_closed_on_missing_ppp_or_cq() -> None:
    assert compute_entry_strength(
        ppp_pct=None,
        entry_quality_score=Decimal("0.75"),
    ) is None
    assert compute_entry_strength(
        ppp_pct=Decimal("20"),
        entry_quality_score=None,
    ) is None


def test_entry_strength_rejects_invalid_ranges() -> None:
    assert compute_entry_strength(
        ppp_pct=Decimal("-1"),
        entry_quality_score=Decimal("0.75"),
    ) is None
    assert compute_entry_strength(
        ppp_pct=Decimal("20"),
        entry_quality_score=Decimal("1.01"),
    ) is None
