from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.execution import worker


def _plan(*, execution_mode: str = "PAPER", plan_state: str = "IDLE") -> worker.PlanRuntime:
    return worker.PlanRuntime(
        execution_plan_id=71,
        trading_account_id=19,
        asset_id=3,
        symbol="BTC",
        sleeve_code="CORE",
        venue="bitvavo",
        market="BTC-EUR",
        side="SELL",
        desired_action="SPREAD_CAPTURE_PASSIVE",
        execution_intent="PLACE_PASSIVE_LIMIT",
        action_type="PLACE_ORDER",
        requested_side="SELL",
        execution_mode=execution_mode,
        target_fraction=Decimal("0.1"),
        reference_price_eur=Decimal("100"),
        passive_price_eur=Decimal("99"),
        urgent_limit_price_eur=Decimal("101"),
        max_reprices=2,
        max_wait_seconds=60,
        max_chase_bps=Decimal("10"),
        min_spread_bps_for_capture=Decimal("1"),
        escalation_to_urgent_limit=False,
        abort_if_signal_invalidates=True,
        plan_state=plan_state,
        notes="test",
        plan_ts_utc=datetime(2026, 7, 21, 12, 0, 0),
        valid_until_ts_utc=None,
    )


@pytest.mark.parametrize(
    ("passive_price", "urgent_price"),
    [
        (None, None),
        (None, "101.0"),
        ("not-a-decimal", None),
        ("99.0", "101.0"),
    ],
    ids=["both-null", "one-null", "malformed", "complete"],
)
def test_live_real_row_fails_before_price_hydration_or_followup(
    monkeypatch: pytest.MonkeyPatch,
    passive_price: object,
    urgent_price: object,
) -> None:
    database_row = {
        "execution_plan_id": 71,
        "execution_mode": "LIVE",
        "passive_price_eur": passive_price,
        "urgent_limit_price_eur": urgent_price,
    }
    query_calls: list[str] = []

    class Cursor:
        def execute(self, sql: str, _params: object = None) -> None:
            query_calls.append(sql)

        def fetchall(self) -> list[dict[str, object]]:
            return [
                {
                    "execution_plan_id": database_row["execution_plan_id"],
                    "execution_mode": database_row["execution_mode"],
                }
            ]

    @contextmanager
    def row_shaped_db_cursor(*_args: object, **_kwargs: object):
        yield object(), Cursor()

    monkeypatch.setattr(worker, "db_cursor", row_shaped_db_cursor)

    boundary_calls: list[str] = []
    def forbidden(*_args: object, **_kwargs: object) -> object:
        boundary_calls.append("forbidden")
        raise AssertionError("LIVE fail-closed boundary was crossed")

    monkeypatch.setattr(worker, "_fetch_latest_events_for_plans", forbidden)
    monkeypatch.setattr(worker, "_write_event", forbidden)
    monkeypatch.setenv("BITVAVO_API_KEY", "must-not-authorize")
    monkeypatch.setenv("BITVAVO_API_SECRET", "must-not-authorize")
    monkeypatch.setenv("SYNTH_LIVE_EXECUTION_PERMISSION", "granted")
    monkeypatch.setenv("SYNTH_BROKER_WRITE_PERMISSION", "granted")

    with pytest.raises(worker.LiveExecutionPrerequisitesUnavailable) as exc_info:
        worker.process_execution_plans(
            execution_mode="live",
            market_data_client_factory=forbidden,
        )

    assert exc_info.value.code == "LIVE_EXECUTION_PREREQUISITES_UNAVAILABLE"
    assert str(exc_info.value) == (
        "LIVE_EXECUTION_PREREQUISITES_UNAVAILABLE:"
        "CANONICAL_DECISION_GATE_PERMISSION_PRODUCER_REQUIRED,"
        "ACCOUNT_BOUND_TRADE_CREDENTIAL_BINDING_REQUIRED,"
        "LIVE_EXECUTOR_ACTIVATION_REQUIRED"
    )
    assert len(query_calls) == 1
    assert "SELECT execution_plan_id, execution_mode" in query_calls[0]
    assert boundary_calls == []


def test_global_live_mode_cannot_convert_persisted_paper(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan()
    calls: list[int] = []
    monkeypatch.setattr(
        worker,
        "_fetch_actionable_plan_headers",
        lambda: [{"execution_plan_id": plan.execution_plan_id, "execution_mode": "PAPER"}],
    )
    monkeypatch.setattr(worker, "_fetch_actionable_plans", lambda _ids: [plan])
    monkeypatch.setattr(worker, "_fetch_latest_events_for_plans", lambda _ids: {})
    monkeypatch.setattr(worker, "_place_initial_order_paper", lambda value: calls.append(value.execution_plan_id))

    result = worker.process_execution_plans(
        execution_mode="live",
        market_data_client_factory=lambda: (_ for _ in ()).throw(
            AssertionError("PAPER IDLE path must not construct a client")
        ),
    )

    assert calls == [71]
    assert result["paper_placed"] == 1
    assert result["live_placed"] == 0


@pytest.mark.parametrize("mode", ["paper", "Paper", "live", "Live", "", "UNKNOWN"])
def test_noncanonical_persisted_mode_is_rejected_before_processing(mode: str) -> None:
    with pytest.raises(ValueError, match="^PLAN_EXECUTION_MODE_NOT_CANONICAL$"):
        worker._classify_actionable_plan_modes(
            [{"execution_plan_id": 71, "execution_mode": mode}]
        )


def test_only_exact_persisted_modes_are_classified() -> None:
    assert worker._classify_actionable_plan_modes(
        [{"execution_plan_id": 71, "execution_mode": "PAPER"}]
    ) == [71]
    with pytest.raises(worker.LiveExecutionPrerequisitesUnavailable):
        worker._classify_actionable_plan_modes(
            [{"execution_plan_id": 72, "execution_mode": "LIVE"}]
        )


def test_paper_import_loads_only_database_environment(tmp_path: Path) -> None:
    sentinel_keys = (
        "BITVAVO_API_KEY",
        "BITVAVO_API_SECRET",
        "SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY",
        "SYNTH_LIVE_EXECUTION_PERMISSION",
        "SYNTH_BROKER_WRITE_PERMISSION",
    )
    (tmp_path / ".env").write_text(
        "DB_HOST=paper-db\n" + "".join(f"{key}=sentinel-{key}\n" for key in sentinel_keys),
        encoding="utf-8",
    )
    code = """
import json, os, sys
from src.execution import worker
from src.execution import run_paper_execution_runner_v1
from src.orchestration import run_live_paper_cycle_v1, run_live_paper_loop_v1, run_paper_cycle_v1
print(json.dumps({
    'db_host': os.environ.get('DB_HOST'),
    'secrets': {key: os.environ.get(key) for key in %r},
    'private_imported': 'src.execution.bitvavo_client' in sys.modules,
    'legacy_db_imported': 'src.common.db' in sys.modules,
    'pure_db_imported': 'src.common.db_core_v1' in sys.modules,
    'public_module': worker.BitvavoPublicMarketDataClient.__module__,
    'paper_runner_private_imported': 'src.execution.bitvavo_client' in sys.modules,
}))
""" % (sentinel_keys,)
    env = os.environ.copy()
    for key in (*sentinel_keys, "DB_HOST"):
        env.pop(key, None)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["db_host"] == "paper-db"
    assert result["secrets"] == {key: None for key in sentinel_keys}
    assert result["private_imported"] is False
    assert result["legacy_db_imported"] is False
    assert result["pure_db_imported"] is True
    assert result["paper_runner_private_imported"] is False
    assert result["public_module"] == "src.market_data.bitvavo_public_client_v1"


def test_legacy_db_import_preserves_dotenv_compatibility(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "DB_HOST=legacy-db\nSYNTH_LEGACY_COMPAT_SENTINEL=from-dotenv\n",
        encoding="utf-8",
    )
    code = """
import json, os
from src.common import db
print(json.dumps({
    'db_host': os.environ.get('DB_HOST'),
    'legacy': os.environ.get('SYNTH_LEGACY_COMPAT_SENTINEL'),
}))
"""
    env = os.environ.copy()
    env.pop("SYNTH_LEGACY_COMPAT_SENTINEL", None)
    env["DB_HOST"] = "process-db"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == {
        "db_host": "process-db",
        "legacy": "from-dotenv",
    }


def test_legacy_db_import_is_safe_without_dotenv(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    subprocess.run(
        [sys.executable, "-c", "from src.common import db; assert db.DEFAULT_DATABASE == 'synth'"],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_worker_source_contains_no_private_or_broker_write_path() -> None:
    source = Path(worker.__file__).read_text(encoding="utf-8")
    assert "src.execution.bitvavo_client" not in source
    assert "permission_gate" not in source
    assert ".place_order(" not in source
    assert ".cancel_order(" not in source
    assert "BITVAVO_API_KEY" not in source
    assert "BITVAVO_API_SECRET" not in source

    paper_runner = (
        Path(worker.__file__).with_name("run_paper_execution_runner_v1.py")
    ).read_text(encoding="utf-8")
    assert "load_dotenv" not in paper_runner
    assert "src.execution.bitvavo_client" not in paper_runner
    assert "repo.fetch_open_plans" in paper_runner
    assert "execute_plan_paper(plan, repo)" in paper_runner
    assert "FROM execution_plan" not in paper_runner
