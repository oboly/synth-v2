from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from src.operations import run_host_preflight_v1 as preflight
from src.operations.validate_writer_capability_ownership_v1 import (
    validate_registry_payload,
)
from src.operations.writer_capability_authorization_v1 import (
    ExecutionMode,
    verify_writer_execution_authorization,
)


REGISTRY_PATH = Path("deploy/ownership/writer_capability_ownership_v1.json")
SCHEMA_PATH = Path("deploy/ownership/writer_capability_ownership_v1.schema.json")
CONTRACT_DOC = Path("docs/ops/writer_capability_host_ownership_contract_v1.md")
UNASSIGNED = "UNASSIGNED"


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _capabilities(registry: dict | None = None) -> list[dict]:
    return (registry or _registry())["capabilities"]


def _cap(registry: dict, capability_id: str) -> dict:
    return next(cap for cap in registry["capabilities"] if cap["capability_id"] == capability_id)


def _errors(registry: dict) -> list[str]:
    return validate_registry_payload(registry, repo_root=Path.cwd()).errors


def _active_registry(capability_id: str = "public_price_snapshot") -> dict:
    registry = copy.deepcopy(_registry())
    cap = _cap(registry, capability_id)
    cap["production_runtime_owner"] = "devlap"
    cap["production_authorization_status"] = "AUTHORIZED"
    cap["runtime_lifecycle"] = "AUTHORIZED_INACTIVE"
    cap["production_decision_evidence"] = "docs/ops/example_authorization.md#decision"
    return registry


def test_registry_and_schema_parse_and_baseline_semantics_pass() -> None:
    registry = _registry()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == "writer_capability_ownership_schema_v1"
    assert "exactly_one_production_owner_per_capability" not in registry["invariants"]
    assert validate_registry_payload(registry, repo_root=Path.cwd()).ok


def test_lifecycle_aware_invariants_replace_exactly_one_before_cutover() -> None:
    inv = _registry()["invariants"]
    assert inv["at_most_one_authorized_active_owner_per_capability"] is True
    assert inv["exactly_one_authorized_active_owner_required_when_lifecycle_active"] is True
    assert inv["unassigned_capability_must_have_zero_authorized_owners"] is True
    assert inv["historical_or_observed_runtime_state_does_not_grant_authorization"] is True
    assert inv["acceptance_does_not_grant_production_authorization"] is True
    assert inv["authorized_inactive_owner_requires_acceptance_and_production_decision_evidence"] is True


def test_public_price_is_authorized_inactive_and_other_lanes_remain_unassigned() -> None:
    ids = {cap["capability_id"] for cap in _capabilities()}
    assert ids == {
        "public_price_snapshot",
        "public_candle_freshness",
        "market_rotation_pressure",
        "native_short_4h_chain",
    }
    price = _cap(_registry(), "public_price_snapshot")
    assert price["candidate_host"] == "gurkdb"
    assert price["selected_host"] == "gurkdb"
    assert price["acceptance_host"] == "gurkdb"
    assert price["acceptance_status"] == "ACCEPTED"
    assert price["production_runtime_owner"] == "gurkdb"
    assert price["production_authorization_status"] == "AUTHORIZED"
    assert price["runtime_lifecycle"] == "AUTHORIZED_INACTIVE"
    assert price["production_decision_evidence"]

    # The remaining lanes retain their prior selection/unassigned state.
    selected_for_preflight = {
        "public_candle_freshness",
        "market_rotation_pressure",
    }
    for cap in _capabilities():
        if cap["capability_id"] == "public_price_snapshot":
            continue
        assert cap["production_runtime_owner"] == UNASSIGNED, cap["capability_id"]
        assert cap["production_authorization_status"] == UNASSIGNED, cap["capability_id"]
        assert cap["production_decision_evidence"] == "", cap["capability_id"]
        if cap["capability_id"] in selected_for_preflight:
            assert cap["selected_host"] == "gurkdb", cap["capability_id"]
            assert cap["runtime_lifecycle"] == "SELECTED_PENDING_PREFLIGHT", cap["capability_id"]
        else:
            assert cap["selected_host"] == UNASSIGNED, cap["capability_id"]
            assert cap["runtime_lifecycle"] == UNASSIGNED, cap["capability_id"]


def test_authorized_inactive_public_price_observation_is_installed_but_inactive() -> None:
    price = _cap(_registry(), "public_price_snapshot")
    assert price["observed_runtime_state"] == [
        {
            "host": "gurkdb",
            "unit": "synth-market-price-snapshot-writer.timer",
            "unit_path": "deploy/systemd/synth-market-price-snapshot-writer.timer",
            "installed_at_observation": True,
            "enabled_at_observation": False,
            "active_at_observation": False,
            "observed_at_utc": "2026-07-21T22:30:53Z",
            "observed_at_precision": "exact",
            "current_state": "INACTIVE_VERIFIED",
            "authorization_status": "UNASSIGNED",
            "runtime_state_classification": "NONE_OBSERVED",
            "evidence_source": "docs/ops/public_price_snapshot_gurkdb_host_acceptance_20260721.md#rollback-proof",
        }
    ]


def test_rotation_pressure_acceptance_and_observed_legacy_runtime_are_preserved() -> None:
    rp = _cap(_registry(), "market_rotation_pressure")
    assert rp["acceptance_host"] == "devlap"
    assert rp["acceptance_status"] == "ACCEPTED"
    assert rp["historical_runtime_assignment"]["host"] == "devlap"
    assert rp["historical_runtime_assignment"]["status"] == "SUPERSEDED"
    assert rp["historical_runtime_assignment"]["grants_current_authority"] is False
    observed = rp["observed_runtime_state"]
    assert observed == [
        {
            "host": "devlap",
            "unit": "synth-market-rotation-pressure-writer.timer",
            "unit_path": "deploy/systemd/synth-market-rotation-pressure-writer.timer",
            "installed_at_observation": True,
            "enabled_at_observation": True,
            "active_at_observation": True,
            "observed_at_utc": "2026-07-14T18:56:00Z",
            "observed_at_precision": "approximate_minute",
            "current_state": "UNVERIFIED",
            "authorization_status": "SUPERSEDED",
            "runtime_state_classification": "OBSERVED_LEGACY_RUNTIME_PENDING_CONTAINMENT",
            "evidence_source": "docs/ops/market_rotation_pressure_runtime_owners_v1.md#installedenabledactive-timer-evidence",
        }
    ]


@pytest.mark.parametrize(
    "field,value",
    (
        ("runtime_lifecycle", "BOGUS"),
        ("production_authorization_status", "ACCEPTED"),
        ("acceptance_status", "DONE"),
        ("production_runtime_owner", "theone"),
    ),
)
def test_invalid_enums_fail(field: str, value: str) -> None:
    registry = copy.deepcopy(_registry())
    _cap(registry, "public_price_snapshot")[field] = value
    assert _errors(registry)


def test_unknown_fields_fail() -> None:
    registry = copy.deepcopy(_registry())
    _cap(registry, "public_price_snapshot")["surprise"] = True
    assert any("unknown fields" in err for err in _errors(registry))


def test_unassigned_with_owner_or_evidence_is_rejected() -> None:
    registry = copy.deepcopy(_registry())
    cap = _cap(registry, "public_price_snapshot")
    cap["runtime_lifecycle"] = "SELECTED_PENDING_PREFLIGHT"
    cap["production_authorization_status"] = UNASSIGNED
    cap["production_runtime_owner"] = UNASSIGNED
    cap["production_decision_evidence"] = ""
    cap["production_runtime_owner"] = "devlap"
    assert any("zero authorized production owners" in err for err in _errors(registry))
    cap["production_runtime_owner"] = UNASSIGNED
    cap["production_decision_evidence"] = "docs/ops/some_acceptance.md"
    assert any("unassigned production owner must not carry decision evidence" in err for err in _errors(registry))


def test_active_without_exactly_one_owner_and_evidence_is_rejected() -> None:
    registry = copy.deepcopy(_registry())
    cap = _cap(registry, "public_price_snapshot")
    cap["runtime_lifecycle"] = "ACTIVE"
    cap["production_authorization_status"] = "AUTHORIZED"
    cap["production_runtime_owner"] = UNASSIGNED
    cap["production_decision_evidence"] = ""
    assert any("requires exactly one production_runtime_owner" in err for err in _errors(registry))
    cap["production_runtime_owner"] = "gurkdb"
    assert any("requires production_decision_evidence" in err for err in _errors(registry))


def test_authorized_inactive_requires_matching_accepted_host() -> None:
    registry = copy.deepcopy(_registry())
    cap = _cap(registry, "public_price_snapshot")
    cap["acceptance_status"] = "PENDING"
    cap["acceptance_evidence"] = None
    assert any("requires acceptance_status=ACCEPTED" in err for err in _errors(registry))

    cap["acceptance_status"] = "ACCEPTED"
    cap["acceptance_evidence"] = _cap(_registry(), "public_price_snapshot")["acceptance_evidence"]
    cap["acceptance_host"] = "devlap"
    assert any("acceptance_host must equal production_runtime_owner" in err for err in _errors(registry))


def test_multiple_active_authorized_runtime_observations_are_rejected() -> None:
    registry = _active_registry()
    cap = _cap(registry, "public_price_snapshot")
    cap["runtime_lifecycle"] = "ACTIVE"
    active = {
        "host": "devlap",
        "unit": "one.timer",
        "unit_path": "deploy/systemd/synth-market-price-snapshot-writer.timer",
        "installed_at_observation": True,
        "enabled_at_observation": True,
        "active_at_observation": True,
        "observed_at_utc": "2026-07-20T00:00:00Z",
        "observed_at_precision": "exact",
        "current_state": "ACTIVE_OBSERVED",
        "authorization_status": "AUTHORIZED",
        "runtime_state_classification": "AUTHORIZED_RUNTIME_OBSERVED",
        "evidence_source": "docs/ops/example.md",
    }
    cap["observed_runtime_state"] = [active, {**active, "unit": "two.timer"}]
    assert any("multiple authorized active runtime observations" in err for err in _errors(registry))


def test_acceptance_and_historical_state_cannot_authorize_production() -> None:
    registry = copy.deepcopy(_registry())
    rp = _cap(registry, "market_rotation_pressure")
    rp["runtime_lifecycle"] = "AUTHORIZED_INACTIVE"
    rp["production_runtime_owner"] = "devlap"
    rp["production_authorization_status"] = "AUTHORIZED"
    rp["production_decision_evidence"] = rp["historical_runtime_assignment"]["source"]
    errors = _errors(registry)
    assert any("acceptance or historical evidence cannot authorize production" in err for err in errors)
    assert any("historical assignment host cannot be reused as active authority" in err for err in errors)


def test_missing_registry_paths_fail() -> None:
    registry = copy.deepcopy(_registry())
    _cap(registry, "public_price_snapshot")["timer"] = "deploy/systemd/nope.timer"
    assert any("referenced timer path missing" in err for err in _errors(registry))


def test_incomplete_native_short_inventory_fails() -> None:
    registry = copy.deepcopy(_registry())
    native = _cap(registry, "native_short_4h_chain")
    native["database_writes"] = ["native_short_scope_status"]
    native["modules_invoked"] = ["src.market_data.native_short_repository_source_identity_v1"]
    errors = _errors(registry)
    assert any("incomplete invoked module inventory" in err for err in errors)
    assert any("incomplete database write inventory" in err for err in errors)


def test_arbitrary_owner_identity_overrides_are_rejected_and_not_in_wrappers() -> None:
    registry = copy.deepcopy(_registry())
    _cap(registry, "public_price_snapshot")["owner_identity_env"] = "SYNTH_MARKET_PRICE_WRITER_OWNER"
    assert any("owner_identity_env overrides are forbidden" in err for err in _errors(registry))
    wrapper_text = Path("scripts/run_market_price_snapshot_once.sh").read_text(encoding="utf-8")
    assert "SYNTH_MARKET_PRICE_WRITER_OWNER" not in wrapper_text


def test_shared_read_only_mode_blocks_mutation() -> None:
    decision = verify_writer_execution_authorization(
        capability_id="public_price_snapshot",
        mode=ExecutionMode.READ_ONLY,
        repo_root=Path.cwd(),
        checkout_path=Path.cwd(),
    )
    assert not decision.allowed
    assert any("READ_ONLY" in reason for reason in decision.reasons)


def test_shared_production_mode_blocks_without_production_authorization_file() -> None:
    # Registry ownership is necessary but the host-local authorization file is
    # deliberately absent until independent review and merge.
    decision = verify_writer_execution_authorization(
        capability_id="public_price_snapshot",
        mode=ExecutionMode.PRODUCTION,
        repo_root=Path.cwd(),
        checkout_path=Path.cwd(),
    )
    assert not decision.allowed


def test_shared_authorization_rejects_unknown_capability() -> None:
    decision = verify_writer_execution_authorization(
        capability_id="not_a_capability",
        mode=ExecutionMode.PRODUCTION,
        repo_root=Path.cwd(),
        checkout_path=Path.cwd(),
    )
    assert not decision.allowed
    assert any("unknown capability_id" in reason for reason in decision.reasons)


def test_guard_cli_fails_closed_when_registry_declared_authorization_file_is_missing() -> None:
    # The production authorization path is registry-declared (not overridable);
    # on a host without that file the guard fails closed.
    result = subprocess.run(
        [
            "python",
            "-m",
            "src.operations.verify_writer_capability_authorization_v1",
            "--capability",
            "public_price_snapshot",
            "--service",
            "synth-market-price-snapshot-writer.service",
            "--checkout-path",
            str(Path.cwd()),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 3
    assert "authorization_guard=fail_closed" in result.stdout


def test_guard_cli_rejects_authorization_file_override() -> None:
    # The removed --authorization-file override must not be accepted.
    result = subprocess.run(
        [
            "python", "-m", "src.operations.verify_writer_capability_authorization_v1",
            "--capability", "public_price_snapshot",
            "--service", "synth-market-price-snapshot-writer.service",
            "--checkout-path", str(Path.cwd()),
            "--authorization-file", "/tmp/whatever.json",
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "unrecognized arguments" in result.stderr or "authorization-file" in result.stderr


def test_preflight_strict_fails_on_required_warn_and_unverified() -> None:
    assert preflight._strict_exit_status(
        [preflight.CheckResult("warn_check", preflight.STATUS_WARN, "warn")]
    ) == 4
    assert preflight._strict_exit_status(
        [preflight.CheckResult("unknown_check", preflight.STATUS_UNVERIFIED, "unknown")]
    ) == 5


def test_preflight_cli_checks_expected_host_commit_and_blocks_strict() -> None:
    head = subprocess.check_output(["git", "rev-parse", "--verify", "HEAD"], text=True).strip()
    result = subprocess.run(
        [
            "python",
            "-m",
            "src.operations.run_host_preflight_v1",
            "--capability",
            "public_price_snapshot",
            "--expected-host",
            "definitely-wrong-host",
            "--expected-commit",
            head,
            "--checkout-path",
            str(Path.cwd()),
            "--strict",
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 3
    payload = json.loads(result.stdout)
    host_check = next(check for check in payload["checks"] if check["name"] == "host_identity")
    assert host_check["status"] == "FAIL"


def test_preflight_uses_venv_python_for_capability_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], *, cwd: Path | None = None, timeout: int = 5) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(preflight, "_venv_python", lambda checkout_path: checkout_path / "venv/bin/python")
    monkeypatch.setattr(preflight, "_run", fake_run)
    result = preflight._capability_module_imports(Path.cwd(), "public_price_snapshot")
    assert result.status == preflight.STATUS_PASS
    assert calls
    assert calls[0][0].endswith("venv/bin/python")


def test_all_referenced_timer_service_wrapper_paths_exist() -> None:
    for cap in _capabilities():
        assert Path(cap["wrapper"]).exists(), cap["capability_id"]
        assert Path(cap["service"]).exists(), cap["capability_id"]
        assert Path(cap["timer"]).exists(), cap["capability_id"]
        for observed in cap["observed_runtime_state"]:
            assert Path(observed["unit_path"]).exists(), cap["capability_id"]


def test_all_systemd_trees_are_searched_and_duplicate_capability_units_fail(tmp_path: Path) -> None:
    registry = copy.deepcopy(_registry())
    duplicate = tmp_path / "docs/ops/systemd/duplicate-price.service"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text(
        "[Service]\nExecStart=/bin/bash scripts/run_market_price_snapshot_once.sh\n",
        encoding="utf-8",
    )
    for tree in ("deploy/systemd", "docs/ops/systemd", "scripts/odroid/systemd"):
        target = tmp_path / tree
        target.mkdir(parents=True, exist_ok=True)
    for cap in _capabilities(registry):
        for key in ("wrapper", "service", "timer"):
            source = Path(cap[key])
            target = tmp_path / source
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    errors = validate_registry_payload(registry, repo_root=tmp_path).errors
    assert any("duplicate or unexpected unit invocations" in err for err in errors)


def test_consumers_reporting_account_paths_invoke_zero_writer_capabilities() -> None:
    assert validate_registry_payload(_registry(), repo_root=Path.cwd()).ok


def test_contract_doc_contains_state_machine_and_installed_timer_warning() -> None:
    text = CONTRACT_DOC.read_text(encoding="utf-8")
    for marker in (
        "candidate_host",
        "selected_host",
        "acceptance_host",
        "production_runtime_owner",
        "runtime_lifecycle",
        "OBSERVED_LEGACY_RUNTIME_PENDING_CONTAINMENT",
        "An installed timer may continue running operationally",
        "record candidate/selected state without production authorization",
        "disable the old timer",
        "mark lifecycle `ACTIVE`",
    ):
        assert marker in text
