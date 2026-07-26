from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).parent.parent
CHAIN = ROOT / "scripts/run_chain_4h.sh"
SERVICE = ROOT / "deploy/systemd/synth-chain-4h.service"
TIMER = ROOT / "deploy/systemd/synth-chain-4h.timer"
PRICE_VALIDATOR = "src.operations.run_persisted_market_price_freshness_v1"
CANDLE_VALIDATOR = "src.operations.run_persisted_market_candle_freshness_v1"
NATIVE_SCOPE_RUNNER = "scripts/run_native_short_scope_status_chain_once.sh"
NATIVE_SNAPSHOT_RUNNER = "src.market_data.run_native_short_fib_context_snapshot_v1"
AUTH_GUARD = "src.operations.verify_writer_capability_authorization_v1"
DB_BINDING_PREFLIGHT = (
    "src.operations.run_synth_chain_4h_db_environment_preflight_v1"
)
DB_GRANT_PREFLIGHT = "src.operations.run_synth_chain_4h_db_grant_preflight_v1"


def _write(path: Path, source: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _run_with_blocked_validator(
    tmp_path: Path,
    blocked_module: str,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    fake_chain, fake_repo, env, call_log = _prepare_fake_chain(tmp_path)
    env["CHAIN_BLOCK_MODULE"] = blocked_module
    result = subprocess.run(
        ["bash", str(fake_chain)],
        cwd=fake_repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = call_log.read_text(encoding="utf-8").splitlines()
    return result, calls


def _prepare_fake_chain(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, str], Path]:
    fake_repo = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    call_log = tmp_path / "calls.log"
    fake_chain = fake_repo / "scripts/run_chain_4h.sh"
    chain_source = CHAIN.read_text(encoding="utf-8").replace(
        'CHAIN_4H_LOCK_FILE="/tmp/synth_chain_4h.lock"',
        f'CHAIN_4H_LOCK_FILE="{tmp_path / "chain-4h.lock"}"',
    )
    _write(fake_chain, chain_source, executable=True)
    _write(fake_repo / "scripts/synth_maintenance_guard.sh", "")
    _write(
        fake_repo / "scripts/run_native_short_scope_status_chain_once.sh",
        """#!/usr/bin/env bash
echo "native_scope_runner" >> "$CHAIN_CALL_LOG"
printf '%s\n' "$*" > "$CHAIN_NATIVE_ARGS_LOG"
""",
        executable=True,
    )
    _write(
        fake_repo / "venv/bin/activate",
        'export PATH="${CHAIN_FAKE_BIN}:$PATH"\n',
    )
    _write(
        fake_bin / "git",
        '#!/usr/bin/env bash\nprintf "%040d\\n" 0\n',
        executable=True,
    )
    _write(
        fake_bin / "python",
        """#!/usr/bin/env bash
set -u
if [[ "${1:-}" == "-c" ]]; then
    if [[ "${2:-}" == *"from datetime"* ]]; then
        echo "2026-07-19T08:00:00+00:00"
    fi
    exit 0
fi
if [[ "${1:-}" == "-m" ]]; then
    module="${2:-}"
    echo "${module}" >> "${CHAIN_CALL_LOG}"
    if [[ -n "${CHAIN_HOLD_MODULE:-}" && "${module}" == "${CHAIN_HOLD_MODULE}" ]]; then
        : > "${CHAIN_HOLD_READY}"
        while [[ ! -e "${CHAIN_HOLD_RELEASE}" ]]; do
            sleep 0.02
        done
    fi
    if [[ "${module}" == "${CHAIN_BLOCK_MODULE}" ]]; then
        echo "validation_result=BLOCKED freshness_classification=STALE snapshot_row_count=0 database_writes=0"
        exit 37
    fi
fi
exit 0
""",
        executable=True,
    )
    env = os.environ.copy()
    env.update(
        {
            "CHAIN_BLOCK_MODULE": "",
            "CHAIN_CALL_LOG": str(call_log),
            "CHAIN_FAKE_BIN": str(fake_bin),
            "CHAIN_HOLD_MODULE": "",
            "CHAIN_HOLD_READY": str(tmp_path / "hold.ready"),
            "CHAIN_HOLD_RELEASE": str(tmp_path / "hold.release"),
            "CHAIN_NATIVE_ARGS_LOG": str(tmp_path / "native-args.log"),
            "SYNTH_CHAIN_4H_LOCKED": "1",
            "SYNTH_CHAIN_4H_LOCK_FILE": str(
                tmp_path / "inherited-lock-redirect-must-not-be-used"
            ),
            "SYNTH_MAINTENANCE_LOCK": str(tmp_path / "no-maintenance-lock"),
            "SYNTH_REPO_DIR": str(tmp_path / "inherited-redirect-must-not-be-used"),
        }
    )
    return fake_chain, fake_repo, env, call_log


@pytest.mark.parametrize(
    ("blocked_module", "expected_calls"),
    (
        (
            PRICE_VALIDATOR,
            [
                DB_BINDING_PREFLIGHT,
                DB_GRANT_PREFLIGHT,
                AUTH_GUARD,
                "src.market_data.native_short_repository_source_identity_v1",
                PRICE_VALIDATOR,
            ],
        ),
        (
            CANDLE_VALIDATOR,
            [
                DB_BINDING_PREFLIGHT,
                DB_GRANT_PREFLIGHT,
                AUTH_GUARD,
                "src.market_data.native_short_repository_source_identity_v1",
                PRICE_VALIDATOR,
                CANDLE_VALIDATOR,
            ],
        ),
    ),
)
def test_freshness_block_stops_before_all_native_short_publication(
    tmp_path: Path,
    blocked_module: str,
    expected_calls: list[str],
) -> None:
    result, calls = _run_with_blocked_validator(tmp_path, blocked_module)
    assert result.returncode == 37
    assert calls == expected_calls
    assert NATIVE_SCOPE_RUNNER not in calls
    assert NATIVE_SNAPSHOT_RUNNER not in calls
    assert "freshness_classification=STALE" in result.stdout
    assert "snapshot_row_count=0" in result.stdout
    assert "database_writes=0" in result.stdout


def test_inherited_repository_and_lock_guard_cannot_redirect_or_bypass_chain(
    tmp_path: Path,
) -> None:
    result, calls = _run_with_blocked_validator(tmp_path, PRICE_VALIDATOR)

    assert result.returncode == 37
    assert calls == [
        DB_BINDING_PREFLIGHT,
        DB_GRANT_PREFLIGHT,
        AUTH_GUARD,
        "src.market_data.native_short_repository_source_identity_v1",
        PRICE_VALIDATOR,
    ]
    assert "inherited-redirect-must-not-be-used" not in result.stderr


def test_outer_lock_rejects_concurrent_invocation_and_keeps_nested_stages_working(
    tmp_path: Path,
) -> None:
    fake_chain, fake_repo, env, call_log = _prepare_fake_chain(tmp_path)
    ready = Path(env["CHAIN_HOLD_READY"])
    release = Path(env["CHAIN_HOLD_RELEASE"])
    env["CHAIN_HOLD_MODULE"] = (
        "src.market_data.native_short_repository_source_identity_v1"
    )
    first = subprocess.Popen(
        ["bash", str(fake_chain)],
        cwd=fake_repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    first_stdout = ""
    first_stderr = ""
    try:
        deadline = time.monotonic() + 5
        while (
            not ready.exists()
            and first.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert ready.exists(), (
            "first chain did not acquire the lock and reach its hold point"
        )

        second = subprocess.run(
            ["bash", str(fake_chain)],
            cwd=fake_repo,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert second.returncode == 75
        assert "reason=LOCK_HELD" in second.stdout
    finally:
        release.touch()
        try:
            first_stdout, first_stderr = first.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            first.kill()
            first_stdout, first_stderr = first.communicate(timeout=5)
    assert first.returncode == 0, first_stdout + first_stderr
    calls = call_log.read_text(encoding="utf-8").splitlines()
    assert calls.count("src.market_data.native_short_repository_source_identity_v1") == 1
    assert calls.count("native_scope_runner") == 1
    assert calls.count(NATIVE_SNAPSHOT_RUNNER) == 1
    native_args = Path(env["CHAIN_NATIVE_ARGS_LOG"]).read_text(encoding="utf-8")
    assert (
        "--allowed-untracked-path "
        "docs/todo/replay_parameter_study_harness_v1.md"
    ) in native_args


def test_exactly_one_canonical_native_short_owner_path() -> None:
    chain = CHAIN.read_text(encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")
    assert service.count("scripts/run_chain_4h.sh") == 1
    assert timer.count("Unit=synth-chain-4h.service") == 1
    assert chain.count(NATIVE_SCOPE_RUNNER) == 1
    assert chain.count(NATIVE_SNAPSHOT_RUNNER) == 1
    assert chain.index(NATIVE_SCOPE_RUNNER) < chain.index(NATIVE_SNAPSHOT_RUNNER)
    unit_paths = tuple(sorted((ROOT / "deploy/systemd").glob("synth-*.*"))) + tuple(
        sorted((ROOT / "docs/ops/systemd").glob("synth-*.*"))
    )
    other_units = "\n".join(
        path.read_text(encoding="utf-8") for path in unit_paths if path != SERVICE
    )
    assert NATIVE_SCOPE_RUNNER not in other_units
    assert NATIVE_SNAPSHOT_RUNNER not in other_units
    assert "scripts/run_chain_4h.sh" not in other_units
    for writer_unit in (
        "synth-market-price-snapshot-writer.service",
        "synth-market-candle-freshness-writer.service",
    ):
        assert writer_unit not in service
        assert writer_unit not in timer


def test_canonical_service_pins_non_login_environment_and_outer_lock() -> None:
    chain = CHAIN.read_text(encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")

    assert "ExecStart=/bin/bash -lc" not in service
    assert (
        "ExecStart=/bin/bash /home/gurk/projects/synth-v2/scripts/run_chain_4h.sh"
        in service
    )
    assert "WorkingDirectory=/home/gurk/projects/synth-v2" in service
    assert "User=gurk" in service
    assert "Group=gurk" in service
    assert "EnvironmentFile=" not in "\n".join(
        line for line in service.splitlines() if not line.lstrip().startswith("#")
    )
    assert "Environment=SYNTH_REPO_DIR=/home/gurk/projects/synth-v2" in service
    assert "Environment=SYNTH_CHAIN_4H_LOCKED=0" in service
    assert "Environment=SYNTH_CHAIN_4H_LOCK_FILE=/tmp/synth_chain_4h.lock" in service
    assert "Environment=SYNTH_DB_BINDING_PROFILE=synth_chain_4h" in service
    assert "Environment=SYNTH_CHAIN_4H_DB_HOST=gurkdb" in service
    assert "Environment=SYNTH_CHAIN_4H_DB_PORT=3306" in service
    assert "Environment=SYNTH_CHAIN_4H_DB_USER=synth_chain_4h_writer" in service
    assert "Environment=SYNTH_CHAIN_4H_DB_NAME=synth" in service
    assert (
        "Environment=SYNTH_CHAIN_4H_DB_PASSWORD_FILE="
        "/etc/synth/synth-chain-4h-db-password-v1"
    ) in service
    assert "SYNTH_CHAIN_4H_DB_PASSWORD=" not in service
    assert DB_BINDING_PREFLIGHT in service
    assert DB_BINDING_PREFLIGHT in chain
    assert DB_GRANT_PREFLIGHT in service
    assert DB_GRANT_PREFLIGHT in chain
    assert service.index(DB_BINDING_PREFLIGHT) < service.index(DB_GRANT_PREFLIGHT)
    assert chain.index(DB_BINDING_PREFLIGHT) < chain.index(DB_GRANT_PREFLIGHT)
    assert "unset SYNTH_REPO_DIR" in chain
    assert "unset SYNTH_CHAIN_4H_LOCKED" in chain
    assert "unset SYNTH_CHAIN_4H_LOCK_FILE" in chain
    assert 'CHAIN_4H_LOCK_FILE="/tmp/synth_chain_4h.lock"' in chain
    assert "${SYNTH_REPO_DIR" not in chain
    assert "${SYNTH_CHAIN_4H_LOCK_FILE" not in chain
    assert "flock -n 8" in chain
    assert "reason=LOCK_HELD" in chain
    assert 'if [ "${SYNTH_CHAIN_4H_LOCKED:-0}" != "1" ]' not in chain
    assert chain.count("--allowed-untracked-path") == 3
    assert "docs/todo/replay_parameter_study_harness_v1.md" in chain
    assert AUTH_GUARD in chain
    assert "ConditionHost=devlap" in timer
    assert "OnCalendar=*-*-* 00,04,08,12,16,20:12:00 UTC" in timer
    assert "RandomizedDelaySec=120" in timer
    assert "AccuracySec=1s" in timer


def test_legacy_4h_unit_templates_are_inert_retirement_stubs() -> None:
    legacy_service = (
        ROOT / "docs/ops/systemd/synth-4h-market-chain.service"
    ).read_text(encoding="utf-8")
    legacy_timer = (
        ROOT / "docs/ops/systemd/synth-4h-market-chain.timer"
    ).read_text(encoding="utf-8")
    assert "RETIRED" in legacy_service
    assert "RefuseManualStart=yes" in legacy_service
    assert "ExecStart=/usr/bin/false" in legacy_service
    assert "scripts/run_chain_4h.sh" not in legacy_service
    assert "[Install]" not in legacy_service
    assert "RETIRED" in legacy_timer
    assert "RefuseManualStart=yes" in legacy_timer
    assert "OnCalendar=" not in legacy_timer
    assert "[Install]" not in legacy_timer


def test_canonical_reporting_and_linked_profile_consumers_do_not_rebuild_native_short() -> None:
    paths = (
        ROOT / "docs/ops/systemd/synth-paper-advice-dashboard-render.service",
        ROOT / "scripts/odroid/run_paper_advice_dashboard_refresh_once.sh",
        ROOT / "docs/ops/systemd/synth-linked-profile-runtime-refresh.service",
        ROOT / "scripts/odroid/run_linked_profile_runtime_orchestrator_once.sh",
        ROOT / "scripts/odroid/run_account_wallet_snapshot_dashboard_render_once.sh",
        ROOT / "scripts/odroid/run_account_profit_plan_snapshot_render_once.sh",
    )
    executable = "\n".join(
        line
        for path in paths
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    for forbidden in (
        "run_native_short_scope_status_chain",
        "run_native_short_fib_context_v1",
        "run_native_short_fib_context_snapshot_v1",
        "--write-files",
        "--publish",
    ):
        assert forbidden not in executable


def test_validators_are_select_only_and_emit_zero_write_evidence() -> None:
    for runner_path in (
        ROOT / "src/operations/run_persisted_market_price_freshness_v1.py",
        ROOT / "src/operations/run_persisted_market_candle_freshness_v1.py",
    ):
        source = runner_path.read_text(encoding="utf-8")
        assert 'cur.execute("START TRANSACTION READ ONLY")' in source
        assert "conn.rollback()" in source
        assert "database_writes=0" in source
        for writer in (
            "run_market_price_snapshot_v1",
            "run_candles_etl",
            "refresh_public_prices",
        ):
            assert writer not in source
    price_source = (
        ROOT / "src/operations/run_persisted_market_price_freshness_v1.py"
    ).read_text(encoding="utf-8")
    for evidence in (
        "public_price_validation_result",
        "freshness_classification",
        "snapshot_row_count",
        "database_writes=0",
    ):
        assert evidence in price_source
    candle_source = (
        ROOT / "src/operations/run_persisted_market_candle_freshness_v1.py"
    ).read_text(encoding="utf-8")
    for evidence in (
        "validation_result",
        "freshness_classification",
        "expected_close_row_count",
        "database_writes=0",
    ):
        assert evidence in candle_source
