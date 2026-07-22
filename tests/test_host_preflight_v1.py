from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.operations import run_host_preflight_v1 as preflight
from src.operations.validate_host_preflight_external_evidence_v1 import (
    validate_external_evidence,
)


REGISTRY_PATH = Path("deploy/ownership/writer_capability_ownership_v1.json")
OBS = "2026-07-21T00:00:00Z"
REFERENCE = datetime(2026, 7, 21, 0, 0, 0, tzinfo=UTC)

# Required PREFLIGHT_EXTERNAL checks for market_rotation_pressure: exchange and
# private_exchange_credentials are proven non-required from its call graph, but
# runtime_configuration (MariaDB config) remains required.
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
}


def _all_pass_local(**_kwargs) -> dict[str, preflight.CheckResult]:
    return {
        name: preflight.CheckResult(name, preflight.STATUS_PASS, "ok")
        for name in preflight.PREFLIGHT_LOCAL_CHECKS
    }


def _external_evidence(capability: str, statuses: dict[str, str]) -> dict[str, dict]:
    payload = {
        "schema_version": "host_preflight_external_evidence_schema_v1",
        "capability": capability,
        "hostname": "gurkdb",
        "checkout_commit": "0" * 40,
        "observed_at_utc": OBS,
        "checks": {
            name: {
                "status": status,
                "detail": f"{name} probe result",
                "evidence_source": "ops/preflight_probe_v1",
                "observed_at_utc": OBS,
            }
            for name, status in statuses.items()
        },
        "safety_markers": dict(VALID_SAFETY_MARKERS),
    }
    result = validate_external_evidence(
        payload,
        capability=capability,
        expected_host="gurkdb",
        expected_commit="0" * 40,
        reference_time=REFERENCE,
    )
    assert result.ok, result.errors
    return result.checks


# ---------------------------------------------------------------------------
# Stage layout and capability-specific requirement matrix
# ---------------------------------------------------------------------------


def test_check_stage_partition_is_exhaustive_and_disjoint() -> None:
    groups = (
        preflight.PREFLIGHT_LOCAL_CHECKS,
        preflight.PREFLIGHT_EXTERNAL_CHECKS,
        preflight.ACCEPTANCE_CHECKS,
        preflight.CUTOVER_CHECKS,
    )
    names = [name for group in groups for name in group]
    assert len(names) == len(set(names)) == 23
    assert set(names) == set(preflight.CHECK_ORDER)
    assert len(preflight.PREFLIGHT_LOCAL_CHECKS) == 12
    assert len(preflight.PREFLIGHT_EXTERNAL_CHECKS) == 8
    assert "runtime_configuration" in preflight.PREFLIGHT_EXTERNAL_CHECKS
    assert "private_exchange_credentials" in preflight.PREFLIGHT_EXTERNAL_CHECKS
    assert "secrets_and_configuration" not in preflight.PREFLIGHT_EXTERNAL_CHECKS
    assert preflight.ACCEPTANCE_CHECKS == ("runtime_per_writer", "resource_usage_per_writer")
    assert preflight.CUTOVER_CHECKS == ("rollback_capability",)


def test_market_rotation_pressure_capability_specific_dependency_matrix() -> None:
    # Proven from code: rotation history/pressure read persisted candles from
    # MariaDB and use only optional public CoinGecko context; no exchange API.
    # MariaDB runtime configuration is required; only the private exchange key is
    # not (there is none).
    assert preflight._external_required("market_rotation_pressure", "mariadb_connectivity") is True
    assert preflight._external_required("market_rotation_pressure", "runtime_configuration") is True
    assert preflight._external_required("market_rotation_pressure", "exchange_api_connectivity") is False
    assert preflight._external_required("market_rotation_pressure", "private_exchange_credentials") is False
    # The public writers call a public exchange endpoint and need MariaDB
    # runtime configuration, but no private exchange credentials.
    for cap in ("public_price_snapshot", "public_candle_freshness"):
        assert preflight._external_required(cap, "exchange_api_connectivity") is True
        assert preflight._external_required(cap, "runtime_configuration") is True
        assert preflight._external_required(cap, "private_exchange_credentials") is False


@pytest.mark.parametrize(
    "capability",
    ("public_price_snapshot", "public_candle_freshness", "market_rotation_pressure"),
)
def test_selected_public_capabilities_strict_behaviour(
    capability: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(preflight, "_local_checks", _all_pass_local)
    required_external = tuple(
        name
        for name in preflight.PREFLIGHT_EXTERNAL_CHECKS
        if preflight._external_required(capability, name)
    )
    # Without external evidence, every required external check is UNVERIFIED.
    bare = preflight.run_preflight(
        capability=capability,
        expected_host="gurkdb",
        expected_commit="0" * 40,
        checkout_path=Path.cwd(),
    )
    assert preflight._strict_exit_status(bare) == 5
    # With all required external evidence PASS, strict preflight passes.
    evidence = _external_evidence(capability, {name: "PASS" for name in required_external})
    passed = preflight.run_preflight(
        capability=capability,
        expected_host="gurkdb",
        expected_commit="0" * 40,
        checkout_path=Path.cwd(),
        external_evidence_checks=evidence,
    )
    assert preflight._strict_exit_status(passed) == 0


def test_runtime_configuration_required_but_private_exchange_credentials_not() -> None:
    results = preflight.run_preflight(
        capability="public_price_snapshot",
        expected_host="nowhere",
        expected_commit="0" * 40,
        checkout_path=Path.cwd(),
    )
    by_name = {r.name: r for r in results}
    runtime = by_name["runtime_configuration"]
    assert runtime.required is True
    assert runtime.stage == preflight.STAGE_PREFLIGHT_EXTERNAL
    private = by_name["private_exchange_credentials"]
    assert private.required is False
    assert private.stage == preflight.STAGE_PREFLIGHT_EXTERNAL


# ---------------------------------------------------------------------------
# Strict semantics: local-only, missing external, required WARN
# ---------------------------------------------------------------------------


def test_local_only_preflight_without_external_evidence_is_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight, "_local_checks", _all_pass_local)
    results = preflight.run_preflight(
        capability="market_rotation_pressure",
        expected_host="gurkdb",
        expected_commit="0" * 40,
        checkout_path=Path.cwd(),
    )
    # Required external checks remain UNVERIFIED -> strict exit 5.
    assert preflight._strict_exit_status(results) == 5


def test_valid_required_external_evidence_produces_strict_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight, "_local_checks", _all_pass_local)
    evidence = _external_evidence(
        "market_rotation_pressure", {name: "PASS" for name in RP_REQUIRED_EXTERNAL}
    )
    results = preflight.run_preflight(
        capability="market_rotation_pressure",
        expected_host="gurkdb",
        expected_commit="0" * 40,
        checkout_path=Path.cwd(),
        external_evidence_checks=evidence,
    )
    assert preflight._strict_exit_status(results) == 0
    # Non-required external checks are still UNVERIFIED but do not block.
    exchange = next(r for r in results if r.name == "exchange_api_connectivity")
    assert exchange.status == preflight.STATUS_UNVERIFIED and exchange.required is False


def test_missing_required_external_evidence_remains_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight, "_local_checks", _all_pass_local)
    # Only one required external check supplied; the rest stay UNVERIFIED.
    evidence = _external_evidence("market_rotation_pressure", {"mariadb_connectivity": "PASS"})
    results = preflight.run_preflight(
        capability="market_rotation_pressure",
        expected_host="gurkdb",
        expected_commit="0" * 40,
        checkout_path=Path.cwd(),
        external_evidence_checks=evidence,
    )
    assert preflight._strict_exit_status(results) == 5


def test_required_external_warn_remains_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight, "_local_checks", _all_pass_local)
    statuses = {name: "PASS" for name in RP_REQUIRED_EXTERNAL}
    statuses["dns"] = "WARN"
    evidence = _external_evidence("market_rotation_pressure", statuses)
    results = preflight.run_preflight(
        capability="market_rotation_pressure",
        expected_host="gurkdb",
        expected_commit="0" * 40,
        checkout_path=Path.cwd(),
        external_evidence_checks=evidence,
    )
    assert preflight._strict_exit_status(results) == 4


def test_evidence_cannot_flip_a_local_check(monkeypatch: pytest.MonkeyPatch) -> None:
    # A locally-measured FAIL stays authoritative even with full external PASS.
    def failing_local(**_kwargs):
        checks = _all_pass_local()
        checks["host_identity"] = preflight.CheckResult(
            "host_identity", preflight.STATUS_FAIL, "actual=other expected=gurkdb"
        )
        return checks

    monkeypatch.setattr(preflight, "_local_checks", failing_local)
    evidence = _external_evidence(
        "market_rotation_pressure", {name: "PASS" for name in RP_REQUIRED_EXTERNAL}
    )
    results = preflight.run_preflight(
        capability="market_rotation_pressure",
        expected_host="gurkdb",
        expected_commit="0" * 40,
        checkout_path=Path.cwd(),
        external_evidence_checks=evidence,
    )
    host = next(r for r in results if r.name == "host_identity")
    assert host.status == preflight.STATUS_FAIL
    assert preflight._strict_exit_status(results) == 3


# ---------------------------------------------------------------------------
# Deferred acceptance / cutover checks
# ---------------------------------------------------------------------------


def test_acceptance_and_cutover_checks_are_deferred_and_non_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight, "_local_checks", _all_pass_local)
    evidence = _external_evidence(
        "market_rotation_pressure", {name: "PASS" for name in RP_REQUIRED_EXTERNAL}
    )
    results = preflight.run_preflight(
        capability="market_rotation_pressure",
        expected_host="gurkdb",
        expected_commit="0" * 40,
        checkout_path=Path.cwd(),
        external_evidence_checks=evidence,
    )
    by_name = {r.name: r for r in results}
    for name in ("runtime_per_writer", "resource_usage_per_writer"):
        r = by_name[name]
        assert r.stage == preflight.STAGE_ACCEPTANCE
        assert r.required is False and r.required_stage == preflight.STAGE_ACCEPTANCE
        assert r.status == preflight.STATUS_UNVERIFIED  # never silently PASS
    rollback = by_name["rollback_capability"]
    assert rollback.stage == preflight.STAGE_CUTOVER
    assert rollback.required is False and rollback.required_stage == preflight.STAGE_CUTOVER
    assert rollback.status == preflight.STATUS_UNVERIFIED
    # They remain visible but do not block a strict preflight PASS.
    assert preflight._strict_exit_status(results) == 0


# ---------------------------------------------------------------------------
# systemd diagnostic scoping
# ---------------------------------------------------------------------------

RP_UNITS = (
    "deploy/systemd/synth-market-rotation-pressure-writer.service",
    "deploy/systemd/synth-market-rotation-pressure-writer.timer",
)


def test_unrelated_xfs_scrub_all_diagnostic_does_not_warn() -> None:
    # rc=0 unrelated xfs warning remains informational PASS.
    stderr = (
        "/usr/lib/systemd/system/xfs_scrub_all.service:5: Unit configured to use "
        "KillMode=none. This is unsafe, as it disables systemd's process lifecycle "
        "management for the service."
    )
    result = preflight._classify_systemd_verify(0, stderr, "", RP_UNITS)
    assert result.status == preflight.STATUS_PASS
    assert "known_unrelated=1" in result.detail


def test_relevant_synth_unit_warning_still_blocks() -> None:
    stderr = (
        "deploy/systemd/synth-market-rotation-pressure-writer.service:12: Unknown key "
        "name 'Frobnicate' in section 'Service', ignoring."
    )
    result = preflight._classify_systemd_verify(0, stderr, "", RP_UNITS)
    assert result.status == preflight.STATUS_WARN
    assert "synth-market-rotation-pressure-writer.service" in result.detail


def test_relevant_synth_unit_failure_blocks_even_with_unrelated_noise() -> None:
    stderr = (
        "/usr/lib/systemd/system/xfs_scrub_all.service:5: KillMode warning\n"
        "deploy/systemd/synth-market-rotation-pressure-writer.timer:3: Failed to parse"
    )
    result = preflight._classify_systemd_verify(1, stderr, "", RP_UNITS)
    assert result.status == preflight.STATUS_FAIL
    assert "synth-market-rotation-pressure-writer.timer" in result.detail


def test_clean_verify_passes() -> None:
    result = preflight._classify_systemd_verify(0, "", "", RP_UNITS)
    assert result.status == preflight.STATUS_PASS


def test_nonzero_with_empty_output_fails_closed() -> None:
    result = preflight._classify_systemd_verify(1, "", "", RP_UNITS)
    assert result.status == preflight.STATUS_FAIL
    assert "no diagnostic output" in result.detail


def test_nonzero_with_generic_unknown_diagnostic_fails_closed() -> None:
    stderr = "Failed to load unit file: No such file or directory"
    result = preflight._classify_systemd_verify(1, stderr, "", RP_UNITS)
    assert result.status == preflight.STATUS_FAIL
    assert "Failed to load unit" in result.detail


def test_nonzero_with_only_known_unrelated_diagnostic_is_ignored() -> None:
    # rc=1 but every line is positively classified as unrelated -> PASS.
    stderr = "/usr/lib/systemd/system/xfs_scrub_all.service:5: KillMode=none is unsafe"
    result = preflight._classify_systemd_verify(1, stderr, "", RP_UNITS)
    assert result.status == preflight.STATUS_PASS
    assert "ignored_known_unrelated=1" in result.detail


def test_nonzero_with_relevant_synth_diagnostic_fails() -> None:
    stderr = "deploy/systemd/synth-market-rotation-pressure-writer.service:9: bad directive"
    result = preflight._classify_systemd_verify(1, stderr, "", RP_UNITS)
    assert result.status == preflight.STATUS_FAIL
    assert "synth-market-rotation-pressure-writer.service" in result.detail


# ---------------------------------------------------------------------------
# Ownership registry state remains explicit after the public-price rollout
# ---------------------------------------------------------------------------


def test_ownership_registry_records_only_public_price_as_active() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    caps = {c["capability_id"]: c for c in registry["capabilities"]}
    price = caps["public_price_snapshot"]
    assert price["runtime_lifecycle"] == "ACTIVE"
    assert price["production_runtime_owner"] == "gurkdb"
    assert price["production_authorization_status"] == "AUTHORIZED"
    for cap_id in ("public_candle_freshness", "market_rotation_pressure"):
        cap = caps[cap_id]
        assert cap["runtime_lifecycle"] == "SELECTED_PENDING_PREFLIGHT", cap_id
        assert cap["production_runtime_owner"] == "UNASSIGNED", cap_id
        assert cap["production_authorization_status"] == "UNASSIGNED", cap_id
    native = caps["native_short_4h_chain"]
    assert native["runtime_lifecycle"] == "UNASSIGNED"
    assert native["production_runtime_owner"] == "UNASSIGNED"
    assert native["production_authorization_status"] == "UNASSIGNED"


def test_json_output_exposes_stage_and_strict_stage_contract(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(preflight, "_local_checks", _all_pass_local)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_host_preflight_v1",
            "--capability", "market_rotation_pressure",
            "--expected-host", "gurkdb",
            "--expected-commit", "0" * 40,
            "--checkout-path", str(Path.cwd()),
            "--output", "json",
        ],
    )
    rc = preflight.main()
    assert rc == 0  # non-strict always returns zero
    payload = json.loads(capsys.readouterr().out)
    assert payload["strict_requires_stages"] == ["PREFLIGHT_LOCAL", "PREFLIGHT_EXTERNAL"]
    assert payload["deferred_stages"] == ["ACCEPTANCE", "CUTOVER"]
    stages = {c["name"]: c["stage"] for c in payload["checks"]}
    assert stages["mariadb_connectivity"] == "PREFLIGHT_EXTERNAL"
    assert stages["rollback_capability"] == "CUTOVER"


# ---------------------------------------------------------------------------
# Machine-readable and redacted evidence failures
# ---------------------------------------------------------------------------


SENTINEL_SECRET = "SENTINEL_SECRET_VALUE_MUST_NOT_APPEAR"


def _runner_manifest_with_host(hostname: str) -> dict:
    observed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": "host_preflight_external_evidence_schema_v1",
        "capability": "market_rotation_pressure",
        "hostname": hostname,
        "checkout_commit": "0" * 40,
        "observed_at_utc": observed_at,
        "checks": {
            "dns": {
                "status": "PASS",
                "detail": "probe ok",
                "evidence_source": "ops/preflight_probe_v1",
                "observed_at_utc": observed_at,
            }
        },
        "safety_markers": dict(VALID_SAFETY_MARKERS),
    }


def _run_main_with_evidence(
    monkeypatch: pytest.MonkeyPatch,
    evidence_path: Path,
    *,
    output: str,
    strict: bool = False,
) -> int:
    argv = [
        "run_host_preflight_v1",
        "--capability",
        "market_rotation_pressure",
        "--expected-host",
        "gurkdb",
        "--expected-commit",
        "0" * 40,
        "--checkout-path",
        str(Path.cwd()),
        "--external-evidence-file",
        str(evidence_path),
        "--output",
        output,
    ]
    if strict:
        argv.append("--strict")
    monkeypatch.setattr("sys.argv", argv)
    return preflight.main()


def test_invalid_evidence_json_is_one_redacted_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence_path = tmp_path / "invalid_evidence.json"
    evidence_path.write_text(
        json.dumps(_runner_manifest_with_host(SENTINEL_SECRET)),
        encoding="utf-8",
    )
    rc = _run_main_with_evidence(monkeypatch, evidence_path, output="json")
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert rc == 2
    assert payload["status"] == "FAILED"
    assert payload["reason"] == "EXTERNAL_EVIDENCE_INVALID"
    assert payload["errors"] == [
        {
            "code": "HOSTNAME_MISMATCH",
            "field": "hostname",
            "provided_length": len(SENTINEL_SECRET),
            "provided_type": "str",
        }
    ]
    assert captured.err == ""
    assert SENTINEL_SECRET not in captured.out + captured.err


@pytest.mark.parametrize("file_state", ("invalid_json", "missing"))
def test_unreadable_or_invalid_json_evidence_stays_json(
    file_state: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence_path = tmp_path / "evidence.json"
    if file_state == "invalid_json":
        evidence_path.write_text(f"{{{SENTINEL_SECRET}", encoding="utf-8")
    rc = _run_main_with_evidence(monkeypatch, evidence_path, output="json")
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert rc == 2
    assert payload["status"] == "FAILED"
    assert payload["error_count"] == 1
    assert captured.err == ""
    assert SENTINEL_SECRET not in captured.out + captured.err


def test_invalid_evidence_table_is_redacted_and_human_readable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence_path = tmp_path / "invalid_evidence.json"
    evidence_path.write_text(
        json.dumps(_runner_manifest_with_host(SENTINEL_SECRET)),
        encoding="utf-8",
    )
    rc = _run_main_with_evidence(monkeypatch, evidence_path, output="table")
    captured = capsys.readouterr()
    assert rc == 2
    assert "FAILED runner=host_preflight_v1" in captured.out
    assert "EVIDENCE_ERROR hostname mismatch" in captured.out
    assert "host_mutations=0" in captured.out
    assert captured.err == ""
    assert SENTINEL_SECRET not in captured.out + captured.err


def test_strict_nonzero_json_is_one_document(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(preflight, "_local_checks", _all_pass_local)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_host_preflight_v1",
            "--capability",
            "market_rotation_pressure",
            "--expected-host",
            "gurkdb",
            "--expected-commit",
            "0" * 40,
            "--checkout-path",
            str(Path.cwd()),
            "--output",
            "json",
            "--strict",
        ],
    )
    rc = preflight.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert rc == 5
    assert payload["runner"] == "host_preflight_v1"
    assert captured.err == ""
