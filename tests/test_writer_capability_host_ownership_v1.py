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
NATIVE_SHORT_PREFLIGHT_DOC = Path(
    "docs/ops/native_short_4h_chain_ownership_preflight_v1.md"
)
UNASSIGNED = "UNASSIGNED"


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _capabilities(registry: dict | None = None) -> list[dict]:
    return (registry or _registry())["capabilities"]


def _cap(registry: dict, capability_id: str) -> dict:
    return next(cap for cap in registry["capabilities"] if cap["capability_id"] == capability_id)


def _errors(registry: dict) -> list[str]:
    return validate_registry_payload(registry, repo_root=Path.cwd()).errors


def _valid_active_registry(capability_id: str = "public_price_snapshot") -> dict:
    registry = copy.deepcopy(_registry())
    cap = _cap(registry, capability_id)
    cap["runtime_lifecycle"] = "ACTIVE"
    cap["observed_runtime_state"] = [
        observation
        for observation in cap["observed_runtime_state"]
        if observation["authorization_status"] == "AUTHORIZED"
        and observation["current_state"] == "ACTIVE_OBSERVED"
    ]
    return registry


def _valid_authorized_inactive_registry() -> dict:
    registry = copy.deepcopy(_registry())
    cap = _cap(registry, "public_price_snapshot")
    cap["runtime_lifecycle"] = "AUTHORIZED_INACTIVE"
    cap["observed_runtime_state"] = [
        observation
        for observation in cap["observed_runtime_state"]
        if observation["current_state"] == "INACTIVE_VERIFIED"
    ]
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
    assert inv[
        "production_authorized_lifecycle_requires_acceptance_and_production_decision_evidence"
    ] is True
    assert "authorized_inactive_owner_requires_acceptance_and_production_decision_evidence" not in inv


def test_public_price_and_candle_are_active() -> None:
    ids = {cap["capability_id"] for cap in _capabilities()}
    assert ids == {
        "public_price_snapshot",
        "public_candle_freshness",
        "market_rotation_pressure",
        "native_short_4h_chain",
        "sector_rotation_snapshot",
    }
    price = _cap(_registry(), "public_price_snapshot")
    assert price["candidate_host"] == "gurkdb"
    assert price["selected_host"] == "gurkdb"
    assert price["acceptance_host"] == "gurkdb"
    assert price["acceptance_status"] == "ACCEPTED"
    assert price["production_runtime_owner"] == "gurkdb"
    assert price["production_authorization_status"] == "AUTHORIZED"
    assert price["runtime_lifecycle"] == "ACTIVE"
    assert price["production_decision_evidence"]

    # Only the separately authorized public writers have production ownership.
    for cap in _capabilities():
        if cap["capability_id"] == "public_price_snapshot":
            continue
        if cap["capability_id"] == "public_candle_freshness":
            assert cap["selected_host"] == "gurkdb"
            assert cap["acceptance_host"] == "gurkdb"
            assert cap["acceptance_status"] == "ACCEPTED"
            assert cap["acceptance_evidence"]
            assert cap["production_runtime_owner"] == "gurkdb"
            assert cap["production_authorization_status"] == "AUTHORIZED"
            assert cap["runtime_lifecycle"] == "ACTIVE"
            assert cap["production_decision_evidence"]
        elif cap["capability_id"] == "market_rotation_pressure":
            assert cap["selected_host"] == "gurkdb", cap["capability_id"]
            assert cap["acceptance_host"] == "gurkdb"
            assert cap["acceptance_status"] == "ACCEPTED"
            assert cap["acceptance_evidence"]
            assert cap["production_runtime_owner"] == "gurkdb"
            assert cap["production_authorization_status"] == "AUTHORIZED"
            assert cap["runtime_lifecycle"] == "ACTIVE", cap["capability_id"]
            assert cap["production_decision_evidence"]
        elif cap["capability_id"] == "sector_rotation_snapshot":
            assert cap["candidate_host"] == "gurkdb"
            assert cap["selected_host"] == "gurkdb"
            assert cap["acceptance_host"] == "gurkdb"
            assert cap["acceptance_status"] == "ACCEPTED"
            assert cap["acceptance_evidence"]
            assert cap["production_runtime_owner"] == "gurkdb"
            assert cap["production_decision_evidence"]
            assert cap["runtime_lifecycle"] == "AUTHORIZED_INACTIVE", cap["capability_id"]
            assert cap["production_authorization_status"] == "AUTHORIZED"
            assert cap["observed_runtime_state"] == []
            assert cap["historical_runtime_assignment"] is None
        else:
            assert cap["capability_id"] == "native_short_4h_chain"
            assert cap["candidate_host"] == "gurkdb"
            assert cap["selected_host"] == "gurkdb"
            assert cap["acceptance_host"] == "gurkdb"
            assert cap["acceptance_status"] == "ACCEPTED"
            assert cap["production_runtime_owner"] == "gurkdb"
            assert cap["production_authorization_status"] == "AUTHORIZED"
            assert cap["runtime_lifecycle"] == "AUTHORIZED_INACTIVE"
            assert cap["production_decision_evidence"]


def test_public_price_observations_preserve_inactive_and_append_active() -> None:
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
        },
        {
            "host": "gurkdb",
            "unit": "synth-market-price-snapshot-writer.timer",
            "unit_path": "deploy/systemd/synth-market-price-snapshot-writer.timer",
            "installed_at_observation": True,
            "enabled_at_observation": True,
            "active_at_observation": True,
            "observed_at_utc": "2026-07-22T12:10:15Z",
            "observed_at_precision": "exact",
            "current_state": "ACTIVE_OBSERVED",
            "authorization_status": "AUTHORIZED",
            "runtime_state_classification": "AUTHORIZED_RUNTIME_OBSERVED",
            "evidence_source": "docs/ops/public_price_snapshot_gurkdb_host_acceptance_20260721.md#scheduled-production-activation-proof-20260722",
        }
    ]


def test_candle_freshness_observed_active_runtime_is_recorded() -> None:
    candle = _cap(_registry(), "public_candle_freshness")
    assert candle["observed_runtime_state"] == [
        {
            "host": "gurkdb",
            "unit": "synth-market-candle-freshness-writer.timer",
            "unit_path": "deploy/systemd/synth-market-candle-freshness-writer.timer",
            "installed_at_observation": True,
            "enabled_at_observation": True,
            "active_at_observation": True,
            "observed_at_utc": "2026-08-10T18:32:25Z",
            "observed_at_precision": "exact",
            "current_state": "ACTIVE_OBSERVED",
            "authorization_status": "AUTHORIZED",
            "runtime_state_classification": "AUTHORIZED_RUNTIME_OBSERVED",
            "evidence_source": "docs/ops/public_candle_freshness_gurkdb_acceptance_20260723.md#gurkdb-activation-evidence-20260810",
        }
    ]


def test_rotation_pressure_acceptance_and_observed_legacy_runtime_are_preserved() -> None:
    rp = _cap(_registry(), "market_rotation_pressure")
    assert rp["acceptance_host"] == "gurkdb"
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
        },
        {
            "host": "gurkdb",
            "unit": "synth-market-rotation-pressure-writer.timer",
            "unit_path": "deploy/systemd/synth-market-rotation-pressure-writer.timer",
            "installed_at_observation": True,
            "enabled_at_observation": True,
            "active_at_observation": True,
            "observed_at_utc": "2026-08-08T12:20:26Z",
            "observed_at_precision": "exact",
            "current_state": "ACTIVE_OBSERVED",
            "authorization_status": "AUTHORIZED",
            "runtime_state_classification": "AUTHORIZED_RUNTIME_OBSERVED",
            "evidence_source": "docs/ops/market_rotation_pressure_gurkdb_acceptance_20260808.md#gurkdb-activation-evidence-20260808",
        },
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


def test_valid_authorized_inactive_state_passes() -> None:
    result = validate_registry_payload(
        _valid_authorized_inactive_registry(), repo_root=Path.cwd()
    )
    assert result.ok, result.errors


def test_authorized_inactive_requires_matching_accepted_host() -> None:
    registry = _valid_authorized_inactive_registry()
    cap = _cap(registry, "public_price_snapshot")
    cap["acceptance_status"] = "PENDING"
    cap["acceptance_evidence"] = None
    assert any(
        "lifecycle AUTHORIZED_INACTIVE requires acceptance_status=ACCEPTED" in err
        for err in _errors(registry)
    )

    cap["acceptance_status"] = "ACCEPTED"
    cap["acceptance_evidence"] = _cap(_registry(), "public_price_snapshot")["acceptance_evidence"]
    cap["acceptance_host"] = "devlap"
    assert any(
        "lifecycle AUTHORIZED_INACTIVE requires acceptance_host=production_runtime_owner" in err
        for err in _errors(registry)
    )


def test_authorized_inactive_rejects_authorized_active_observation() -> None:
    registry = _valid_active_registry()
    cap = _cap(registry, "public_price_snapshot")
    cap["runtime_lifecycle"] = "AUTHORIZED_INACTIVE"
    assert any(
        "AUTHORIZED_INACTIVE requires no authorized observed active runtime" in err
        for err in _errors(registry)
    )


def test_active_missing_acceptance_is_rejected() -> None:
    registry = _valid_active_registry()
    cap = _cap(registry, "public_price_snapshot")
    cap["acceptance_status"] = "UNASSIGNED"
    cap["acceptance_host"] = UNASSIGNED
    cap["acceptance_evidence"] = None
    assert any(
        "lifecycle ACTIVE requires acceptance_status=ACCEPTED" in err
        for err in _errors(registry)
    )


def test_active_null_acceptance_evidence_is_rejected() -> None:
    registry = _valid_active_registry()
    _cap(registry, "public_price_snapshot")["acceptance_evidence"] = None
    assert any(
        "lifecycle ACTIVE requires structured acceptance_evidence" in err
        for err in _errors(registry)
    )


def test_active_wrong_acceptance_host_is_rejected() -> None:
    registry = _valid_active_registry()
    _cap(registry, "public_price_snapshot")["acceptance_host"] = "devlap"
    assert any(
        "lifecycle ACTIVE requires acceptance_host=production_runtime_owner" in err
        for err in _errors(registry)
    )


def test_active_wrong_selected_host_is_rejected() -> None:
    registry = _valid_active_registry()
    _cap(registry, "public_price_snapshot")["selected_host"] = "devlap"
    assert any(
        "lifecycle ACTIVE requires selected_host=production_runtime_owner" in err
        for err in _errors(registry)
    )


def test_active_wrong_observation_host_is_rejected() -> None:
    registry = _valid_active_registry()
    _cap(registry, "public_price_snapshot")["observed_runtime_state"][0]["host"] = "devlap"
    errors = _errors(registry)
    assert any("observed AUTHORIZED host must equal production_runtime_owner" in err for err in errors)
    assert any(
        "ACTIVE requires an authorized observed active runtime for production_runtime_owner" in err
        for err in errors
    )


def test_active_without_authorized_active_observation_is_rejected() -> None:
    registry = _valid_active_registry()
    observation = _cap(registry, "public_price_snapshot")["observed_runtime_state"][0]
    observation["authorization_status"] = UNASSIGNED
    observation["current_state"] = "INACTIVE_VERIFIED"
    observation["active_at_observation"] = False
    observation["enabled_at_observation"] = False
    observation["runtime_state_classification"] = "NONE_OBSERVED"
    assert any(
        "ACTIVE requires an authorized observed active runtime for production_runtime_owner" in err
        for err in _errors(registry)
    )


def test_valid_active_state_passes() -> None:
    result = validate_registry_payload(_valid_active_registry(), repo_root=Path.cwd())
    assert result.ok, result.errors


def test_independent_review_active_without_acceptance_reproducer_fails_closed() -> None:
    registry = _valid_active_registry()
    cap = _cap(registry, "public_price_snapshot")
    cap["production_runtime_owner"] = "gurkdb"
    cap["production_authorization_status"] = "AUTHORIZED"
    cap["production_decision_evidence"] = (
        "docs/ops/public_price_snapshot_gurkdb_host_acceptance_20260721.md#production-decision-evidence"
    )
    cap["acceptance_status"] = "UNASSIGNED"
    cap["acceptance_host"] = UNASSIGNED
    cap["acceptance_evidence"] = None

    result = validate_registry_payload(registry, repo_root=Path.cwd())

    assert not result.ok
    assert len(result.errors) >= 1
    assert any(
        "lifecycle ACTIVE requires acceptance_status=ACCEPTED" in err
        for err in result.errors
    )


def test_multiple_active_authorized_runtime_observations_are_rejected() -> None:
    registry = _valid_active_registry()
    cap = _cap(registry, "public_price_snapshot")
    active = cap["observed_runtime_state"][0]
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


def test_native_short_owner_is_authorized_inactive_on_gurkdb_with_closed_scope_boundaries() -> None:
    registry = _registry()
    native = _cap(registry, "native_short_4h_chain")
    contract = NATIVE_SHORT_PREFLIGHT_DOC.read_text(encoding="utf-8")

    assert native["candidate_host"] == "gurkdb"
    assert native["selected_host"] == "gurkdb"
    assert native["acceptance_host"] == "gurkdb"
    assert native["acceptance_status"] == "ACCEPTED"
    assert native["production_runtime_owner"] == "gurkdb"
    assert native["production_authorization_status"] == "AUTHORIZED"
    assert native["runtime_lifecycle"] == "AUTHORIZED_INACTIVE"
    assert native["authorization_guard"]["authorization_file"] == (
        "/etc/synth/writer-capability-native-short-4h-chain-authorization-v1.json"
    )
    assert "canonical_owner=gurkdb" in contract
    assert "publication_host must equal writer_host" in contract
    assert "scope=BTC_ONLY, PAPER execution mode only" in contract
    assert "live_trading=NOT_GRANTED" in contract
    assert "multi_asset_promotion=0" in contract
    for blocker in (
        "DB_CONNECTIVITY_PROOF_MISSING",
        "DB_WRITER_AUTHORITY_PROOF_MISSING",
        "PUBLICATION_PATH_OWNERSHIP_PROOF_MISSING",
        "EXACT_INSTALLED_UNIT_EQUIVALENCE_MISSING",
        "ALL_HOST_SCHEDULER_INVENTORY_MISSING",
        "ROLLBACK_PROOF_MISSING",
        "WRITER_PUBLICATION_COLOCATION_PROOF_MISSING",
    ):
        assert blocker in contract


def test_native_short_preflight_names_one_repository_scheduler_and_retired_legacy_pair() -> None:
    contract = NATIVE_SHORT_PREFLIGHT_DOC.read_text(encoding="utf-8")
    service = Path("deploy/systemd/synth-chain-4h.service").read_text(encoding="utf-8")
    timer = Path("deploy/systemd/synth-chain-4h.timer").read_text(encoding="utf-8")
    legacy_service = Path(
        "docs/ops/systemd/synth-4h-market-chain.service"
    ).read_text(encoding="utf-8")
    legacy_timer = Path(
        "docs/ops/systemd/synth-4h-market-chain.timer"
    ).read_text(encoding="utf-8")

    assert "ConditionHost=gurkdb" in service
    assert "User=gurk" in service
    assert "Group=gurk" in service
    assert "WorkingDirectory=/home/gurk/projects/synth-v2" in service
    assert "ConditionHost=gurkdb" in timer
    assert timer.count("Unit=synth-chain-4h.service") == 1
    assert "deploy/systemd/synth-chain-4h.timer" in contract
    assert "deploy/systemd/synth-chain-4h.service" in contract
    assert "No publication timer is permitted." in contract
    assert "RefuseManualStart=yes" in legacy_service
    assert "RefuseManualStart=yes" in legacy_timer
    assert "scripts/run_chain_4h.sh" not in legacy_service
    assert "OnCalendar=" not in legacy_timer


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


def test_sector_rotation_snapshot_wrong_capability_identity_fails() -> None:
    registry = copy.deepcopy(_registry())
    _cap(registry, "sector_rotation_snapshot")["capability_identity"] = "wrong-identity"
    assert any(
        "capability_identity must be 'sector-rotation-snapshot-writer'" in err
        for err in _errors(registry)
    )


def test_sector_rotation_snapshot_missing_capability_fails() -> None:
    registry = copy.deepcopy(_registry())
    registry["capabilities"] = [
        cap for cap in registry["capabilities"] if cap["capability_id"] != "sector_rotation_snapshot"
    ]
    assert any("must contain exactly" in err for err in _errors(registry))


def test_sector_rotation_snapshot_duplicate_capability_fails() -> None:
    registry = copy.deepcopy(_registry())
    registry["capabilities"].append(copy.deepcopy(_cap(registry, "sector_rotation_snapshot")))
    assert any("duplicate capability_id" in err for err in _errors(registry))


def test_sector_rotation_snapshot_unknown_capability_id_fails() -> None:
    registry = copy.deepcopy(_registry())
    _cap(registry, "sector_rotation_snapshot")["capability_id"] = "sector_rotation_snapshot_v2"
    errors = _errors(registry)
    assert any("invalid capability_id" in err for err in errors)
    assert any("must contain exactly" in err for err in errors)


def test_sector_rotation_snapshot_database_writes_exactly_one_table() -> None:
    cap = _cap(_registry(), "sector_rotation_snapshot")
    assert cap["database_writes"] == ["sector_rotation_snapshot"]


def test_sector_rotation_snapshot_wrapper_and_module_are_forbidden_consumer_tokens() -> None:
    registry = _registry()
    assert "scripts/run_sector_rotation_engine_once.sh" in registry["forbidden_writer_invocation_tokens"]
    assert "src.research.run_sector_rotation_engine_v1" in registry["forbidden_writer_invocation_tokens"]


def test_sector_rotation_snapshot_production_verifier_denies_execution() -> None:
    # Registry ownership is now AUTHORIZED_INACTIVE, but the host-local
    # production authorization file is deliberately absent until a separate,
    # explicitly authorized cutover step installs it.
    decision = verify_writer_execution_authorization(
        capability_id="sector_rotation_snapshot",
        mode=ExecutionMode.PRODUCTION,
        repo_root=Path.cwd(),
        checkout_path=Path.cwd(),
    )
    assert not decision.allowed


def test_existing_four_capabilities_unchanged_by_sector_rotation_onboarding() -> None:
    registry = _registry()
    price = _cap(registry, "public_price_snapshot")
    assert price["runtime_lifecycle"] == "ACTIVE"
    assert price["production_authorization_status"] == "AUTHORIZED"
    candle = _cap(registry, "public_candle_freshness")
    assert candle["runtime_lifecycle"] == "ACTIVE"
    assert candle["production_authorization_status"] == "AUTHORIZED"
    rotation_pressure = _cap(registry, "market_rotation_pressure")
    assert rotation_pressure["runtime_lifecycle"] == "ACTIVE"
    assert rotation_pressure["production_runtime_owner"] == "gurkdb"
    native_short = _cap(registry, "native_short_4h_chain")
    assert native_short["production_authorization_status"] == "AUTHORIZED"
    assert native_short["runtime_lifecycle"] == "AUTHORIZED_INACTIVE"


def test_contract_doc_contains_state_machine_and_installed_timer_warning() -> None:
    text = CONTRACT_DOC.read_text(encoding="utf-8")
    for marker in (
        "candidate_host",
        "selected_host",
        "acceptance_host",
        "production_runtime_owner",
        "runtime_lifecycle",
        "production_authorized_lifecycle_requires_acceptance_and_production_decision_evidence",
        "OBSERVED_LEGACY_RUNTIME_PENDING_CONTAINMENT",
        "An installed timer may continue running operationally",
        "record candidate/selected state without production authorization",
        "disable the old timer",
        "mark lifecycle `ACTIVE`",
    ):
        assert marker in text
    assert "authorized_inactive_owner_requires_acceptance_and_production_decision_evidence" not in text
