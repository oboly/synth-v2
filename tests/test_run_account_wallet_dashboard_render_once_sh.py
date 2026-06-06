from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


SCRIPT_PATH = Path("scripts/odroid/run_account_wallet_dashboard_render_once.sh")


def _write_file(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)


def _prepare_fake_repo(root: Path) -> None:
    _write_file(root / "venv/bin/activate", "", mode=0o644)
    for name in ("favicon.svg", "favicon-16x16.png", "favicon-32x32.png", "apple-touch-icon.png", "favicon.ico"):
        _write_file(root / f"assets/brand/synth/{name}", "x")


def _prepare_fake_python(fake_bin: Path) -> Path:
    script = fake_bin / "python"
    _write_file(
        script,
        """#!/usr/bin/env python3
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

log_path = Path(os.environ["FAKE_LOG_PATH"])
with log_path.open("a", encoding="utf-8") as handle:
    handle.write(" ".join(sys.argv[1:]) + "\\n")

args = sys.argv[1:]
if len(args) >= 2 and args[0] == "-m":
    module = args[1]
    argv = args[2:]
    def arg_value(flag, default=""):
        if flag in argv:
            idx = argv.index(flag)
            if idx + 1 < len(argv):
                return argv[idx + 1]
        return default
    if module == "src.market_data.run_market_price_snapshot_v1":
        raise SystemExit(0)
    if module == "src.market_data.run_native_short_fib_context_v1":
        out_dir = Path(arg_value("--output-dir"))
        mode = os.environ.get("FAKE_NATIVE_MODE", "success")
        out_dir.mkdir(parents=True, exist_ok=True)
        if mode == "success":
            rows_csv = out_dir / "native_short_fib_context_rows_v1.csv"
            with rows_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "symbol","context_status","primary_4h_lifecycle_state",
                    "supporting_1h_state","active_target_levels_json"
                ])
                writer.writeheader()
                writer.writerow({
                    "symbol": "WLD",
                    "context_status": "NATIVE_SHORT_CONTEXT_AVAILABLE",
                    "primary_4h_lifecycle_state": "MAP_COMPLETED",
                    "supporting_1h_state": "ALIGNED_WITH_4H",
                    "active_target_levels_json": "[]",
                })
                writer.writerow({
                    "symbol": "PLUME",
                    "context_status": "NATIVE_SHORT_CONTEXT_AVAILABLE",
                    "primary_4h_lifecycle_state": "BELOW_BREAKOUT_GATE",
                    "supporting_1h_state": "NEUTRAL_OR_NOT_CONFIRMING",
                    "active_target_levels_json": "[\\"0.1\\"]",
                })
            (out_dir / "coverage_summary_v1.csv").write_text("context_status,row_count\\nNATIVE_SHORT_CONTEXT_AVAILABLE,2\\n", encoding="utf-8")
            (out_dir / "manifest_v1.json").write_text(json.dumps({"row_count": 2}), encoding="utf-8")
        elif mode == "malformed":
            (out_dir / "native_short_fib_context_rows_v1.csv").write_text("symbol\\nWLD\\n", encoding="utf-8")
        else:
            raise SystemExit(1)
        raise SystemExit(0)
    if module == "src.reporting.run_account_wallet_dashboard_v1":
        out_root = Path(arg_value("--output-root"))
        profile = arg_value("--account-profile")
        profile_dir = out_root / "accounts" / profile
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "wallet.html").write_text("wallet", encoding="utf-8")
        raise SystemExit(0)
    if module == "src.reporting.run_manual_short_trader_dashboard_v1":
        out_root = Path(arg_value("--output-root"))
        profile = arg_value("--account-profile")
        profile_dir = out_root / "accounts" / profile
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "open-orders-monitor.html").write_text("monitor", encoding="utf-8")
        raise SystemExit(0)
    if module == "src.reporting.run_manual_short_trader_profit_plan_v1":
        out_root = Path(arg_value("--output-root"))
        profile = arg_value("--account-profile")
        profile_dir = out_root / "accounts" / profile
        profile_dir.mkdir(parents=True, exist_ok=True)
        native_path = Path(arg_value("--native-short-context-rows"))
        if not native_path.exists():
            raise SystemExit(2)
        (profile_dir / "profit-plan.html").write_text("profit", encoding="utf-8")
        raise SystemExit(0)
real_python = os.environ["REAL_PYTHON"]
proc = subprocess.run([real_python, *args], stdin=sys.stdin)
raise SystemExit(proc.returncode)
""",
        mode=0o755,
    )
    return script


def test_wrapper_passes_native_short_rows_and_orders_runners_correctly() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fake_repo = root / "repo"
        fake_bin = root / "bin"
        output_root = root / "out"
        log_path = root / "calls.log"
        _prepare_fake_repo(fake_repo)
        _prepare_fake_python(fake_bin)
        env = os.environ.copy()
        env["SYNTH_REPO_DIR"] = str(fake_repo)
        env["SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT"] = str(output_root)
        env["FAKE_LOG_PATH"] = str(log_path)
        env["FAKE_NATIVE_MODE"] = "success"
        env["REAL_PYTHON"] = os.environ.get("PYTHON", "python3")
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
        subprocess.run(["bash", str(SCRIPT_PATH), "joost"], check=True, env=env, cwd=Path.cwd())
        calls = log_path.read_text(encoding="utf-8").splitlines()
        native_idx = next(i for i, line in enumerate(calls) if "src.market_data.run_native_short_fib_context_v1" in line)
        profit_idx = next(i for i, line in enumerate(calls) if "src.reporting.run_manual_short_trader_profit_plan_v1" in line)
        assert native_idx < profit_idx
        assert "--native-short-context-rows" in calls[profit_idx]
        assert str(output_root / "accounts/joost/_runtime/native_short_context_v1/native_short_fib_context_rows_v1.csv") in calls[profit_idx]
        assert (output_root / "accounts/joost/_runtime/native_short_context_v1/native_short_fib_context_rows_v1.csv").exists()


def test_wrapper_failed_native_refresh_preserves_previous_valid_output_and_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fake_repo = root / "repo"
        fake_bin = root / "bin"
        output_root = root / "out"
        log_path = root / "calls.log"
        _prepare_fake_repo(fake_repo)
        _prepare_fake_python(fake_bin)
        previous_dir = output_root / "accounts/joost/_runtime/native_short_context_v1"
        previous_dir.mkdir(parents=True, exist_ok=True)
        previous_rows = previous_dir / "native_short_fib_context_rows_v1.csv"
        previous_rows.write_text("previous-valid", encoding="utf-8")
        env = os.environ.copy()
        env["SYNTH_REPO_DIR"] = str(fake_repo)
        env["SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT"] = str(output_root)
        env["FAKE_LOG_PATH"] = str(log_path)
        env["FAKE_NATIVE_MODE"] = "malformed"
        env["REAL_PYTHON"] = os.environ.get("PYTHON", "python3")
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
        proc = subprocess.run(["bash", str(SCRIPT_PATH), "joost"], env=env, cwd=Path.cwd(), capture_output=True, text=True)
        assert proc.returncode != 0
        assert previous_rows.read_text(encoding="utf-8") == "previous-valid"
        calls = log_path.read_text(encoding="utf-8").splitlines()
        assert not any("src.reporting.run_manual_short_trader_profit_plan_v1" in line for line in calls)


def test_wrapper_script_contains_native_phase_and_atomic_runtime_path() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'phase_start "build_native_short_context"' in source
    assert "--native-short-context-rows" in source
    assert "/_runtime/native_short_context_v1" in source
    assert "native_short_context_validation=ok" in source


def main() -> None:
    for test in (
        test_wrapper_passes_native_short_rows_and_orders_runners_correctly,
        test_wrapper_failed_native_refresh_preserves_previous_valid_output_and_fails_closed,
        test_wrapper_script_contains_native_phase_and_atomic_runtime_path,
    ):
        test()
    print("ok")


if __name__ == "__main__":
    main()
