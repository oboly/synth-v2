"""
validate_writer_capability_ownership_v1

Read-only structural and semantic validation for the writer-capability host
ownership registry.

Safety boundary:
- reads only repository files supplied by path
- no host mutation, no systemctl mutation, no writer invocation
- no database, broker, reporting, decision_gate, execution_planner, or executor

host_mutations=0 database_writes=0 writer_invocations=0 systemctl_mutations=0
broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0
decision_gate=none execution_planner=none executor=none
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


REGISTRY_PATH = Path("deploy/ownership/writer_capability_ownership_v1.json")
SCHEMA_PATH = Path("deploy/ownership/writer_capability_ownership_v1.schema.json")

EXPECTED_CAPABILITY_IDS = {
    "public_price_snapshot",
    "public_candle_freshness",
    "market_rotation_pressure",
    "native_short_4h_chain",
}
CAPABILITY_IDENTITY = {
    "public_price_snapshot": "public-price-snapshot-writer",
    "public_candle_freshness": "public-candle-freshness-writer",
    "market_rotation_pressure": "market-rotation-pressure-writer",
    "native_short_4h_chain": "native-short-4h-chain",
}
_RFC3339_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$"
)


def _valid_literal_utc(value: Any) -> bool:
    """Canonical literal-Z shape AND a real calendar date/time.

    Rejects timezone offsets, timezone-less values, and impossible dates such as
    2026-02-31 while accepting valid leap days such as 2024-02-29.
    """
    if not isinstance(value, str) or not _RFC3339_RE.match(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True
ALLOWED_ADDITIONAL_WRITER_CLASSIFICATIONS = {
    "shared_market_only_chain",
    "read_only_caller",
    "retired_obsolete_path",
    "architectural_violation_removed",
}
REMOVED_PATH_CLASSIFICATIONS = {"retired_obsolete_path", "architectural_violation_removed"}
UNASSIGNED = "UNASSIGNED"
AUTHORIZATION_REQUIRED_LIFECYCLES = {"AUTHORIZED_INACTIVE", "ACTIVE"}
NO_AUTHORIZATION_LIFECYCLES = {
    "UNASSIGNED",
    "SELECTED_PENDING_PREFLIGHT",
    "PREFLIGHT_PASSED",
    "ACCEPTED_PENDING_CUTOVER",
    "SUPERSEDED",
}
REQUIRED_INVARIANTS = {
    "at_most_one_authorized_active_owner_per_capability",
    "exactly_one_authorized_active_owner_required_when_lifecycle_active",
    "unassigned_capability_must_have_zero_authorized_owners",
    "historical_or_observed_runtime_state_does_not_grant_authorization",
    "acceptance_does_not_grant_production_authorization",
    "consumers_reporting_account_runtimes_own_zero_writer_capabilities",
    "all_production_runtime_owners_unassigned_by_this_correction",
}
AUTHORIZATION_GUARD_MODULE = "src.operations.verify_writer_capability_authorization_v1"
REQUIRED_NATIVE_SHORT_WRITES = {
    "native_short_scope_status",
    "native_short_map_status",
    "feat_candle",
    "signal_engine_state",
    "advice_state",
    "ranking_state",
    "asset_interval_quality_snapshot",
    "selection_state",
    "execution_zone_context",
    "trade_setup_filter_observation",
    "trade_setup_filter_policy_preview",
    "paper_advice_observation",
    "strategy_runtime_snapshot",
}
REQUIRED_NATIVE_SHORT_MODULES = {
    "src.market_data.native_short_repository_source_identity_v1",
    "src.operations.run_persisted_market_price_freshness_v1",
    "src.operations.run_persisted_market_candle_freshness_v1",
    "src.market_data.run_native_short_scope_status_chain_v1",
    "src.market_data.run_native_short_fib_context_snapshot_v1",
    "src.features.run_feat_candle",
    "src.signal_engine.run_signal_state_etl",
    "src.advice.run_advice_engine",
    "src.ranking.run_ranking_engine",
    "src.measurement.run_asset_interval_quality_snapshot",
    "src.selection.run_selection_engine_v2",
    "src.zone.run_zone_engine_v1",
    "src.trade_setup_filter.run_trade_setup_filter_v1",
    "src.research.run_trade_setup_filter_policy_preview_v1",
    "src.advice.run_paper_advice_policy_v1",
    "src.strategy_runtime.run_strategy_runtime_snapshot",
}
SYSTEMD_TREES = (
    Path("deploy/systemd"),
    Path("docs/ops/systemd"),
    Path("scripts/odroid/systemd"),
)


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


class RegistryValidationError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryValidationError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RegistryValidationError(f"{path}: root must be an object")
    return payload


def _ensure_keys(
    obj: dict[str, Any],
    required: set[str],
    allowed: set[str],
    label: str,
    errors: list[str],
) -> None:
    missing = sorted(required - set(obj))
    extra = sorted(set(obj) - allowed)
    if missing:
        errors.append(f"{label}: missing required fields {missing}")
    if extra:
        errors.append(f"{label}: unknown fields {extra}")


def _enum_values(registry: dict[str, Any], enum_name: str) -> set[str]:
    values = registry.get("enums", {}).get(enum_name, [])
    return set(values) if isinstance(values, list) else set()


def _is_repo_relative(path: str) -> bool:
    return bool(path) and not path.startswith("/") and ".." not in Path(path).parts


def _path_exists(repo_root: Path, rel: str) -> bool:
    return _is_repo_relative(rel) and (repo_root / rel).exists()


def _unit_directive_values(path: Path, key: str) -> list[str]:
    values: list[str] = []
    current_section = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1]
            continue
        if current_section and "=" in line:
            directive, _, value = line.partition("=")
            if directive.strip() == key:
                values.append(value.strip())
    return values


def _unit_non_comment_text(path: Path) -> str:
    lines = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and not line.startswith(";"):
            lines.append(line)
    return "\n".join(lines)


def _all_unit_files(repo_root: Path) -> list[Path]:
    paths: list[Path] = []
    for tree in SYSTEMD_TREES:
        root = repo_root / tree
        if root.exists():
            paths.extend(sorted(root.glob("*.service")))
            paths.extend(sorted(root.glob("*.timer")))
    return paths


def validate_registry_payload(
    registry: dict[str, Any],
    *,
    repo_root: Path | None = None,
) -> ValidationResult:
    repo = repo_root or Path.cwd()
    errors: list[str] = []
    warnings: list[str] = []

    root_required = {
        "schema_version",
        "contract_version",
        "purpose",
        "authoritative_doc",
        "schema",
        "invariants",
        "enums",
        "host_status",
        "candidate_topology",
        "capabilities",
        "consumers_with_zero_writer_capabilities",
        "forbidden_writer_invocation_tokens",
        "forbidden_account_execution_tokens",
        "call_graph_scan_trees",
        "additional_writer_paths",
        "market_only_processing_chains_with_zero_public_writers",
    }
    _ensure_keys(registry, root_required, root_required, "registry", errors)

    if registry.get("schema_version") != "writer_capability_ownership_schema_v1":
        errors.append("registry.schema_version must be writer_capability_ownership_schema_v1")
    if registry.get("contract_version") != "v1":
        errors.append("registry.contract_version must be v1")
    if registry.get("schema") != str(SCHEMA_PATH):
        errors.append(f"registry.schema must be {SCHEMA_PATH}")

    invariants = registry.get("invariants")
    if not isinstance(invariants, dict):
        errors.append("registry.invariants must be an object")
    else:
        for key in REQUIRED_INVARIANTS:
            if invariants.get(key) is not True:
                errors.append(f"registry.invariants.{key} must be true")
        if "exactly_one_production_owner_per_capability" in invariants:
            errors.append("obsolete invariant exactly_one_production_owner_per_capability is forbidden")

    host_ids = _enum_values(registry, "host_id")
    acceptance_statuses = _enum_values(registry, "acceptance_status")
    auth_statuses = _enum_values(registry, "production_authorization_status")
    lifecycles = _enum_values(registry, "runtime_lifecycle")
    observed_states = _enum_values(registry, "observed_current_state")
    observed_auth_statuses = _enum_values(registry, "observed_authorization_status")
    observed_classes = _enum_values(registry, "observed_runtime_classification")
    historical_statuses = _enum_values(registry, "historical_assignment_status")
    if not {"devlap", "gurkdb", "odroid", UNASSIGNED}.issubset(host_ids):
        errors.append("enums.host_id must include devlap, gurkdb, odroid, UNASSIGNED")

    capabilities = registry.get("capabilities")
    if not isinstance(capabilities, list):
        errors.append("registry.capabilities must be a list")
        return ValidationResult(errors, warnings)

    ids: list[str] = []
    active_observations: dict[str, list[str]] = {}
    service_by_capability: dict[str, str] = {}
    module_token_by_capability: dict[str, set[str]] = {}

    capability_required = {
        "capability_id",
        "kind",
        "capability_identity",
        "wrapper",
        "service",
        "timer",
        "systemd_unit",
        "timer_unit",
        "committed_unit_binding",
        "authorization_guard",
        "lock",
        "cadence",
        "database_writes",
        "artifact_publications",
        "status_publications",
        "downstream_state_changes",
        "wrappers_invoked",
        "modules_invoked",
        "account_or_reporting_coupling",
        "evaluated_separately",
        "candidate_host",
        "selected_host",
        "acceptance_host",
        "acceptance_status",
        "acceptance_evidence",
        "production_runtime_owner",
        "production_authorization_status",
        "runtime_lifecycle",
        "production_decision_evidence",
        "observed_runtime_state",
        "historical_runtime_assignment",
    }
    capability_allowed = capability_required | {"evaluated_separately_reason", "intervals"}

    for cap in capabilities:
        if not isinstance(cap, dict):
            errors.append("capability entry must be an object")
            continue
        cap_id = str(cap.get("capability_id", ""))
        label = f"capability[{cap_id or '?'}]"
        _ensure_keys(cap, capability_required, capability_allowed, label, errors)
        ids.append(cap_id)

        if cap_id not in EXPECTED_CAPABILITY_IDS:
            errors.append(f"{label}: invalid capability_id")
        if cap_id in CAPABILITY_IDENTITY and cap.get("capability_identity") != CAPABILITY_IDENTITY[cap_id]:
            errors.append(
                f"{label}: capability_identity must be {CAPABILITY_IDENTITY[cap_id]!r} for {cap_id}"
            )
        if cap.get("kind") not in _enum_values(registry, "capability_kind"):
            errors.append(f"{label}: invalid kind {cap.get('kind')!r}")
        for field in ("candidate_host", "selected_host", "acceptance_host", "production_runtime_owner"):
            if cap.get(field) not in host_ids:
                errors.append(f"{label}: invalid {field} {cap.get(field)!r}")
        if cap.get("acceptance_status") not in acceptance_statuses:
            errors.append(f"{label}: invalid acceptance_status {cap.get('acceptance_status')!r}")
        if cap.get("production_authorization_status") not in auth_statuses:
            errors.append(
                f"{label}: invalid production_authorization_status "
                f"{cap.get('production_authorization_status')!r}"
            )
        if cap.get("runtime_lifecycle") not in lifecycles:
            errors.append(f"{label}: invalid runtime_lifecycle {cap.get('runtime_lifecycle')!r}")

        if cap.get("selected_host") != UNASSIGNED and cap.get("candidate_host") == UNASSIGNED:
            errors.append(f"{label}: selected_host requires a candidate_host")
        if cap.get("acceptance_status") == "ACCEPTED" and cap.get("acceptance_host") == UNASSIGNED:
            errors.append(f"{label}: ACCEPTED acceptance_status requires acceptance_host")

        acceptance_evidence = cap.get("acceptance_evidence")
        if cap.get("acceptance_status") == "ACCEPTED":
            if not isinstance(acceptance_evidence, dict):
                errors.append(f"{label}: ACCEPTED acceptance_status requires structured acceptance_evidence")
            else:
                for key in ("approval_reference", "evidence_doc", "accepted_at_utc", "scope"):
                    if not str(acceptance_evidence.get(key) or "").strip():
                        errors.append(f"{label}: acceptance_evidence.{key} is required and non-empty")
                accepted_at = str(acceptance_evidence.get("accepted_at_utc", ""))
                if not _valid_literal_utc(accepted_at):
                    errors.append(f"{label}: acceptance_evidence.accepted_at_utc must be RFC3339 UTC")
        elif acceptance_evidence is not None:
            errors.append(f"{label}: acceptance_evidence must be null unless acceptance_status is ACCEPTED")
        if cap.get("production_decision_evidence") and cap.get("production_runtime_owner") == UNASSIGNED:
            errors.append(f"{label}: unassigned production owner must not carry decision evidence")
        if cap.get("production_decision_evidence") and cap.get("production_decision_evidence") in {
            cap.get("acceptance_host"),
            cap.get("historical_runtime_assignment", {}).get("source")
            if isinstance(cap.get("historical_runtime_assignment"), dict)
            else None,
        }:
            errors.append(f"{label}: acceptance or historical evidence cannot authorize production")

        lifecycle = cap.get("runtime_lifecycle")
        owner = cap.get("production_runtime_owner")
        auth_status = cap.get("production_authorization_status")
        evidence = str(cap.get("production_decision_evidence") or "")
        if lifecycle in NO_AUTHORIZATION_LIFECYCLES:
            if owner != UNASSIGNED or auth_status == "AUTHORIZED":
                errors.append(f"{label}: lifecycle {lifecycle} must have zero authorized production owners")
        if lifecycle in AUTHORIZATION_REQUIRED_LIFECYCLES:
            if owner == UNASSIGNED:
                errors.append(f"{label}: lifecycle {lifecycle} requires exactly one production_runtime_owner")
            if auth_status != "AUTHORIZED":
                errors.append(f"{label}: lifecycle {lifecycle} requires production_authorization_status=AUTHORIZED")
            if not evidence.strip():
                errors.append(f"{label}: lifecycle {lifecycle} requires production_decision_evidence")
        if lifecycle == "ACTIVE":
            observed = cap.get("observed_runtime_state")
            if not isinstance(observed, list) or not any(
                item.get("authorization_status") == "AUTHORIZED"
                and item.get("current_state") == "ACTIVE_OBSERVED"
                for item in observed
                if isinstance(item, dict)
            ):
                errors.append(f"{label}: ACTIVE requires an authorized observed active runtime")

        for rel_field in ("wrapper", "service", "timer"):
            rel = cap.get(rel_field)
            if not isinstance(rel, str) or not _path_exists(repo, rel):
                errors.append(f"{label}: referenced {rel_field} path missing or invalid: {rel!r}")

        guard = cap.get("authorization_guard")
        if not isinstance(guard, dict):
            errors.append(f"{label}: authorization_guard must be an object")
        else:
            if guard.get("module") != AUTHORIZATION_GUARD_MODULE:
                errors.append(f"{label}: authorization_guard.module invalid")
            if guard.get("required") is not True:
                errors.append(f"{label}: authorization_guard.required must be true")

        binding = cap.get("committed_unit_binding")
        service_path = repo / str(cap.get("service"))
        if isinstance(binding, dict) and service_path.exists():
            condition_values = _unit_directive_values(service_path, "ConditionHost")
            if binding.get("host_bound_candidate_artifact") is not True:
                errors.append(f"{label}: committed unit binding must be explicitly host-bound")
            if binding.get("condition_host") not in condition_values:
                errors.append(f"{label}: service must contain ConditionHost={binding.get('condition_host')}")
            if binding.get("user") not in _unit_directive_values(service_path, "User"):
                errors.append(f"{label}: service User= does not match registry")
            if binding.get("working_directory") not in _unit_directive_values(service_path, "WorkingDirectory"):
                errors.append(f"{label}: service WorkingDirectory= does not match registry")
            exec_start_pre = "\n".join(_unit_directive_values(service_path, "ExecStartPre"))
            if AUTHORIZATION_GUARD_MODULE not in exec_start_pre:
                errors.append(f"{label}: service missing mandatory authorization guard ExecStartPre")

        lock = cap.get("lock")
        if not isinstance(lock, dict) or lock.get("scope") != "HOST_LOCAL":
            errors.append(f"{label}: lock must declare scope=HOST_LOCAL")

        observed_runtime = cap.get("observed_runtime_state")
        if not isinstance(observed_runtime, list):
            errors.append(f"{label}: observed_runtime_state must be a list")
        else:
            for idx, item in enumerate(observed_runtime):
                item_label = f"{label}.observed_runtime_state[{idx}]"
                if not isinstance(item, dict):
                    errors.append(f"{item_label}: must be an object")
                    continue
                item_required = {
                    "host",
                    "unit",
                    "unit_path",
                    "installed_at_observation",
                    "enabled_at_observation",
                    "active_at_observation",
                    "observed_at_utc",
                    "observed_at_precision",
                    "current_state",
                    "authorization_status",
                    "runtime_state_classification",
                    "evidence_source",
                }
                _ensure_keys(item, item_required, item_required, item_label, errors)
                if item.get("host") not in host_ids - {UNASSIGNED}:
                    errors.append(f"{item_label}: invalid host")
                if item.get("current_state") not in observed_states:
                    errors.append(f"{item_label}: invalid current_state")
                if item.get("authorization_status") not in observed_auth_statuses:
                    errors.append(f"{item_label}: invalid authorization_status")
                if item.get("runtime_state_classification") not in observed_classes:
                    errors.append(f"{item_label}: invalid runtime_state_classification")
                if not _path_exists(repo, str(item.get("unit_path", ""))):
                    errors.append(f"{item_label}: unit_path missing or invalid")
                if not _valid_literal_utc(item.get("observed_at_utc")):
                    errors.append(f"{item_label}: observed_at_utc must be RFC3339 UTC")
                if item.get("active_at_observation") is True and item.get("authorization_status") != "AUTHORIZED":
                    if item.get("runtime_state_classification") != "OBSERVED_LEGACY_RUNTIME_PENDING_CONTAINMENT":
                        errors.append(
                            f"{item_label}: observed active legacy runtime must be classified as pending containment"
                        )
                # An observed runtime may claim AUTHORIZED status only when the
                # capability itself canonically authorizes exactly that host.
                # Observation must never convert into authorization.
                if item.get("authorization_status") == "AUTHORIZED":
                    if owner == UNASSIGNED:
                        errors.append(
                            f"{item_label}: observed authorization_status=AUTHORIZED requires an assigned production owner"
                        )
                    if item.get("host") != owner:
                        errors.append(
                            f"{item_label}: observed AUTHORIZED host must equal production_runtime_owner"
                        )
                    if auth_status != "AUTHORIZED":
                        errors.append(
                            f"{item_label}: observed AUTHORIZED requires production_authorization_status=AUTHORIZED"
                        )
                    if lifecycle not in AUTHORIZATION_REQUIRED_LIFECYCLES:
                        errors.append(
                            f"{item_label}: observed AUTHORIZED requires runtime_lifecycle AUTHORIZED_INACTIVE or ACTIVE"
                        )
                    if not evidence.strip():
                        errors.append(
                            f"{item_label}: observed AUTHORIZED requires production_decision_evidence"
                        )
                    if item.get("current_state") == "ACTIVE_OBSERVED" and lifecycle != "ACTIVE":
                        errors.append(
                            f"{item_label}: observed AUTHORIZED ACTIVE_OBSERVED requires runtime_lifecycle ACTIVE"
                        )
                    active_observations.setdefault(cap_id, []).append(str(item.get("unit")))

        historical = cap.get("historical_runtime_assignment")
        if historical is not None:
            if not isinstance(historical, dict):
                errors.append(f"{label}: historical_runtime_assignment must be object or null")
            else:
                hist_required = {
                    "host",
                    "status",
                    "source",
                    "reason",
                    "preserved_evidence",
                    "grants_current_authority",
                }
                _ensure_keys(historical, hist_required, hist_required, f"{label}.historical_runtime_assignment", errors)
                if historical.get("status") not in historical_statuses:
                    errors.append(f"{label}: historical assignment status must be SUPERSEDED")
                if historical.get("grants_current_authority") is not False:
                    errors.append(f"{label}: historical assignment must grant_current_authority=false")
                if owner != UNASSIGNED and historical.get("host") == owner:
                    errors.append(f"{label}: historical assignment host cannot be reused as active authority")

        if "owner_identity_env" in cap:
            errors.append(f"{label}: owner_identity_env overrides are forbidden")
        if cap.get("account_or_reporting_coupling") is not False:
            errors.append(f"{label}: account_or_reporting_coupling must be false")
        service_by_capability[cap_id] = str(cap.get("service", ""))
        module_token_by_capability[cap_id] = set(str(x) for x in cap.get("modules_invoked", []))

    if len(ids) != len(set(ids)):
        errors.append("registry.capabilities contains duplicate capability_id values")
    if set(ids) != EXPECTED_CAPABILITY_IDS:
        errors.append(f"registry.capabilities must contain exactly {sorted(EXPECTED_CAPABILITY_IDS)}")

    for cap_id, units in active_observations.items():
        if len(units) > 1:
            errors.append(f"capability[{cap_id}]: multiple authorized active runtime observations {units}")

    native_modules = module_token_by_capability.get("native_short_4h_chain", set())
    if not REQUIRED_NATIVE_SHORT_MODULES.issubset(native_modules):
        errors.append(
            "capability[native_short_4h_chain]: incomplete invoked module inventory "
            f"missing {sorted(REQUIRED_NATIVE_SHORT_MODULES - native_modules)}"
        )
    native = next((c for c in capabilities if isinstance(c, dict) and c.get("capability_id") == "native_short_4h_chain"), None)
    if isinstance(native, dict):
        native_writes = set(str(x) for x in native.get("database_writes", []))
        if not REQUIRED_NATIVE_SHORT_WRITES.issubset(native_writes):
            errors.append(
                "capability[native_short_4h_chain]: incomplete database write inventory "
                f"missing {sorted(REQUIRED_NATIVE_SHORT_WRITES - native_writes)}"
            )
        if not native.get("artifact_publications"):
            errors.append("capability[native_short_4h_chain]: artifact publication inventory is required")

    _validate_units_for_duplicates(registry, repo, errors)
    _validate_consumers(registry, repo, errors)
    _validate_call_graph(registry, repo, errors)
    return ValidationResult(errors, warnings)


def _registered_writer_paths(registry: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for cap in registry.get("capabilities", []):
        if not isinstance(cap, dict):
            continue
        for key in ("wrapper", "service", "timer"):
            value = cap.get(key)
            if isinstance(value, str) and value:
                paths.add(value)
        for wrapper in cap.get("wrappers_invoked", []):
            paths.add(str(wrapper))
    return paths


def _validate_call_graph(registry: dict[str, Any], repo: Path, errors: list[str]) -> None:
    """Structural, repository-wide writer call-graph validation.

    Every file that invokes a public-market writer token must be either a
    registered capability wrapper/service or an explicitly classified entry in
    ``additional_writer_paths``. Public-market writers must never share a path
    with account/execution layers.
    """
    public_tokens = tuple(str(x) for x in registry.get("forbidden_writer_invocation_tokens", []))
    account_tokens = tuple(str(x) for x in registry.get("forbidden_account_execution_tokens", []))
    scan_trees = [str(x) for x in registry.get("call_graph_scan_trees", [])]
    registered_paths = _registered_writer_paths(registry)

    additional_by_path: dict[str, dict[str, Any]] = {}
    for entry in registry.get("additional_writer_paths", []):
        if not isinstance(entry, dict):
            errors.append("additional_writer_paths entry must be an object")
            continue
        rel = str(entry.get("path", ""))
        additional_by_path[rel] = entry
        classification = entry.get("classification")
        if classification not in ALLOWED_ADDITIONAL_WRITER_CLASSIFICATIONS:
            errors.append(f"additional_writer_paths[{rel}]: invalid classification {classification!r}")
        full = repo / rel
        if not _is_repo_relative(rel) or not full.exists():
            errors.append(f"additional_writer_paths[{rel}]: path missing or invalid")
            continue
        text = _non_comment_source(full)
        found_public = [tok for tok in public_tokens if tok in text and tok != rel]
        found_account = [tok for tok in account_tokens if tok in text]
        if classification in REMOVED_PATH_CLASSIFICATIONS:
            if found_public:
                errors.append(
                    f"additional_writer_paths[{rel}]: classified removed but still invokes public writer tokens {found_public}"
                )
            if found_account:
                errors.append(
                    f"additional_writer_paths[{rel}]: classified removed but still invokes account/execution tokens {found_account}"
                )
        else:
            if found_account:
                errors.append(
                    f"additional_writer_paths[{rel}]: market-only path must not invoke account/execution tokens {found_account}"
                )
            if classification == "read_only_caller" and found_public:
                errors.append(
                    f"additional_writer_paths[{rel}]: read_only_caller must not invoke public writer tokens {found_public}"
                )
            declared = {str(x) for x in entry.get("invokes_public_writer_tokens", [])}
            if set(found_public) != declared:
                errors.append(
                    f"additional_writer_paths[{rel}]: declared public writer tokens {sorted(declared)} "
                    f"do not match discovered {sorted(found_public)}"
                )

    for tree in scan_trees:
        root = repo / tree
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".sh"}:
                continue
            rel = str(path.relative_to(repo))
            text = _non_comment_source(path)
            found_public = [tok for tok in public_tokens if tok in text and tok != rel]
            if not found_public:
                continue
            if rel in registered_paths:
                found_account = [tok for tok in account_tokens if tok in text]
                if found_account:
                    errors.append(
                        f"registered writer path {rel} must not invoke account/execution tokens {found_account}"
                    )
                continue
            if rel in additional_by_path:
                continue
            errors.append(
                f"unregistered writer path invokes public writer tokens: {rel} -> {found_public}"
            )

    # Market-only processing chains must own zero public-market-data ingestion:
    # they consume already-persisted candles and must never invoke a public
    # writer token. This proves 1h/1d chains cannot bypass candle-writer
    # authorization by silently owning ingestion.
    for rel in (str(x) for x in registry.get("market_only_processing_chains_with_zero_public_writers", [])):
        full = repo / rel
        if not _is_repo_relative(rel) or not full.exists():
            errors.append(f"market_only_processing_chain missing or invalid: {rel}")
            continue
        text = _non_comment_source(full)
        found_public = [tok for tok in public_tokens if tok in text and tok != rel]
        found_account = [tok for tok in account_tokens if tok in text]
        if found_public:
            errors.append(
                f"market_only_processing_chain {rel} must not invoke public writer tokens {found_public}"
            )
        if found_account:
            errors.append(
                f"market_only_processing_chain {rel} must not invoke account/execution tokens {found_account}"
            )


def _capability_for_unit_text(registry: dict[str, Any], text: str) -> set[str]:
    matches: set[str] = set()
    for cap in registry.get("capabilities", []):
        if not isinstance(cap, dict):
            continue
        tokens = set(str(x) for x in cap.get("wrappers_invoked", []))
        tokens.update(str(x) for x in cap.get("modules_invoked", []))
        tokens.add(str(cap.get("wrapper", "")))
        for token in tokens:
            if token and token in text:
                matches.add(str(cap.get("capability_id")))
    return matches


def _validate_units_for_duplicates(registry: dict[str, Any], repo: Path, errors: list[str]) -> None:
    unit_hits: dict[str, list[str]] = {}
    for path in _all_unit_files(repo):
        text = _unit_non_comment_text(path)
        for capability_id in _capability_for_unit_text(registry, text):
            rel = str(path.relative_to(repo))
            unit_hits.setdefault(capability_id, []).append(rel)

    for cap in registry.get("capabilities", []):
        if not isinstance(cap, dict):
            continue
        cap_id = str(cap.get("capability_id"))
        declared_service = str(cap.get("service"))
        hits = sorted(set(unit_hits.get(cap_id, [])))
        unexpected = [hit for hit in hits if hit != declared_service]
        if unexpected:
            errors.append(f"capability[{cap_id}]: duplicate or unexpected unit invocations {unexpected}")
        if declared_service and declared_service not in hits:
            errors.append(f"capability[{cap_id}]: declared service does not invoke capability token")


def _validate_consumers(registry: dict[str, Any], repo: Path, errors: list[str]) -> None:
    forbidden = tuple(str(x) for x in registry.get("forbidden_writer_invocation_tokens", []))
    consumer_paths = [Path(str(x)) for x in registry.get("consumers_with_zero_writer_capabilities", [])]
    scan_roots = [repo / "scripts/odroid", repo / "src/reporting", repo / "apps"]
    paths = set(repo / p for p in consumer_paths)
    for root in scan_roots:
        if root.exists():
            paths.update(path for path in root.rglob("*") if path.is_file() and path.suffix in {".py", ".sh", ".service", ".timer"})
    for path in sorted(paths):
        if not path.exists():
            errors.append(f"consumer path missing: {path.relative_to(repo)}")
            continue
        text = _non_comment_source(path)
        for token in forbidden:
            if token in text:
                errors.append(f"consumer/reporting path invokes writer token: {path.relative_to(repo)} -> {token}")


def _non_comment_source(path: Path) -> str:
    lines = []
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("#") or stripped.startswith(";"):
            continue
        lines.append(raw_line)
    return "\n".join(lines)


def validate_registry_file(path: Path, *, repo_root: Path | None = None) -> ValidationResult:
    registry = _read_json(path)
    return validate_registry_payload(registry, repo_root=repo_root or path.resolve().parents[2])


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate writer-capability ownership registry.")
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", choices=("table", "json"), default="table")
    args = parser.parse_args()

    try:
        result = validate_registry_file(args.registry, repo_root=args.repo_root)
    except RegistryValidationError as exc:
        result = ValidationResult(errors=[str(exc)], warnings=[])

    payload = {
        "ok": result.ok,
        "errors": result.errors,
        "warnings": result.warnings,
        "safety_markers": {
            "host_mutations": 0,
            "database_writes": 0,
            "writer_invocations": 0,
            "systemctl_mutations": 0,
            "broker_private_calls": 0,
            "broker_writes": 0,
        },
    }
    if args.output == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"validation_ok={str(result.ok).lower()} error_count={len(result.errors)} warning_count={len(result.warnings)}")
        for error in result.errors:
            print(f"ERROR {error}")
        for warning in result.warnings:
            print(f"WARN {warning}")
        print(
            "host_mutations=0 database_writes=0 writer_invocations=0 "
            "systemctl_mutations=0 broker_private_calls=0 broker_writes=0"
        )
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
