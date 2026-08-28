from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.account.account_mode_contract_v1 import (
    is_account_mode_live_trading_enabled_consistent,
)
from src.account_provisioning.live_execution_trading_account_provisioning_v1 import (
    LiveExecutionTradingAccountProvisioningError,
    default_description,
    provision_live_execution_trading_account,
    resolve_live_execution_trading_account,
)
from src.account_provisioning.run_provision_live_execution_trading_account_v1 import parse_args

SOURCE_ID = 3
ACCOUNT_CODE = "bitvavo_joost_live"
CANONICAL_DESCRIPTION = default_description(SOURCE_ID)


class _Conn:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


LIVE_READONLY_SOURCE = {
    "trading_account_id": SOURCE_ID,
    "venue": "bitvavo",
    "account_mode": "live_readonly",
    "enabled": 1,
}


class _Repo:
    """Fake repository: fixed source row, mutable account_code lookup."""

    def __init__(self, _conn, *, source=LIVE_READONLY_SOURCE, existing=None):
        self.source = source
        self.existing = existing
        self.inserted = None

    def find_source_account(self, **_):
        return self.source

    def find_by_account_code(self, **_):
        return self.existing

    def insert_trading_account(self, **kwargs):
        assert self.existing is None, "insert must never run when a row already exists"
        self.inserted = kwargs
        self.existing = {
            "trading_account_id": 99,
            "account_code": kwargs["account_code"],
            "venue": kwargs["venue"],
            "account_mode": kwargs["account_mode"],
            "enabled": int(kwargs["enabled"]),
            "live_trading_enabled": int(kwargs["live_trading_enabled"]),
            "description": kwargs["description"],
        }
        return 99


def _run(repo_kwargs: dict, *, apply: bool):
    conn = _Conn()
    result = provision_live_execution_trading_account(
        account_code=ACCOUNT_CODE,
        venue="bitvavo",
        source_trading_account_id=SOURCE_ID,
        description=None,
        apply=apply,
        conn_factory=lambda: conn,
        repository_factory=lambda _conn: _Repo(_conn, **repo_kwargs),
        now_utc=datetime(2026, 8, 28, tzinfo=UTC),
    )
    return result, conn


# ---------------------------------------------------------------------------
# Canonical target shape / contract compliance
# ---------------------------------------------------------------------------


def test_target_account_mode_and_live_trading_enabled_satisfy_the_shared_contract() -> None:
    assert is_account_mode_live_trading_enabled_consistent("live", True)


def test_default_description_matches_canonical_target_shape_for_source_3() -> None:
    assert default_description(3) == (
        "Bitvavo execution-capable LIVE trading identity paired with "
        "read-only snapshot source trading_account_id=3"
    )


# ---------------------------------------------------------------------------
# Create path
# ---------------------------------------------------------------------------


def test_apply_creates_the_canonical_row_when_absent() -> None:
    result, conn = _run({"existing": None}, apply=True)
    assert result.status == "CREATED"
    assert result.created is True
    assert result.trading_account_id == 99
    assert conn.committed is True


def test_apply_insert_uses_exact_canonical_field_values() -> None:
    repo_holder = {}

    class _CapturingRepo(_Repo):
        def insert_trading_account(self, **kwargs):
            repo_holder.update(kwargs)
            return super().insert_trading_account(**kwargs)

    conn = _Conn()
    provision_live_execution_trading_account(
        account_code=ACCOUNT_CODE,
        venue="bitvavo",
        source_trading_account_id=SOURCE_ID,
        description=None,
        apply=True,
        conn_factory=lambda: conn,
        repository_factory=lambda c: _CapturingRepo(c, existing=None),
        now_utc=datetime(2026, 8, 28, tzinfo=UTC),
    )
    assert repo_holder["account_code"] == ACCOUNT_CODE
    assert repo_holder["venue"] == "bitvavo"
    assert repo_holder["account_mode"] == "live"
    assert repo_holder["enabled"] is True
    assert repo_holder["live_trading_enabled"] is True
    assert repo_holder["description"] == CANONICAL_DESCRIPTION


# ---------------------------------------------------------------------------
# Idempotent already-provisioned path
# ---------------------------------------------------------------------------


def _matching_existing_row(trading_account_id: int = 99) -> dict:
    return {
        "trading_account_id": trading_account_id,
        "account_code": ACCOUNT_CODE,
        "venue": "bitvavo",
        "account_mode": "live",
        "enabled": 1,
        "live_trading_enabled": 1,
        "description": CANONICAL_DESCRIPTION,
    }


def test_apply_is_idempotent_and_never_reinserts_when_already_provisioned() -> None:
    result, conn = _run({"existing": _matching_existing_row()}, apply=True)
    assert result.status == "ALREADY_PROVISIONED"
    assert result.created is False
    assert result.trading_account_id == 99
    assert conn.committed is False
    assert conn.rolled_back is False


def test_check_reports_already_provisioned_without_mutation() -> None:
    result, conn = _run({"existing": _matching_existing_row()}, apply=False)
    assert result.status == "ALREADY_PROVISIONED"
    assert conn.committed is False


def test_check_reports_would_create_without_mutation() -> None:
    result, conn = _run({"existing": None}, apply=False)
    assert result.status == "WOULD_CREATE"
    assert result.trading_account_id is None
    assert result.created is False
    assert conn.committed is False


# ---------------------------------------------------------------------------
# Conflict path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"venue": "kraken"},
        {"account_mode": "paper"},
        {"account_mode": "live_readonly"},
        {"enabled": 0},
        {"live_trading_enabled": 0},
        {"description": "some other description"},
    ],
)
def test_apply_fails_closed_on_any_protected_field_mismatch(overrides) -> None:
    existing = {**_matching_existing_row(), **overrides}
    with pytest.raises(LiveExecutionTradingAccountProvisioningError, match="ACCOUNT_IDENTITY_CONFLICT"):
        _run({"existing": existing}, apply=True)


def test_check_also_fails_closed_on_conflict_not_only_apply() -> None:
    existing = {**_matching_existing_row(), "account_mode": "paper"}
    with pytest.raises(LiveExecutionTradingAccountProvisioningError, match="ACCOUNT_IDENTITY_CONFLICT"):
        _run({"existing": existing}, apply=False)


def test_conflict_never_auto_corrects_the_existing_row() -> None:
    existing = _matching_existing_row()
    existing["enabled"] = 0

    class _NoInsertRepo(_Repo):
        def insert_trading_account(self, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("must never insert/mutate on conflict")

    conn = _Conn()
    with pytest.raises(LiveExecutionTradingAccountProvisioningError):
        provision_live_execution_trading_account(
            account_code=ACCOUNT_CODE,
            venue="bitvavo",
            source_trading_account_id=SOURCE_ID,
            description=None,
            apply=True,
            conn_factory=lambda: conn,
            repository_factory=lambda c: _NoInsertRepo(c, existing=existing),
        )
    assert conn.rolled_back is True
    assert conn.committed is False


# ---------------------------------------------------------------------------
# Rollback on failure
# ---------------------------------------------------------------------------


def test_insert_failure_rolls_back_and_closes() -> None:
    class _FailingRepo(_Repo):
        def insert_trading_account(self, **kwargs):
            raise RuntimeError("simulated DB failure")

    conn = _Conn()
    with pytest.raises(RuntimeError):
        provision_live_execution_trading_account(
            account_code=ACCOUNT_CODE,
            venue="bitvavo",
            source_trading_account_id=SOURCE_ID,
            description=None,
            apply=True,
            conn_factory=lambda: conn,
            repository_factory=lambda c: _FailingRepo(c, existing=None),
        )
    assert conn.rolled_back is True
    assert conn.committed is False
    assert conn.closed is True


def test_source_validation_failure_rolls_back_and_closes() -> None:
    conn = _Conn()
    with pytest.raises(LiveExecutionTradingAccountProvisioningError, match="SOURCE_ACCOUNT_NOT_FOUND"):
        provision_live_execution_trading_account(
            account_code=ACCOUNT_CODE,
            venue="bitvavo",
            source_trading_account_id=SOURCE_ID,
            description=None,
            apply=True,
            conn_factory=lambda: conn,
            repository_factory=lambda c: _Repo(c, source=None, existing=None),
        )
    assert conn.rolled_back is True
    assert conn.closed is True


# ---------------------------------------------------------------------------
# Source validation
# ---------------------------------------------------------------------------


def test_source_account_not_found_rejected() -> None:
    with pytest.raises(LiveExecutionTradingAccountProvisioningError, match="SOURCE_ACCOUNT_NOT_FOUND"):
        _run({"source": None, "existing": None}, apply=False)


def test_source_account_venue_mismatch_rejected() -> None:
    source = {**LIVE_READONLY_SOURCE, "venue": "kraken"}
    with pytest.raises(LiveExecutionTradingAccountProvisioningError, match="SOURCE_ACCOUNT_VENUE_MISMATCH"):
        _run({"source": source, "existing": None}, apply=False)


@pytest.mark.parametrize("bad_mode", ["paper", "live"])
def test_source_account_must_be_live_readonly(bad_mode) -> None:
    source = {**LIVE_READONLY_SOURCE, "account_mode": bad_mode}
    with pytest.raises(LiveExecutionTradingAccountProvisioningError, match="SOURCE_ACCOUNT_NOT_LIVE_READONLY"):
        _run({"source": source, "existing": None}, apply=False)


def test_source_account_must_be_enabled() -> None:
    source = {**LIVE_READONLY_SOURCE, "enabled": 0}
    with pytest.raises(LiveExecutionTradingAccountProvisioningError, match="SOURCE_ACCOUNT_DISABLED"):
        _run({"source": source, "existing": None}, apply=False)


def test_live_readonly_source_row_is_never_mutated() -> None:
    """The repository fake exposes no update/delete method at all; this
    module's source code must never reference one either."""
    source = Path(
        "src/account_provisioning/live_execution_trading_account_provisioning_v1.py"
    ).read_text()
    assert "UPDATE trading_account" not in source
    assert "DELETE FROM trading_account" not in source
    tree = ast.parse(source)
    class_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    assert "LiveExecutionTradingAccountProvisioningRepository" in class_names


# ---------------------------------------------------------------------------
# No credential/permission/kill-switch side effects
# ---------------------------------------------------------------------------


def test_module_has_no_credential_permission_or_kill_switch_imports() -> None:
    tree = ast.parse(
        Path("src/account_provisioning/live_execution_trading_account_provisioning_v1.py").read_text()
    )
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden = (
        "src.account_provisioning.credential_repository_v1",
        "src.account_provisioning.credential_crypto_v1",
        "src.account_provisioning.trade_execution_provisioning_v1",
        "src.executor.execution_credential_scope_v1",
        "src.executor.execution_kill_switch_v1",
        "src.executor.execution_live_authority_v1",
        "src.decision_gate",
        "src.execution_planner",
        "src.executor.manual_execution_bitvavo",
        "src.broker",
    )
    for module_name in imported_modules:
        for forbidden_prefix in forbidden:
            assert not module_name.startswith(forbidden_prefix), module_name

    # Restrict to the actual SQL string literals passed to cursor.execute()
    # -- docstrings legitimately explain what this module does *not* touch,
    # by naming those tables/concepts.
    tree = ast.parse(
        Path("src/account_provisioning/live_execution_trading_account_provisioning_v1.py").read_text()
    )
    sql_literals: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            sql_literals.append(node.args[0].value)
    assert sql_literals, "expected at least one cursor.execute() call"
    combined = "\n".join(sql_literals)
    assert "trading_account_credential" not in combined
    assert "executor_credential_binding" not in combined
    assert "kill_switch" not in combined.lower()
    assert "live_permission" not in combined.lower()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_requires_check_or_apply_exclusively() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--account-code", ACCOUNT_CODE, "--source-trading-account-id", "3"])
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--account-code",
                ACCOUNT_CODE,
                "--source-trading-account-id",
                "3",
                "--check",
                "--apply",
            ]
        )


def test_cli_check_mode_parses() -> None:
    args = parse_args(
        ["--account-code", ACCOUNT_CODE, "--source-trading-account-id", "3", "--check"]
    )
    assert args.check is True
    assert args.apply is False
    assert args.venue == "bitvavo"


def test_cli_never_exposes_secret_arguments() -> None:
    source = Path(
        "src/account_provisioning/run_provision_live_execution_trading_account_v1.py"
    ).read_text()
    for forbidden in ("--api-key", "--api-secret", "api_secret", "api_key"):
        assert forbidden not in source
