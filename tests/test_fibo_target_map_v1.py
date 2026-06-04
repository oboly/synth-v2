from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.research.run_fibo_target_map_v1 import (
    AssetRef,
    Candle,
    build_row_for_symbol,
    build_rows,
    is_partial_scope,
    merge_rows_by_symbol,
)


EXPECTED_ROW_FIELDS = [
    "symbol",
    "venue",
    "interval",
    "anchor_start_ts",
    "anchor_end_ts",
    "swing_low_price",
    "swing_high_price",
    "leg_direction",
    "range_pct",
    "local_reaction_price",
    "fib_1272_price",
    "fib_1618_price",
    "fib_2618_price",
    "fib_3618_price",
    "fib_4236_price",
    "current_price",
    "anchor_quality",
    "bars_since_anchor_end",
    "swing_window",
    "anchor_reason",
    "target_status",
    "current_target_band",
    "distance_to_local_reaction_pct",
    "next_extension_target_level",
    "next_extension_target_price",
    "distance_to_next_extension_pct",
    "main_extension_target_level",
    "main_extension_target_price",
    "stretch_target_level",
    "stretch_target_price",
    "bull_target_level",
    "bull_target_price",
    "moonbag_target_level",
    "moonbag_target_price",
    "next_fibo_support_level",
    "next_fibo_support_price",
    "distance_to_next_fibo_support_pct",
    "secondary_fibo_support_level",
    "secondary_fibo_support_price",
    "distance_to_secondary_fibo_support_pct",
    "reentry_zone_label",
    "reentry_distance_pct",
    "tp_reentry_risk_label",
    "next_target_level",
    "next_target_price",
    "distance_to_next_target_pct",
]


def _candles(symbol: str, *, base_low: float, base_high: float) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    highs = [base_high * 0.85, base_high * 0.83, base_high * 0.90, base_high * 0.95, base_high, base_high * 0.98, base_high * 0.96]
    lows = [base_low * 1.20, base_low, base_low * 1.10, base_low * 1.25, base_low * 1.45, base_low * 1.55, base_low * 1.40]
    closes = [base_low * 1.18, base_low * 1.05, base_low * 1.28, base_low * 1.48, base_low * 1.72, base_low * 1.62, base_low * 1.58]
    rows: list[Candle] = []
    for index, (high_price, low_price, close_price) in enumerate(zip(highs, lows, closes)):
        open_ts = start + timedelta(days=index)
        close_ts = open_ts + timedelta(days=1)
        rows.append(
            Candle(
                asset_id=1,
                symbol=symbol,
                open_ts_utc=open_ts,
                close_ts_utc=close_ts,
                open_price=(high_price + low_price) / 2.0,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
            )
        )
    return rows


def test_wld_ondo_like_fixture_emits_zone_rows_when_candles_exist() -> None:
    assets = [AssetRef(asset_id=1, symbol="WLD"), AssetRef(asset_id=2, symbol="ONDO")]
    rows = build_rows(
        assets=assets,
        requested_symbols=["WLD", "ONDO"],
        candles_by_symbol={
            "WLD": _candles("WLD", base_low=0.20, base_high=0.36),
            "ONDO": _candles("ONDO", base_low=0.17, base_high=0.42),
        },
        venue="bitvavo",
        interval="1d",
        swing_window=1,
    )
    assert [row["symbol"] for row in rows] == ["ONDO", "WLD"]
    assert all(row["target_status"] != "MISSING_MARKET_DATA" for row in rows)
    assert all(row["fib_1618_price"] is not None for row in rows)
    assert all(row["next_fibo_support_price"] is not None for row in rows)


def test_missing_market_data_produces_explicit_skip_reason() -> None:
    rows = build_rows(
        assets=[AssetRef(asset_id=1, symbol="WLD")],
        requested_symbols=["WLD"],
        candles_by_symbol={},
        venue="bitvavo",
        interval="1d",
        swing_window=1,
    )
    assert len(rows) == 1
    assert rows[0]["symbol"] == "WLD"
    assert rows[0]["target_status"] == "MISSING_MARKET_DATA"
    assert rows[0]["anchor_reason"] == "no_market_candles_found_for_symbol"


def test_requested_symbol_not_in_universe_is_not_silently_excluded() -> None:
    rows = build_rows(
        assets=[AssetRef(asset_id=1, symbol="WLD")],
        requested_symbols=["ONDO", "WLD"],
        candles_by_symbol={"WLD": _candles("WLD", base_low=0.20, base_high=0.36)},
        venue="bitvavo",
        interval="1d",
        swing_window=1,
    )
    assert [row["symbol"] for row in rows] == ["ONDO", "WLD"]
    assert rows[0]["target_status"] == "MISSING_MARKET_DATA"
    assert rows[0]["anchor_reason"] == "symbol_not_found_in_asset_universe"
    assert rows[1]["target_status"] != "MISSING_MARKET_DATA"


def test_canonical_output_schema_remains_stable() -> None:
    row = build_row_for_symbol(
        "WLD",
        _candles("WLD", base_low=0.20, base_high=0.36),
        venue="bitvavo",
        interval="1d",
        swing_window=1,
    )
    assert list(row.keys()) == EXPECTED_ROW_FIELDS


def test_partial_scope_merges_without_dropping_existing_symbols() -> None:
    existing = [
        {"symbol": "NEAR", "target_status": "BELOW_LOCAL_REACTION"},
        {"symbol": "RENDER", "target_status": "BETWEEN_1272_1618"},
    ]
    new = [
        {"symbol": "WLD", "target_status": "BETWEEN_1618_2618"},
        {"symbol": "ONDO", "target_status": "BELOW_LOCAL_REACTION"},
    ]
    merged = merge_rows_by_symbol(existing, new)
    assert [row["symbol"] for row in merged] == ["NEAR", "ONDO", "RENDER", "WLD"]


def test_is_partial_scope_detects_scoped_runs() -> None:
    assert is_partial_scope(requested_symbols=["WLD"], max_symbols=0) is True
    assert is_partial_scope(requested_symbols=None, max_symbols=10) is True
    assert is_partial_scope(requested_symbols=None, max_symbols=0) is False


def test_runner_has_no_forbidden_imports_or_order_mutation_strings() -> None:
    source = Path("src/research/run_fibo_target_map_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {"decision_gate", "execution_planner", "executor"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for item in forbidden_imports:
                assert item not in module
    assert "placeOrder" not in source
    assert "cancelOrder" not in source
    assert "create order" not in source.lower()


def main() -> None:
    test_wld_ondo_like_fixture_emits_zone_rows_when_candles_exist()
    test_missing_market_data_produces_explicit_skip_reason()
    test_requested_symbol_not_in_universe_is_not_silently_excluded()
    test_canonical_output_schema_remains_stable()
    test_partial_scope_merges_without_dropping_existing_symbols()
    test_is_partial_scope_detects_scoped_runs()
    test_runner_has_no_forbidden_imports_or_order_mutation_strings()
    print("ok")


if __name__ == "__main__":
    main()
