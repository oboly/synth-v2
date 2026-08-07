from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path


ORCHESTRATOR = Path("scripts/odroid/run_linked_profile_runtime_orchestrator_once.sh")
SAFE_RENDERER = Path("scripts/odroid/run_account_wallet_snapshot_dashboard_render_once.sh")
PROFIT_PLAN_RENDERER = Path("scripts/odroid/run_account_profit_plan_snapshot_render_once.sh")


def _make_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _install_validator_shim(
    tmp_path: Path,
    calls_path: Path,
    *,
    result_line: str = "PASS\tFRESH\tWITHIN_THRESHOLD\t2026-07-18T10:00:00+00:00\t60.000000\t42",
    exit_status: int = 0,
) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    return _make_executable(
        fake_bin / "python",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"${1:-}\" == \"-m\" && \"${2:-}\" == \"src.operations.run_persisted_market_price_freshness_v1\" ]]; then\n"
        f"  echo validate >> {calls_path}\n"
        f"  printf '%s\\n' '{result_line}'\n"
        f"  exit {exit_status}\n"
        "fi\n"
        f"exec {sys.executable} \"$@\"\n",
    )


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
    assert "run_persisted_market_price_freshness_v1" in text
    assert "run_market_price_snapshot_v1" not in text
    assert "SYNTH_MARKET_PRICE_REFRESH_SCRIPT" not in text
    assert "run_linked_profile_dashboard_refresh_v1" in text
    assert "flock -n 9" in text
    assert "native_short_context_build_in_render_stage" in text
    assert text.count('phase_start "profit_plan_render"') == 1
    assert "run_account_profit_plan_snapshot_render_once.sh" in text


def test_profit_plan_owner_has_no_legacy_builder_or_independent_scheduler() -> None:
    owner_text = PROFIT_PLAN_RENDERER.read_text(encoding="utf-8")
    assert "run_native_short_fib_context_v1" not in owner_text
    assert "run_manual_short_trader_profit_plan_v1" not in owner_text
    assert "run_account_profit_plan_snapshot_render_owner_v1" in owner_text
    assert not list(Path("docs/ops/systemd").glob("*profit-plan*snapshot*"))


def test_orchestrator_smoke_records_metadata_and_runs_stages_in_order(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".venv" / "bin").mkdir(parents=True)
    (repo_dir / ".venv" / "bin" / "activate").write_text("# fake venv\n", encoding="utf-8")

    calls_path = tmp_path / "calls.txt"
    metadata_path = tmp_path / "latest_run.json"

    validator = _install_validator_shim(tmp_path, calls_path)
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
    profit_script = _make_executable(
        tmp_path / "profit.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo profit:$1 >> {calls_path}\n",
    )
    enrollment_script = _make_executable(
        tmp_path / "enrollment.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo enrollment:ALL >> {calls_path}\n",
    )

    env = os.environ.copy()
    env.update(
        {
            "SYNTH_REPO_DIR": str(repo_dir),
            "SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT": str(tmp_path / "web"),
            "SYNTH_LINKED_PROFILE_RUNTIME_LOCK": str(tmp_path / "orchestrator.lock"),
            "SYNTH_LINKED_PROFILE_RUNTIME_SKIP_DISK_HEALTH": "1",
            "SYNTH_LINKED_PROFILE_LIST": "joost,hugo",
            "SYNTH_ACCOUNT_WALLET_REFRESH_SCRIPT": str(account_script),
            "SYNTH_LINKED_PROFILE_RENDER_SCRIPT": str(render_script),
            "SYNTH_ACCOUNT_PROFIT_PLAN_RENDER_SCRIPT": str(profit_script),
            "SYNTH_HELD_MARKET_ENROLLMENT_SCRIPT": str(enrollment_script),
            "SYNTH_LINKED_PROFILE_RUNTIME_METADATA_PATH": str(metadata_path),
            "SYNTH_LINKED_PROFILE_RUNTIME_RUN_ID": "test-run-1",
            "PATH": f"{validator.parent}:{env['PATH']}",
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
        "validate",
        "account:joost",
        "render:joost",
        "account:hugo",
        "render:hugo",
        "enrollment:ALL",
        "profit:joost",
        "profit:hugo",
    ]

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "linked_profile_runtime_orchestrator_v3"
    assert payload["run_id"] == "test-run-1"
    assert payload["overall_result"] == "ok"
    assert payload["profiles"] == ["joost", "hugo"]
    assert payload["profile_count"] == 2
    assert payload["public_price_validation_result"] == "PASS"
    assert payload["persisted_public_price_as_of_utc"] == "2026-07-18T10:00:00+00:00"
    assert payload["persisted_public_price_age_seconds"] == 60.0
    assert payload["freshness_classification"] == "FRESH"
    assert payload["account_refresh"] == {"success": 2, "failure": 0}
    assert payload["snapshot_render"] == {"success": 2, "failure": 0}
    assert payload["profit_plan_render"] == {"success": 2, "failure": 0}
    assert payload["held_market_enrollment"] == {"result": "ok"}
    assert payload["safety"]["native_short_context_build_in_render_stage"] is False
    assert payload["safety"]["renderer_private_broker_calls"] == 0
    assert [stage["phase"] for stage in payload["stages"]] == [
        "disk_log_health",
        "validate_persisted_public_prices",
        "discover_linked_profiles",
        "refresh_account_snapshot",
        "render_snapshot_dashboard",
        "refresh_account_snapshot",
        "render_snapshot_dashboard",
        "held_market_enrollment",
        "profit_plan_render",
        "profit_plan_render",
    ]


def test_orchestrator_skips_enrollment_when_an_account_refresh_fails(tmp_path: Path) -> None:
    """Enrollment must never run off partial/stale balance data -- if any
    profile's account refresh failed this cycle, enrollment is skipped
    (not silently run anyway), and the run is marked degraded."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".venv" / "bin").mkdir(parents=True)
    (repo_dir / ".venv" / "bin" / "activate").write_text("# fake venv\n", encoding="utf-8")

    calls_path = tmp_path / "calls.txt"
    metadata_path = tmp_path / "latest_run.json"

    validator = _install_validator_shim(tmp_path, calls_path)
    account_script = _make_executable(
        tmp_path / "account.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo account:$1 >> {calls_path}\n"
        "if [[ \"$1\" == \"hugo\" ]]; then exit 1; fi\n",
    )
    render_script = _make_executable(
        tmp_path / "render.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo render:$1 >> {calls_path}\n",
    )
    profit_script = _make_executable(
        tmp_path / "profit.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo profit:$1 >> {calls_path}\n",
    )
    enrollment_script = _make_executable(
        tmp_path / "enrollment.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo enrollment:ALL >> {calls_path}\n",
    )

    env = os.environ.copy()
    env.update(
        {
            "SYNTH_REPO_DIR": str(repo_dir),
            "SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT": str(tmp_path / "web"),
            "SYNTH_LINKED_PROFILE_RUNTIME_LOCK": str(tmp_path / "orchestrator.lock"),
            "SYNTH_LINKED_PROFILE_RUNTIME_SKIP_DISK_HEALTH": "1",
            "SYNTH_LINKED_PROFILE_LIST": "joost,hugo",
            "SYNTH_ACCOUNT_WALLET_REFRESH_SCRIPT": str(account_script),
            "SYNTH_LINKED_PROFILE_RENDER_SCRIPT": str(render_script),
            "SYNTH_ACCOUNT_PROFIT_PLAN_RENDER_SCRIPT": str(profit_script),
            "SYNTH_HELD_MARKET_ENROLLMENT_SCRIPT": str(enrollment_script),
            "SYNTH_LINKED_PROFILE_RUNTIME_METADATA_PATH": str(metadata_path),
            "SYNTH_LINKED_PROFILE_RUNTIME_RUN_ID": "test-run-2",
            "PATH": f"{validator.parent}:{env['PATH']}",
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

    assert result.returncode != 0, result.stdout + result.stderr
    assert "enrollment:ALL" not in calls_path.read_text(encoding="utf-8")

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["overall_result"] == "degraded"
    assert payload["held_market_enrollment"] == {"result": "skipped_account_refresh"}


def test_orchestrator_degrades_but_continues_when_one_profile_fails(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".venv" / "bin").mkdir(parents=True)
    (repo_dir / ".venv" / "bin" / "activate").write_text("# fake venv\n", encoding="utf-8")

    calls_path = tmp_path / "calls.txt"
    metadata_path = tmp_path / "latest_run.json"

    validator = _install_validator_shim(tmp_path, calls_path)
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
    profit_script = _make_executable(
        tmp_path / "profit.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo profit:$1 >> {calls_path}\n",
    )

    env = os.environ.copy()
    env.update(
        {
            "SYNTH_REPO_DIR": str(repo_dir),
            "SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT": str(tmp_path / "web"),
            "SYNTH_LINKED_PROFILE_RUNTIME_LOCK": str(tmp_path / "orchestrator.lock"),
            "SYNTH_LINKED_PROFILE_RUNTIME_SKIP_DISK_HEALTH": "1",
            "SYNTH_LINKED_PROFILE_LIST": "joost,hugo",
            "SYNTH_ACCOUNT_WALLET_REFRESH_SCRIPT": str(account_script),
            "SYNTH_LINKED_PROFILE_RENDER_SCRIPT": str(render_script),
            "SYNTH_ACCOUNT_PROFIT_PLAN_RENDER_SCRIPT": str(profit_script),
            "SYNTH_LINKED_PROFILE_RUNTIME_METADATA_PATH": str(metadata_path),
            "SYNTH_LINKED_PROFILE_RUNTIME_RUN_ID": "test-run-2",
            "PATH": f"{validator.parent}:{env['PATH']}",
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
        "validate",
        "account:joost",
        "render:joost",
        "account:hugo",
        "render:hugo",
    ]

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["overall_result"] == "degraded"
    assert payload["account_refresh"] == {"success": 1, "failure": 1}
    assert payload["snapshot_render"] == {"success": 2, "failure": 0}
    assert payload["profit_plan_render"] == {"success": 0, "failure": 2}
    assert not any(line.startswith("profit:") for line in calls_path.read_text(encoding="utf-8").splitlines())
    assert any(
        stage["phase"] == "refresh_account_snapshot"
        and stage["profile"] == "hugo"
        and stage["result"] == "failed_continuing"
        for stage in payload["stages"]
    )


def test_orchestrator_blocks_before_account_or_render_when_prices_are_stale(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".venv" / "bin").mkdir(parents=True)
    (repo_dir / ".venv" / "bin" / "activate").write_text("# fake venv\n", encoding="utf-8")
    calls_path = tmp_path / "calls.txt"
    metadata_path = tmp_path / "latest_run.json"
    validator = _install_validator_shim(
        tmp_path,
        calls_path,
        result_line="BLOCKED\tSTALE\tEXCEEDS_THRESHOLD\t2026-07-18T09:00:00+00:00\t3660.000000\t42",
        exit_status=1,
    )
    forbidden_stage = _make_executable(
        tmp_path / "forbidden.sh",
        "#!/usr/bin/env bash\necho forbidden >> " + str(calls_path) + "\nexit 0\n",
    )
    env = os.environ.copy()
    env.update(
        {
            "SYNTH_REPO_DIR": str(repo_dir),
            "SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT": str(tmp_path / "web"),
            "SYNTH_LINKED_PROFILE_RUNTIME_LOCK": str(tmp_path / "orchestrator.lock"),
            "SYNTH_LINKED_PROFILE_RUNTIME_SKIP_DISK_HEALTH": "1",
            "SYNTH_LINKED_PROFILE_LIST": "joost",
            "SYNTH_ACCOUNT_WALLET_REFRESH_SCRIPT": str(forbidden_stage),
            "SYNTH_LINKED_PROFILE_RENDER_SCRIPT": str(forbidden_stage),
            "SYNTH_ACCOUNT_PROFIT_PLAN_RENDER_SCRIPT": str(forbidden_stage),
            "SYNTH_LINKED_PROFILE_RUNTIME_METADATA_PATH": str(metadata_path),
            "SYNTH_LINKED_PROFILE_RUNTIME_RUN_ID": "test-run-stale",
            "PATH": f"{validator.parent}:{env['PATH']}",
        }
    )
    result = subprocess.run(
        ["bash", str(ORCHESTRATOR)],
        cwd=Path.cwd(), env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert calls_path.read_text(encoding="utf-8").splitlines() == ["validate"]
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["overall_result"] == "blocked_public_price_validation"
    assert payload["public_price_validation_result"] == "BLOCKED"
    assert payload["freshness_classification"] == "STALE"
    assert payload["account_refresh"] == {"success": 0, "failure": 0}
    assert payload["snapshot_render"] == {"success": 0, "failure": 0}
    assert payload["profit_plan_render"] == {"success": 0, "failure": 0}
