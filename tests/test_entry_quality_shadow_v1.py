from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.research.entry_quality_shadow_v1 import (
    EntryQualityInput,
    compute_entry_quality_shadow,
    compute_entry_strength,
)
from src.research.run_entry_quality_shadow_v1 import _load_ppp_csv, _source_asof


def test_entry_quality_uses_trade_quality_as_independent_baseline() -> None:
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

    assert result.entry_quality_score == Decimal("0.680000")
    assert result.entry_quality_state == "GOOD"
    assert "BASELINE_FROM_TRADE_QUALITY_SCORE" in result.reasons
    assert "TIMING_REFINEMENT_OBSERVED_NOT_APPLIED" in result.reasons
    assert "QUALITY_PENALTY_OBSERVED_NOT_APPLIED" in result.reasons
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


def test_blocked_1h_does_not_block_higher_timeframe_cq() -> None:
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


def test_source_asof_uses_evidence_timestamp_not_runner_time() -> None:
    row = SimpleNamespace(symbol="AAVE", asof_ts_utc="2026-08-28 04:00:00")
    assert _source_asof(row) == "2026-08-28 04:00:00"


def test_source_asof_fails_closed_when_missing() -> None:
    row = SimpleNamespace(symbol="AAVE", asof_ts_utc=None)
    with pytest.raises(ValueError, match="Missing canonical source as-of"):
        _source_asof(row)


def test_ppp_csv_rejects_mixed_planning_and_actionable(tmp_path) -> None:
    path = tmp_path / "ppp.csv"
    path.write_text(
        "symbol,ppp_pct,ppp_kind,ppp_source_ref\n"
        "AAVE,20,ACTIONABLE_PPP,action:aave\n"
        "ETH,10,PLANNING_PPP,planning:eth\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must contain exactly one PPP kind"):
        _load_ppp_csv(str(path))


def test_ppp_csv_rejects_unknown_kind(tmp_path) -> None:
    path = tmp_path / "ppp.csv"
    path.write_text(
        "symbol,ppp_pct,ppp_kind,ppp_source_ref\n"
        "AAVE,20,SURPRISE_PPP,source:aave\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported ppp_kind"):
        _load_ppp_csv(str(path))
