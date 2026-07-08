from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path


ORCHESTRATOR = Path("scripts/odroid/run_linked_profile_runtime_orchestrator_once.sh")
SAFE_RENDERER = Path("scripts/odroid/run_account_wallet_snapshot_dashboard_render_once.sh")


def _make_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_safe_snapshot_renderer_does_not_build_or_publish_native_short_context() -> None:
    text = SAFE_RENDERER.read_text(encoding="utf-8")

    assert "run_native_short_fib_context_v1" not in text
    assert "native_short_fib_context_rows_v1.csv" not in text
    assert "--native-short-context-rows" not in text
    assert "run_manual_short_trader_profit_plan_v1" not in text
    assert "native_short_context_build=disabled" in text
    assert "profit_plan_render=disabled" in text


def test_orchestrator_uses_new_safe_renderer_not_legacy_native_short_wrapper() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")

    assert "run_linked_profile_dashboard_refresh_once.sh" not in text
    assert "run_account_wallet_dashboard_render_once.sh" not in text
    assert "run_account_wallet_snapshot_dashboard_render_once.sh" in text
    assert "run_account_wallet_refresh_once.sh" in text
    assert "run_market_price_snapshot_v1" in text
    assert "run_linked_profile_dashboard_refresh_v1" in text
    assert "flock -n 9" in text
    assert "native_short_context_build_in_render_stage" in text


def test_orchestrator_smoke_records_metadata_and_runs_stages_in_order(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".venv" / "bin").mkdir(parents=True)
    (repo_dir / ".venv" / "bin" / "activate").write_text("# fake venv\n", encoding="utf-8")

    calls_path = tmp_path / "calls.txt"
    metadata_path = tmp_path / "latest_run.json"

    market_script = _make_executable(
        tmp_path / "market.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo market:$1:$2 >> {calls_path}\n",
    )
    account_script = _make_executable(
        tmp_path / "account.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo account:$1 >> {calls_path}\n",
    )
    render_script = _make_executable(
        tmp_path / "render.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo render:$1 >> {calls_path}\n",
    )

    env = os.environ.copy()
    env.update(
        {
            "SYNTH_REPO_DIR": str(repo_dir),
            "SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT": str(tmp_path / "web"),
            "SYNTH_LINKED_PROFILE_RUNTIME_LOCK": str(tmp_path / "orchestrator.lock"),
            "SYNTH_LINKED_PROFILE_RUNTIME_SKIP_DISK_HEALTH": "1",
            "SYNTH_LINKED_PROFILE_LIST": "joost,hugo",
            "SYNTH_MARKET_PRICE_REFRESH_SCRIPT": str(market_script),
            "SYNTH_ACCOUNT_WALLET_REFRESH_SCRIPT": str(account_script),
            "SYNTH_LINKED_PROFILE_RENDER_SCRIPT": str(render_script),
            "SYNTH_LINKED_PROFILE_RUNTIME_METADATA_PATH": str(metadata_path),
            "SYNTH_LINKED_PROFILE_RUNTIME_RUN_ID": "test-run-1",
        }
    )

    result = subprocess.run(
        ["bash", str(ORCHESTRATOR)],
        cwd=Path.cwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls_path.read_text(encoding="utf-8").splitlines() == [
        "market:bitvavo:EUR",
        "account:joost",
        "render:joost",
        "account:hugo",
        "render:hugo",
    ]

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "linked_profile_runtime_orchestrator_v1"
    assert payload["run_id"] == "test-run-1"
    assert payload["overall_result"] == "ok"
    assert payload["profiles"] == ["joost", "hugo"]
    assert payload["profile_count"] == 2
    assert payload["public_price_result"] == "ok"
    assert payload["account_refresh"] == {"success": 2, "failure": 0}
    assert payload["snapshot_render"] == {"success": 2, "failure": 0}
    assert payload["safety"]["native_short_context_build_in_render_stage"] is False
    assert payload["safety"]["renderer_private_broker_calls"] == 0
    assert [stage["phase"] for stage in payload["stages"]] == [
        "disk_log_health",
        "refresh_public_prices",
        "discover_linked_profiles",
        "refresh_account_snapshot",
        "render_snapshot_dashboard",
        "refresh_account_snapshot",
        "render_snapshot_dashboard",
    ]


def test_orchestrator_degrades_but_continues_when_one_profile_fails(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".venv" / "bin").mkdir(parents=True)
    (repo_dir / ".venv" / "bin" / "activate").write_text("# fake venv\n", encoding="utf-8")

    calls_path = tmp_path / "calls.txt"
    metadata_path = tmp_path / "latest_run.json"

    market_script = _make_executable(
        tmp_path / "market.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n",
    )
    account_script = _make_executable(
        tmp_path / "account.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo account:$1 >> {calls_path}\n"
        "if [[ \"$1\" == \"hugo\" ]]; then exit 7; fi\n",
    )
    render_script = _make_executable(
        tmp_path / "render.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo render:$1 >> {calls_path}\n",
    )

    env = os.environ.copy()
    env.update(
        {
            "SYNTH_REPO_DIR": str(repo_dir),
            "SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT": str(tmp_path / "web"),
            "SYNTH_LINKED_PROFILE_RUNTIME_LOCK": str(tmp_path / "orchestrator.lock"),
            "SYNTH_LINKED_PROFILE_RUNTIME_SKIP_DISK_HEALTH": "1",
            "SYNTH_LINKED_PROFILE_LIST": "joost,hugo",
            "SYNTH_MARKET_PRICE_REFRESH_SCRIPT": str(market_script),
            "SYNTH_ACCOUNT_WALLET_REFRESH_SCRIPT": str(account_script),
            "SYNTH_LINKED_PROFILE_RENDER_SCRIPT": str(render_script),
            "SYNTH_LINKED_PROFILE_RUNTIME_METADATA_PATH": str(metadata_path),
            "SYNTH_LINKED_PROFILE_RUNTIME_RUN_ID": "test-run-2",
        }
    )

    result = subprocess.run(
        ["bash", str(ORCHESTRATOR)],
        cwd=Path.cwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert calls_path.read_text(encoding="utf-8").splitlines() == [
        "account:joost",
        "render:joost",
        "account:hugo",
        "render:hugo",
    ]

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["overall_result"] == "degraded"
    assert payload["account_refresh"] == {"success": 1, "failure": 1}
    assert payload["snapshot_render"] == {"success": 2, "failure": 0}
    assert any(
        stage["phase"] == "refresh_account_snapshot"
        and stage["profile"] == "hugo"
        and stage["result"] == "failed_continuing"
        for stage in payload["stages"]
    )
