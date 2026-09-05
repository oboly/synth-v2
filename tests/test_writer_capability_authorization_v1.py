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


CANDLE_CAP = "public_candle_freshness"
CANDLE_SERVICE = "synth-market-candle-freshness-writer.service"


def _candle_authorization(commit: str) -> dict:
    auth = _production_authorization(commit)
    auth["authorization_id"] = "auth-candle-0001"
    auth["capability_id"] = CANDLE_CAP
    auth["capability_identity"] = "public-candle-freshness-writer"
    auth["service"] = CANDLE_SERVICE
    auth["systemd_unit"] = CANDLE_SERVICE
    return auth


def _candle_ancestor_authorization(anchor_commit: str) -> dict:
    auth = _candle_authorization(anchor_commit)
    auth["commit_verification_mode"] = "ANCESTOR"
    auth["required_branch"] = "main"
    return auth


def _candle_registry_file(tmp_path: Path, auth_file: Path) -> Path:
    from tests.writer_auth_support import registry_with_auth_file

    return registry_with_auth_file(tmp_path, CANDLE_CAP, auth_file, authorize=True)


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
    rp["production_runtime_owner"] = "UNASSIGNED"
    rp["production_authorization_status"] = "UNASSIGNED"
    rp["runtime_lifecycle"] = "SELECTED_PENDING_PREFLIGHT"
    rp["production_decision_evidence"] = ""
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
# Authorization file: Sector Rotation production-schema onboarding.
#
# sector_rotation_snapshot / sector-rotation-snapshot-writer were already
# closed-set members of the ownership registry validator, the acceptance
# permit schema, and the Python CAPABILITY_IDENTITY mapping, but the
# production authorization schema's capability_id/capability_identity enums
# had not been extended, so every schema-valid Sector Rotation PRODUCTION
# authorization artifact was structurally impossible. These tests prove the
# closed-enum addition and nothing broader.
# ---------------------------------------------------------------------------

SECTOR_PROD_SERVICE = "synth-sector-rotation-writer.service"


def _sector_authorization(commit: str, **overrides: object) -> dict:
    auth = _production_authorization(commit)
    auth["authorization_id"] = "auth-sector-0001"
    auth["capability_id"] = "sector_rotation_snapshot"
    auth["capability_identity"] = "sector-rotation-snapshot-writer"
    auth["service"] = SECTOR_PROD_SERVICE
    auth["systemd_unit"] = SECTOR_PROD_SERVICE
    auth.update(overrides)
    return auth


def test_sector_rotation_production_authorization_schema_accepts_valid_payload(tmp_path: Path) -> None:
    _, head = _temp_git(tmp_path)
    auth_path = _write_json(tmp_path / "auth.json", _sector_authorization(head))
    result = load_and_validate_authorization(auth_path, AUTH_SCHEMA)
    assert result.ok, result.errors
    assert result.payload["capability_id"] == "sector_rotation_snapshot"
    assert result.payload["capability_identity"] == "sector-rotation-snapshot-writer"


def test_sector_rotation_production_authorization_wrong_identity_rejected_semantically(
    tmp_path: Path,
) -> None:
    # "market-rotation-pressure-writer" is independently a valid member of
    # the capability_identity enum, so a capability_id/capability_identity
    # cross-mismatch is not a schema violation on its own -- it is caught by
    # the semantic PRODUCTION verification step (_verify_production), which
    # compares the authorization's capability_identity against the identity
    # canonically owned by capability_id=sector_rotation_snapshot.
    from tests.writer_auth_support import registry_with_auth_file

    repo, head = _temp_git(tmp_path)
    auth_path = _write_json(
        tmp_path / "auth.json",
        _sector_authorization(head, capability_identity="market-rotation-pressure-writer"),
    )
    # Independent of umask: the file-security check (owner/group-writable)
    # runs before content validation and is not what this test targets.
    auth_path.chmod(0o644)
    schema_result = load_and_validate_authorization(auth_path, AUTH_SCHEMA)
    assert schema_result.ok, schema_result.errors

    registry_path = registry_with_auth_file(
        tmp_path, "sector_rotation_snapshot", auth_path, authorize=True, host="devlap"
    )
    decision = verify_writer_execution_authorization(
        capability_id="sector_rotation_snapshot",
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=repo,
        registry_path=registry_path,
        actual_host="devlap",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert not decision.allowed
    assert any("capability_identity mismatch" in r for r in decision.reasons)


def test_unknown_capability_id_rejected_by_production_authorization_schema(tmp_path: Path) -> None:
    auth = _sector_authorization(
        "a" * 40,
        capability_id="not_a_real_capability",
        capability_identity="not-a-real-capability-writer",
    )
    path = _write_json(tmp_path / "auth.json", auth)
    result = load_and_validate_authorization(path, AUTH_SCHEMA)
    assert not result.ok
    assert any("capability_id" in e for e in result.errors)


def test_existing_four_production_capabilities_still_accepted_by_schema(tmp_path: Path) -> None:
    _, head = _temp_git(tmp_path)
    existing = [
        (PRICE_CAP, "public-price-snapshot-writer", PRICE_SERVICE),
        (CANDLE_CAP, "public-candle-freshness-writer", CANDLE_SERVICE),
        (
            "market_rotation_pressure",
            "market-rotation-pressure-writer",
            "synth-market-rotation-pressure-writer.service",
        ),
        ("native_short_4h_chain", "native-short-4h-chain", "synth-chain-4h.service"),
    ]
    for capability_id, identity, service in existing:
        auth = _production_authorization(head)
        auth["capability_id"] = capability_id
        auth["capability_identity"] = identity
        auth["service"] = service
        auth["systemd_unit"] = service
        auth_path = _write_json(tmp_path / f"auth-{capability_id}.json", auth)
        result = load_and_validate_authorization(auth_path, AUTH_SCHEMA)
        assert result.ok, (capability_id, result.errors)


def test_production_and_acceptance_schemas_remain_separate_for_sector_rotation(tmp_path: Path) -> None:
    _, head = _temp_git(tmp_path)
    # A PRODUCTION-shaped Sector Rotation payload must not validate against
    # the ACCEPTANCE permit schema (different required fields/purpose const).
    production_path = _write_json(tmp_path / "prod.json", _sector_authorization(head))
    against_acceptance_schema = load_and_validate_authorization(production_path, ACCEPT_SCHEMA)
    assert not against_acceptance_schema.ok

    # An ACCEPTANCE-shaped Sector Rotation permit must not validate against
    # the PRODUCTION authorization schema.
    acceptance_payload = {
        "permit_version": "writer_capability_acceptance_permit_v1",
        "permit_id": "permit-sector-0002",
        "issued_at_utc": "2026-08-11T00:00:00Z",
        "expiry_utc": "2099-01-01T00:00:00Z",
        "purpose": "ACCEPTANCE",
        "capability_id": "sector_rotation_snapshot",
        "capability_identity": "sector-rotation-snapshot-writer",
        "acceptance_host": "gurkdb",
        "authorized_commit": head,
        "approval_reference": "ref",
    }
    acceptance_path = _write_json(tmp_path / "accept.json", acceptance_payload)
    against_production_schema = load_and_validate_authorization(acceptance_path, AUTH_SCHEMA)
    assert not against_production_schema.ok


def test_production_authorization_schema_has_no_wildcard_capability() -> None:
    schema = json.loads(AUTH_SCHEMA.read_text(encoding="utf-8"))
    cap_id_enum = schema["properties"]["capability_id"]["enum"]
    cap_identity_enum = schema["properties"]["capability_identity"]["enum"]
    assert cap_id_enum == [
        "public_price_snapshot",
        "public_candle_freshness",
        "market_rotation_pressure",
        "native_short_4h_chain",
        "sector_rotation_snapshot",
    ]
    assert cap_identity_enum == [
        "public-price-snapshot-writer",
        "public-candle-freshness-writer",
        "market-rotation-pressure-writer",
        "native-short-4h-chain",
        "sector-rotation-snapshot-writer",
    ]
    assert "*" not in cap_id_enum
    assert "*" not in cap_identity_enum
    assert schema["additionalProperties"] is False


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


SECTOR_CAP = "sector_rotation_snapshot"
SECTOR_IDENTITY = "sector-rotation-snapshot-writer"


def _sector_permit(head: str, **overrides: object) -> dict:
    permit = {
        "permit_version": "writer_capability_acceptance_permit_v1",
        "permit_id": "permit-sector-0001",
        "issued_at_utc": "2026-08-11T00:00:00Z",
        "expiry_utc": "2099-01-01T00:00:00Z",
        "purpose": "ACCEPTANCE",
        "capability_id": SECTOR_CAP,
        "capability_identity": SECTOR_IDENTITY,
        "acceptance_host": "devlap",
        "authorized_commit": head,
        "approval_reference": "ref",
    }
    permit.update(overrides)
    return permit


def test_sector_rotation_acceptance_permit_is_accepted(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    permit_path = _write_json(tmp_path / "permit.json", _sector_permit(head))
    decision = verify_writer_execution_authorization(
        capability_id=SECTOR_CAP,
        mode=ExecutionMode.ACCEPTANCE,
        repo_root=REPO,
        checkout_path=repo,
        acceptance_permit_path=permit_path,
        acceptance_permit_root=tmp_path,
        actual_host="devlap",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert decision.allowed, decision.reasons
    assert decision.authorization is not None
    assert decision.authorization.capability_id == SECTOR_CAP


def test_sector_rotation_acceptance_permit_wrong_identity_rejected(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    permit_path = _write_json(
        tmp_path / "permit.json",
        _sector_permit(head, capability_identity="market-rotation-pressure-writer"),
    )
    decision = verify_writer_execution_authorization(
        capability_id=SECTOR_CAP,
        mode=ExecutionMode.ACCEPTANCE,
        repo_root=REPO,
        checkout_path=repo,
        acceptance_permit_path=permit_path,
        acceptance_permit_root=tmp_path,
        actual_host="devlap",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert not decision.allowed
    assert any("capability_identity mismatch" in r for r in decision.reasons)


def test_unknown_capability_id_rejected_by_acceptance_permit_schema(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    permit_path = _write_json(
        tmp_path / "permit.json",
        _sector_permit(
            head,
            capability_id="not_a_real_capability",
            capability_identity="not-a-real-capability-writer",
        ),
    )
    decision = verify_writer_execution_authorization(
        capability_id="not_a_real_capability",
        mode=ExecutionMode.ACCEPTANCE,
        repo_root=REPO,
        checkout_path=repo,
        acceptance_permit_path=permit_path,
        acceptance_permit_root=tmp_path,
        actual_host="devlap",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert not decision.allowed
    assert any("unknown capability_id" in r for r in decision.reasons)


def test_sector_rotation_acceptance_permit_cannot_authorize_production(tmp_path: Path) -> None:
    # A valid ACCEPTANCE-mode sector-rotation permit must never satisfy
    # PRODUCTION authorization, and the registry entry for sector_rotation_snapshot
    # remains UNASSIGNED/pending, so PRODUCTION stays denied regardless.
    repo, head = _temp_git(tmp_path)
    permit_path = _write_json(tmp_path / "permit.json", _sector_permit(head))
    accept = verify_writer_execution_authorization(
        capability_id=SECTOR_CAP,
        mode=ExecutionMode.ACCEPTANCE,
        repo_root=REPO,
        checkout_path=repo,
        acceptance_permit_path=permit_path,
        acceptance_permit_root=tmp_path,
        actual_host="devlap",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert accept.allowed, accept.reasons

    from tests.writer_auth_support import registry_with_auth_file

    prod_registry = registry_with_auth_file(tmp_path, SECTOR_CAP, permit_path)
    prod = verify_writer_execution_authorization(
        capability_id=SECTOR_CAP,
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=repo,
        registry_path=prod_registry,
        actual_host="devlap",
    )
    assert not prod.allowed


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


# ---------------------------------------------------------------------------
# ANCESTOR commit-verification mode: a stable production authorization file
# survives normal approved fast-forward deploys without a per-commit edit.
# ---------------------------------------------------------------------------

def _temp_git_main(tmp_path: Path, name: str = "checkout") -> tuple[Path, str]:
    """Real two-commit repo on an explicit ``main`` branch. Returns
    (repo_path, anchor_commit) -- the anchor is the first commit; a second
    commit advances HEAD past it, simulating a later approved deploy."""
    repo = tmp_path / name
    repo.mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "anchor"], cwd=repo, check=True, env=env)
    anchor = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    (repo / "tracked.txt").write_text("tracked v2\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "later approved deploy"], cwd=repo, check=True, env=env)
    return repo, anchor


def _ancestor_authorization(anchor_commit: str) -> dict:
    auth = _production_authorization(anchor_commit)
    auth["commit_verification_mode"] = "ANCESTOR"
    auth["required_branch"] = "main"
    return auth


def test_ancestor_mode_head_descendant_on_main_passes(tmp_path: Path) -> None:
    repo, anchor = _temp_git_main(tmp_path)
    auth_path = _write_json(tmp_path / "auth.json", _ancestor_authorization(anchor))
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
    # validated_commit reflects the actual executing HEAD, not the fixed anchor.
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    assert decision.authorization.validated_commit == head
    assert head != anchor


def test_ancestor_mode_rejects_non_ancestor_commit(tmp_path: Path) -> None:
    repo, _anchor = _temp_git_main(tmp_path)
    unrelated = "f" * 40
    auth_path = _write_json(tmp_path / "auth.json", _ancestor_authorization(unrelated))
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
    assert not decision.allowed
    assert any("is not an ancestor of HEAD" in e for e in decision.reasons)


def test_ancestor_mode_rejects_wrong_branch(tmp_path: Path) -> None:
    repo, anchor = _temp_git_main(tmp_path)
    subprocess.run(["git", "checkout", "-q", "-b", "feature/x"], cwd=repo, check=True)
    auth_path = _write_json(tmp_path / "auth.json", _ancestor_authorization(anchor))
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
    assert not decision.allowed
    assert any("expected 'main'" in e for e in decision.reasons)


def test_ancestor_mode_rejects_detached_head(tmp_path: Path) -> None:
    repo, anchor = _temp_git_main(tmp_path)
    subprocess.run(["git", "checkout", "-q", "--detach", "HEAD"], cwd=repo, check=True)
    auth_path = _write_json(tmp_path / "auth.json", _ancestor_authorization(anchor))
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
    assert not decision.allowed
    assert any("detached" in e for e in decision.reasons)


def test_ancestor_mode_requires_required_branch_main(tmp_path: Path) -> None:
    repo, anchor = _temp_git_main(tmp_path)
    auth = _ancestor_authorization(anchor)
    auth["required_branch"] = "develop"
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(auth), encoding="utf-8")
    result = load_and_validate_authorization(path, AUTH_SCHEMA)
    assert not result.ok


def test_ancestor_mode_missing_required_branch_field_rejected_by_schema(tmp_path: Path) -> None:
    auth = _ancestor_authorization("a" * 40)
    del auth["required_branch"]
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(auth), encoding="utf-8")
    result = load_and_validate_authorization(path, AUTH_SCHEMA)
    assert not result.ok


def test_unknown_commit_verification_mode_rejected(tmp_path: Path) -> None:
    repo, anchor = _temp_git_main(tmp_path)
    auth = _ancestor_authorization(anchor)
    auth["commit_verification_mode"] = "WILDCARD"
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(auth), encoding="utf-8")
    result = load_and_validate_authorization(path, AUTH_SCHEMA)
    assert not result.ok


# ---------------------------------------------------------------------------
# public_candle_freshness ANCESTOR migration: capability-specific coverage
# for the authorization guard rotated from EXACT to ANCESTOR semantics,
# mirroring the native_short_4h_chain model above via the same shared guard.
# ---------------------------------------------------------------------------

def test_candle_freshness_exact_authorized_commit_passes(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    auth_path = _write_json(tmp_path / "auth.json", _candle_authorization(head))
    registry_path = _candle_registry_file(tmp_path, auth_path)
    decision = verify_writer_execution_authorization(
        capability_id=CANDLE_CAP,
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=repo,
        registry_path=registry_path,
        actual_host="devlap",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert decision.allowed, decision.reasons


def test_candle_freshness_ancestor_mode_descendant_head_accepted(tmp_path: Path) -> None:
    repo, anchor = _temp_git_main(tmp_path)
    auth_path = _write_json(tmp_path / "auth.json", _candle_ancestor_authorization(anchor))
    registry_path = _candle_registry_file(tmp_path, auth_path)
    decision = verify_writer_execution_authorization(
        capability_id=CANDLE_CAP,
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=repo,
        registry_path=registry_path,
        actual_host="devlap",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert decision.allowed, decision.reasons
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    assert decision.authorization.validated_commit == head
    assert head != anchor


def test_candle_freshness_ancestor_mode_rejects_unrelated_commit(tmp_path: Path) -> None:
    repo, _anchor = _temp_git_main(tmp_path)
    unrelated = "f" * 40
    auth_path = _write_json(tmp_path / "auth.json", _candle_ancestor_authorization(unrelated))
    registry_path = _candle_registry_file(tmp_path, auth_path)
    decision = verify_writer_execution_authorization(
        capability_id=CANDLE_CAP,
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=repo,
        registry_path=registry_path,
        actual_host="devlap",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert not decision.allowed
    assert any("is not an ancestor of HEAD" in e for e in decision.reasons)


def test_candle_freshness_ancestor_mode_rejects_dirty_checkout(tmp_path: Path) -> None:
    repo, anchor = _temp_git_main(tmp_path)
    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    auth_path = _write_json(tmp_path / "auth.json", _candle_ancestor_authorization(anchor))
    registry_path = _candle_registry_file(tmp_path, auth_path)
    decision = verify_writer_execution_authorization(
        capability_id=CANDLE_CAP,
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=repo,
        registry_path=registry_path,
        actual_host="devlap",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert not decision.allowed
    assert any("unstaged tracked changes" in e for e in decision.reasons)


def test_candle_freshness_malformed_authorization_rejected(tmp_path: Path) -> None:
    auth = _candle_ancestor_authorization("a" * 40)
    auth["authorized_commit"] = "not-a-sha"
    path = _write_json(tmp_path / "auth.json", auth)
    result = load_and_validate_authorization(path, AUTH_SCHEMA)
    assert not result.ok


def test_candle_freshness_missing_authorization_file_blocks_production(tmp_path: Path) -> None:
    from tests.writer_auth_support import registry_with_auth_file

    registry_path = registry_with_auth_file(tmp_path, CANDLE_CAP, tmp_path / "missing.json")
    decision = verify_writer_execution_authorization(
        capability_id=CANDLE_CAP,
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=REPO,
        registry_path=registry_path,
    )
    assert not decision.allowed


def test_exact_mode_is_unaffected_default_when_field_absent(tmp_path: Path) -> None:
    """Backward compatibility: an authorization file with no
    commit_verification_mode field keeps the original exact-HEAD-match
    semantics -- a later commit on the same branch still fails."""
    repo, anchor = _temp_git_main(tmp_path)
    auth_path = _write_json(tmp_path / "auth.json", _production_authorization(anchor))
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
    assert not decision.allowed
    assert any("does not match expected commit" in e for e in decision.reasons)


# ---------------------------------------------------------------------------
# fast_rotation_c1_history (#748): MANUAL_ACCEPTANCE_ONLY runtime_shape.
# ---------------------------------------------------------------------------

C1_CAP = "fast_rotation_c1_history"
C1_IDENTITY = "fast-rotation-c1-history-writer"


def _c1_permit(head: str, **overrides: object) -> dict:
    permit = {
        "permit_version": "writer_capability_acceptance_permit_v1",
        "permit_id": "permit-c1-0001",
        "issued_at_utc": "2026-09-05T00:00:00Z",
        "expiry_utc": "2099-01-01T00:00:00Z",
        "purpose": "ACCEPTANCE",
        "capability_id": C1_CAP,
        "capability_identity": C1_IDENTITY,
        "acceptance_host": "gurkdb",
        "authorized_commit": head,
        "approval_reference": "ref",
    }
    permit.update(overrides)
    return permit


def test_fast_rotation_c1_history_identity_resolves_exactly() -> None:
    from src.operations import validate_writer_capability_ownership_v1 as reg_validator
    from src.operations.writer_capability_authorization_v1 import CAPABILITY_IDENTITY

    assert CAPABILITY_IDENTITY[C1_CAP] == C1_IDENTITY
    assert reg_validator.CAPABILITY_IDENTITY[C1_CAP] == C1_IDENTITY


def test_fast_rotation_c1_history_read_only_mode_blocks_mutation() -> None:
    decision = verify_writer_execution_authorization(
        capability_id=C1_CAP,
        mode=ExecutionMode.READ_ONLY,
        repo_root=REPO,
        checkout_path=REPO,
    )
    assert not decision.allowed
    assert any("READ_ONLY" in reason for reason in decision.reasons)


def test_fast_rotation_c1_history_acceptance_denied_without_permit() -> None:
    decision = verify_writer_execution_authorization(
        capability_id=C1_CAP,
        mode=ExecutionMode.ACCEPTANCE,
        repo_root=REPO,
        checkout_path=REPO,
    )
    assert not decision.allowed
    assert any("requires an acceptance permit path" in r for r in decision.reasons)


def test_fast_rotation_c1_history_acceptance_denied_for_wrong_capability_permit(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    # A valid permit minted for a different capability must not authorize C1.
    permit_path = _write_json(
        tmp_path / "permit.json",
        _sector_permit(head, acceptance_host="devlap"),
    )
    permit_path.chmod(0o644)
    decision = verify_writer_execution_authorization(
        capability_id=C1_CAP,
        mode=ExecutionMode.ACCEPTANCE,
        repo_root=REPO,
        checkout_path=repo,
        acceptance_permit_path=permit_path,
        acceptance_permit_root=tmp_path,
        actual_host="devlap",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert not decision.allowed
    assert any("capability_id mismatch" in r for r in decision.reasons)


def test_fast_rotation_c1_history_acceptance_denied_wrong_host(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    permit_path = _write_json(tmp_path / "permit.json", _c1_permit(head))
    permit_path.chmod(0o644)
    decision = verify_writer_execution_authorization(
        capability_id=C1_CAP,
        mode=ExecutionMode.ACCEPTANCE,
        repo_root=REPO,
        checkout_path=repo,
        acceptance_permit_path=permit_path,
        acceptance_permit_root=tmp_path,
        actual_host="devlap",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert not decision.allowed
    assert any("actual hostname does not match acceptance host" in r for r in decision.reasons)


def test_fast_rotation_c1_history_acceptance_denied_expired_permit(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    permit_path = _write_json(
        tmp_path / "permit.json",
        _c1_permit(head, acceptance_host="gurkdb", expiry_utc="2020-01-01T00:00:00Z"),
    )
    permit_path.chmod(0o644)
    decision = verify_writer_execution_authorization(
        capability_id=C1_CAP,
        mode=ExecutionMode.ACCEPTANCE,
        repo_root=REPO,
        checkout_path=repo,
        acceptance_permit_path=permit_path,
        acceptance_permit_root=tmp_path,
        actual_host="gurkdb",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert not decision.allowed
    assert any("acceptance permit has expired" in r for r in decision.reasons)


def test_fast_rotation_c1_history_acceptance_permit_is_accepted(tmp_path: Path) -> None:
    repo, head = _temp_git(tmp_path)
    permit_path = _write_json(
        tmp_path / "permit.json", _c1_permit(head, acceptance_host="gurkdb")
    )
    permit_path.chmod(0o644)
    decision = verify_writer_execution_authorization(
        capability_id=C1_CAP,
        mode=ExecutionMode.ACCEPTANCE,
        repo_root=REPO,
        checkout_path=repo,
        acceptance_permit_path=permit_path,
        acceptance_permit_root=tmp_path,
        actual_host="gurkdb",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert decision.allowed, decision.reasons
    assert decision.authorization is not None
    assert decision.authorization.capability_id == C1_CAP


def test_fast_rotation_c1_history_production_denied_while_manual_acceptance_only(
    tmp_path: Path,
) -> None:
    # Layer 1: if the registry's other production fields were accidentally
    # flipped toward an authorized-looking state, the registry itself becomes
    # semantically invalid (validate_writer_capability_ownership_v1 requires
    # MANUAL_ACCEPTANCE_ONLY capabilities to keep production owner/
    # authorization/lifecycle/evidence fully unassigned), so the whole
    # registry load fails and PRODUCTION is denied before any per-capability
    # check even runs.
    from tests.writer_auth_support import registry_with_auth_file

    repo, head = _temp_git(tmp_path)
    fake_auth_path = _write_json(tmp_path / "fake_auth.json", {"not": "used"})
    registry_path = registry_with_auth_file(
        tmp_path, C1_CAP, fake_auth_path, authorize=True, host="gurkdb"
    )
    decision = verify_writer_execution_authorization(
        capability_id=C1_CAP,
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=repo,
        registry_path=registry_path,
        actual_host="gurkdb",
        expected_working_directory=os.path.realpath(str(repo)),
    )
    assert not decision.allowed
    assert any(
        "must keep production owner" in r and "MANUAL_ACCEPTANCE_ONLY" in r
        for r in decision.reasons
    )


def test_fast_rotation_c1_history_production_denied_by_runtime_shape_independent_of_registry_state() -> None:
    # Layer 2: the code-level structural denial in
    # writer_capability_authorization_v1._verify_production runs purely off
    # cap.get("runtime_shape") and is independent of the registry-semantic
    # check above -- it is exercised directly here against the canonical,
    # unmodified (fully UNASSIGNED) registry entry.
    from src.operations.writer_capability_authorization_v1 import (
        RUNTIME_SHAPE_MANUAL_ACCEPTANCE_ONLY,
    )

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    cap = _cap(registry, C1_CAP)
    assert cap["runtime_shape"] == RUNTIME_SHAPE_MANUAL_ACCEPTANCE_ONLY
    assert cap["production_runtime_owner"] == "UNASSIGNED"


def test_fast_rotation_c1_history_production_denied_with_unmodified_canonical_registry() -> None:
    # The as-shipped registry entry (production fields all UNASSIGNED) also
    # denies PRODUCTION, independent of the explicit runtime_shape check above.
    decision = verify_writer_execution_authorization(
        capability_id=C1_CAP,
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=REPO,
    )
    assert not decision.allowed


def test_fast_rotation_c1_history_not_in_production_authorization_schema_enum() -> None:
    # Deliberate: fast_rotation_c1_history is never added to the PRODUCTION
    # authorization schema's capability enum, so a well-formed-looking
    # PRODUCTION authorization file naming it is rejected at the schema layer,
    # before any semantic check runs.
    schema = json.loads(AUTH_SCHEMA.read_text(encoding="utf-8"))
    assert C1_CAP not in schema["properties"]["capability_id"]["enum"]
    assert C1_IDENTITY not in schema["properties"]["capability_identity"]["enum"]


def test_fast_rotation_c1_history_in_acceptance_permit_schema_enum() -> None:
    schema = json.loads(ACCEPT_SCHEMA.read_text(encoding="utf-8"))
    assert C1_CAP in schema["properties"]["capability_id"]["enum"]
    assert C1_IDENTITY in schema["properties"]["capability_identity"]["enum"]
