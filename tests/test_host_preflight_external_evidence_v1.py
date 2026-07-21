from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.operations import run_host_preflight_v1 as preflight
from src.operations.validate_host_preflight_external_evidence_v1 import (
    SCHEMA_PATH,
    SCHEMA_VERSION,
    load_and_validate_external_evidence,
    validate_external_evidence,
)


CAPABILITY = "market_rotation_pressure"
HOST = "gurkdb"
COMMIT = "a" * 40
OBS = "2026-07-21T00:00:00Z"

RP_REQUIRED_EXTERNAL = (
    "mariadb_connectivity",
    "dns",
    "ntp_time_sync",
    "journald_logrotation",
    "firewall_outbound_connectivity",
)


def _check(status: str = "PASS") -> dict:
    return {
        "status": status,
        "detail": "probe ok latency_ms=4",
        "evidence_source": "ops/preflight_probe_v1#run",
        "observed_at_utc": OBS,
    }


def _manifest(**overrides) -> dict:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "capability": CAPABILITY,
        "hostname": HOST,
        "checkout_commit": COMMIT,
        "observed_at_utc": OBS,
        "checks": {name: _check() for name in RP_REQUIRED_EXTERNAL},
        "safety_markers": {"database_writes": 0, "exchange_calls": 0},
    }
    payload.update(overrides)
    return payload


def _validate(payload: dict, *, host: str = HOST, commit: str = COMMIT, capability: str = CAPABILITY):
    return validate_external_evidence(
        payload, capability=capability, expected_host=host, expected_commit=commit
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_manifest_is_accepted_and_normalized() -> None:
    result = _validate(_manifest())
    assert result.ok, result.errors
    assert set(result.checks) == set(RP_REQUIRED_EXTERNAL)
    assert result.checks["mariadb_connectivity"]["status"] == "PASS"


def test_schema_file_parses_and_declares_stable_version() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    allowed = schema["properties"]["checks"]["propertyNames"]["enum"]
    assert set(allowed) == set(preflight.PREFLIGHT_EXTERNAL_CHECKS)


# ---------------------------------------------------------------------------
# Exact matching: capability / host / commit
# ---------------------------------------------------------------------------


def test_mismatched_hostname_is_rejected() -> None:
    result = _validate(_manifest(hostname="devlap"))
    assert not result.ok
    assert any("hostname mismatch" in e for e in result.errors)


def test_mismatched_commit_is_rejected() -> None:
    result = _validate(_manifest(), commit="b" * 40)
    assert not result.ok
    assert any("checkout_commit mismatch" in e for e in result.errors)


def test_mismatched_capability_is_rejected() -> None:
    result = _validate(_manifest(), capability="public_price_snapshot")
    assert not result.ok
    assert any("capability mismatch" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Stage boundaries: no local override, no acceptance/cutover smuggling
# ---------------------------------------------------------------------------


def test_external_evidence_cannot_override_local_checks() -> None:
    payload = _manifest()
    payload["checks"]["host_identity"] = _check()
    result = _validate(payload)
    assert not result.ok
    assert any("must not override local checks" in e for e in result.errors)


def test_acceptance_or_cutover_evidence_as_preflight_is_rejected() -> None:
    for smuggled in ("runtime_per_writer", "rollback_capability"):
        payload = _manifest()
        payload["checks"][smuggled] = _check()
        result = _validate(payload)
        assert not result.ok
        assert any("must not be presented as preflight evidence" in e for e in result.errors), smuggled


def test_unknown_check_is_rejected() -> None:
    payload = _manifest()
    payload["checks"]["quantum_entanglement"] = _check()
    result = _validate(payload)
    assert not result.ok
    assert any("unknown preflight-external check" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Malformed structure
# ---------------------------------------------------------------------------


def test_malformed_timestamp_is_rejected() -> None:
    payload = _manifest()
    payload["checks"]["dns"]["observed_at_utc"] = "2026-13-40 25:00"
    result = _validate(payload)
    assert not result.ok
    assert any("observed_at_utc" in e for e in result.errors)


def test_bad_schema_version_is_rejected() -> None:
    result = _validate(_manifest(schema_version="something_else"))
    assert not result.ok
    assert any("schema_version" in e for e in result.errors)


def test_unknown_top_level_field_is_rejected() -> None:
    result = _validate(_manifest(surprise=True))
    assert not result.ok
    assert any("unknown top-level fields" in e for e in result.errors)


def test_unknown_check_field_is_rejected() -> None:
    payload = _manifest()
    payload["checks"]["dns"]["command"] = "rm -rf /"
    result = _validate(payload)
    assert not result.ok
    assert any("unknown fields" in e for e in result.errors)


def test_duplicate_keys_are_rejected(tmp_path: Path) -> None:
    raw = (
        '{"schema_version": "%s", "capability": "%s", "hostname": "%s", '
        '"checkout_commit": "%s", "observed_at_utc": "%s", "hostname": "devlap", '
        '"checks": {}, "safety_markers": {}}'
    ) % (SCHEMA_VERSION, CAPABILITY, HOST, COMMIT, OBS)
    path = tmp_path / "dup.json"
    path.write_text(raw, encoding="utf-8")
    result = load_and_validate_external_evidence(
        path, capability=CAPABILITY, expected_host=HOST, expected_commit=COMMIT
    )
    assert not result.ok
    assert any("duplicate key" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Secret / credential rejection
# ---------------------------------------------------------------------------


def test_forbidden_secret_like_key_is_rejected() -> None:
    payload = _manifest()
    payload["safety_markers"]["api_key"] = "irrelevant"
    result = _validate(payload)
    assert not result.ok
    assert any("forbidden secret-like key" in e for e in result.errors)


def test_secret_like_value_in_detail_is_rejected() -> None:
    payload = _manifest()
    payload["checks"]["dns"]["detail"] = "resolver password=hunter2 for probe"
    result = _validate(payload)
    assert not result.ok
    assert any("secret-like value" in e for e in result.errors)


def test_private_key_block_in_evidence_source_is_rejected() -> None:
    payload = _manifest()
    payload["checks"]["dns"]["evidence_source"] = "-----BEGIN OPENSSH PRIVATE KEY-----abc"
    result = _validate(payload)
    assert not result.ok
    assert any("secret-like value" in e for e in result.errors)


# ---------------------------------------------------------------------------
# End-to-end file load and merge into a strict preflight
# ---------------------------------------------------------------------------


def test_valid_evidence_file_merges_into_strict_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")

    result = load_and_validate_external_evidence(
        path, capability=CAPABILITY, expected_host=HOST, expected_commit=COMMIT
    )
    assert result.ok, result.errors

    monkeypatch.setattr(
        preflight,
        "_local_checks",
        lambda **_k: {
            name: preflight.CheckResult(name, preflight.STATUS_PASS, "ok")
            for name in preflight.PREFLIGHT_LOCAL_CHECKS
        },
    )
    results = preflight.run_preflight(
        capability=CAPABILITY,
        expected_host=HOST,
        expected_commit=COMMIT,
        checkout_path=Path.cwd(),
        external_evidence_checks=result.checks,
    )
    assert preflight._strict_exit_status(results) == 0
    mariadb = next(r for r in results if r.name == "mariadb_connectivity")
    assert mariadb.status == "PASS"
    assert mariadb.evidence_source == "ops/preflight_probe_v1#run"


def test_missing_evidence_file_reports_error(tmp_path: Path) -> None:
    result = load_and_validate_external_evidence(
        tmp_path / "nope.json", capability=CAPABILITY, expected_host=HOST, expected_commit=COMMIT
    )
    assert not result.ok
    assert any("cannot read evidence file" in e for e in result.errors)
