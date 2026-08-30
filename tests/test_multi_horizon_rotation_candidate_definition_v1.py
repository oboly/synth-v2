from __future__ import annotations

from pathlib import Path

import yaml


CONFIG_PATH = Path("config/research/multi_horizon_rotation_candidate_definition_v1.yaml")


def load_config() -> dict:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def test_candidate_definition_requires_exact_15m_grid_alignment() -> None:
    config = load_config()

    assert config["source"]["input_interval"] == "15m"
    assert config["cohort"]["asof_must_align_exactly_to_input_close_grid"] is True
    assert config["windows"]["every_boundary_must_align_exactly_to_input_close_grid"] is True


def test_candidate_definition_forbids_stale_boundary_substitution() -> None:
    config = load_config()
    windows = config["windows"]

    assert windows["return_start_boundary_close_must_exist_exactly"] is True
    assert windows["return_end_boundary_close_must_exist_exactly"] is True
    assert windows["stale_pre_boundary_close_substitution"] == "forbidden"
    assert windows["contiguous_input_candles_required"] is True
    assert windows["missing_boundary_or_gap_result"] == "INSUFFICIENT_DATA"


def test_candidate_window_shapes_remain_frozen() -> None:
    config = load_config()

    assert config["windows"]["expected_candles_per_window"] == {
        "C1": 1,
        "C2": 4,
        "C3": 16,
    }
    assert [candidate["horizon_minutes"] for candidate in config["candidates"]] == [15, 60, 240]
