from __future__ import annotations

from decimal import Decimal

from src.research import verify_fib_exit_ladder_v1_pit_replay_phase_c_v1 as verifier


EXPECTED_POLICIES = {
    "LINK": ("PRO_3X4X", "0.80"),
    "XLM": ("PRO_3X4X", "0.80"),
    "SOL": ("SUPERCYCLE", "0.80"),
    "XRP": ("PRO_3X4X", "0.80"),
    "HOT": ("EXPLOSIVE_SUPERCYCLE", "0.40"),
}

EXPECTED_OUTCOMES = {
    "LINK": "REVISED",
    "XLM": "REJECTED",
    "SOL": "REJECTED",
    "XRP": "REVISED",
    "HOT": "REJECTED",
}

EXPECTED_OOS_ALPHAS = {
    "LINK": (Decimal("0"), Decimal("17.04854530022269843270725661")),
    "XLM": (Decimal("0"), Decimal("0")),
    "SOL": (Decimal("-72.1120047768768384703926335"), Decimal("0")),
    "XRP": (Decimal("0"), Decimal("59.12102260550632163535389343")),
    "HOT": (Decimal("0"), Decimal("0")),
}


def test_phase_c_raw_evidence_hash_and_frozen_identity() -> None:
    data = verifier.load_raw_evidence()
    assert data["code_commit_sha"] == verifier.CODE_COMMIT_SHA
    assert tuple(data["symbols"]) == verifier.EXPECTED_SYMBOLS
    assert data["methodology_promotion_grade"] == 0
    assert data["promotion_eligible"] is False


def test_phase_c_verifier_rederives_selection_and_dispositions_from_raw_rows() -> None:
    result = verifier.verify_evidence()
    assets = {row["symbol"]: row for row in result["assets"]}

    assert set(assets) == set(verifier.EXPECTED_SYMBOLS)
    for symbol, (family, fraction) in EXPECTED_POLICIES.items():
        row = assets[symbol]
        assert row["selected_target_family"] == family
        assert row["selected_max_ladder_sell_fraction"] == fraction
        assert row["outcome"] == EXPECTED_OUTCOMES[symbol]
        assert Decimal(row["oos_window_1_alpha_vs_hold_pct"]) == EXPECTED_OOS_ALPHAS[symbol][0]
        assert Decimal(row["oos_window_2_alpha_vs_hold_pct"]) == EXPECTED_OOS_ALPHAS[symbol][1]

    assert result["overall_disposition"] == "REJECTED"


def test_phase_c_original_vs_selected_assignment_delta_is_only_xrp() -> None:
    result = verifier.verify_evidence()
    changed = {
        symbol
        for symbol, row in result["original_vs_selected"].items()
        if row["assignment_changed"]
    }
    assert changed == {"XRP"}
    assert result["original_vs_selected"]["XRP"] == {
        "original_target_family": "SUPERCYCLE",
        "original_max_ladder_sell_fraction": "0.80",
        "selected_target_family": "PRO_3X4X",
        "selected_max_ladder_sell_fraction": "0.80",
        "assignment_changed": True,
    }


def test_phase_c_promotion_remains_fail_closed_on_oos_evidence() -> None:
    result = verifier.verify_evidence()
    assert result["methodology_promotion_grade"] == 0
    assert result["promotion_eligible"] is False
    assert result["promotion_blocker"] == "POSITIVE_OOS_ALPHA_NOT_MET"
    assert result["overall_disposition"] == "REJECTED"
