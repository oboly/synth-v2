"""
Tests for the writer-capability host-ownership correction.

These lock in the corrected contract:
- acceptance_host is never an implicit production_runtime_owner;
- exactly one production_runtime_owner per writer capability;
- consumers / reporting / account runtimes own zero writer capabilities;
- no duplicate writer timers or repair paths;
- the Native SHORT 4h chain is evaluated separately from the DB writers;
- owner identities are host-independent (no host name encoded);
- the read-only host preflight runner performs no forbidden coupling.

Sources of truth:
    deploy/ownership/writer_capability_ownership_v1.json
    docs/ops/writer_capability_host_ownership_contract_v1.md
    src/operations/run_host_preflight_v1.py
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

REGISTRY_PATH = Path("deploy/ownership/writer_capability_ownership_v1.json")
CONTRACT_DOC = Path("docs/ops/writer_capability_host_ownership_contract_v1.md")
PREFLIGHT = Path("src/operations/run_host_preflight_v1.py")

HOST_NAMES = ("devlap", "odroid", "gurkdb", "gurkDB", "theone")
UNASSIGNED = "UNASSIGNED"


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _capabilities() -> list[dict]:
    return _registry()["writer_capabilities"]


def _executable_lines(path: Path) -> str:
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def test_registry_parses_and_declares_invariants() -> None:
    reg = _registry()
    inv = reg["invariants"]
    assert inv["acceptance_host_is_not_production_owner"] is True
    assert inv["exactly_one_production_owner_per_capability"] is True
    assert inv["production_owner_requires_separate_decision_evidence"] is True
    assert inv["acceptance_evidence_cannot_satisfy_production_decision"] is True
    assert inv["historical_runtime_assignment_is_not_active_ownership"] is True
    assert inv["owner_identity_is_host_independent"] is True
    assert inv["consumers_reporting_account_runtimes_own_zero_writer_capabilities"] is True
    assert inv["all_production_runtime_owners_unassigned_by_this_correction"] is True
    # No host is canonized as a proven owner by this correction.
    assert reg["host_status"] == {
        "gurkdb": "UNVERIFIED",
        "devlap": "UNVERIFIED",
        "odroid": "UNVERIFIED",
    }


def test_acceptance_host_is_not_implicitly_production_owner() -> None:
    for cap in _capabilities():
        owner = cap["production_runtime_owner"]
        evidence = cap["production_decision_evidence"]
        if owner == UNASSIGNED:
            # An unassigned capability may still name an acceptance host, but
            # must never carry production ownership without a decision.
            assert evidence == "", cap["capability_id"]
        else:
            # Production ownership requires separate, recorded decision evidence;
            # acceptance placement alone can never canonize it.
            assert evidence.strip(), cap["capability_id"]


def test_all_four_production_owners_are_unassigned_by_this_correction() -> None:
    # Required outcome: no capability carries a production_runtime_owner in this
    # correction PR — including market_rotation_pressure.
    ids = {cap["capability_id"] for cap in _capabilities()}
    assert ids == {
        "public_price_snapshot",
        "public_candle_freshness",
        "market_rotation_pressure",
        "native_short_4h_chain",
    }
    for cap in _capabilities():
        assert cap["production_runtime_owner"] == UNASSIGNED, cap["capability_id"]
        assert cap["production_owner_status"] == UNASSIGNED, cap["capability_id"]


def test_no_capability_has_a_production_owner_status_of_accepted() -> None:
    # Acceptance never becomes a production authorization state.
    for cap in _capabilities():
        assert cap["production_owner_status"] != "ACCEPTED", cap["capability_id"]


def test_only_rotation_pressure_has_a_recorded_host_acceptance() -> None:
    # Acceptance (distinct from production ownership) is recorded only for
    # rotation-pressure, on devlap.
    accepted = [
        cap["capability_id"]
        for cap in _capabilities()
        if cap["acceptance_status"] == "ACCEPTED"
    ]
    assert accepted == ["market_rotation_pressure"]


def test_accepted_acceptance_host_coexists_with_unassigned_production_owner() -> None:
    # Requirement 1: an accepted acceptance_host=devlap must coexist with
    # production_runtime_owner=UNASSIGNED.
    caps = {cap["capability_id"]: cap for cap in _capabilities()}
    rp = caps["market_rotation_pressure"]
    assert rp["acceptance_host"] == "devlap"
    assert rp["acceptance_status"] == "ACCEPTED"
    assert rp["production_runtime_owner"] == UNASSIGNED
    assert rp["production_owner_status"] == UNASSIGNED


def test_acceptance_evidence_cannot_satisfy_production_decision_evidence() -> None:
    # Requirement 2: no capability may use acceptance / prior-runtime evidence
    # as its production_decision_evidence. Because every owner is UNASSIGNED, the
    # decision evidence must be empty for all, and acceptance evidence lives only
    # in the historical assignment, never in production_decision_evidence.
    for cap in _capabilities():
        assert cap["production_decision_evidence"] == "", cap["capability_id"]
    rp = {c["capability_id"]: c for c in _capabilities()}["market_rotation_pressure"]
    hist = rp["historical_runtime_assignment"]
    # Acceptance evidence is preserved, but only inside the SUPERSEDED history.
    assert "PR #100" in hist["preserved_evidence"] or "PR #100" in hist["source"]
    assert "do NOT satisfy production_decision_evidence" in hist["preserved_evidence"]


def test_historical_runtime_assignment_does_not_grant_active_ownership() -> None:
    # Requirement 3: a historical assignment is SUPERSEDED context, not ownership.
    for cap in _capabilities():
        hist = cap.get("historical_runtime_assignment")
        if hist is None:
            continue
        assert hist["status"] == "SUPERSEDED", cap["capability_id"]
        assert hist["host"], cap["capability_id"]
        assert hist["reason"].strip(), cap["capability_id"]
        # A superseded prior host must not equal the current (absent) owner.
        assert cap["production_runtime_owner"] == UNASSIGNED, cap["capability_id"]


def test_exactly_one_production_owner_per_capability() -> None:
    for cap in _capabilities():
        owner = cap["production_runtime_owner"]
        # A single scalar owner, never a list, never comma-joined hosts.
        assert isinstance(owner, str)
        assert "," not in owner and " and " not in owner, cap["capability_id"]
    ids = [cap["capability_id"] for cap in _capabilities()]
    assert len(ids) == len(set(ids))


def test_owner_identities_are_host_independent() -> None:
    for cap in _capabilities():
        identity = cap["owner_identity"].lower()
        for host in HOST_NAMES:
            assert host.lower() not in identity, cap["capability_id"]


def test_native_short_4h_chain_is_evaluated_separately() -> None:
    caps = {cap["capability_id"]: cap for cap in _capabilities()}
    chain = caps["native_short_4h_chain"]
    assert chain["evaluated_separately"] is True
    assert chain["kind"] == "market_only_chain"
    assert chain["evaluated_separately_reason"].strip()
    # The light DB writers must not be flagged as chain-coupled.
    for other in ("public_price_snapshot", "public_candle_freshness"):
        assert caps[other]["evaluated_separately"] is False


def test_writer_capabilities_have_no_account_or_reporting_coupling() -> None:
    for cap in _capabilities():
        assert cap["account_or_reporting_coupling"] is False, cap["capability_id"]


def test_consumers_own_zero_writer_capabilities() -> None:
    reg = _registry()
    forbidden = tuple(reg["forbidden_writer_invocation_tokens"])
    for rel in reg["consumers_with_zero_writer_capabilities"]:
        path = Path(rel)
        assert path.exists(), rel
        executable = _executable_lines(path)
        for token in forbidden:
            assert token not in executable, f"{rel} invokes forbidden writer token {token}"


def test_no_duplicate_writer_timers() -> None:
    unit_targets: dict[str, list[str]] = {}
    for timer in Path("deploy/systemd").glob("*.timer"):
        for line in timer.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*Unit=(\S+)", line)
            if m:
                unit_targets.setdefault(m.group(1), []).append(timer.name)
    for unit, timers in unit_targets.items():
        assert len(timers) == 1, f"{unit} is driven by duplicate timers {timers}"


def test_retired_odroid_writer_units_do_not_exist() -> None:
    assert not Path("scripts/odroid/systemd/synth-market-candle-freshness.service").exists()
    assert not Path("scripts/odroid/systemd/synth-market-candle-freshness.timer").exists()


def test_registry_wrapper_and_unit_paths_exist() -> None:
    for cap in _capabilities():
        assert Path(cap["wrapper"]).exists(), cap["capability_id"]
        service = cap["service"]
        if service and service.startswith("deploy/systemd/"):
            assert Path(service).exists(), cap["capability_id"]


def test_contract_doc_has_required_sections() -> None:
    text = CONTRACT_DOC.read_text(encoding="utf-8")
    for marker in (
        "acceptance_host",
        "production_runtime_owner",
        "writer_capability",
        "host_preflight",
        "runtime_acceptance",
        "## Acceptance procedure",
        "## Cutover procedure",
        "## Rollback procedure",
        "## Host-selection contract",
        "## Host preflight contract",
        "historical correction",
    ):
        assert marker in text, marker
    # gurkDB documented as a candidate, not a proven owner (whitespace-normalized
    # so the assertion is insensitive to line wrapping / markdown emphasis).
    normalized = re.sub(r"[\s*]+", " ", text)
    assert "preferred candidate, not a proven owner" in normalized
    assert "devlap acceptance" in normalized


def test_preflight_runner_has_no_forbidden_layer_imports() -> None:
    forbidden = (
        "src.account",
        "src.reporting",
        "src.decision_gate",
        "src.execution_planner",
        "src.executor",
        "src.broker",
        "src.market_data",
        "src.etl",
    )
    tree = ast.parse(PREFLIGHT.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not any(name.startswith(forbidden) for name in imported), imported


def test_preflight_runner_is_read_only_and_covers_full_checklist() -> None:
    text = PREFLIGHT.read_text(encoding="utf-8")
    for marker in ("host_mutations=0", "database_writes=0", "writer_invocations=0"):
        assert marker in text
    for check in (
        "host_identity",
        "os_and_architecture",
        "cpu_and_load",
        "ram_and_swap",
        "disk_space_and_inodes",
        "python_and_virtualenv",
        "mariadb_connectivity",
        "exchange_api_connectivity",
        "systemd",
        "rollback_capability",
    ):
        assert check in text, check
