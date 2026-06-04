from __future__ import annotations

import ast
import json
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.research.multi_horizon_fib_backtest_v1 import run_multi_horizon_backtest
from src.research.multi_horizon_fib_contract_v1 import Candle


def _series(
    symbol: str,
    interval_code: str,
    values: list[tuple[str, str, str]],
    *,
    start: datetime,
    step: timedelta,
) -> list[Candle]:
    rows: list[Candle] = []
    for index, (high_price, low_price, close_price) in enumerate(values):
        open_ts = start + index * step
        close_ts = open_ts + step
        rows.append(
            Candle(
                symbol=symbol,
                venue="bitvavo",
                quote="EUR",
                interval_code=interval_code,
                open_ts_utc=open_ts,
                close_ts_utc=close_ts,
                open_price=(Decimal(high_price) + Decimal(low_price)) / Decimal("2"),
                high_price=Decimal(high_price),
                low_price=Decimal(low_price),
                close_price=Decimal(close_price),
            )
        )
    return rows


def _symbol_inputs(extra_daily: list[tuple[str, str, str]] | None = None) -> list[dict[str, object]]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    daily = [
        ("12", "10", "11"),
        ("11", "9", "10"),
        ("13", "10", "12"),
        ("16", "11", "15"),
        ("14", "12", "13"),
        ("18", "13", "17"),
        ("15", "12", "13"),
        ("19", "14", "18"),
        ("17", "15", "16"),
    ]
    if extra_daily:
        daily.extend(extra_daily)
    weekly = [
        ("20", "10", "18"),
        ("18", "12", "14"),
        ("24", "13", "23"),
        ("22", "15", "19"),
        ("28", "18", "26"),
        ("25", "17", "21"),
        ("30", "19", "28"),
        ("27", "20", "22"),
        ("32", "21", "30"),
    ]
    four_hour = daily + [("20", "16", "19"), ("18", "15", "16")]
    one_hour = four_hour + [("21", "17", "20"), ("19", "16", "17")]
    return [
        {
            "symbol": "WLD",
            "candles_by_interval": {
                "1h": _series("WLD", "1h", one_hour, start=start, step=timedelta(hours=1)),
                "4h": _series("WLD", "4h", four_hour, start=start, step=timedelta(hours=4)),
                "1d": _series("WLD", "1d", daily, start=start, step=timedelta(days=1)),
                "1w": _series("WLD", "1w", weekly, start=start, step=timedelta(weeks=1)),
            },
            "context_rows": [],
        }
    ]


def test_bootstrap_creates_deterministic_events_and_checkpoints() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_multi_horizon_backtest(
            mode="bootstrap",
            output_dir=Path(tmpdir),
            symbol_inputs=_symbol_inputs(),
            horizons=["SHORT", "MEDIUM", "LONG"],
            venue="bitvavo",
            quote="EUR",
            workers=1,
            pivot_span=1,
            write_files=True,
        )
        assert result["manifest"]["row_counts"]["swing_events"] > 0
        assert (Path(tmpdir) / "checkpoints" / "WLD_SHORT_checkpoint_v1.json").exists()
        assert (Path(tmpdir) / "checkpoints" / "WLD_MEDIUM_checkpoint_v1.json").exists()
        assert (Path(tmpdir) / "checkpoints" / "WLD_LONG_checkpoint_v1.json").exists()


def test_interrupted_bootstrap_resumes_without_duplicates() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        first = run_multi_horizon_backtest(
            mode="bootstrap",
            output_dir=Path(tmpdir),
            symbol_inputs=_symbol_inputs(),
            horizons=["SHORT"],
            venue="bitvavo",
            quote="EUR",
            workers=1,
            pivot_span=1,
            write_files=True,
        )
        second = run_multi_horizon_backtest(
            mode="incremental",
            output_dir=Path(tmpdir),
            symbol_inputs=_symbol_inputs(),
            horizons=["SHORT"],
            venue="bitvavo",
            quote="EUR",
            workers=1,
            pivot_span=1,
            write_files=True,
        )
        assert len(second["swing_events"]) == len(first["swing_events"])
        assert len({row["event_id"] for row in second["swing_events"]}) == len(second["swing_events"])


def test_incremental_run_processes_new_candles_plus_overlap_and_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base = run_multi_horizon_backtest(
            mode="bootstrap",
            output_dir=Path(tmpdir),
            symbol_inputs=_symbol_inputs(),
            horizons=["MEDIUM"],
            venue="bitvavo",
            quote="EUR",
            workers=1,
            pivot_span=1,
            write_files=True,
        )
        extended_inputs = _symbol_inputs(extra_daily=[("22", "18", "21"), ("20", "17", "18")])
        incremental = run_multi_horizon_backtest(
            mode="incremental",
            output_dir=Path(tmpdir),
            symbol_inputs=extended_inputs,
            horizons=["MEDIUM"],
            venue="bitvavo",
            quote="EUR",
            workers=1,
            pivot_span=1,
            write_files=True,
        )
        repeated = run_multi_horizon_backtest(
            mode="incremental",
            output_dir=Path(tmpdir),
            symbol_inputs=extended_inputs,
            horizons=["MEDIUM"],
            venue="bitvavo",
            quote="EUR",
            workers=1,
            pivot_span=1,
            write_files=True,
        )
        assert len(incremental["swing_events"]) >= len(base["swing_events"])
        assert len(repeated["swing_events"]) == len(incremental["swing_events"])
        assert len({row["event_id"] for row in repeated["swing_events"]}) == len(repeated["swing_events"])


def test_version_mismatch_requires_rebuild() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_multi_horizon_backtest(
            mode="bootstrap",
            output_dir=Path(tmpdir),
            symbol_inputs=_symbol_inputs(),
            horizons=["SHORT"],
            venue="bitvavo",
            quote="EUR",
            workers=1,
            write_files=True,
        )
        checkpoint_path = Path(tmpdir) / "checkpoints" / "WLD_SHORT_checkpoint_v1.json"
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        payload["algorithm_version"] = "mismatch"
        checkpoint_path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            run_multi_horizon_backtest(
                mode="incremental",
                output_dir=Path(tmpdir),
                symbol_inputs=_symbol_inputs(),
                horizons=["SHORT"],
                venue="bitvavo",
                quote="EUR",
                workers=1,
                pivot_span=1,
                write_files=False,
            )
        except RuntimeError as exc:
            assert "requires rebuild" in str(exc)
        else:
            raise AssertionError("expected version mismatch to fail closed")


def test_worker_count_does_not_change_output() -> None:
    with tempfile.TemporaryDirectory() as tmpdir_a, tempfile.TemporaryDirectory() as tmpdir_b:
        serial = run_multi_horizon_backtest(
            mode="bootstrap",
            output_dir=Path(tmpdir_a),
            symbol_inputs=_symbol_inputs(),
            horizons=["SHORT", "MEDIUM"],
            venue="bitvavo",
            quote="EUR",
            workers=1,
            pivot_span=1,
            write_files=False,
        )
        parallel = run_multi_horizon_backtest(
            mode="bootstrap",
            output_dir=Path(tmpdir_b),
            symbol_inputs=_symbol_inputs(),
            horizons=["SHORT", "MEDIUM"],
            venue="bitvavo",
            quote="EUR",
            workers=2,
            pivot_span=1,
            write_files=False,
        )
        assert serial["swing_events"] == parallel["swing_events"]
        assert serial["fib_level_outcomes"] == parallel["fib_level_outcomes"]


def test_missing_interval_source_emits_explicit_skip_reason() -> None:
    broken = _symbol_inputs()
    broken[0]["candles_by_interval"].pop("1w")
    result = run_multi_horizon_backtest(
        mode="bootstrap",
        output_dir=Path(tempfile.mkdtemp()),
        symbol_inputs=broken,
        horizons=["LONG"],
        venue="bitvavo",
        quote="EUR",
        workers=1,
        pivot_span=1,
        write_files=False,
    )
    assert result["coverage_summary"][0]["skip_reason"] == "MISSING_PRIMARY_INTERVAL_HISTORY"


def test_unknown_regime_breath_remains_unknown() -> None:
    result = run_multi_horizon_backtest(
        mode="bootstrap",
        output_dir=Path(tempfile.mkdtemp()),
        symbol_inputs=_symbol_inputs(),
        horizons=["SHORT"],
        venue="bitvavo",
        quote="EUR",
        workers=1,
        pivot_span=1,
        write_files=False,
    )
    first = result["swing_events"][0]
    assert first["market_regime"] == "UNKNOWN"
    assert first["breath_phase"] == "UNKNOWN"


def test_module_has_no_forbidden_imports_or_order_strings() -> None:
    source = Path("src/research/multi_horizon_fib_backtest_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {"decision_gate", "execution_planner", "executor"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for name in forbidden_imports:
                assert name not in module
    for forbidden in ("placeOrder", "cancelOrder", "create order", "broker_writes = 1"):
        assert forbidden not in source


def main() -> None:
    test_bootstrap_creates_deterministic_events_and_checkpoints()
    test_interrupted_bootstrap_resumes_without_duplicates()
    test_incremental_run_processes_new_candles_plus_overlap_and_is_idempotent()
    test_version_mismatch_requires_rebuild()
    test_worker_count_does_not_change_output()
    test_missing_interval_source_emits_explicit_skip_reason()
    test_unknown_regime_breath_remains_unknown()
    test_module_has_no_forbidden_imports_or_order_strings()
    print("ok")


if __name__ == "__main__":
    main()
