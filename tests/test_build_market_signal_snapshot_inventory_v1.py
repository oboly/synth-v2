from __future__ import annotations

import ast
import csv
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.market_data.native_short_fib_context_v1 import NativeShortContextRow
from src.research import build_market_signal_snapshot_inventory_v1 as inv


ROOT = Path(__file__).parent.parent
MODULE_PATH = ROOT / "src" / "research" / "build_market_signal_snapshot_inventory_v1.py"
FORBIDDEN_IMPORT_FRAGMENTS = (
    "selection_engine",
    "decision_gate",
    "execution_planner",
    "executor",
    "agents",
    "broker",
    "account",
    "order",
    "wallet",
    "balance",
    "dashboard",
)


def _ts(hours: int = 0) -> datetime:
    return datetime(2026, 6, 5, 12, 0, tzinfo=UTC) + timedelta(hours=hours)


def _native_row(
    symbol: str = "BTC",
    *,
    context_status: str = "NATIVE_SHORT_CONTEXT_AVAILABLE",
    freshness_status: str = "FRESH",
    lifecycle_state: str = "TARGET_ACTIVE",
    support_state: str = "ALIGNED_WITH_4H",
    latest_primary_offset_hours: int = 0,
    latest_support_offset_hours: int = 0,
) -> NativeShortContextRow:
    return NativeShortContextRow(
        symbol=symbol,
        venue="bitvavo",
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
        context_status=context_status,
        map_cycle_id=f"{symbol}-cycle-1",
        anchor_start_ts_utc=_ts(-48),
        anchor_end_ts_utc=_ts(-36),
        anchor_low_price=Decimal("100"),
        anchor_high_price=Decimal("120"),
        breakout_gate_price=Decimal("120"),
        latest_primary_close_ts_utc=_ts(latest_primary_offset_hours),
        latest_support_close_ts_utc=_ts(latest_support_offset_hours),
        latest_primary_close_price=Decimal("130"),
        ext_1_272_price=Decimal("125"),
        ext_1_618_price=Decimal("140"),
        ext_2_000_price=Decimal("160"),
        active_target_levels=(Decimal("140"), Decimal("160")),
        previous_target_levels=(Decimal("125"),),
        reload_r382_price=Decimal("118"),
        reload_r500_price=Decimal("115"),
        reload_r618_price=Decimal("112"),
        reload_r786_price=Decimal("108"),
        invalidation_price=Decimal("98"),
        primary_4h_lifecycle_state=lifecycle_state,
        supporting_1h_state=support_state,
        context_freshness_status=freshness_status,
        max_primary_high_since_anchor=Decimal("132"),
        min_primary_low_since_anchor=Decimal("110"),
        source_name="native_short_fib_context_v1",
        source_version="0.1",
        source_primary_ref="obs_market_candle:4h:BTC",
        source_support_ref="obs_market_candle:1h:BTC",
        current_map_status="MAP_ACTIVE",
        previous_map_cycle_id="BTC-cycle-0",
        previous_map_lifecycle_state="MAP_COMPLETED",
        rollover_state="ROLLED_FORWARD",
        selection_reason="LATEST_ACTIVE_MAP",
    )


def _candle(symbol: str, hours: int, price: str = "100") -> inv.InventoryCandle:
    p = Decimal(price)
    return inv.InventoryCandle(
        symbol=symbol,
        close_ts_utc=_ts(hours),
        open_price=p,
        high_price=p + Decimal("1"),
        low_price=p - Decimal("1"),
        close_price=p,
    )


def _candles(symbol: str, *, count: int = 20, start_hours: int = -76, step_hours: int = 4) -> list[inv.InventoryCandle]:
    return [
        _candle(symbol, start_hours + index * step_hours, str(100 + index % 4))
        for index in range(count)
    ]


def _build(
    tmp_path: Path,
    *,
    symbols: list[str] | None = None,
    native_rows: dict[str, NativeShortContextRow] | None = None,
    native_source_missing: bool = False,
    candles_by_timeframe: dict[str, dict[str, list[inv.InventoryCandle]]] | None = None,
) -> inv.SnapshotBuildResult:
    resolved_symbols = symbols or ["BTC"]
    if candles_by_timeframe is None:
        candles_by_timeframe = {
            "4h": {symbol: _candles(symbol) for symbol in resolved_symbols},
            "1h": {symbol: [_candle(symbol, -2), _candle(symbol, -1), _candle(symbol, 0)] for symbol in resolved_symbols},
        }
    return inv.build_inventory(
        symbols=resolved_symbols,
        venue="bitvavo",
        as_of_ts_utc=_ts(0),
        native_short_rows_path=Path("fixtures/native_short_rows.csv"),
        output_root=tmp_path,
        candle_lookback_days=90,
        native_rows_override=native_rows if native_rows is not None else {"BTC": _native_row("BTC")},
        native_source_missing_override=native_source_missing,
        candles_by_timeframe=candles_by_timeframe,
    )


def _find_row(result: inv.SnapshotBuildResult, *, symbol: str, signal_id: str, timeframe: str) -> dict[str, Any]:
    matches = [
        row
        for row in result.rows
        if row["symbol"] == symbol and row["signal_id"] == signal_id and row["timeframe"] == timeframe
    ]
    assert len(matches) == 1
    return matches[0]


def _imports_for(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
                for alias in node.names:
                    names.append(f"{node.module}.{alias.name}")
            for alias in node.names:
                names.append(alias.name)
    return names


def test_registry_contains_only_verified_canonical_source_families() -> None:
    registry = inv._registry()
    families = {entry["signal_family"] for entry in registry}
    assert families == {
        "native_short_map_context",
        "local_ma_atr_context",
        "impulse_health_context",
        "extension_context",
        "market_candle_observation",
    }
    joined = json.dumps(registry)
    for fabricated_family in ("RSI", "volume", "participation", "rotation", "breakout", "BTC-relative"):
        assert fabricated_family not in joined
    assert len({entry["signal_id"] for entry in registry}) == len(registry)


def test_native_short_available_row_retains_lifecycle_map_cycle_freshness_and_lineage(tmp_path: Path) -> None:
    result = _build(tmp_path, native_rows={"BTC": _native_row("BTC")})
    row = _find_row(result, symbol="BTC", signal_id="native_short_map_lineage", timeframe="4h+1h")
    assert row["availability_status"] == "AVAILABLE"
    assert row["coverage_status"] == "AVAILABLE"
    assert row["source_record_id"] == "BTC-cycle-1"
    assert row["freshness_ts_utc"] == "2026-06-05T12:00:00Z"
    assert row["source_lineage"]["map_cycle_id"] == "BTC-cycle-1"
    assert row["source_lineage"]["selection_reason"] == "LATEST_ACTIVE_MAP"
    assert row["source_lineage"]["source_primary_ref"] == "obs_market_candle:4h:BTC"
    assert row["source_lineage"]["primary_4h_lifecycle_state"] == "TARGET_ACTIVE"


def test_missing_native_short_row_emits_explicit_unavailable_snapshot_row(tmp_path: Path) -> None:
    result = _build(tmp_path, symbols=["BTC", "ETH"], native_rows={"BTC": _native_row("BTC")})
    row = _find_row(result, symbol="ETH", signal_id="native_short_context_status", timeframe="4h+1h")
    assert row["availability_status"] == "DATA_UNAVAILABLE"
    assert row["coverage_status"] == "SOURCE_MISSING"
    assert row["normalized_state"] == "DATA_UNAVAILABLE"
    assert row["raw_value"] is None


def test_stale_and_partial_source_status_remain_visible_without_fallback(tmp_path: Path) -> None:
    result = _build(
        tmp_path,
        symbols=["BTC", "ETH"],
        native_rows={
            "BTC": _native_row("BTC", context_status="CONTEXT_INVALID_OR_STALE", freshness_status="STALE_PRIMARY_4H"),
            "ETH": _native_row("ETH", context_status="INSUFFICIENT_1H_HISTORY", support_state="UNKNOWN"),
        },
    )
    stale = _find_row(result, symbol="BTC", signal_id="native_short_context_status", timeframe="4h+1h")
    partial = _find_row(result, symbol="ETH", signal_id="native_short_1h_support_state", timeframe="1h")
    assert stale["normalized_state"] == "CONTEXT_INVALID_OR_STALE"
    assert stale["coverage_status"] == "STALE"
    assert partial["normalized_state"] == "UNKNOWN"
    assert partial["coverage_status"] == "PARTIAL"


def test_candle_input_excludes_candles_after_as_of_ts(tmp_path: Path) -> None:
    result = _build(
        tmp_path,
        candles_by_timeframe={
            "4h": {"BTC": [_candle("BTC", -4), _candle("BTC", 0), _candle("BTC", 4)]},
            "1h": {"BTC": [_candle("BTC", -1), _candle("BTC", 1)]},
        },
    )
    row_4h = _find_row(result, symbol="BTC", signal_id="candle_availability_4h", timeframe="4h")
    row_1h = _find_row(result, symbol="BTC", signal_id="candle_availability_1h", timeframe="1h")
    assert row_4h["raw_value"]["candle_count"] == 2
    assert row_4h["freshness_ts_utc"] == "2026-06-05T12:00:00Z"
    assert row_1h["raw_value"]["candle_count"] == 1
    assert row_1h["freshness_ts_utc"] == "2026-06-05T11:00:00Z"


def test_snapshot_output_is_deterministic_for_identical_fixture_inputs(tmp_path: Path) -> None:
    first = _build(tmp_path / "first")
    second = _build(tmp_path / "second")
    assert first.run_id == second.run_id
    for filename in (
        "signal_registry.json",
        "signal_snapshot_rows.jsonl",
        "coverage_summary.csv",
        "freshness_summary.csv",
        "manifest.json",
    ):
        assert (first.output_dir / filename).read_bytes() == (second.output_dir / filename).read_bytes()


def test_coverage_and_freshness_summaries_count_states_correctly(tmp_path: Path) -> None:
    result = _build(
        tmp_path,
        symbols=["BTC", "ETH", "SOL"],
        native_rows={
            "BTC": _native_row("BTC"),
            "ETH": _native_row("ETH", context_status="INSUFFICIENT_1H_HISTORY"),
            "SOL": _native_row("SOL", context_status="CONTEXT_INVALID_OR_STALE", freshness_status="STALE_PRIMARY_4H"),
        },
        candles_by_timeframe={
            "4h": {
                "BTC": _candles("BTC"),
                "ETH": [],
                "SOL": [_candle("SOL", -24)],
            },
            "1h": {
                "BTC": [_candle("BTC", 0)],
                "ETH": [],
                "SOL": [_candle("SOL", -10)],
            },
        },
    )
    with (result.output_dir / "coverage_summary.csv").open(encoding="utf-8", newline="") as handle:
        coverage = {(row["signal_id"], row["timeframe"]): row for row in csv.DictReader(handle)}
    candle_freshness_4h = coverage[("candle_freshness_4h", "4h")]
    assert candle_freshness_4h["eligible_symbols"] == "3"
    assert candle_freshness_4h["available_symbols"] == "1"
    assert candle_freshness_4h["stale_symbols"] == "1"
    assert candle_freshness_4h["unavailable_symbols"] == "1"

    with (result.output_dir / "freshness_summary.csv").open(encoding="utf-8", newline="") as handle:
        freshness = {(row["signal_id"], row["timeframe"]): row for row in csv.DictReader(handle)}
    summary = freshness[("candle_freshness_4h", "4h")]
    assert summary["freshest_timestamp"] == "2026-06-05T12:00:00Z"
    assert summary["oldest_available_timestamp"] == "2026-06-04T12:00:00Z"
    assert summary["stale_count"] == "1"
    assert summary["missing_timestamp_count"] == "1"


def test_runner_imports_no_account_selection_decision_planner_executor_broker_or_order_code() -> None:
    imports = _imports_for(MODULE_PATH)
    for imported in imports:
        for fragment in FORBIDDEN_IMPORT_FRAGMENTS:
            assert fragment not in imported, (
                f"forbidden import fragment {fragment!r} found in {imported!r}"
            )


def test_db_reader_uses_bounded_select_and_no_db_writes() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.sql = ""
            self.params: tuple[Any, ...] = ()

        def __enter__(self) -> "Cursor":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, sql: str, params: tuple[Any, ...]) -> None:
            self.sql = sql
            self.params = params

        def fetchall(self) -> list[dict[str, Any]]:
            return [
                {
                    "symbol": "BTC",
                    "close_ts_utc": _ts(1),
                    "open_price": "1",
                    "high_price": "2",
                    "low_price": "1",
                    "close_price": "2",
                }
            ]

    class Conn:
        def __init__(self) -> None:
            self.cursor_obj = Cursor()
            self.commit_called = False

        def cursor(self) -> Cursor:
            return self.cursor_obj

        def commit(self) -> None:
            self.commit_called = True

    conn = Conn()
    rows = inv._fetch_candles_by_symbol(
        conn,
        "bitvavo",
        "4h",
        ["BTC"],
        _ts(-24),
        _ts(0),
    )
    sql_upper = conn.cursor_obj.sql.upper()
    assert "SELECT" in sql_upper
    assert "INSERT" not in sql_upper
    assert "UPDATE" not in sql_upper
    assert "DELETE" not in sql_upper
    assert "CLOSE_TS_UTC <= %S" in sql_upper
    assert conn.commit_called is False
    assert rows["BTC"] == []


def test_generated_artifacts_are_research_local_and_manifest_marks_non_predictive(tmp_path: Path) -> None:
    result = _build(tmp_path)
    assert result.output_dir.is_relative_to(tmp_path)
    assert inv.DEFAULT_OUTPUT_ROOT == Path("data/research/market_signal_snapshot_inventory_v1")
    manifest = json.loads((result.output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert "research-only" in manifest["safety_statement"]
    assert "market-only" in manifest["safety_statement"]
    assert "read-only" in manifest["safety_statement"]
    assert "non-predictive" in manifest["safety_statement"]
    assert not (ROOT / "data/research/market_signal_snapshot_inventory_v1").exists()
