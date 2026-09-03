from __future__ import annotations

import ast
import importlib
import json
from argparse import Namespace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_NAME = "src.research.run_fib_exit_ladder_v1_pit_replay_phase_c_v1"
MODULE_PATH = Path("src/research/run_fib_exit_ladder_v1_pit_replay_phase_c_v1.py")


def test_phase_c_runner_preserves_frozen_universe_and_defaults() -> None:
    module = importlib.import_module(MODULE_NAME)
    assert tuple(module.DEFAULT_SYMBOLS) == ("LINK", "XLM", "SOL", "XRP", "HOT")
    assert [label for label, _ in module.WINDOWS] == [
        "SELECTION_WINDOW",
        "OOS_WINDOW_1",
        "OOS_WINDOW_2",
    ]
    assert module.METHODOLOGY_VERSION == "FIB_EXIT_LADDER_V1_PIT_REPLAY_CONTRACT_V1"


def test_phase_c_runner_rejects_unfrozen_symbol_scope() -> None:
    module = importlib.import_module(MODULE_NAME)
    with pytest.raises(ValueError, match="frozen universe mismatch"):
        module._parse_symbols("LINK,XLM,SOL,XRP,HOT,SUI")


def test_phase_c_runner_requires_exact_code_commit_sha() -> None:
    module = importlib.import_module(MODULE_NAME)
    expected = "a" * 40
    assert module._require_code_commit_sha(expected) == expected
    with pytest.raises(ValueError, match="exact 40-character hexadecimal"):
        module._require_code_commit_sha("abc")


def test_phase_c_result_row_contains_frozen_anchor_and_decision_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(MODULE_NAME)
    result = SimpleNamespace(fills=())
    monkeypatch.setattr(module, "_jsonable", lambda value: {"status": "OK"} if value is result else str(value))
    monkeypatch.setattr(module, "_outcome_components", lambda result, candles: {})
    monkeypatch.setattr(
        module.engine,
        "find_pit_anchor",
        lambda candles: SimpleNamespace(
            anchor_low=Decimal("1"),
            anchor_low_ts="anchor-low-ts",
            wave1_high=Decimal("2"),
            wave1_high_ts="wave1-high-ts",
            wave2_low=Decimal("1.5"),
            wave2_low_ts="wave2-low-ts",
            confirmation_idx=17,
            confirmation_ts="confirmation-ts",
            entry_ts="observable-ts",
        ),
    )

    row = module._result_row(result, [object()])
    assert row["anchor_low"] == "1"
    assert row["wave1_high"] == "2"
    assert row["wave2_low"] == "1.5"
    assert row["confirmation_idx"] == 17
    assert row["confirmation_ts"] == "confirmation-ts"
    assert row["observable_ts"] == "observable-ts"
    assert row["fills"] == []


def test_phase_c_outcome_components_emit_frozen_section_11_fields() -> None:
    module = importlib.import_module(MODULE_NAME)
    fill = SimpleNamespace(sell_fraction=Decimal("0.25"), limit_price=Decimal("120"))
    result = SimpleNamespace(
        fills=(fill,),
        status=module.engine.STATUS_OK,
        entry_price=Decimal("100"),
    )
    candle = SimpleNamespace(close_price=Decimal("110"))

    components = module._outcome_components(result, [candle])
    assert components == {
        "fill_count": 1,
        "filled_fraction": "0.25",
        "remaining_fraction": "0.75",
        "avg_exit_price": "120",
        "realized_return_pct_on_full_position": "5.00",
        "remaining_return_pct_on_full_position": "7.50",
    }


def test_phase_c_asset_without_selection_is_explicit_insufficient_data(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module(MODULE_NAME)
    replay = SimpleNamespace(selected_policy=None)
    monkeypatch.setattr(module, "_grid_rows", lambda replay, candles: [{"status": "NO_ANCHOR_SET_FOUND"}])

    row = module._asset_evidence_row(
        symbol="LINK",
        asset_id=1,
        row_counts={"SELECTION_WINDOW": 100},
        candles_by_window={"SELECTION_WINDOW": []},
        replay=replay,
    )
    assert row["status"] == module.engine.STATUS_INSUFFICIENT_DATA
    assert row["selected_policy"] is None
    assert row["oos_window_1"] is None
    assert row["oos_window_2"] is None


def _args(tmp_path: Path, *, resume: bool = False) -> Namespace:
    return Namespace(
        venue="bitvavo",
        interval="1d",
        symbols="LINK,XLM,SOL,XRP,HOT",
        env_file=None,
        out_json=str(tmp_path / "evidence.json"),
        checkpoint_json=str(tmp_path / "checkpoint.json"),
        resume=resume,
        code_commit_sha="b" * 40,
    )


def test_phase_c_build_evidence_checkpoints_each_completed_asset_and_logs_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = importlib.import_module(MODULE_NAME)

    class FakeConn:
        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    checkpoint_snapshots: list[list[str]] = []
    real_atomic_write = module._atomic_write_json

    def capture_checkpoint(path: Path, evidence: dict) -> str:
        checkpoint_snapshots.append([row["symbol"] for row in evidence["assets"]])
        return real_atomic_write(path, evidence)

    monkeypatch.setattr(module.scoreboard, "load_env", lambda env_file: None)
    monkeypatch.setattr(module.scoreboard, "connect_read_only", lambda: FakeConn())
    monkeypatch.setattr(module.ladder_bt, "detect_candle_columns", lambda conn: {"open": "open"})
    monkeypatch.setattr(module.ladder_bt, "fetch_asset_id", lambda conn, symbol: None)
    monkeypatch.setattr(module, "_atomic_write_json", capture_checkpoint)

    evidence = module.build_evidence(_args(tmp_path))
    assert evidence["code_commit_sha"] == "b" * 40
    assert [row["status"] for row in evidence["assets"]] == ["ASSET_NOT_FOUND"] * 5
    assert checkpoint_snapshots == [
        ["LINK"],
        ["LINK", "XLM"],
        ["LINK", "XLM", "SOL"],
        ["LINK", "XLM", "SOL", "XRP"],
        ["LINK", "XLM", "SOL", "XRP", "HOT"],
    ]
    lines = capsys.readouterr().out.splitlines()
    assert any("phase=FETCH_ASSET_ID" in line and "row_count=0" in line and "elapsed_ms=" in line for line in lines)
    assert sum(line.startswith("CHECKPOINT ") for line in lines) == 5


def test_phase_c_resume_validates_identity_and_skips_completed_prefix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = importlib.import_module(MODULE_NAME)
    args = _args(tmp_path, resume=True)
    expected = module._base_evidence(
        symbols=list(module.DEFAULT_SYMBOLS),
        venue="bitvavo",
        interval="1d",
        code_commit_sha="b" * 40,
    )
    expected["assets"] = [{"symbol": "LINK", "status": "ASSET_NOT_FOUND"}]
    module._atomic_write_json(Path(args.checkpoint_json), expected)

    class FakeConn:
        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    seen_symbols: list[str] = []
    monkeypatch.setattr(module.scoreboard, "load_env", lambda env_file: None)
    monkeypatch.setattr(module.scoreboard, "connect_read_only", lambda: FakeConn())
    monkeypatch.setattr(module.ladder_bt, "detect_candle_columns", lambda conn: {})
    monkeypatch.setattr(
        module.ladder_bt,
        "fetch_asset_id",
        lambda conn, symbol: seen_symbols.append(symbol) or None,
    )

    evidence = module.build_evidence(args)
    assert seen_symbols == ["XLM", "SOL", "XRP", "HOT"]
    assert [row["symbol"] for row in evidence["assets"]] == list(module.DEFAULT_SYMBOLS)


def test_phase_c_resume_rejects_mismatched_checkpoint(tmp_path: Path) -> None:
    module = importlib.import_module(MODULE_NAME)
    args = _args(tmp_path, resume=True)
    checkpoint = module._base_evidence(
        symbols=list(module.DEFAULT_SYMBOLS),
        venue="bitvavo",
        interval="1d",
        code_commit_sha="a" * 40,
    )
    Path(args.checkpoint_json).write_text(json.dumps(checkpoint), encoding="utf-8")
    with pytest.raises(ValueError, match="checkpoint identity mismatch for code_commit_sha"):
        module.build_evidence(args)


def test_phase_c_atomic_write_uses_replace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = importlib.import_module(MODULE_NAME)
    calls: list[tuple[Path, Path]] = []
    real_replace = module.os.replace

    def capture_replace(src: Path, dst: Path) -> None:
        calls.append((Path(src), Path(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", capture_replace)
    path = tmp_path / "checkpoint.json"
    module._atomic_write_json(path, {"assets": []})
    assert calls == [(tmp_path / "checkpoint.json.tmp", path)]
    assert path.exists()
    assert not (tmp_path / "checkpoint.json.tmp").exists()


def test_phase_c_main_emits_flushed_startup_metadata_and_single_success_terminal_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = importlib.import_module(MODULE_NAME)
    args = Namespace(out_json="evidence.json")
    monkeypatch.setattr(module, "parse_args", lambda: args)
    monkeypatch.setattr(module, "build_evidence", lambda args: {"assets": []})
    monkeypatch.setattr(module, "write_evidence", lambda path, evidence: "c" * 64)

    assert module.main() == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("STARTED ")
    assert f"runner={module.RUNNER_NAME}" in lines[0]
    assert f"mode={module.RUN_MODE}" in lines[0]
    assert f"scope={module.RUN_SCOPE}" in lines[0]
    assert f"worker={module.RUN_WORKER}" in lines[0]
    assert any("phase=WRITE_EVIDENCE" in line and "row_count=0" in line and "elapsed_ms=" in line for line in lines)
    assert sum(line.startswith("FINISHED ") for line in lines) == 1
    assert sum(line.startswith("FAILED ") for line in lines) == 0
    assert sum(line.startswith("INTERRUPTED ") for line in lines) == 0


def test_phase_c_emit_is_unbuffered(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module(MODULE_NAME)
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(module, "print", lambda message, flush=False: calls.append((message, flush)), raising=False)
    module._emit("hello")
    assert calls == [("hello", True)]


def test_phase_c_main_emits_single_failure_terminal_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = importlib.import_module(MODULE_NAME)
    monkeypatch.setattr(module, "parse_args", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    assert module.main() == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("STARTED ")
    assert sum(line.startswith("FAILED ") for line in lines) == 1
    assert sum(line.startswith("FINISHED ") for line in lines) == 0
    assert sum(line.startswith("INTERRUPTED ") for line in lines) == 0


def test_phase_c_main_help_has_one_terminal_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = importlib.import_module(MODULE_NAME)
    monkeypatch.setattr(module, "parse_args", lambda: (_ for _ in ()).throw(SystemExit(0)))

    assert module.main() == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("STARTED ")
    assert sum(line.startswith("FINISHED ") for line in lines) == 1
    assert "status=HELP" in lines[-1]
    assert sum(line.startswith("FAILED ") for line in lines) == 0


def test_phase_c_main_interruption_has_one_interrupted_terminal_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = importlib.import_module(MODULE_NAME)
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: (_ for _ in ()).throw(module.RunnerInterrupted("SIGTERM")),
    )

    assert module.main() == 130
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("STARTED ")
    assert sum(line.startswith("INTERRUPTED ") for line in lines) == 1
    assert "reason=SIGTERM" in lines[-1]
    assert "elapsed_ms=" in lines[-1]
    assert sum(line.startswith("FAILED ") for line in lines) == 0
    assert sum(line.startswith("FINISHED ") for line in lines) == 0


def test_phase_c_runner_installs_sigint_and_sigterm_handlers() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "signal.SIGINT" in source
    assert "signal.SIGTERM" in source
    assert "_install_signal_handlers()" in source
    assert "_restore_signal_handlers(previous_handlers)" in source


def test_phase_c_runner_has_no_production_layer_imports() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")

    forbidden = ("decision_gate", "execution_planner", "executor", "broker", "exit_policy")
    assert not [name for name in imported if any(token in name for token in forbidden)]


def test_phase_c_runner_keeps_promotion_fail_closed_in_source() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert '"methodology_promotion_grade": 0' in source
    assert '"promotion_eligible": False' in source
    assert '"code_commit_sha": code_commit_sha' in source
    assert "connect_read_only()" in source
    assert "conn.rollback()" in source
    assert "conn.close()" in source
    assert "os.replace(tmp_path, path)" in source
    assert '"--resume"' in source
    assert "row_count=" in source
    assert "elapsed_ms=" in source
