"""Issue #551 Phase 1: canonical SELL LIVE readiness controller.

Ownership
---------

This module is a read-only orchestration/reporting layer. It owns nothing
of permission, credential, kill-switch, planner, executor, or broker
semantics -- it only *reads* the existing canonical contracts already built
and reviewed for Issue #392 phases 1-6 and reports their state:

- ``src/executor/execution_credential_scope_v1.py`` (TRADE_EXECUTION binding)
- ``src/decision_gate/automatic_exit_live_permission_repository_v1.py`` +
  ``automatic_exit_live_permission_contract_v1.py`` (decision-gate LIVE
  permission -- Gate 1)
- ``src/executor/execution_kill_switch_v1.py`` (global kill switch)
- ``src/executor/execution_live_authority_v1.py`` (executor operational LIVE
  authority -- Gate 2; not itself queried here, see note below)
- ``src/execution_planner/automatic_exit_execution_handoff_adapter_v1.py`` +
  ``automatic_exit_execution_handoff_application_v1.py`` (candidate ->
  decision_gate -> planner -> executor handoff seam)
- ``deploy/ownership/account_runtime_capability_ownership_v1.json``
  (runtime/service ownership and activation status)

Phase 1 boundary
----------------

This controller performs PRECHECK, PRODUCTION_SCHEMA_READY,
CREDENTIAL_BINDING_READY, LIVE_PERMISSION_READY, KILL_SWITCH_READY,
RUNTIME_READY, DRY_RUN_ACCEPTANCE, PAPER_ACCEPTANCE, and CANARY_READY
checks, then stops at LIVE_AUTHORIZATION_REQUIRED. It never advances past
that state. It never mutates production DB state, never applies a
migration, never provisions a credential, never flips the kill switch,
never enables a service/timer, and never submits an order.

``DRY_RUN_ACCEPTANCE``/``PAPER_ACCEPTANCE`` prove the candidate ->
decision_gate -> planner -> adapter -> executor-mode-resolution code path
end-to-end using a synthetic, clearly-labelled in-memory fixture (mirroring
the fixture shape already proven by
``tests/test_automatic_exit_execution_handoff_adapter_v1.py``). They
deliberately stop before ``ExecutionHandoffRepositoryV1.intake`` /
``.intake_live_authorized`` -- calling either would perform a real DB write,
which Phase 1 categorically forbids even in DRY_RUN/PAPER mode. This is a
narrower proof than a full repository-level acceptance (see
``docs/status/issue_392_phase6_sell_live_readiness_v1.md``'s 2026-08-19
update for that separate, already-completed acceptance); it is sufficient
for Phase 1 because it never needs a live database to prove the code path
is wired and deterministic.

Executor operational LIVE authority (Gate 2,
``execution_live_authority_v1.require_execution_live_authority_v1``) is
account/venue/side/market/executor_identity/runtime_owner-scoped and has no
meaningful "readiness" state independent of an actual grant row an operator
would provision only immediately before a real activation decision; this
controller does not attempt to resolve or report on a hypothetical grant.
The kill-switch check (Gate 2's other half) is checked directly because it
is a single global switch with a meaningful idle state.

Safety:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  production_db_mutation=0
  production_migration_apply=0
  credential_provisioning=0
  live_permission_provisioning=0
  kill_switch_mutation=0
  service_mutation=0
  decision_gate=read-only (queries persisted permission evidence only)
  execution_planner=read-only (synthetic in-memory fixture only)
  executor=read-only (kill switch + credential scope reads only)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Final

# --- Contract constants -----------------------------------------------

SCHEMA_VERSION: Final[str] = "sell_live_readiness_v1"
CONTROLLER_VERSION: Final[str] = "v1"

PHASE_PRECHECK: Final[str] = "PRECHECK"
PHASE_PRODUCTION_SCHEMA_READY: Final[str] = "PRODUCTION_SCHEMA_READY"
PHASE_CREDENTIAL_BINDING_READY: Final[str] = "CREDENTIAL_BINDING_READY"
PHASE_LIVE_PERMISSION_READY: Final[str] = "LIVE_PERMISSION_READY"
PHASE_KILL_SWITCH_READY: Final[str] = "KILL_SWITCH_READY"
PHASE_RUNTIME_READY: Final[str] = "RUNTIME_READY"
PHASE_DRY_RUN_ACCEPTANCE: Final[str] = "DRY_RUN_ACCEPTANCE"
PHASE_PAPER_ACCEPTANCE: Final[str] = "PAPER_ACCEPTANCE"
PHASE_CANARY_READY: Final[str] = "CANARY_READY"
PHASE_LIVE_AUTHORIZATION_REQUIRED: Final[str] = "LIVE_AUTHORIZATION_REQUIRED"

# Deterministic, canonical ordering. Never reordered at runtime.
PHASE_ORDER: Final[tuple[str, ...]] = (
    PHASE_PRECHECK,
    PHASE_PRODUCTION_SCHEMA_READY,
    PHASE_CREDENTIAL_BINDING_READY,
    PHASE_LIVE_PERMISSION_READY,
    PHASE_KILL_SWITCH_READY,
    PHASE_RUNTIME_READY,
    PHASE_DRY_RUN_ACCEPTANCE,
    PHASE_PAPER_ACCEPTANCE,
    PHASE_CANARY_READY,
    PHASE_LIVE_AUTHORIZATION_REQUIRED,
)

# Phases evaluated unconditionally, independent of each other's outcome
# (all are read-only, so nothing is unsafe about evaluating every one and
# reporting an aggregate blocker list). LIVE_AUTHORIZATION_REQUIRED is
# handled separately: it is only ever reached/PASSED when every phase in
# this tuple passed.
_GATED_PHASES: Final[tuple[str, ...]] = PHASE_ORDER[:-1]

STATUS_PASSED: Final[str] = "PASSED"
STATUS_BLOCKED: Final[str] = "BLOCKED"
STATUS_NOT_EVALUATED: Final[str] = "NOT_EVALUATED"

TERMINAL_BLOCKED: Final[str] = "BLOCKED"
TERMINAL_CANARY_READY: Final[str] = "CANARY_READY"
TERMINAL_LIVE_AUTHORIZATION_REQUIRED: Final[str] = "LIVE_AUTHORIZATION_REQUIRED"
VALID_TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {TERMINAL_BLOCKED, TERMINAL_CANARY_READY, TERMINAL_LIVE_AUTHORIZATION_REQUIRED}
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_PATH: Final[Path] = REPO_ROOT / "data" / "ops" / "sell_live_readiness_v1.json"
DEFAULT_OWNERSHIP_REGISTRY_PATH: Final[Path] = (
    REPO_ROOT / "deploy" / "ownership" / "account_runtime_capability_ownership_v1.json"
)

# Presence-only schema check. Table names are exact canonical names already
# defined by reviewed #392/#206/#413 migrations; this controller never
# defines or applies a migration of its own.
REQUIRED_PRODUCTION_TABLES: Final[tuple[str, ...]] = (
    "trading_account",
    "trading_account_credential",
    "executor_credential_binding",
    "automatic_exit_live_decision_gate_permission_v1",
    "automatic_exit_live_decision_gate_permission_revocation_v1",
    "executor_execution_handoff",
    "executor_execution_leg",
    "executor_live_authority_grant",
    "executor_live_authority_revocation",
    "executor_kill_switch_event",
)

# Capabilities that must exist and be actively running before a SELL LIVE
# canary could ever execute end to end. Report-only: this controller never
# starts, enables, or installs any of these.
REQUIRED_RUNTIME_CAPABILITY_IDS: Final[tuple[str, ...]] = (
    "AUTOMATIC_EXIT_POLICY_RUNTIME",
    "SHARED_EXECUTOR_RUNTIME",
)
_RUNTIME_ACTIVE_STATUSES: Final[frozenset[str]] = frozenset({"ACTIVE", "ENABLED", "RUNNING"})

SUPPORTED_ACCOUNT_MODES: Final[frozenset[str]] = frozenset({"paper", "live"})

# Purely synthetic, obviously-non-production identity used only for the
# in-memory DRY_RUN_ACCEPTANCE / PAPER_ACCEPTANCE code-path proof. Never
# read from or written to any database.
_SYNTHETIC_ACCEPTANCE_TRADING_ACCOUNT_ID: Final[int] = 900551001
_SYNTHETIC_ACCEPTANCE_POSITION_REFERENCE: Final[str] = "issue-551-synthetic-position"
_SYNTHETIC_ACCEPTANCE_ASSET_ID: Final[int] = 900551
_SYNTHETIC_ACCEPTANCE_MARKET: Final[str] = "SYNTH-EUR"


class SellLiveReadinessControllerError(RuntimeError):
    """Raised only for genuinely unrecoverable controller-configuration bugs."""


# --- Canary contract preview (Section J) -------------------------------


class SellLiveCanaryContractPreviewError(ValueError):
    """The SELL canary preview could not be constructed safely."""


@dataclass(frozen=True)
class SellLiveCanaryContractPreviewV1:
    """A bounded first-LIVE SELL canary contract that CAN be constructed.

    This is a preview/feasibility object only. Constructing it activates
    nothing: it is never persisted as an authority grant, never consulted by
    the executor, and never wired into ``execution_live_authority_v1`` or
    ``execution_kill_switch_v1``. It exists purely so the readiness artifact
    can show a reviewer the exact bounded shape a first SELL canary
    activation would take, once a human separately authorizes it.

    This is deliberately a new, SELL-scoped contract rather than a reuse of
    ``src/executor/live_canary_bounds_v1.py``: that module is hard-coded
    BUY-only (``CANARY_ALLOWED_SIDE = "BUY"``) by explicit, reviewed design
    for the first-LIVE BUY canary, and this issue requires
    ``allowed_side=SELL``. Reusing it would either require weakening its
    BUY-only invariant (unacceptable -- that invariant is safety-load-bearing
    for the BUY canary) or silently overloading one object for two
    structurally distinct one-sided contracts. A parallel, equally-narrow
    SELL-only contract preserves the same fail-closed shape without touching
    the existing reviewed BUY module at all.
    """

    version: str
    trading_account_id: int
    venue: str
    allowed_side: str
    allowed_market: str
    max_orders_per_cycle: int
    max_notional_eur: str
    kill_switch_required: bool
    deployed_sha: str

    def __post_init__(self) -> None:
        if self.version != CONTROLLER_VERSION:
            raise SellLiveCanaryContractPreviewError("UNSUPPORTED_CANARY_PREVIEW_VERSION")
        if (
            not isinstance(self.trading_account_id, int)
            or isinstance(self.trading_account_id, bool)
            or self.trading_account_id <= 0
        ):
            raise SellLiveCanaryContractPreviewError("CANARY_ACCOUNT_MUST_BE_POSITIVE_INT")
        if not isinstance(self.venue, str) or not self.venue.strip():
            raise SellLiveCanaryContractPreviewError("CANARY_VENUE_REQUIRED")
        if self.allowed_side != "SELL":
            raise SellLiveCanaryContractPreviewError("CANARY_SIDE_MUST_BE_SELL")
        if not isinstance(self.allowed_market, str) or not self.allowed_market.strip():
            raise SellLiveCanaryContractPreviewError("CANARY_MARKET_REQUIRED")
        if (
            not isinstance(self.max_orders_per_cycle, int)
            or isinstance(self.max_orders_per_cycle, bool)
            or self.max_orders_per_cycle <= 0
        ):
            raise SellLiveCanaryContractPreviewError("CANARY_MAX_ORDERS_PER_CYCLE_MUST_BE_POSITIVE_INT")
        try:
            notional = Decimal(self.max_notional_eur)
        except (InvalidOperation, TypeError):
            raise SellLiveCanaryContractPreviewError("CANARY_MAX_NOTIONAL_EUR_INVALID") from None
        if not notional.is_finite() or notional <= 0:
            raise SellLiveCanaryContractPreviewError("CANARY_MAX_NOTIONAL_EUR_INVALID")
        if self.kill_switch_required is not True:
            raise SellLiveCanaryContractPreviewError("CANARY_KILL_SWITCH_MUST_BE_REQUIRED")
        if not isinstance(self.deployed_sha, str) or not self.deployed_sha.strip():
            raise SellLiveCanaryContractPreviewError("CANARY_DEPLOYED_SHA_REQUIRED")


# --- Phase result / config ----------------------------------------------


@dataclass(frozen=True)
class PhaseResultV1:
    phase: str
    status: str
    reason_code: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "status": self.status,
            "reason_code": self.reason_code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ControllerConfigV1:
    trading_account_id: int
    venue: str
    executor_identity: str
    runtime_owner: str
    canary_allowed_market: str
    canary_max_orders_per_cycle: int
    canary_max_notional_eur: str
    now_ts_utc: datetime
    expected_deployed_sha: str | None = None
    ownership_registry_path: Path = DEFAULT_OWNERSHIP_REGISTRY_PATH
    # Dependency injection seams for tests only. Production runs (main())
    # never set these -- each phase falls back to the canonical repository
    # class with its own default legacy DB cursor factory.
    connection_factory: Callable[[], Any] | None = None
    credential_scope_repository: Any | None = None
    kill_switch_repository: Any | None = None


# --- Small helpers --------------------------------------------------------


def _blocked(phase: str, reason_code: str, detail: dict[str, Any] | None = None) -> PhaseResultV1:
    return PhaseResultV1(phase=phase, status=STATUS_BLOCKED, reason_code=reason_code, detail=detail or {})


def _passed(phase: str, reason_code: str = "OK", detail: dict[str, Any] | None = None) -> PhaseResultV1:
    return PhaseResultV1(phase=phase, status=STATUS_PASSED, reason_code=reason_code, detail=detail or {})


def _exc_detail(exc: BaseException) -> dict[str, Any]:
    """Non-secret exception summary: exception class + first fixed code arg only.

    Never includes the full exception message/str(), which for a DB driver
    exception could in principle echo connection parameters. Only the first
    positional argument is used, and only when it looks like a short
    uppercase reason code (the canonical style used throughout this
    repository's fail-closed exceptions), never an arbitrary message.
    """
    reason = "UNKNOWN"
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], str) and len(args[0]) <= 128:
        candidate = args[0]
        if candidate.replace("_", "").replace(":", "").isalnum() and candidate.isupper():
            reason = candidate
    return {"exception_type": type(exc).__name__, "reason": reason}


def repository_sha_v1(repo_root: Path = REPO_ROOT) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(repo_root),
            timeout=10,
        )
        sha = completed.stdout.strip()
        return sha if sha else "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def _open_connection(config: ControllerConfigV1) -> Any:
    if config.connection_factory is not None:
        return config.connection_factory()
    from src.common.db import get_db_connection

    return get_db_connection()


# --- Phase implementations -------------------------------------------------


def _phase_precheck(config: ControllerConfigV1, repository_sha: str) -> PhaseResultV1:
    if (
        not isinstance(config.trading_account_id, int)
        or isinstance(config.trading_account_id, bool)
        or config.trading_account_id <= 0
    ):
        return _blocked(PHASE_PRECHECK, "TRADING_ACCOUNT_ID_MUST_BE_POSITIVE_INT")
    if not config.venue or not config.venue.strip():
        return _blocked(PHASE_PRECHECK, "VENUE_REQUIRED")
    if not config.executor_identity or not config.executor_identity.strip():
        return _blocked(PHASE_PRECHECK, "EXECUTOR_IDENTITY_REQUIRED")
    if not config.runtime_owner or not config.runtime_owner.strip():
        return _blocked(PHASE_PRECHECK, "RUNTIME_OWNER_REQUIRED")

    detail: dict[str, Any] = {"repository_sha": repository_sha}
    if config.expected_deployed_sha:
        detail["expected_deployed_sha"] = config.expected_deployed_sha
        if config.expected_deployed_sha != repository_sha:
            return _blocked(
                PHASE_PRECHECK,
                "REPOSITORY_DEPLOYED_SHA_MISMATCH",
                detail,
            )
    else:
        detail["deployed_sha_warning"] = (
            "NO_EXPECTED_DEPLOYED_SHA_SUPPLIED: deployment match not verified by this run"
        )

    # Account identity (Section C): a canonical trading_account row must
    # exist, and account_mode must agree with live_trading_enabled exactly
    # the same way decision_gate.automatic_exit_gate_v1 already requires
    # (REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT). This controller does not
    # re-derive that rule independently -- it restates the same canonical
    # invariant as a read-only precondition check.
    try:
        conn = _open_connection(config)
    except Exception as exc:
        detail.update(_exc_detail(exc))
        return _blocked(PHASE_PRECHECK, "PRODUCTION_DB_UNAVAILABLE", detail)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT trading_account_id, account_mode, enabled, live_trading_enabled, venue "
                "FROM trading_account WHERE trading_account_id=%s",
                [config.trading_account_id],
            )
            row = cur.fetchone()
    except Exception as exc:
        detail.update(_exc_detail(exc))
        return _blocked(PHASE_PRECHECK, "PRODUCTION_DB_UNAVAILABLE", detail)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if row is None:
        return _blocked(PHASE_PRECHECK, "TRADING_ACCOUNT_NOT_FOUND", detail)
    account_mode = str(row["account_mode"])
    live_trading_enabled = bool(row["live_trading_enabled"])
    enabled = bool(row["enabled"])
    venue = str(row["venue"])
    detail.update(
        {
            "account_mode": account_mode,
            "enabled": enabled,
            "live_trading_enabled": live_trading_enabled,
            "account_venue": venue,
        }
    )
    if account_mode not in SUPPORTED_ACCOUNT_MODES:
        return _blocked(PHASE_PRECHECK, "UNSUPPORTED_ACCOUNT_MODE", detail)
    if not enabled:
        return _blocked(PHASE_PRECHECK, "TRADING_ACCOUNT_DISABLED", detail)
    if (account_mode == "live") != live_trading_enabled:
        return _blocked(PHASE_PRECHECK, "ACCOUNT_MODE_EVIDENCE_INCONSISTENT", detail)
    if venue != config.venue:
        return _blocked(PHASE_PRECHECK, "ACCOUNT_VENUE_MISMATCH", detail)
    return _passed(PHASE_PRECHECK, "OK", detail)


def _phase_production_schema_ready(config: ControllerConfigV1) -> PhaseResultV1:
    try:
        conn = _open_connection(config)
    except Exception as exc:
        return _blocked(PHASE_PRODUCTION_SCHEMA_READY, "PRODUCTION_DB_UNAVAILABLE", _exc_detail(exc))
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            rows = cur.fetchall()
        present = set()
        for row in rows:
            if isinstance(row, dict):
                present.add(next(iter(row.values())))
            else:
                present.add(row[0])
    except Exception as exc:
        return _blocked(PHASE_PRODUCTION_SCHEMA_READY, "PRODUCTION_DB_UNAVAILABLE", _exc_detail(exc))
    finally:
        try:
            conn.close()
        except Exception:
            pass

    missing = sorted(table for table in REQUIRED_PRODUCTION_TABLES if table not in present)
    if missing:
        return _blocked(
            PHASE_PRODUCTION_SCHEMA_READY,
            "PRODUCTION_SCHEMA_TABLES_MISSING",
            {"missing_tables": missing},
        )
    return _passed(PHASE_PRODUCTION_SCHEMA_READY, "OK", {"required_tables_present": len(REQUIRED_PRODUCTION_TABLES)})


def _phase_credential_binding_ready(config: ControllerConfigV1) -> PhaseResultV1:
    from src.executor.execution_credential_scope_v1 import (
        CredentialScopeDeniedError,
        ExecutorCredentialScopeRepository,
    )

    repo = config.credential_scope_repository or ExecutorCredentialScopeRepository()
    try:
        binding = repo.resolve(
            trading_account_id=config.trading_account_id,
            venue=config.venue,
            executor_identity=config.executor_identity,
            runtime_owner=config.runtime_owner,
        )
    except CredentialScopeDeniedError as exc:
        return _blocked(PHASE_CREDENTIAL_BINDING_READY, str(exc), _exc_detail(exc))
    except Exception as exc:
        return _blocked(PHASE_CREDENTIAL_BINDING_READY, "PRODUCTION_DB_UNAVAILABLE", _exc_detail(exc))
    return _passed(
        PHASE_CREDENTIAL_BINDING_READY,
        "OK",
        {
            "executor_credential_binding_id": binding.executor_credential_binding_id,
            "credential_status": binding.credential_status,
        },
    )


def _phase_live_permission_ready(config: ControllerConfigV1) -> PhaseResultV1:
    from src.decision_gate.automatic_exit_live_permission_contract_v1 import (
        AutomaticExitLivePermissionContractError,
        resolve_automatic_exit_live_decision_gate_permission_v1,
    )
    from src.decision_gate.automatic_exit_live_permission_repository_v1 import (
        AutomaticExitLivePermissionRepositoryError,
        load_automatic_exit_live_permission_history_v1,
        load_automatic_exit_live_permission_revocation_history_v1,
    )

    try:
        conn = _open_connection(config)
    except Exception as exc:
        return _blocked(PHASE_LIVE_PERMISSION_READY, "PRODUCTION_DB_UNAVAILABLE", _exc_detail(exc))
    try:
        permissions = load_automatic_exit_live_permission_history_v1(
            conn, trading_account_id=config.trading_account_id
        )
        revocations = load_automatic_exit_live_permission_revocation_history_v1(
            conn, trading_account_id=config.trading_account_id
        )
    except Exception as exc:
        return _blocked(PHASE_LIVE_PERMISSION_READY, "PRODUCTION_DB_UNAVAILABLE", _exc_detail(exc))
    finally:
        try:
            conn.close()
        except Exception:
            pass

    try:
        resolved = resolve_automatic_exit_live_decision_gate_permission_v1(
            permissions,
            revocations,
            trading_account_id=config.trading_account_id,
            at=config.now_ts_utc,
        )
    except AutomaticExitLivePermissionContractError as exc:
        return _blocked(PHASE_LIVE_PERMISSION_READY, str(exc), _exc_detail(exc))

    if resolved is None:
        return _blocked(PHASE_LIVE_PERMISSION_READY, "LIVE_PERMISSION_NOT_GRANTED")
    if not resolved.live_execution_permitted:
        return _blocked(
            PHASE_LIVE_PERMISSION_READY,
            "LIVE_PERMISSION_NOT_PERMITTED",
            {"permission_id": resolved.permission_id},
        )
    return _passed(
        PHASE_LIVE_PERMISSION_READY,
        "OK",
        {"permission_id": resolved.permission_id, "permission_version": resolved.permission_version},
    )


# Purely advisory: the canonical kill-switch contract
# (``execution_kill_switch_v1``) defines no staleness threshold for a
# DISENGAGED event -- its correctness does not depend on event age. This
# threshold exists only to surface an operator-facing hint in the artifact's
# warnings; it never blocks a phase.
_KILL_SWITCH_STALE_ADVISORY_SECONDS: Final[int] = 30 * 24 * 3600


def _phase_kill_switch_ready(config: ControllerConfigV1) -> tuple[PhaseResultV1, list[str]]:
    from src.executor.execution_kill_switch_v1 import (
        KILL_SWITCH_DISENGAGED,
        KILL_SWITCH_ENGAGED,
        ExecutionKillSwitchRepositoryV1,
    )

    warnings: list[str] = []
    repo = config.kill_switch_repository or ExecutionKillSwitchRepositoryV1()
    try:
        latest = repo.latest_event()
    except Exception as exc:
        return _blocked(PHASE_KILL_SWITCH_READY, "PRODUCTION_DB_UNAVAILABLE", _exc_detail(exc)), warnings

    if latest is None:
        # Deliberately stricter than the runtime's own clear-by-default
        # behavior (see execution_kill_switch_v1.is_engaged(), which treats
        # "no event" as clear). A readiness controller preparing a first
        # LIVE canary must not treat total absence of authoritative
        # kill-switch history as equivalent to an explicit, reviewed
        # DISENGAGED decision -- so it fails closed here instead.
        return _blocked(PHASE_KILL_SWITCH_READY, "KILL_SWITCH_STATE_UNKNOWN"), warnings
    if latest.state == KILL_SWITCH_ENGAGED:
        return _blocked(PHASE_KILL_SWITCH_READY, "KILL_SWITCH_ENGAGED", {"event_id": latest.event_id}), warnings
    if latest.state != KILL_SWITCH_DISENGAGED:
        return _blocked(PHASE_KILL_SWITCH_READY, "KILL_SWITCH_STATE_AMBIGUOUS", {"event_id": latest.event_id}), warnings

    created_ts_utc = latest.created_ts_utc
    if created_ts_utc.tzinfo is None:
        created_ts_utc = created_ts_utc.replace(tzinfo=timezone.utc)
    age_seconds = (config.now_ts_utc - created_ts_utc).total_seconds()
    if age_seconds > _KILL_SWITCH_STALE_ADVISORY_SECONDS:
        warnings.append(
            f"KILL_SWITCH_DISENGAGED_EVENT_AGE_ADVISORY: latest DISENGAGED event "
            f"(event_id={latest.event_id}) is {int(age_seconds)}s old; confirm it is still "
            "the operator's current intent before authorizing LIVE."
        )
    return _passed(PHASE_KILL_SWITCH_READY, "OK", {"event_id": latest.event_id}), warnings


def _phase_runtime_ready(config: ControllerConfigV1) -> PhaseResultV1:
    path = config.ownership_registry_path
    try:
        raw = path.read_text(encoding="utf-8")
        registry = json.loads(raw)
    except Exception as exc:
        return _blocked(PHASE_RUNTIME_READY, "RUNTIME_OWNERSHIP_REGISTRY_UNREADABLE", _exc_detail(exc))

    capabilities = {
        entry.get("capability_id"): entry
        for entry in registry.get("capabilities", [])
        if isinstance(entry, dict)
    }
    not_active: dict[str, str] = {}
    for capability_id in REQUIRED_RUNTIME_CAPABILITY_IDS:
        entry = capabilities.get(capability_id)
        if entry is None:
            not_active[capability_id] = "MISSING"
            continue
        status = str(entry.get("activation_status", "UNKNOWN"))
        if status not in _RUNTIME_ACTIVE_STATUSES:
            not_active[capability_id] = status
    if not_active:
        return _blocked(PHASE_RUNTIME_READY, "RUNTIME_CAPABILITY_NOT_ACTIVE", {"not_active": not_active})
    return _passed(PHASE_RUNTIME_READY, "OK", {"checked_capabilities": list(REQUIRED_RUNTIME_CAPABILITY_IDS)})


def _build_synthetic_acceptance_plan() -> Any:
    """Build a synthetic, in-memory-only AutomaticExitPlanV1 for path proof.

    Never touches a database and never calls any executor handoff/intake
    method. Mirrors the fixture shape already proven by
    ``tests/test_automatic_exit_execution_handoff_adapter_v1.py``.
    """
    from src.decision_gate.automatic_exit_gate_v1 import STATE_APPROVED, AutomaticExitGateDecisionV1
    from src.exit_policy.automatic_exit_candidate_v1 import AutomaticExitCandidateV1
    from src.execution_planner.automatic_exit_planner_v1 import (
        AutomaticExitPlanningContextV1,
        build_automatic_exit_plan_v1,
    )
    from src.market_rules.venue_execution_constraints_v1 import STATUS_FRESH, VenueExecutionConstraints

    from datetime import datetime as _dt

    now = _dt(2026, 8, 17, 12, 0, tzinfo=timezone.utc)

    candidate = AutomaticExitCandidateV1(
        trading_account_id=_SYNTHETIC_ACCEPTANCE_TRADING_ACCOUNT_ID,
        position_reference=_SYNTHETIC_ACCEPTANCE_POSITION_REFERENCE,
        venue="bitvavo",
        asset_id=_SYNTHETIC_ACCEPTANCE_ASSET_ID,
        market=_SYNTHETIC_ACCEPTANCE_MARKET,
        candidate_action="REDUCE",
        reduction_fraction_candidate=Decimal("0.25"),
        urgency_candidate="NORMAL",
        reason_code="TARGET_REACHED",
        evidence_id="issue-551-synthetic-evidence-1",
        exit_profile_id="issue-551-synthetic-profile-1",
        exit_profile_version="1",
        target_price=Decimal("100"),
        invalidation_price=Decimal("80"),
        observed_ts_utc=now,
    )
    decision = AutomaticExitGateDecisionV1(
        state=STATE_APPROVED,
        reason_code="OK",
        candidate=candidate,
        approved_fraction_candidate=Decimal("0.25"),
        approved_quantity_ceiling_base=Decimal("2.57"),
    )
    constraints = VenueExecutionConstraints(
        venue="bitvavo",
        market=_SYNTHETIC_ACCEPTANCE_MARKET,
        tick_size=Decimal("0.05"),
        qty_step_size=Decimal("0.1"),
        min_base_quantity=Decimal("0.1"),
        min_quote_notional=Decimal("5"),
        supported_order_types=("limit",),
        supported_time_in_force=("GTC",),
        source_provenance="PUBLIC",
        metadata_synced_ts_utc=now,
        status=STATUS_FRESH,
    )
    context = AutomaticExitPlanningContextV1(
        trading_account_id=_SYNTHETIC_ACCEPTANCE_TRADING_ACCOUNT_ID,
        position_reference=_SYNTHETIC_ACCEPTANCE_POSITION_REFERENCE,
        venue="bitvavo",
        asset_id=_SYNTHETIC_ACCEPTANCE_ASSET_ID,
        market=_SYNTHETIC_ACCEPTANCE_MARKET,
        reference_price=Decimal("100.01"),
        venue_constraints=constraints,
        planning_ts_utc=now,
    )
    return build_automatic_exit_plan_v1(decision=decision, context=context)


def _phase_dry_run_acceptance() -> PhaseResultV1:
    from src.execution_planner.automatic_exit_execution_handoff_adapter_v1 import (
        AutomaticExitPlanAdapterError,
        adapt_automatic_exit_plan_to_approved_execution_plan_v1,
        derive_automatic_exit_plan_reference_id_v1,
    )
    from src.executor.execution_handoff_v1 import RUNTIME_MODE_DRY_RUN

    try:
        plan_a = _build_synthetic_acceptance_plan()
        plan_b = _build_synthetic_acceptance_plan()
        approved_a = adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan_a)
        approved_b = adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan_b)
        if approved_a.side != "SELL":
            return _blocked(PHASE_DRY_RUN_ACCEPTANCE, "ADAPTED_PLAN_SIDE_NOT_SELL")
        # Idempotency/restart-readiness proof (Section I): rebuilding the
        # identical logical plan from scratch must derive the identical
        # plan_reference_id (deterministic, retry-stable identity), never a
        # persistence call.
        ref_a = derive_automatic_exit_plan_reference_id_v1(plan_a)
        ref_b = derive_automatic_exit_plan_reference_id_v1(plan_b)
        if ref_a != ref_b:
            return _blocked(PHASE_DRY_RUN_ACCEPTANCE, "PLAN_REFERENCE_ID_NOT_DETERMINISTIC")
        if RUNTIME_MODE_DRY_RUN not in {"DRY_RUN"}:
            return _blocked(PHASE_DRY_RUN_ACCEPTANCE, "UNEXPECTED_DRY_RUN_MODE_CONSTANT")
    except AutomaticExitPlanAdapterError as exc:
        return _blocked(PHASE_DRY_RUN_ACCEPTANCE, str(exc), _exc_detail(exc))
    except Exception as exc:
        return _blocked(PHASE_DRY_RUN_ACCEPTANCE, "DRY_RUN_ACCEPTANCE_PATH_FAILED", _exc_detail(exc))
    return _passed(PHASE_DRY_RUN_ACCEPTANCE, "OK", {"plan_reference_id": ref_a})


def _phase_paper_acceptance() -> PhaseResultV1:
    from src.execution_planner.automatic_exit_execution_handoff_adapter_v1 import (
        AutomaticExitPlanAdapterError,
        adapt_automatic_exit_plan_to_approved_execution_plan_v1,
    )
    from src.execution_planner.automatic_exit_execution_handoff_application_v1 import (
        AutomaticExitExecutorModeError,
        resolve_automatic_exit_executor_mode_v1,
    )
    from src.executor.execution_handoff_v1 import RUNTIME_MODE_PAPER

    try:
        plan = _build_synthetic_acceptance_plan()
        approved = adapt_automatic_exit_plan_to_approved_execution_plan_v1(plan)
        if approved.side != "SELL":
            return _blocked(PHASE_PAPER_ACCEPTANCE, "ADAPTED_PLAN_SIDE_NOT_SELL")
        resolved_mode = resolve_automatic_exit_executor_mode_v1("paper")
        if resolved_mode != RUNTIME_MODE_PAPER:
            return _blocked(PHASE_PAPER_ACCEPTANCE, "PAPER_ACCOUNT_MODE_DID_NOT_RESOLVE_TO_PAPER_EXECUTOR_MODE")
    except (AutomaticExitPlanAdapterError, AutomaticExitExecutorModeError) as exc:
        return _blocked(PHASE_PAPER_ACCEPTANCE, str(exc), _exc_detail(exc))
    except Exception as exc:
        return _blocked(PHASE_PAPER_ACCEPTANCE, "PAPER_ACCEPTANCE_PATH_FAILED", _exc_detail(exc))
    return _passed(PHASE_PAPER_ACCEPTANCE, "OK", {"resolved_executor_mode": resolved_mode})


def _phase_canary_ready(config: ControllerConfigV1, repository_sha: str) -> tuple[PhaseResultV1, SellLiveCanaryContractPreviewV1 | None]:
    try:
        preview = SellLiveCanaryContractPreviewV1(
            version=CONTROLLER_VERSION,
            trading_account_id=config.trading_account_id,
            venue=config.venue,
            allowed_side="SELL",
            allowed_market=config.canary_allowed_market,
            max_orders_per_cycle=config.canary_max_orders_per_cycle,
            max_notional_eur=str(config.canary_max_notional_eur),
            kill_switch_required=True,
            deployed_sha=repository_sha,
        )
    except SellLiveCanaryContractPreviewError as exc:
        return _blocked(PHASE_CANARY_READY, str(exc), _exc_detail(exc)), None
    return _passed(PHASE_CANARY_READY, "OK", asdict(preview)), preview


def _phase_live_authorization_required() -> PhaseResultV1:
    return _passed(
        PHASE_LIVE_AUTHORIZATION_REQUIRED,
        "OK",
        {
            "message": (
                "All Phase 1 read-only checks passed. LIVE trading is NOT "
                "authorized by this controller. A separate, explicit, "
                "human LIVE authorization decision -- provisioning "
                "executor_live_authority_grant, confirming the kill switch, "
                "and reviewing the canary_contract_preview -- is required "
                "before any order can be submitted."
            )
        },
    )


# --- Orchestration ----------------------------------------------------------


def _default_emit(event: dict[str, Any]) -> None:
    print(json.dumps(event, sort_keys=True, default=str), flush=True)


def run_controller(
    config: ControllerConfigV1,
    emit: Callable[[dict[str, Any]], None] = _default_emit,
) -> dict[str, Any]:
    """Run every Phase 1 readiness phase in canonical deterministic order.

    Returns the full readiness artifact (see module docstring / issue #551
    for the required schema). Never mutates any DB, credential, permission,
    kill-switch, runtime, or broker state. Idempotent: repeated calls with
    the same inputs produce the same phase_results/terminal_state (apart
    from ``generated_at_utc``, which always reflects the current run).
    """
    repository_sha = repository_sha_v1()
    emit({"event": "STARTED", "controller": "sell_live_activation_controller_v1", "mode": "check",
          "trading_account_id": config.trading_account_id, "venue": config.venue})

    warnings: list[str] = []
    results: dict[str, PhaseResultV1] = {}
    canary_preview: SellLiveCanaryContractPreviewV1 | None = None

    for phase in _GATED_PHASES:
        emit({"event": "PHASE_STARTED", "phase": phase})
        if phase == PHASE_PRECHECK:
            result = _phase_precheck(config, repository_sha)
        elif phase == PHASE_PRODUCTION_SCHEMA_READY:
            result = _phase_production_schema_ready(config)
        elif phase == PHASE_CREDENTIAL_BINDING_READY:
            result = _phase_credential_binding_ready(config)
        elif phase == PHASE_LIVE_PERMISSION_READY:
            result = _phase_live_permission_ready(config)
        elif phase == PHASE_KILL_SWITCH_READY:
            result, phase_warnings = _phase_kill_switch_ready(config)
            warnings.extend(phase_warnings)
        elif phase == PHASE_RUNTIME_READY:
            result = _phase_runtime_ready(config)
        elif phase == PHASE_DRY_RUN_ACCEPTANCE:
            result = _phase_dry_run_acceptance()
        elif phase == PHASE_PAPER_ACCEPTANCE:
            result = _phase_paper_acceptance()
        elif phase == PHASE_CANARY_READY:
            result, canary_preview = _phase_canary_ready(config, repository_sha)
        else:  # pragma: no cover - exhaustive by construction
            raise SellLiveReadinessControllerError(f"UNKNOWN_PHASE:{phase}")
        results[phase] = result
        emit({
            "event": "PHASE_PASSED" if result.status == STATUS_PASSED else "PHASE_BLOCKED",
            "phase": phase,
            "reason_code": result.reason_code,
        })

    any_blocked = any(results[phase].status == STATUS_BLOCKED for phase in _GATED_PHASES)
    if any_blocked:
        results[PHASE_LIVE_AUTHORIZATION_REQUIRED] = PhaseResultV1(
            phase=PHASE_LIVE_AUTHORIZATION_REQUIRED,
            status=STATUS_NOT_EVALUATED,
            reason_code="UPSTREAM_PHASE_BLOCKED",
        )
        terminal_state = TERMINAL_BLOCKED
    else:
        emit({"event": "PHASE_STARTED", "phase": PHASE_LIVE_AUTHORIZATION_REQUIRED})
        result = _phase_live_authorization_required()
        results[PHASE_LIVE_AUTHORIZATION_REQUIRED] = result
        emit({"event": "PHASE_PASSED", "phase": PHASE_LIVE_AUTHORIZATION_REQUIRED, "reason_code": result.reason_code})
        terminal_state = TERMINAL_LIVE_AUTHORIZATION_REQUIRED

    blockers = [
        {"phase": phase, "reason_code": results[phase].reason_code, "detail": results[phase].detail}
        for phase in PHASE_ORDER
        if results[phase].status == STATUS_BLOCKED
    ]

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": config.now_ts_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repository_sha": repository_sha,
        "deployed_sha": config.expected_deployed_sha,
        "trading_account_id": config.trading_account_id,
        "venue": config.venue,
        "phase_results": [results[phase].to_json() for phase in PHASE_ORDER],
        "blockers": blockers,
        "warnings": warnings,
        "canary_contract_preview": asdict(canary_preview) if canary_preview is not None else None,
        "terminal_state": terminal_state,
    }
    if terminal_state not in VALID_TERMINAL_STATES:  # pragma: no cover - defensive
        raise SellLiveReadinessControllerError(f"INVALID_TERMINAL_STATE:{terminal_state}")

    emit({"event": "FINISHED", "terminal_state": terminal_state, "blocker_count": len(blockers)})
    return artifact


def persist_artifact_v1(artifact: dict[str, Any], path: Path = DEFAULT_ARTIFACT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


# --- CLI ---------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Issue #551 Phase 1: read-only SELL LIVE readiness controller. "
            "Never mutates production state; stops at LIVE_AUTHORIZATION_REQUIRED."
        )
    )
    parser.add_argument("--check", action="store_true", required=True,
                         help="Required. This controller supports only read-only check mode in Phase 1.")
    parser.add_argument("--trading-account-id", type=int, required=True)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--executor-identity", required=True)
    parser.add_argument("--runtime-owner", required=True)
    parser.add_argument("--expected-deployed-sha", default=None)
    parser.add_argument("--canary-market", required=True)
    parser.add_argument("--canary-max-orders-per-cycle", type=int, required=True)
    parser.add_argument("--canary-max-notional-eur", required=True)
    parser.add_argument("--artifact-path", default=str(DEFAULT_ARTIFACT_PATH))
    parser.add_argument("--ownership-registry-path", default=str(DEFAULT_OWNERSHIP_REGISTRY_PATH))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from src.executor import _trusted_clock_v1 as trusted_clock

    config = ControllerConfigV1(
        trading_account_id=args.trading_account_id,
        venue=args.venue,
        executor_identity=args.executor_identity,
        runtime_owner=args.runtime_owner,
        canary_allowed_market=args.canary_market,
        canary_max_orders_per_cycle=args.canary_max_orders_per_cycle,
        canary_max_notional_eur=args.canary_max_notional_eur,
        now_ts_utc=trusted_clock.utc_now(),
        expected_deployed_sha=args.expected_deployed_sha,
        ownership_registry_path=Path(args.ownership_registry_path),
    )
    artifact = run_controller(config)
    persisted_path = persist_artifact_v1(artifact, Path(args.artifact_path))
    print(json.dumps(artifact, indent=2, sort_keys=True, default=str))
    print(f"ARTIFACT_PATH={persisted_path}")
    print("broker_private_calls=0\nbroker_writes=0\norder_submission=0\nlive_orders=0")
    return 0 if artifact["terminal_state"] != TERMINAL_BLOCKED else 1


if __name__ == "__main__":
    raise SystemExit(main())
