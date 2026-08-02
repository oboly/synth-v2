from __future__ import annotations

"""Lightweight native SHORT production readiness check.

Boundary: operations/deployment orchestration only. This runner performs no
database write, no host mutation, no systemd mutation, and no writer
invocation. It reuses the existing canonical contracts listed below and only
orchestrates/normalizes their results into one blocker/warning readiness
verdict; it does not reimplement any of them.

Reused, not reimplemented:
- src.operations.run_synth_chain_4h_db_environment_preflight_v1
  (repository unit / binding-shape / secret-file preflight)
- src.operations.run_synth_chain_4h_db_grant_preflight_v1
  (real connection, identity, and grant audit)
- src.operations.synth_chain_4h_db_authority_v1
  (canonical required-object/privilege manifest)
- src.operations.run_native_short_systemd_equivalence_preflight_v1
  (installed-unit inspection helpers)
- src.operations.writer_capability_authorization_v1
  (capability registry lookup and file-security validation)
- src.operations.persisted_market_price_freshness_v1 /
  persisted_market_candle_freshness_v1 (freshness classifiers)
- src.market_data.native_short_repository_source_identity_v1
  (checkout identity/dirty-state inspection)

Deliberately small: this is a single-user personal trading system, not an
enterprise compliance framework. Only conditions that make an actual
production chain run almost certain to fail immediately are hard blockers;
everything else that is merely non-ideal is a warning. No policy engine, no
severity levels beyond blocker/warning, no approval records.

Exit codes:
    0  ready (warnings, if any, do not block)
    1  one or more hard blockers
    2  the readiness runner itself could not evaluate safely

Safety markers:
host_mutations=0 database_writes=0 systemd_mutations=0 credential_changes=0
writer_invocations=0 canonical_publication=0 broker_private_calls=0
broker_writes=0 order_submission=0 live_orders=0 decision_gate=none
execution_planner=none executor=none
"""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

import pymysql
from pymysql.cursors import DictCursor

from src.market_data.native_short_repository_source_identity_v1 import (
    CONTROLLED_CHAIN_4H_UNTRACKED_PATH,
    REPOSITORY_ROOT,
    NativeShortRepositorySourceIdentityError,
    _dirty_counts,
    inspect_running_repository_source,
)
from src.operations import (
    run_native_short_systemd_equivalence_preflight_v1 as systemd_preflight,
)
from src.operations import (
    run_synth_chain_4h_db_environment_preflight_v1 as env_preflight,
)
from src.operations import (
    run_synth_chain_4h_db_grant_preflight_v1 as grant_preflight,
)
from src.operations import persisted_market_candle_freshness_v1 as candle_freshness
from src.operations import persisted_market_price_freshness_v1 as price_freshness
from src.operations.synth_chain_4h_db_authority_v1 import (
    OPERATIONAL_DATABASE,
    REQUIRED_OBJECT_PRIVILEGES,
)
from src.operations.writer_capability_authorization_v1 import (
    REPO_RELATIVE_REGISTRY,
    REPO_RELATIVE_REGISTRY_SCHEMA,
    _validate_writer_file_security,
    capability_entry,
    load_and_validate_registry,
)


RUNNER_NAME = "run_native_short_production_readiness_v1"
RUNNER_VERSION = "0.1"
CAPABILITY_ID = "native_short_4h_chain"
SERVICE_UNIT = systemd_preflight.SERVICE_UNIT
TIMER_UNIT = systemd_preflight.TIMER_UNIT
DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE = "EUR"
DEFAULT_PRIMARY_INTERVAL_CODE = "4h"
DEFAULT_MAX_PRICE_AGE_SECONDS = 900

_SAFETY_MARKERS = {
    "host_mutations": 0,
    "database_writes": 0,
    "systemd_mutations": 0,
    "credential_changes": 0,
    "writer_invocations": 0,
    "canonical_publication": 0,
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
}


class ReadinessEvaluationError(RuntimeError):
    """Raised only when the runner itself cannot safely evaluate a check --
    never used for "the check ran and found a problem" (that is a hard
    blocker instead). Maps to exit code 2."""


@dataclass
class ReadinessOutcome:
    hard_blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def block(self, code: str, detail: str) -> None:
        self.hard_blockers.append(f"{code}: {detail}")

    def warn(self, code: str, detail: str) -> None:
        self.warnings.append(f"{code}: {detail}")

    @property
    def ready(self) -> bool:
        return not self.hard_blockers


# ---------------------------------------------------------------------------
# Registry lookup (shared, not reimplemented).
# ---------------------------------------------------------------------------

def _load_capability_entry(repo_root: Path) -> dict[str, Any]:
    registry_path = repo_root / REPO_RELATIVE_REGISTRY
    schema_path = repo_root / REPO_RELATIVE_REGISTRY_SCHEMA
    result = load_and_validate_registry(registry_path, schema_path, repo_root=repo_root)
    if not result.ok:
        raise ReadinessEvaluationError(
            "REGISTRY_UNAVAILABLE " + "; ".join(result.errors)
        )
    cap = capability_entry(result.payload or {}, CAPABILITY_ID)
    if cap is None:
        raise ReadinessEvaluationError(f"REGISTRY_CAPABILITY_MISSING capability={CAPABILITY_ID}")
    return cap


# ---------------------------------------------------------------------------
# HARD BLOCKER: checkout resolves correctly and is on branch main.
# ---------------------------------------------------------------------------

def _current_branch(repo_root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "symbolic-ref", "-q", "--short", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def check_checkout(outcome: ReadinessOutcome, *, repo_root: Path) -> None:
    try:
        state = inspect_running_repository_source()
    except NativeShortRepositorySourceIdentityError as exc:
        outcome.block("CHECKOUT_UNRESOLVED", str(exc))
        return

    branch = _current_branch(repo_root)
    if branch != "main":
        outcome.block(
            "CHECKOUT_NOT_ON_MAIN",
            f"HEAD is on {branch or 'DETACHED'}, expected main",
        )

    staged, unstaged, untracked = _dirty_counts(
        state.status_porcelain,
        allowed_untracked_path=CONTROLLED_CHAIN_4H_UNTRACKED_PATH,
    )
    if staged or unstaged or untracked:
        outcome.block(
            "CHECKOUT_DIRTY",
            f"staged={staged} unstaged={unstaged} untracked={untracked}",
        )
        return

    controlled_line = f"?? {CONTROLLED_CHAIN_4H_UNTRACKED_PATH}"
    if controlled_line in state.status_porcelain.splitlines():
        outcome.warn(
            "CONTROLLED_UNTRACKED_FILE_PRESENT",
            f"{CONTROLLED_CHAIN_4H_UNTRACKED_PATH} is present (non-critical, always allowed)",
        )


# ---------------------------------------------------------------------------
# HARD BLOCKER: native-short authorization file exists and is readable.
# ---------------------------------------------------------------------------

def check_authorization_file(outcome: ReadinessOutcome, *, cap: dict[str, Any]) -> None:
    guard = cap.get("authorization_guard") if isinstance(cap.get("authorization_guard"), dict) else {}
    raw_path = guard.get("authorization_file")
    if not raw_path:
        outcome.block("AUTHORIZATION_FILE_UNDECLARED", "registry has no authorization_guard.authorization_file")
        return
    path = Path(str(raw_path))
    if not path.exists():
        outcome.block("AUTHORIZATION_FILE_MISSING", str(path))
        return
    reasons = _validate_writer_file_security(path, label="production authorization file")
    if reasons:
        outcome.block("AUTHORIZATION_FILE_INSECURE", "; ".join(reasons))
        return
    if not os.access(path, os.R_OK):
        outcome.block("AUTHORIZATION_FILE_UNREADABLE", str(path))


# ---------------------------------------------------------------------------
# HARD BLOCKER: synth-chain-4h.service exists; User/WorkingDirectory/host
# condition match the canonical gurkdb runtime. WARNING: timer/service state.
# ---------------------------------------------------------------------------

def check_service_identity(outcome: ReadinessOutcome, *, systemctl: str | None) -> None:
    if not systemctl:
        outcome.block("SYSTEMCTL_NOT_FOUND", "systemctl binary not found on PATH")
        return

    state = systemd_preflight._load_unit_state(SERVICE_UNIT, systemctl)
    if state.load_state != "loaded" or state.content is None:
        outcome.block(
            "SERVICE_NOT_INSTALLED",
            f"unit={SERVICE_UNIT} load_state={state.load_state or 'UNAVAILABLE'} "
            f"error={state.error or 'none'}",
        )
        return

    parsed = systemd_preflight._parse_unit(state.content)
    expected = systemd_preflight.EXPECTED_SERVICE_FIELDS
    for key in (
        ("Service", "User"),
        ("Service", "WorkingDirectory"),
        ("Unit", "ConditionHost"),
    ):
        actual = parsed.get(key, ())
        wanted = expected[key]
        if actual != wanted:
            outcome.block(
                "SERVICE_IDENTITY_MISMATCH",
                f"{key[0]}.{key[1]} expected={wanted!r} actual={actual!r}",
            )

    if state.unit_file_state != "enabled" or state.active_state != "active":
        outcome.warn(
            "TIMER_NOT_ACTIVE",
            f"unit={SERVICE_UNIT} unit_file_state={state.unit_file_state or 'UNAVAILABLE'} "
            f"active_state={state.active_state or 'UNAVAILABLE'} "
            "(expected before ACTIVE production cutover; not fatal)",
        )

    result_properties = _systemctl_show(systemctl, SERVICE_UNIT, ("Result", "ExecMainStatus"))
    last_result = result_properties.get("Result", "")
    if last_result and last_result != "success":
        outcome.warn(
            "SERVICE_LAST_RESULT_NOT_SUCCESS",
            f"unit={SERVICE_UNIT} Result={last_result} "
            f"ExecMainStatus={result_properties.get('ExecMainStatus', 'UNAVAILABLE')}",
        )


def _systemctl_show(systemctl: str, unit: str, properties: tuple[str, ...]) -> dict[str, str]:
    try:
        completed = subprocess.run(
            [systemctl, "--system", "show", unit, "--no-pager", f"--property={','.join(properties)}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if completed.returncode != 0:
        return {}
    return systemd_preflight._show_properties(completed.stdout)


# ---------------------------------------------------------------------------
# HARD BLOCKER: required scripts/modules referenced by the chain exist.
# ---------------------------------------------------------------------------

def check_required_entrypoints(outcome: ReadinessOutcome, *, cap: dict[str, Any], repo_root: Path) -> None:
    for wrapper in cap.get("wrappers_invoked", []):
        if not (repo_root / str(wrapper)).is_file():
            outcome.block("WRAPPER_SCRIPT_MISSING", str(wrapper))

    for module_name in cap.get("modules_invoked", []):
        try:
            spec = importlib.util.find_spec(str(module_name))
        except (ImportError, ModuleNotFoundError, ValueError) as exc:
            outcome.block("MODULE_UNRESOLVABLE", f"{module_name}: {exc}")
            continue
        if spec is None:
            outcome.block("MODULE_MISSING", str(module_name))


# ---------------------------------------------------------------------------
# HARD BLOCKERS: DB binding availability, required-object existence, grant
# contract. WARNINGS: public price staleness, candle staleness.
# ---------------------------------------------------------------------------

@contextmanager
def _repository_service_environment(repo_root: Path) -> Iterator[None]:
    """Temporarily inject the repository-committed service unit's own
    ``Environment=`` values into ``os.environ`` for the duration of the
    block, so the closed DB-binding preflight (normally supplied these
    values by systemd) can be exercised from a manual CLI invocation. Reads
    only the checked-in unit file; performs no host mutation. Restores
    whatever value -- or absence -- each variable had immediately before, on
    every exit path."""
    service_path = repo_root / systemd_preflight.SERVICE_REL_PATH
    injected = env_preflight._unit_environment(service_path)
    previous: dict[str, str | None] = {key: os.environ.get(key) for key in injected}
    os.environ.update(injected)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _expected_4h_close_ts_utc(now_utc: datetime) -> datetime:
    """Same rounding-down-to-4h-boundary formula as the canonical
    ``scripts/run_chain_4h.sh`` (``CHAIN_4H_END_TS``); duplicated here only
    as a two-line arithmetic expression, not as a reimplemented contract."""
    hour = (now_utc.hour // 4) * 4
    return now_utc.replace(hour=hour, minute=0, second=0, microsecond=0)


def check_database(outcome: ReadinessOutcome, *, repo_root: Path) -> None:
    with _repository_service_environment(repo_root):
        try:
            env_preflight.run_preflight(
                environ=os.environ,
                service_path=repo_root / systemd_preflight.SERVICE_REL_PATH,
            )
        except env_preflight.EnvironmentPreflightError as exc:
            outcome.block("DB_BINDING_UNAVAILABLE", str(exc))
            return

        try:
            grant_config = grant_preflight.load_candidate_config(os.environ)
        except grant_preflight.PreflightConfigurationError as exc:
            outcome.block("DB_BINDING_UNAVAILABLE", str(exc))
            return

        try:
            grant_result = grant_preflight.run_preflight(grant_config)
        except grant_preflight.PreflightConnectionError as exc:
            outcome.block("DB_CONNECTION_FAILED", str(exc))
            return

        if not grant_result.audit.passed:
            outcome.block(
                "GRANT_CONTRACT_MISMATCH",
                f"missing={','.join(grant_result.audit.missing) or 'none'} "
                f"unexpected={','.join(grant_result.audit.unexpected) or 'none'} "
                f"violations={','.join(grant_result.audit.violations) or 'none'}",
            )

        _check_schema_and_freshness(outcome, config=grant_config)


def _check_schema_and_freshness(outcome: ReadinessOutcome, *, config: Any) -> None:
    conn = None
    try:
        conn = pymysql.connect(
            host=config.host,
            port=config.port,
            user=config.user,
            password=config.password,
            database=config.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
        )
    except Exception as exc:  # noqa: BLE001 - already covered by grant_preflight; defensive only
        outcome.block("DB_CONNECTION_FAILED", f"error_type={type(exc).__name__}")
        return

    try:
        with conn.cursor() as cur:
            cur.execute("START TRANSACTION READ ONLY")
            cur.execute(
                "SELECT TABLE_NAME FROM information_schema.tables "
                "WHERE TABLE_SCHEMA = %s",
                (OPERATIONAL_DATABASE,),
            )
            existing = {str(row["TABLE_NAME"]) for row in cur.fetchall()}
        missing_objects = sorted(set(REQUIRED_OBJECT_PRIVILEGES) - existing)
        if missing_objects:
            outcome.block(
                "REQUIRED_OBJECT_MISSING",
                f"database={OPERATIONAL_DATABASE} objects={','.join(missing_objects)}",
            )

        now_utc = datetime.now(UTC)
        price_row = price_freshness.fetch_latest_persisted_price_batch(
            conn, venue=DEFAULT_VENUE, quote_currency=DEFAULT_QUOTE
        )
        price_result = price_freshness.classify_persisted_price_batch(
            price_row,
            now_utc=now_utc,
            stale_after=timedelta(seconds=DEFAULT_MAX_PRICE_AGE_SECONDS),
        )
        if not price_result.is_fresh:
            outcome.warn(
                "PUBLIC_PRICE_STALE",
                f"classification={price_result.freshness_classification} reason={price_result.reason}",
            )

        expected_close = _expected_4h_close_ts_utc(now_utc)
        candle_row = candle_freshness.fetch_persisted_candle_boundary(
            conn,
            venue=DEFAULT_VENUE,
            interval_code=DEFAULT_PRIMARY_INTERVAL_CODE,
            expected_close_ts_utc=expected_close,
        )
        candle_result = candle_freshness.classify_persisted_candle_boundary(
            candle_row, expected_close_ts_utc=expected_close
        )
        if not candle_result.is_fresh:
            outcome.warn(
                "EXPECTED_CANDLE_NOT_PERSISTED",
                f"classification={candle_result.freshness_classification} "
                f"reason={candle_result.reason} expected_close={expected_close.isoformat()}",
            )
    except Exception as exc:  # noqa: BLE001 - a query failure is a real, reportable condition
        outcome.block("DATABASE_QUERY_FAILED", f"error_type={type(exc).__name__}")
    finally:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass


# ---------------------------------------------------------------------------
# Top-level orchestration.
# ---------------------------------------------------------------------------

def evaluate_readiness(*, repo_root: Path | None = None) -> ReadinessOutcome:
    root = repo_root or REPOSITORY_ROOT
    outcome = ReadinessOutcome()

    check_checkout(outcome, repo_root=root)
    cap = _load_capability_entry(root)
    check_authorization_file(outcome, cap=cap)
    check_required_entrypoints(outcome, cap=cap, repo_root=root)
    check_service_identity(outcome, systemctl=shutil.which("systemctl"))
    check_database(outcome, repo_root=root)

    return outcome


def _result_document(outcome: ReadinessOutcome) -> dict[str, Any]:
    return {
        "event": "RESULT",
        "runner": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "ready": outcome.ready,
        "hard_blocker_count": len(outcome.hard_blockers),
        "warning_count": len(outcome.warnings),
        "hard_blockers": list(outcome.hard_blockers),
        "warnings": list(outcome.warnings),
        **_SAFETY_MARKERS,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lightweight read-only native SHORT production readiness check."
    )
    parser.parse_args(argv)

    print(
        f"STARTED runner={RUNNER_NAME} mode=read_only worker_count=1 "
        f"capability={CAPABILITY_ID}",
        file=sys.stderr,
        flush=True,
    )

    try:
        outcome = evaluate_readiness()
    except ReadinessEvaluationError as exc:
        payload = {
            "event": "FAILED",
            "runner": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "ready": False,
            "reason_code": "READINESS_EVALUATION_FAILED",
            "detail": str(exc),
            **_SAFETY_MARKERS,
        }
        print(json.dumps(payload, sort_keys=True))
        return 2
    except Exception as exc:  # noqa: BLE001 - fail closed: never claim ready on a surprise.
        payload = {
            "event": "FAILED",
            "runner": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "ready": False,
            "reason_code": "READINESS_EVALUATION_FAILED",
            "detail": f"{type(exc).__name__}: {exc}",
            **_SAFETY_MARKERS,
        }
        print(json.dumps(payload, sort_keys=True))
        return 2

    for blocker in outcome.hard_blockers:
        print(f"HARD_BLOCKER {blocker}", file=sys.stderr, flush=True)
    for warning in outcome.warnings:
        print(f"WARNING {warning}", file=sys.stderr, flush=True)

    document = _result_document(outcome)
    print(json.dumps(document, sort_keys=True))
    return 0 if outcome.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
