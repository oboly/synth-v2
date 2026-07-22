"""Regression tests for the shared writer-capability authorization library and
the repository-wide writer call-graph. Every test reproduces a specific bypass
that a fresh independent review flagged and proves it now fails closed.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.operations import validate_writer_capability_ownership_v1 as validator
from src.operations import verify_writer_capability_authorization_v1 as guard
from src.operations.writer_capability_authorization_v1 import (
    ExecutionMode,
    load_and_validate_authorization,
    load_and_validate_registry,
    verify_checkout_identity,
    verify_writer_execution_authorization,
)


REPO = Path.cwd()
REGISTRY_PATH = REPO / "deploy/ownership/writer_capability_ownership_v1.json"
REGISTRY_SCHEMA = REPO / "deploy/ownership/writer_capability_ownership_v1.schema.json"
AUTH_SCHEMA = REPO / "deploy/ownership/writer_capability_authorization_v1.schema.json"
ACCEPT_SCHEMA = REPO / "deploy/ownership/writer_capability_acceptance_permit_v1.schema.json"

PRICE_CAP = "public_price_snapshot"
PRICE_SERVICE = "synth-market-price-snapshot-writer.service"


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _cap(registry: dict, capability_id: str) -> dict:
    return next(c for c in registry["capabilities"] if c["capability_id"] == capability_id)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _temp_git(tmp_path: Path, name: str = "checkout") -> tuple[Path, str]:
    repo = tmp_path / name
    repo.mkdir(parents=True)
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True, env=env)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    return repo, head


def _production_authorization(commit: str) -> dict:
    return {
        "authorization_version": "writer_capability_runtime_authorization_v1",
        "authorization_id": "auth-price-0001",
        "authorized_at_utc": "2026-07-20T00:00:00Z",
        "purpose": "PRODUCTION",
        "capability_id": PRICE_CAP,
        "capability_identity": "public-price-snapshot-writer",
        "service": PRICE_SERVICE,
        "systemd_unit": PRICE_SERVICE,
        "authorized_host": "devlap",
        "authorized_commit": commit,
        "production_authorization_status": "AUTHORIZED",
        "runtime_lifecycle": "AUTHORIZED_INACTIVE",
        "decision_evidence": "docs/ops/writer_capability_host_ownership_contract_v1.md#decision",
    }


def _authorized_registry_file(tmp_path: Path, auth_file: Path) -> Path:
    from tests.writer_auth_support import registry_with_auth_file

    return registry_with_auth_file(tmp_path, PRICE_CAP, auth_file, authorize=True)


# ---------------------------------------------------------------------------
# Registry / guard: schema + semantic fail-closed.
# ---------------------------------------------------------------------------

def test_schema_invalid_registry_is_rejected(tmp_path: Path) -> None:
    registry = _registry()
    registry["capabilities"][0].pop("runtime_lifecycle")  # violates schema required
    path = _write_json(tmp_path / "registry.json", registry)
    result = load_and_validate_registry(path, REGISTRY_SCHEMA, repo_root=REPO)
    assert not result.ok
    assert any("schema violation" in e for e in result.errors)


def test_semantic_invalid_registry_is_rejected(tmp_path: Path) -> None:
    registry = _registry()
    # Schema-valid enum value, semantically invalid (owner without lifecycle).
    _cap(registry, PRICE_CAP)["production_runtime_owner"] = "devlap"
    path = _write_json(tmp_path / "registry.json", registry)
    result = load_and_validate_registry(path, REGISTRY_SCHEMA, repo_root=REPO)
    assert not result.ok
    assert any("semantic invalid" in e for e in result.errors)


def test_unknown_registry_root_field_is_rejected(tmp_path: Path) -> None:
    registry = _registry()
    registry["surprise_root_field"] = True
    path = _write_json(tmp_path / "registry.json", registry)
    result = load_and_validate_registry(path, REGISTRY_SCHEMA, repo_root=REPO)
    assert not result.ok
    assert any("schema violation" in e for e in result.errors)


def test_wrong_capability_identity_is_rejected(tmp_path: Path) -> None:
    registry = _registry()
    _cap(registry, PRICE_CAP)["capability_identity"] = "public-candle-freshness-writer"
    errors = validator.validate_registry_payload(registry, repo_root=REPO).errors
    assert any("capability_identity must be" in e for e in errors)


def test_malformed_observed_timestamp_is_rejected() -> None:
    registry = _registry()
    rp = _cap(registry, "market_rotation_pressure")
    rp["observed_runtime_state"][0]["observed_at_utc"] = "2026-07-14 18:56"  # not RFC3339
    errors = validator.validate_registry_payload(registry, repo_root=REPO).errors
    assert any("observed_at_utc must be RFC3339" in e for e in errors)


def test_accepted_without_structured_evidence_is_rejected() -> None:
    registry = _registry()
    rp = _cap(registry, "market_rotation_pressure")
    rp["acceptance_evidence"] = None
    errors = validator.validate_registry_payload(registry, repo_root=REPO).errors
    assert any("requires structured acceptance_evidence" in e for e in errors)


def test_observed_authorized_while_owner_unassigned_is_rejected() -> None:
    registry = _registry()
    rp = _cap(registry, "market_rotation_pressure")
    rp["observed_runtime_state"][0]["authorization_status"] = "AUTHORIZED"
    rp["observed_runtime_state"][0]["current_state"] = "ACTIVE_OBSERVED"
    errors = validator.validate_registry_payload(registry, repo_root=REPO).errors
    assert any("requires an assigned production owner" in e for e in errors)


# ---------------------------------------------------------------------------
# Authorization file: schema fail-closed.
# ---------------------------------------------------------------------------

def test_malformed_authorization_is_rejected(tmp_path: Path) -> None:
    auth = _production_authorization("a" * 40)
    auth["authorized_commit"] = "not-a-sha"
    path = _write_json(tmp_path / "auth.json", auth)
    result = load_and_validate_authorization(path, AUTH_SCHEMA)
    assert not result.ok


def test_unknown_authorization_field_is_rejected(tmp_path: Path) -> None:
    auth = _production_authorization("a" * 40)
    auth["surprise"] = "x"
    path = _write_json(tmp_path / "auth.json", auth)
    result = load_and_validate_authorization(path, AUTH_SCHEMA)
    assert not result.ok
    assert any("schema violation" in e for e in result.errors)


def test_malformed_authorization_timestamp_is_rejected(tmp_path: Path) -> None:
    auth = _production_authorization("a" * 40)
    auth["authorized_at_utc"] = "2026/07/20 00:00"
    path = _write_json(tmp_path / "auth.json", auth)
    result = load_and_validate_authorization(path, AUTH_SCHEMA)
    assert not result.ok


# ---------------------------------------------------------------------------
# Checkout identity.
# ---------------------------------------------------------------------------

def test_wrong_head_rejected(tmp_path: Path) -> None:
    repo, _head = _temp_git(tmp_path)
    errors = verify_checkout_identity(
        checkout_path=repo, expected_commit="a" * 40, expected_working_directory=repo
    )
    assert any("does not match expected commit" in e for e in errors)


def test_dirty_unstaged_checkout_rejected(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    errors = verify_checkout_identity(
        checkout_path=repo, expected_commit=head, expected_working_directory=repo
    )
    assert any("unstaged tracked changes" in e for e in errors)


def test_dirty_staged_checkout_rejected(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    errors = verify_checkout_identity(
        checkout_path=repo, expected_commit=head, expected_working_directory=repo
    )
    assert any("staged tracked changes" in e for e in errors)


def test_wrong_realpath_rejected(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    other = tmp_path / "elsewhere"
    other.mkdir()
    errors = verify_checkout_identity(
        checkout_path=repo, expected_commit=head, expected_working_directory=other
    )
    assert any("does not match expected working directory" in e for e in errors)


def test_symlinked_checkout_rejected(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(repo)
    errors = verify_checkout_identity(
        checkout_path=link, expected_commit=head, expected_working_directory=None
    )
    assert any("symlinked" in e for e in errors)


def test_allowed_unrelated_untracked_documentation_passes(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    (repo / "docs").mkdir()
    (repo / "docs" / "note.md").write_text("note\n", encoding="utf-8")
    errors = verify_checkout_identity(
        checkout_path=repo,
        expected_commit=head,
        expected_working_directory=repo,
        allowed_untracked_paths={"docs/note.md"},
    )
    assert errors == []


def test_untracked_executable_file_rejected_even_if_allowlisted(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "evil.sh").write_text("echo hi\n", encoding="utf-8")
    errors = verify_checkout_identity(
        checkout_path=repo,
        expected_commit=head,
        expected_working_directory=repo,
        allowed_untracked_paths={"scripts/evil.sh"},
    )
    assert any("untracked file not permitted" in e for e in errors)


# ---------------------------------------------------------------------------
# Execution modes / entrypoints.
# ---------------------------------------------------------------------------

def test_read_only_mode_blocks_mutation() -> None:
    decision = verify_writer_execution_authorization(
        capability_id=PRICE_CAP, mode=ExecutionMode.READ_ONLY, repo_root=REPO, checkout_path=REPO
    )
    assert not decision.allowed


def test_production_mode_blocks_while_unassigned(tmp_path: Path) -> None:
    from tests.writer_auth_support import registry_with_auth_file

    registry_path = registry_with_auth_file(tmp_path, PRICE_CAP, tmp_path / "missing.json")
    decision = verify_writer_execution_authorization(
        capability_id=PRICE_CAP,
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=REPO,
        registry_path=registry_path,
    )
    assert not decision.allowed


def test_production_mode_passes_only_with_exact_authorized_tuple(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    auth_path = _write_json(tmp_path / "auth.json", _production_authorization(head))
    registry_path = _authorized_registry_file(tmp_path, auth_path)
    decision = verify_writer_execution_authorization(
        capability_id=PRICE_CAP,
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=repo,
        registry_path=registry_path,
        actual_host="devlap",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert decision.allowed, decision.reasons


def test_production_guard_rejects_active_registry_without_valid_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, head = _temp_git(tmp_path)
    auth = _production_authorization(head)
    auth["runtime_lifecycle"] = "ACTIVE"
    auth_path = _write_json(tmp_path / "auth.json", auth)
    registry_path = _authorized_registry_file(tmp_path, auth_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    cap = _cap(registry, PRICE_CAP)
    cap["runtime_lifecycle"] = "ACTIVE"
    cap["acceptance_status"] = "UNASSIGNED"
    cap["acceptance_host"] = "UNASSIGNED"
    cap["acceptance_evidence"] = None
    observation = cap["observed_runtime_state"][0]
    observation.update(
        {
            "host": "devlap",
            "enabled_at_observation": True,
            "active_at_observation": True,
            "current_state": "ACTIVE_OBSERVED",
            "authorization_status": "AUTHORIZED",
            "runtime_state_classification": "AUTHORIZED_RUNTIME_OBSERVED",
        }
    )
    _write_json(registry_path, registry)
    monkeypatch.setattr(guard.platform, "node", lambda: "devlap")

    decision = guard.run_guard(
        SimpleNamespace(
            repo_root=REPO,
            checkout_path=repo,
            capability=PRICE_CAP,
            service=PRICE_SERVICE,
            registry=registry_path,
            mode=ExecutionMode.PRODUCTION.value,
            acceptance_permit=None,
            allowed_untracked_path=[],
        )
    )

    assert not decision.allowed
    assert any(
        "registry semantic invalid: capability[public_price_snapshot]: "
        "lifecycle ACTIVE requires acceptance_status=ACCEPTED" in reason
        for reason in decision.reasons
    )


def test_production_denied_when_host_mismatches(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    auth_path = _write_json(tmp_path / "auth.json", _production_authorization(head))
    registry_path = _authorized_registry_file(tmp_path, auth_path)
    decision = verify_writer_execution_authorization(
        capability_id=PRICE_CAP,
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=repo,
        registry_path=registry_path,
        actual_host="gurkdb",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert not decision.allowed
    assert any("actual hostname" in r for r in decision.reasons)


def test_acceptance_permit_cannot_authorize_production(tmp_path: Path) -> None:
    # A permit file passed as the production authorization is schema-invalid.
    permit = {
        "permit_version": "writer_capability_acceptance_permit_v1",
        "permit_id": "permit-0001",
        "issued_at_utc": "2026-07-20T00:00:00Z",
        "expiry_utc": "2099-07-20T00:00:00Z",
        "purpose": "ACCEPTANCE",
        "capability_id": PRICE_CAP,
        "capability_identity": "public-price-snapshot-writer",
        "acceptance_host": "devlap",
        "authorized_commit": "a" * 40,
        "approval_reference": "ref",
    }
    permit_path = _write_json(tmp_path / "permit.json", permit)
    from tests.writer_auth_support import registry_with_auth_file

    registry_path = registry_with_auth_file(tmp_path, PRICE_CAP, permit_path)
    decision = verify_writer_execution_authorization(
        capability_id=PRICE_CAP,
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=REPO,
        registry_path=registry_path,
    )
    assert not decision.allowed


def test_production_cannot_be_inferred_from_acceptance(tmp_path: Path) -> None:
    # A valid acceptance permit authorizes ACCEPTANCE only; PRODUCTION stays denied
    # because the registry owner is UNASSIGNED.
    repo, head = _temp_git(tmp_path)
    permit = {
        "permit_version": "writer_capability_acceptance_permit_v1",
        "permit_id": "permit-0001",
        "issued_at_utc": "2026-07-20T00:00:00Z",
        "expiry_utc": "2099-07-20T00:00:00Z",
        "purpose": "ACCEPTANCE",
        "capability_id": PRICE_CAP,
        "capability_identity": "public-price-snapshot-writer",
        "acceptance_host": "devlap",
        "authorized_commit": head,
        "approval_reference": "ref",
    }
    permit_path = _write_json(tmp_path / "permit.json", permit)
    accept = verify_writer_execution_authorization(
        capability_id=PRICE_CAP,
        mode=ExecutionMode.ACCEPTANCE,
        repo_root=REPO,
        checkout_path=repo,
        acceptance_permit_path=permit_path,
        acceptance_permit_root=tmp_path,
        actual_host="devlap",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert accept.allowed, accept.reasons
    # Same permit cannot satisfy PRODUCTION (registry owner UNASSIGNED, and the
    # permit is not a production authorization file).
    from tests.writer_auth_support import registry_with_auth_file

    prod_registry = registry_with_auth_file(tmp_path, PRICE_CAP, permit_path)
    prod = verify_writer_execution_authorization(
        capability_id=PRICE_CAP,
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=repo,
        registry_path=prod_registry,
        actual_host="devlap",
    )
    assert not prod.allowed


def test_expired_acceptance_permit_rejected(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    permit = {
        "permit_version": "writer_capability_acceptance_permit_v1",
        "permit_id": "permit-0001",
        "issued_at_utc": "2020-01-01T00:00:00Z",
        "expiry_utc": "2020-01-02T00:00:00Z",
        "purpose": "ACCEPTANCE",
        "capability_id": PRICE_CAP,
        "capability_identity": "public-price-snapshot-writer",
        "acceptance_host": "devlap",
        "authorized_commit": head,
        "approval_reference": "ref",
    }
    permit_path = _write_json(tmp_path / "permit.json", permit)
    decision = verify_writer_execution_authorization(
        capability_id=PRICE_CAP,
        mode=ExecutionMode.ACCEPTANCE,
        repo_root=REPO,
        checkout_path=repo,
        acceptance_permit_path=permit_path,
        acceptance_permit_root=tmp_path,
        actual_host="devlap",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert not decision.allowed
    assert any("expired" in r for r in decision.reasons)


def test_guard_cli_production_fails_closed_while_unassigned() -> None:
    result = subprocess.run(
        [
            "python", "-m", "src.operations.verify_writer_capability_authorization_v1",
            "--capability", PRICE_CAP, "--service", PRICE_SERVICE,
            "--checkout-path", str(REPO), "--mode", "PRODUCTION",
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 3
    assert "authorization_guard=fail_closed" in result.stdout


def test_direct_python_writer_production_invocation_fails_while_unassigned() -> None:
    env = {**os.environ, "SYNTH_WRITER_EXECUTION_MODE": "PRODUCTION"}
    result = subprocess.run(
        ["python", "-m", "src.research.run_market_rotation_pressure_v1", "--write-db"],
        capture_output=True, text=True, check=False, cwd=str(REPO), env=env,
    )
    assert result.returncode == 3
    assert "writer_authorization=denied" in result.stdout


def _run_candle_etl(extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SYNTH_WRITER_")}
    env.update(extra_env)
    return subprocess.run(
        ["python", "-m", "src.etl.bitvavo.run_candles_etl", "--interval", "1w"],
        capture_output=True, text=True, check=False, cwd=str(REPO), env=env,
    )


def test_candle_etl_non_dry_run_without_capability_env_denied() -> None:
    # Authorization is unconditional: no SYNTH_WRITER_CAPABILITY_ID is required
    # or consulted to decide whether authorization applies.
    result = _run_candle_etl({"SYNTH_WRITER_EXECUTION_MODE": "PRODUCTION"})
    assert result.returncode == 3
    assert "writer_authorization=denied" in result.stdout


def test_candle_etl_default_mode_non_dry_run_denied_while_unassigned() -> None:
    # No mode env at all -> defaults to READ_ONLY -> a write attempt is denied.
    result = _run_candle_etl({})
    assert result.returncode == 3
    assert "writer_authorization=denied" in result.stdout


def test_candle_etl_false_capability_identity_cannot_disable_authorization() -> None:
    result = _run_candle_etl({
        "SYNTH_WRITER_EXECUTION_MODE": "PRODUCTION",
        "SYNTH_WRITER_CAPABILITY_ID": "native_short_4h_chain",
    })
    assert result.returncode == 3
    # Either the inconsistent-claim rejection or the authorization denial; both
    # are fail-closed and neither lets the mutation proceed.
    assert ("INCONSISTENT_CAPABILITY_CLAIM" in result.stdout
            or "writer_authorization=denied" in result.stdout)


def test_candle_etl_dry_run_is_not_gated() -> None:
    # Dry-run performs no mutation, so it is not blocked by the write boundary
    # (it may still fail later for unrelated env/network reasons, but never with
    # a writer-authorization denial).
    env = {k: v for k, v in os.environ.items() if not k.startswith("SYNTH_WRITER_")}
    env["SYNTH_WRITER_EXECUTION_MODE"] = "PRODUCTION"
    dry = subprocess.run(
        ["python", "-m", "src.etl.bitvavo.run_candles_etl", "--interval", "1w", "--dry-run"],
        capture_output=True, text=True, check=False, cwd=str(REPO), env=env,
    )
    assert "writer_authorization=denied" not in dry.stdout


def test_run_chain_1h_and_1d_do_not_invoke_candle_writer() -> None:
    for rel in ("scripts/run_chain_1h.sh", "scripts/run_chain_1d.sh"):
        text = Path(rel).read_text(encoding="utf-8")
        assert "src.etl.bitvavo.run_candles_etl" not in text, rel
    registry = _registry()
    assert set(registry["market_only_processing_chains_with_zero_public_writers"]) == {
        "scripts/run_chain_1h.sh", "scripts/run_chain_1d.sh",
    }
    assert validator.validate_registry_payload(registry, repo_root=REPO).ok


def test_market_only_chain_reintroducing_public_writer_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "scripts" / "chain.sh").write_text(
        "python -m src.etl.bitvavo.run_candles_etl --interval 1h\n", encoding="utf-8"
    )
    registry = {
        "forbidden_writer_invocation_tokens": ["src.etl.bitvavo.run_candles_etl"],
        "forbidden_account_execution_tokens": [],
        "call_graph_scan_trees": [],
        "additional_writer_paths": [],
        "market_only_processing_chains_with_zero_public_writers": ["scripts/chain.sh"],
        "capabilities": [],
    }
    errors: list[str] = []
    validator._validate_call_graph(registry, tmp_path, errors)
    assert any("must not invoke public writer tokens" in e for e in errors)


def test_direct_scope_status_main_invocation_denied_while_unassigned() -> None:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    env = {k: v for k, v in os.environ.items() if not k.startswith("SYNTH_WRITER_")}
    env["SYNTH_WRITER_EXECUTION_MODE"] = "PRODUCTION"
    result = subprocess.run(
        [
            "python", "-m", "src.market_data.run_native_short_scope_status_chain_v1",
            "--venue", "bitvavo", "--quote-currency", "EUR",
            "--fib-trading-horizon", "SHORT", "--primary-interval", "4h",
            "--supporting-interval", "1h", "--execution-mode", "CHAIN",
            "--writer-entrypoint", "scripts/run_chain_4h.sh",
            "--repository-commit", head,
            "--trigger-type", "REPOSITORY_4H_MARKET_CHAIN",
            "--trigger-ref", "scripts/run_chain_4h.sh",
        ],
        capture_output=True, text=True, check=False, cwd=str(REPO), env=env,
    )
    assert result.returncode == 3
    assert "writer_authorization=denied" in result.stdout


def test_direct_scope_status_mutation_function_denied_while_unassigned(monkeypatch) -> None:
    from datetime import datetime, timezone

    from src.market_data import run_native_short_scope_status_chain_v1 as scope_runner

    monkeypatch.setenv("SYNTH_WRITER_EXECUTION_MODE", "PRODUCTION")
    for key in ("SYNTH_WRITER_CAPABILITY_ID", "SYNTH_WRITER_AUTHORIZATION_FILE",
                "SYNTH_WRITER_ACCEPTANCE_PERMIT"):
        monkeypatch.delenv(key, raising=False)
    # get_connection must never be reached: authorization fails first. The
    # authorization boundary is the first statement in execute_runtime, before
    # provenance is validated, so provenance can be None here.
    monkeypatch.setattr(scope_runner, "get_connection",
                        lambda: pytest.fail("must not connect before authorization"))
    with pytest.raises(SystemExit) as exc:
        scope_runner.execute_runtime(
            venue="bitvavo", symbols=[], quote_currency="EUR",
            fib_trading_horizon="SHORT", primary_interval="4h",
            supporting_interval="1h", as_of_utc=datetime.now(timezone.utc),
            provenance=None,  # type: ignore[arg-type]
        )
    assert exc.value.code == 3


def test_wrapper_and_python_authorization_independently_enforced() -> None:
    # Wrapper guard present.
    wrapper = Path("scripts/run_native_short_scope_status_chain_once.sh").read_text(encoding="utf-8")
    assert "verify_writer_capability_authorization_v1" in wrapper
    # Independent Python mutation-boundary guard present in the module itself.
    module = Path("src/market_data/run_native_short_scope_status_chain_v1.py").read_text(encoding="utf-8")
    assert module.count("require_capability_write_authorization") >= 2


# ---------------------------------------------------------------------------
# Repository-wide call graph.
# ---------------------------------------------------------------------------

def test_additional_writer_paths_inventory_present_and_valid() -> None:
    registry = _registry()
    by_path = {e["path"]: e for e in registry["additional_writer_paths"]}
    # 1h/1d are no longer writers; they own zero public ingestion.
    assert "scripts/run_chain_1h.sh" not in by_path
    assert "scripts/run_chain_1d.sh" not in by_path
    assert by_path["src/live/run_live_cycle.py"]["classification"] == "architectural_violation_removed"
    assert validator.validate_registry_payload(registry, repo_root=REPO).ok


def test_run_live_cycle_no_longer_invokes_public_writer_or_execution() -> None:
    text = Path("src/live/run_live_cycle.py").read_text(encoding="utf-8")
    for token in (
        "src.etl.bitvavo.run_candles_etl",
        "src.decision.run_decision_engine",
        "src.risk.run_risk_engine",
        "src.portfolio.run_portfolio_state",
        "src.execution.run_execution_intent",
    ):
        assert token not in text, token


def test_unregistered_writer_path_is_detected(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "scripts" / "rogue.sh").write_text(
        "python -m src.market_data.run_market_price_snapshot_v1 --write-db\n", encoding="utf-8"
    )
    registry = {
        "forbidden_writer_invocation_tokens": ["src.market_data.run_market_price_snapshot_v1"],
        "forbidden_account_execution_tokens": [],
        "call_graph_scan_trees": ["scripts"],
        "additional_writer_paths": [],
        "capabilities": [],
    }
    errors: list[str] = []
    validator._validate_call_graph(registry, tmp_path, errors)
    assert any("unregistered writer path" in e for e in errors)


def test_shared_market_only_chain_may_not_invoke_account_execution(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "scripts" / "chain.sh").write_text(
        "python -m src.etl.bitvavo.run_candles_etl\n"
        "python -m src.execution.run_execution_intent\n",
        encoding="utf-8",
    )
    registry = {
        "forbidden_writer_invocation_tokens": ["src.etl.bitvavo.run_candles_etl"],
        "forbidden_account_execution_tokens": ["src.execution.run_execution_intent"],
        "call_graph_scan_trees": ["scripts"],
        "additional_writer_paths": [
            {
                "path": "scripts/chain.sh",
                "classification": "shared_market_only_chain",
                "capability_binding": "UNASSIGNED",
                "invokes_public_writer_tokens": ["src.etl.bitvavo.run_candles_etl"],
                "note": "x",
            }
        ],
        "capabilities": [],
    }
    errors: list[str] = []
    validator._validate_call_graph(registry, tmp_path, errors)
    assert any("must not invoke account/execution tokens" in e for e in errors)


def test_removed_path_that_still_invokes_writer_is_detected(tmp_path: Path) -> None:
    (tmp_path / "src" / "live").mkdir(parents=True)
    (tmp_path / "src" / "live" / "legacy.py").write_text(
        "import src.etl.bitvavo.run_candles_etl\n", encoding="utf-8"
    )
    registry = {
        "forbidden_writer_invocation_tokens": ["src.etl.bitvavo.run_candles_etl"],
        "forbidden_account_execution_tokens": [],
        "call_graph_scan_trees": ["src/live"],
        "additional_writer_paths": [
            {
                "path": "src/live/legacy.py",
                "classification": "architectural_violation_removed",
                "capability_binding": "NONE",
                "invokes_public_writer_tokens": [],
                "note": "x",
            }
        ],
        "capabilities": [],
    }
    errors: list[str] = []
    validator._validate_call_graph(registry, tmp_path, errors)
    assert any("classified removed but still invokes public writer tokens" in e for e in errors)


def test_registered_writer_path_may_not_invoke_account_execution(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "scripts" / "wrapper.sh").write_text(
        "python -m src.market_data.run_market_price_snapshot_v1 --write-db\n"
        "python -m src.decision.run_decision_engine\n",
        encoding="utf-8",
    )
    registry = {
        "forbidden_writer_invocation_tokens": ["src.market_data.run_market_price_snapshot_v1"],
        "forbidden_account_execution_tokens": ["src.decision.run_decision_engine"],
        "call_graph_scan_trees": ["scripts"],
        "additional_writer_paths": [],
        "capabilities": [
            {
                "capability_id": "public_price_snapshot",
                "wrapper": "scripts/wrapper.sh",
                "service": "x.service",
                "timer": "x.timer",
                "wrappers_invoked": ["scripts/wrapper.sh"],
            }
        ],
    }
    errors: list[str] = []
    validator._validate_call_graph(registry, tmp_path, errors)
    assert any("must not invoke account/execution tokens" in e for e in errors)
