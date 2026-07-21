from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.operations import run_host_preflight_v1 as preflight
from src.operations.validate_host_preflight_external_evidence_v1 import (
    CLOCK_SKEW_ALLOWANCE_SECONDS,
    MAX_DETAIL_LENGTH,
    MAX_EVIDENCE_SOURCE_LENGTH,
    SCHEMA_PATH,
    SCHEMA_VERSION,
    load_and_validate_external_evidence,
    validate_external_evidence,
)


CAPABILITY = "market_rotation_pressure"
HOST = "gurkdb"
COMMIT = "a" * 40
OBS = "2026-07-21T00:00:00Z"
REFERENCE = datetime(2026, 7, 21, 0, 0, 0, tzinfo=UTC)
MAX_AGE = 900

RP_REQUIRED_EXTERNAL = (
    "mariadb_connectivity",
    "dns",
    "ntp_time_sync",
    "journald_logrotation",
    "runtime_configuration",
    "firewall_outbound_connectivity",
)

VALID_SAFETY_MARKERS = {
    "host_mutations": 0,
    "database_writes": 0,
    "writer_invocations": 0,
    "systemctl_mutations": 0,
    "order_submission": 0,
    "broker_writes": 0,
    "authorization_created": False,
    "deployment_performed": False,
    "database_connections": 1,
    "database_read_queries": 3,
    "dns_lookups": 2,
    "exchange_public_calls": 0,
}


def _check(status: str = "PASS", observed_at: str = OBS) -> dict:
    return {
        "status": status,
        "detail": "probe ok latency_ms=4",
        "evidence_source": "ops/preflight_probe_v1#run",
        "observed_at_utc": observed_at,
    }


def _manifest(**overrides) -> dict:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "capability": CAPABILITY,
        "hostname": HOST,
        "checkout_commit": COMMIT,
        "observed_at_utc": OBS,
        "checks": {name: _check() for name in RP_REQUIRED_EXTERNAL},
        "safety_markers": dict(VALID_SAFETY_MARKERS),
    }
    payload.update(overrides)
    return payload


def _validate(
    payload: dict,
    *,
    host: str = HOST,
    commit: str = COMMIT,
    capability: str = CAPABILITY,
    reference_time: datetime = REFERENCE,
    max_age_seconds: int = MAX_AGE,
):
    return validate_external_evidence(
        payload,
        capability=capability,
        expected_host=host,
        expected_commit=commit,
        reference_time=reference_time,
        max_age_seconds=max_age_seconds,
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


def test_schema_and_validator_permit_the_same_external_check_names() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_names = set(schema["properties"]["checks"]["propertyNames"]["enum"])
    assert schema_names == set(preflight.PREFLIGHT_EXTERNAL_CHECKS)
    # The canonical check whose name collides with a forbidden substring.
    assert "private_exchange_credentials" in schema_names


def test_schema_and_validator_enforce_the_same_string_limits() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    check_properties = schema["properties"]["checks"]["additionalProperties"]["properties"]
    assert check_properties["detail"]["maxLength"] == MAX_DETAIL_LENGTH
    assert (
        check_properties["evidence_source"]["maxLength"]
        == MAX_EVIDENCE_SOURCE_LENGTH
    )


# ---------------------------------------------------------------------------
# Canonical `private_exchange_credentials` must not be treated as a secret key
# ---------------------------------------------------------------------------


def test_private_exchange_credentials_check_with_safe_metadata_is_accepted() -> None:
    payload = _manifest()
    payload["checks"]["private_exchange_credentials"] = _check()
    payload["checks"]["private_exchange_credentials"]["detail"] = "private_key_present=false"
    result = _validate(payload)
    assert result.ok, result.errors
    assert "private_exchange_credentials" in result.checks


def test_private_exchange_credentials_check_with_credential_value_is_rejected() -> None:
    payload = _manifest()
    payload["checks"]["private_exchange_credentials"] = _check()
    payload["checks"]["private_exchange_credentials"]["detail"] = (
        "-----BEGIN OPENSSH PRIVATE KEY-----AAAAB3Nza"
    )
    result = _validate(payload)
    assert not result.ok
    assert any("secret-like value" in e for e in result.errors)


def test_unknown_database_credentials_key_is_rejected() -> None:
    payload = _manifest()
    payload["database_credentials"] = "should not be here"
    result = _validate(payload)
    assert not result.ok
    # Arbitrary credential-bearing key is still flagged by the secret-key scan.
    assert any("forbidden secret-like key" in e for e in result.errors)


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
        path,
        capability=CAPABILITY,
        expected_host=HOST,
        expected_commit=COMMIT,
        reference_time=REFERENCE,
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
# Redacted validation issues
# ---------------------------------------------------------------------------


SENTINEL_SECRET = "SENTINEL_SECRET_VALUE_MUST_NOT_APPEAR"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("hostname", SENTINEL_SECRET),
        ("capability", SENTINEL_SECRET),
        ("checkout_commit", SENTINEL_SECRET),
        ("schema_version", SENTINEL_SECRET),
        ("observed_at_utc", SENTINEL_SECRET),
    ),
)
def test_hostile_top_level_values_never_appear_in_errors(field: str, value: str) -> None:
    payload = _manifest()
    payload[field] = value
    result = _validate(payload)
    assert not result.ok
    rendered = json.dumps(result.error_payloads) + "\n" + "\n".join(result.errors)
    assert value not in rendered


def test_hostile_check_status_and_timestamp_never_appear_in_errors() -> None:
    payload = _manifest()
    payload["checks"]["dns"]["status"] = SENTINEL_SECRET
    payload["checks"]["dns"]["observed_at_utc"] = SENTINEL_SECRET
    result = _validate(payload)
    assert not result.ok
    rendered = json.dumps(result.error_payloads) + "\n" + "\n".join(result.errors)
    assert SENTINEL_SECRET not in rendered
    assert {issue.code for issue in result.issues} >= {
        "CHECK_STATUS_INVALID",
        "TIMESTAMP_INVALID",
    }


def test_hostile_arbitrary_key_names_never_appear_in_errors() -> None:
    hostile_key = f"api_key_{SENTINEL_SECRET}"
    payload = _manifest()
    payload[hostile_key] = "present"
    payload["checks"]["dns"][hostile_key] = "present"
    result = _validate(payload)
    assert not result.ok
    rendered = json.dumps(result.error_payloads) + "\n" + "\n".join(result.errors)
    assert hostile_key not in rendered
    assert any(issue.code == "FORBIDDEN_SECRET_LIKE_KEY" for issue in result.issues)


@pytest.mark.parametrize(
    ("field", "limit"),
    (
        ("detail", MAX_DETAIL_LENGTH),
        ("evidence_source", MAX_EVIDENCE_SOURCE_LENGTH),
    ),
)
def test_check_string_limit_boundary_is_accepted(field: str, limit: int) -> None:
    payload = _manifest()
    payload["checks"]["dns"][field] = "x" * limit
    result = _validate(payload)
    assert result.ok, result.errors


@pytest.mark.parametrize(
    ("field", "limit"),
    (
        ("detail", MAX_DETAIL_LENGTH),
        ("evidence_source", MAX_EVIDENCE_SOURCE_LENGTH),
    ),
)
def test_check_string_over_limit_is_rejected(field: str, limit: int) -> None:
    payload = _manifest()
    payload["checks"]["dns"][field] = "x" * (limit + 1)
    result = _validate(payload)
    assert not result.ok
    issue = next(issue for issue in result.issues if issue.code == "STRING_TOO_LONG")
    assert issue.field == f"checks.dns.{field}"
    assert issue.provided_length == limit + 1
    assert issue.limit == limit


# ---------------------------------------------------------------------------
# End-to-end file load and merge into a strict preflight
# ---------------------------------------------------------------------------


def test_valid_evidence_file_merges_into_strict_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")

    result = load_and_validate_external_evidence(
        path,
        capability=CAPABILITY,
        expected_host=HOST,
        expected_commit=COMMIT,
        reference_time=REFERENCE,
    )
    assert result.ok, result.errors
    assert result.age_seconds == 0.0
    assert result.max_age_seconds == MAX_AGE

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
        tmp_path / "nope.json",
        capability=CAPABILITY,
        expected_host=HOST,
        expected_commit=COMMIT,
        reference_time=REFERENCE,
    )
    assert not result.ok
    assert any("cannot read evidence file" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Bounded evidence freshness
# ---------------------------------------------------------------------------


def test_fresh_evidence_is_accepted() -> None:
    # Reference 300s after the manifest: well within the 900s window.
    result = _validate(_manifest(), reference_time=REFERENCE + timedelta(seconds=300))
    assert result.ok, result.errors
    assert result.age_seconds == 300.0


def test_stale_evidence_is_rejected() -> None:
    result = _validate(_manifest(), reference_time=REFERENCE + timedelta(seconds=MAX_AGE + 1))
    assert not result.ok
    assert any("stale" in e for e in result.errors)


def test_future_manifest_is_rejected() -> None:
    # Manifest observed well after the reference time, beyond clock skew.
    result = _validate(
        _manifest(),
        reference_time=REFERENCE - timedelta(seconds=CLOCK_SKEW_ALLOWANCE_SECONDS + 60),
    )
    assert not result.ok
    assert any(
        issue.code == "TIMESTAMP_FUTURE" and issue.field == "observed_at_utc"
        for issue in result.issues
    )


def test_future_check_is_rejected() -> None:
    payload = _manifest()
    future = (REFERENCE + timedelta(seconds=CLOCK_SKEW_ALLOWANCE_SECONDS + 120)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    payload["checks"]["dns"]["observed_at_utc"] = future
    result = _validate(payload, reference_time=REFERENCE + timedelta(seconds=1))
    assert not result.ok
    assert any("in the future" in e for e in result.errors)


def test_check_newer_than_manifest_is_rejected() -> None:
    payload = _manifest()
    newer = (REFERENCE + timedelta(seconds=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload["checks"]["dns"]["observed_at_utc"] = newer
    # Reference kept fresh so only the check-vs-manifest ordering trips.
    result = _validate(payload, reference_time=REFERENCE + timedelta(seconds=300))
    assert not result.ok
    assert any("newer than the manifest" in e for e in result.errors)


def test_age_boundary_is_deterministic() -> None:
    # Age exactly at max is accepted; one second older is rejected.
    at_boundary = _validate(_manifest(), reference_time=REFERENCE + timedelta(seconds=MAX_AGE))
    assert at_boundary.ok, at_boundary.errors
    over_boundary = _validate(_manifest(), reference_time=REFERENCE + timedelta(seconds=MAX_AGE + 1))
    assert not over_boundary.ok


# ---------------------------------------------------------------------------
# Strict safety-marker enforcement
# ---------------------------------------------------------------------------


def test_missing_required_safety_marker_is_rejected() -> None:
    payload = _manifest()
    del payload["safety_markers"]["host_mutations"]
    result = _validate(payload)
    assert not result.ok
    assert any("missing required fields" in e for e in result.errors)


def test_nonzero_mutation_counter_is_rejected() -> None:
    payload = _manifest()
    payload["safety_markers"]["database_writes"] = 1
    result = _validate(payload)
    assert not result.ok
    assert any(
        issue.code == "COUNTER_NONZERO"
        and issue.field == "safety_markers.database_writes"
        for issue in result.issues
    )


def test_negative_counter_is_rejected() -> None:
    payload = _manifest()
    payload["safety_markers"]["database_connections"] = -1
    result = _validate(payload)
    assert not result.ok
    assert any("must not be negative" in e for e in result.errors)


def test_string_counter_is_rejected() -> None:
    payload = _manifest()
    payload["safety_markers"]["host_mutations"] = "0"
    result = _validate(payload)
    assert not result.ok
    assert any("must be an integer" in e for e in result.errors)


def test_authorization_created_true_is_rejected() -> None:
    payload = _manifest()
    payload["safety_markers"]["authorization_created"] = True
    result = _validate(payload)
    assert not result.ok
    assert any(
        issue.code == "FLAG_TRUE"
        and issue.field == "safety_markers.authorization_created"
        for issue in result.issues
    )


def test_deployment_performed_true_is_rejected() -> None:
    payload = _manifest()
    payload["safety_markers"]["deployment_performed"] = True
    result = _validate(payload)
    assert not result.ok
    assert any(
        issue.code == "FLAG_TRUE"
        and issue.field == "safety_markers.deployment_performed"
        for issue in result.issues
    )


def test_boolean_flag_as_int_is_rejected() -> None:
    payload = _manifest()
    payload["safety_markers"]["authorization_created"] = 0
    result = _validate(payload)
    assert not result.ok
    assert any(
        issue.code == "FLAG_TYPE_INVALID"
        and issue.field == "safety_markers.authorization_created"
        for issue in result.issues
    )


def test_unknown_safety_marker_field_is_rejected() -> None:
    payload = _manifest()
    payload["safety_markers"]["mystery_counter"] = 0
    result = _validate(payload)
    assert not result.ok
    assert any("safety_markers has unknown fields" in e for e in result.errors)


def test_read_only_probe_counters_may_be_nonzero() -> None:
    payload = _manifest()
    payload["safety_markers"]["database_connections"] = 5
    payload["safety_markers"]["exchange_public_calls"] = 7
    result = _validate(payload)
    assert result.ok, result.errors
