from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

MODULE_NAME = "src.research.run_fib_exit_ladder_v1_pit_replay_phase_c_v1"


def test_asset_not_found_row_preserves_complete_evidence_shape() -> None:
    module = importlib.import_module(MODULE_NAME)

    row = module._asset_not_found_evidence_row("LINK")

    assert row == {
        "symbol": "LINK",
        "asset_id": None,
        "status": "ASSET_NOT_FOUND",
        "candle_row_counts": {
            "SELECTION_WINDOW": 0,
            "OOS_WINDOW_1": 0,
            "OOS_WINDOW_2": 0,
        },
        "selected_policy": None,
        "selection_grid_rows": [],
        "oos_window_1": None,
        "oos_window_2": None,
    }


def test_all_insufficient_candles_grid_preserves_exact_asset_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(MODULE_NAME)
    replay = SimpleNamespace(
        selected_policy=None,
        selection_grid_results={
            ("family-a", "fraction-a"): SimpleNamespace(
                status=module.engine.STATUS_INSUFFICIENT_CANDLES
            ),
            ("family-b", "fraction-b"): SimpleNamespace(
                status=module.engine.STATUS_INSUFFICIENT_CANDLES
            ),
        },
    )
    monkeypatch.setattr(
        module,
        "_grid_rows",
        lambda replay, candles: [
            {"status": module.engine.STATUS_INSUFFICIENT_CANDLES}
        ],
    )

    row = module._asset_evidence_row(
        symbol="LINK",
        asset_id=1,
        row_counts={
            "SELECTION_WINDOW": 5,
            "OOS_WINDOW_1": 0,
            "OOS_WINDOW_2": 0,
        },
        candles_by_window={"SELECTION_WINDOW": []},
        replay=replay,
    )

    assert row["status"] == module.engine.STATUS_INSUFFICIENT_CANDLES
    assert row["selected_policy"] is None
    assert row["oos_window_1"] is None
    assert row["oos_window_2"] is None


def test_non_candle_no_selection_remains_generic_insufficient_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(MODULE_NAME)
    replay = SimpleNamespace(
        selected_policy=None,
        selection_grid_results={
            ("family-a", "fraction-a"): SimpleNamespace(
                status=module.engine.STATUS_NO_ANCHOR_SET_FOUND
            )
        },
    )
    monkeypatch.setattr(
        module,
        "_grid_rows",
        lambda replay, candles: [
            {"status": module.engine.STATUS_NO_ANCHOR_SET_FOUND}
        ],
    )

    row = module._asset_evidence_row(
        symbol="LINK",
        asset_id=1,
        row_counts={"SELECTION_WINDOW": 100},
        candles_by_window={"SELECTION_WINDOW": []},
        replay=replay,
    )

    assert row["status"] == module.engine.STATUS_INSUFFICIENT_DATA
