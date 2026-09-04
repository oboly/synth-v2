from pathlib import Path


def test_frozen_holdout_selection_is_c1_only() -> None:
    text = Path("docs/research/multi_horizon_rotation_c1_final_holdout_selection_v1.md").read_text()
    assert "C1 -> ADVANCE_TO_FINAL_HOLDOUT" in text
    assert "C2 -> REJECT_BEFORE_FINAL_HOLDOUT" in text
    assert "C3 -> INSUFFICIENT_DATA" in text
    assert "confirmatory test of C1 only" in text
