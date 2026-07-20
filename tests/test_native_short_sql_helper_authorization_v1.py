"""Regression tests for the remaining review findings:

- every Native SHORT SQL mutation helper requires a validated
  WriterMutationAuthorization for native_short_4h_chain, failing closed before
  any cursor.execute / commit / run-row insertion;
- the manual map runner cannot insert its initial run row before authorization;
- the public production verifier has no authorization_path override (registry-only);
- impossible calendar dates are rejected across all *_utc validation layers;
- the low-level mutation guard is NOT monkeypatched in mechanics tests;
- the freshness runner uses the canonical literal-Z contract.
"""
from __future__ import annotations

import inspect
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.operations import validate_writer_capability_ownership_v1 as validator
from src.operations import writer_capability_authorization_v1 as authmod
from src.operations.writer_capability_authorization_v1 import (
    AuthorizationDenied,
    ExecutionMode,
    load_and_validate_acceptance_permit,
    load_and_validate_authorization,
    verify_writer_execution_authorization,
)
from src.market_data import native_short_scope_status_materializer_v1 as scope_mat
from src.market_data import native_short_map_materializer_v1 as map_mat
from tests.writer_auth_support import make_test_authorization, registry_with_auth_file

REPO = Path.cwd()
AUTH_SCHEMA = REPO / "deploy/ownership/writer_capability_authorization_v1.schema.json"
ACCEPT_SCHEMA = REPO / "deploy/ownership/writer_capability_acceptance_permit_v1.schema.json"
NS = "native_short_4h_chain"


class _FakeCursor:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, *a: object, **k: object) -> None:
        self._log.append("execute")

    def executemany(self, *a: object, **k: object) -> None:
        self._log.append("executemany")

    @property
    def lastrowid(self) -> int:
        return 1


class _FakeConn:
    def __init__(self) -> None:
        self.log: list[str] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.log)

    def begin(self) -> None:
        self.log.append("begin")

    def commit(self) -> None:
        self.log.append("commit")

    def rollback(self) -> None:
        self.log.append("rollback")


def _record():
    # A real started-run record via the real builder + real provenance.
    import uuid

    from src.market_data.native_short_writer_provenance_v1 import (
        CANONICAL_REPOSITORY_WRITER_OWNER,
        NativeShortWriterExecutionMode,
        NativeShortWriterProvenance,
    )

    prov = NativeShortWriterProvenance(
        writer_entrypoint="src.market_data.run_native_short_map_materializer_v1",
        repository_writer_owner=CANONICAL_REPOSITORY_WRITER_OWNER,
        runner_name="run_native_short_map_materializer_v1",
        runner_version="0.1",
        execution_mode=NativeShortWriterExecutionMode.MANUAL,
        invocation_uuid=str(uuid.uuid4()),
        repository_commit_sha="b" * 40,
        host_name="test-host",
        process_id=123,
        trigger_type="MANUAL_NATIVE_SHORT_MAP_LEDGER_CANARY",
        trigger_ref="test-canary-1",
    )
    builder = scope_mat.NativeShortRunBuilder(
        provenance=prov,
        contract_version=scope_mat.CONTRACT_VERSION,
        started_at_utc=datetime.now(UTC),
        requested_scope_count=0,
    )
    return builder.started_record()


# ---------------------------------------------------------------------------
# Native SHORT SQL helpers require authorization before execute.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [None, {"capability_id": NS}, True, "auth"])
def test_insert_run_denied_without_valid_context(bad) -> None:
    conn = _FakeConn()
    with pytest.raises(AuthorizationDenied):
        scope_mat._insert_run(conn, _record(), authorization=bad)
    assert conn.log == []


def test_insert_run_denied_with_wrong_capability() -> None:
    conn = _FakeConn()
    wrong = make_test_authorization("public_price_snapshot")
    with pytest.raises(AuthorizationDenied):
        scope_mat._insert_run(conn, _record(), authorization=wrong)
    assert conn.log == []


def test_insert_run_allowed_with_real_native_short_context() -> None:
    conn = _FakeConn()
    ctx = make_test_authorization(NS)
    scope_mat._insert_run(conn, _record(), authorization=ctx)
    assert "execute" in conn.log


def test_all_native_short_sql_helpers_require_context() -> None:
    # Every write helper must fail closed with no context.
    conn = _FakeConn()
    with pytest.raises(AuthorizationDenied):
        scope_mat._finalize_run(conn, 1, _record(), authorization=None)
    assert conn.log == []
    with pytest.raises(AuthorizationDenied):
        map_mat._insert_generation_event(
            conn,
            authorization=None,
            key=None,
            attempt_id="a",
            event_type=None,
            event_ts_utc=datetime.now(UTC),
            provenance=None,
        )
    assert conn.log == []


def test_manual_map_runner_cannot_insert_run_row_before_authorization(monkeypatch) -> None:
    # Direct main() run while UNASSIGNED must fail before any run-row insertion.
    from src.market_data import run_native_short_map_materializer_v1 as map_runner

    calls: list[str] = []
    monkeypatch.setattr(map_runner, "_insert_run", lambda *a, **k: calls.append("insert_run"))
    monkeypatch.setattr(
        map_runner, "get_connection",
        lambda: pytest.fail("must not connect before authorization"),
    )
    monkeypatch.setenv("SYNTH_WRITER_EXECUTION_MODE", "PRODUCTION")
    for key in ("SYNTH_WRITER_CAPABILITY_ID", "SYNTH_WRITER_ACCEPTANCE_PERMIT"):
        monkeypatch.delenv(key, raising=False)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    with pytest.raises(SystemExit) as exc:
        map_runner.main([
            "--symbols", "BTC", "--write",
            "--execution-mode", "MANUAL",
            "--repository-commit", head,
            "--trigger-ref", "test-canary-1",
        ])
    assert exc.value.code == 3
    assert calls == []


# ---------------------------------------------------------------------------
# Production authorization path policy.
# ---------------------------------------------------------------------------

def test_public_verifier_has_no_production_authorization_path_override() -> None:
    sig = inspect.signature(verify_writer_execution_authorization)
    assert "authorization_path" not in sig.parameters


def test_registry_declared_authorization_path_is_used(tmp_path: Path) -> None:
    # A temporary registry pointing authorization_guard at a missing file fails
    # closed (proving the registry field, not any override, is the source).
    registry_path = registry_with_auth_file(
        tmp_path, "public_price_snapshot", tmp_path / "missing.json"
    )
    decision = verify_writer_execution_authorization(
        capability_id="public_price_snapshot",
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=REPO,
        registry_path=registry_path,
    )
    assert not decision.allowed


def test_environment_cannot_redirect_production_authorization(monkeypatch, tmp_path: Path) -> None:
    # Setting the retired env var has no effect: production remains registry-derived.
    monkeypatch.setenv("SYNTH_WRITER_AUTHORIZATION_FILE", str(tmp_path / "evil.json"))
    (tmp_path / "evil.json").write_text("{}", encoding="utf-8")
    decision = verify_writer_execution_authorization(
        capability_id="public_price_snapshot",
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=REPO,
    )
    # Registry owner is UNASSIGNED -> denied; the env file is never consulted.
    assert not decision.allowed


def test_guard_cli_has_no_authorization_file_flag() -> None:
    result = subprocess.run(
        [
            "python", "-m", "src.operations.verify_writer_capability_authorization_v1",
            "--capability", "public_price_snapshot",
            "--service", "synth-market-price-snapshot-writer.service",
            "--checkout-path", str(REPO),
            "--authorization-file", "/tmp/x.json",
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "authorization-file" in result.stderr or "unrecognized" in result.stderr


# ---------------------------------------------------------------------------
# Impossible calendar dates.
# ---------------------------------------------------------------------------

_BAD_DATES = [
    "2026-02-31T00:00:00Z",
    "2025-02-29T00:00:00Z",
    "2026-13-01T00:00:00Z",
    "2026-00-01T00:00:00Z",
    "2026-01-32T00:00:00Z",
    "2026-01-01T24:00:00Z",
]


@pytest.mark.parametrize("value", _BAD_DATES)
def test_shared_parser_rejects_impossible_dates(value: str) -> None:
    assert authmod._utc_literal_to_datetime(value) is None


def test_shared_parser_accepts_valid_leap_day() -> None:
    assert authmod._utc_literal_to_datetime("2024-02-29T00:00:00Z") is not None


@pytest.mark.parametrize("value", _BAD_DATES)
def test_semantic_validator_rejects_impossible_observed_date(value: str) -> None:
    registry = json.loads((REPO / "deploy/ownership/writer_capability_ownership_v1.json").read_text())
    rp = next(c for c in registry["capabilities"] if c["capability_id"] == "market_rotation_pressure")
    rp["observed_runtime_state"][0]["observed_at_utc"] = value
    errors = validator.validate_registry_payload(registry, repo_root=REPO).errors
    assert any("observed_at_utc must be RFC3339" in e for e in errors)


def test_semantic_validator_accepts_leap_day_observed() -> None:
    assert validator._valid_literal_utc("2024-02-29T00:00:00Z")
    assert not validator._valid_literal_utc("2026-02-31T00:00:00Z")


@pytest.mark.parametrize("value", _BAD_DATES)
def test_production_authorization_impossible_date_rejected(tmp_path: Path, value: str) -> None:
    auth = {
        "authorization_version": "writer_capability_runtime_authorization_v1",
        "authorization_id": "auth-0001",
        "authorized_at_utc": value,
        "purpose": "PRODUCTION",
        "capability_id": "public_price_snapshot",
        "capability_identity": "public-price-snapshot-writer",
        "service": "synth-market-price-snapshot-writer.service",
        "systemd_unit": "synth-market-price-snapshot-writer.service",
        "authorized_host": "devlap",
        "authorized_commit": "a" * 40,
        "production_authorization_status": "AUTHORIZED",
        "runtime_lifecycle": "AUTHORIZED_INACTIVE",
        "decision_evidence": "docs/x.md#d",
    }
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(auth), encoding="utf-8")
    # Schema shape passes literal-Z but the load+verify flow must reject the
    # impossible date via real datetime parsing.
    registry_path = registry_with_auth_file(
        tmp_path, "public_price_snapshot", path, authorize=True
    )
    # commit will still mismatch, but the authorized_at_utc parse must fail too;
    # assert the decision is denied and cites the timestamp.
    decision = verify_writer_execution_authorization(
        capability_id="public_price_snapshot",
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=REPO,
        registry_path=registry_path,
        actual_host="devlap",
    )
    assert not decision.allowed
    assert any("authorized_at_utc" in r for r in decision.reasons)


@pytest.mark.parametrize("value", _BAD_DATES)
def test_acceptance_permit_impossible_date_rejected(tmp_path: Path, value: str) -> None:
    permit = {
        "permit_version": "writer_capability_acceptance_permit_v1",
        "permit_id": "permit-0001",
        "issued_at_utc": value,
        "expiry_utc": "2999-01-01T00:00:00Z",
        "purpose": "ACCEPTANCE",
        "capability_id": "public_price_snapshot",
        "capability_identity": "public-price-snapshot-writer",
        "acceptance_host": "devlap",
        "authorized_commit": "a" * 40,
        "approval_reference": "ref",
    }
    root = tmp_path / "root"
    root.mkdir()
    path = root / "permit.json"
    path.write_text(json.dumps(permit), encoding="utf-8")
    decision = verify_writer_execution_authorization(
        capability_id="public_price_snapshot",
        mode=ExecutionMode.ACCEPTANCE,
        repo_root=REPO,
        checkout_path=REPO,
        acceptance_permit_path=path,
        acceptance_permit_root=root,
        actual_host="devlap",
    )
    assert not decision.allowed
    assert any("issued_at_utc" in r for r in decision.reasons)


# ---------------------------------------------------------------------------
# Test fixture integrity: the low-level guard is never monkeypatched.
# ---------------------------------------------------------------------------

def test_install_authorized_context_does_not_patch_low_level_guard(monkeypatch) -> None:
    from tests import writer_auth_support

    original = authmod.require_writer_mutation_authorization
    writer_auth_support.install_authorized_writer_context(monkeypatch)
    # The real guard object must be unchanged.
    assert authmod.require_writer_mutation_authorization is original
    # And it must still deny an invalid context.
    with pytest.raises(AuthorizationDenied):
        authmod.require_writer_mutation_authorization(None, NS)


def test_missing_threaded_context_fails_even_under_authorized_fixture(monkeypatch) -> None:
    from tests import writer_auth_support

    writer_auth_support.install_authorized_writer_context(monkeypatch)
    conn = _FakeConn()
    # A helper called WITHOUT threading the context still fails: the fixture only
    # patches the entry acquisition, not the low-level guard.
    with pytest.raises(AuthorizationDenied):
        scope_mat._insert_run(conn, _record(), authorization=None)
    assert conn.log == []
