from __future__ import annotations

import os
import subprocess
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


def _write(path: Path, source: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _run_with_blocked_validator(
    tmp_path: Path,
    blocked_module: str,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    fake_repo = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    call_log = tmp_path / "calls.log"
    _write(fake_repo / "scripts/synth_maintenance_guard.sh", "")
    _write(
        fake_repo / "scripts/run_native_short_scope_status_chain_once.sh",
        '#!/usr/bin/env bash\necho "native_scope_runner" >> "$CHAIN_CALL_LOG"\n',
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
            "CHAIN_BLOCK_MODULE": blocked_module,
            "CHAIN_CALL_LOG": str(call_log),
            "CHAIN_FAKE_BIN": str(fake_bin),
            "SYNTH_CHAIN_4H_LOCKED": "1",
            "SYNTH_MAINTENANCE_LOCK": str(tmp_path / "no-maintenance-lock"),
            "SYNTH_REPO_DIR": str(fake_repo),
        }
    )
    result = subprocess.run(
        ["bash", str(CHAIN)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = call_log.read_text(encoding="utf-8").splitlines()
    return result, calls


@pytest.mark.parametrize(
    ("blocked_module", "expected_calls"),
    (
        (PRICE_VALIDATOR, ["src.market_data.native_short_repository_source_identity_v1", PRICE_VALIDATOR]),
        (
            CANDLE_VALIDATOR,
            [
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
