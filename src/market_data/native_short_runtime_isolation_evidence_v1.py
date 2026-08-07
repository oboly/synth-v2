from __future__ import annotations

"""Canonical MULTI_SCOPE_FAILURE_ISOLATION_MISSING evidence contract.

Boundary: native SHORT market-data, read-only, market-only, account-agnostic.
This module evaluates evidence only. It performs no database I/O, no
mutation, no promotion, and no writer-capability authorization. It never
calls or wraps ``execute_scope_administration``, and it never widens or
weakens the existing gate matrix
(``native_short_scope_administration_transaction_v1._APPLICABLE_GLOBAL_BLOCKERS_BY_OPERATION``),
which is unchanged. Its result is consumed only by
``native_short_multi_asset_audit_v1.evaluate_global_blockers``, which uses it
to decide whether one named global blocker is still active.

Why this module exists
----------------------
``MULTI_SCOPE_FAILURE_ISOLATION_MISSING`` was introduced as an
unconditionally hardcoded, implementation-pending blocker: at the time, the
native SHORT runtime chain evaluated every supported scope inside a single
shared transaction, so one scope's failure could roll back unrelated scopes'
committed work. Promoting additional scopes while that was true would have
multiplied a single-scope defect across the whole supported set, so the
blocker correctly refused every ``PROMOTE_SCOPE``.

Issue #200 (commit ``4c4d3c0e8a54250ae957364adb7af4858fe8170e``, "Add
per-scope transaction isolation to native SHORT runtime chain") restructured
the chain so each exact canonical scope owns its own transaction boundary and
its own rollback domain. That is the substantive condition the blocker was
waiting for.

A hardcoded ``active`` was honest while no evidence source existed, but it is
the wrong shape now: it cannot distinguish "the guarantee is present" from
"nobody updated the constant". This module replaces the hardcoded state with
deterministic, machine-readable evidence, so the blocker closes only while
the guarantee is genuinely present in the code the runtime would execute, and
re-opens by itself the instant that regresses.

What counts as evidence (both are required)
-------------------------------------------
1. **Ancestry** -- the exact reviewed implementation commit
   (``ISOLATION_IMPLEMENTATION_COMMIT``) must be an ancestor of (or equal to)
   the current ``HEAD``. This is the same weak, non-circular ancestry
   property ``native_short_promotion_bootstrap_evidence_v1`` already uses: a
   fixed, already-existing, immutable historical commit, checked with ``git
   merge-base --is-ancestor``, never compared for equality against ``HEAD``.
   Ancestry alone proves the change landed on this line of history; it does
   not prove the guarantee still holds, which is why check 2 exists.

2. **Structural runtime contract** -- the live runtime module
   ``src.market_data.run_native_short_scope_status_chain_v1`` must actually
   still expose the exact per-scope-isolation contract surface #200
   introduced: the declared transaction boundary and failure policy, the
   per-scope terminal status vocabulary, the per-scope result dataclass
   shape, the runtime result's ``scope_results`` evidence field, and the
   ``evaluate_and_project_scope`` entrypoint the isolated per-scope
   transaction is built around.

   This is deliberately an inspection of the *live imported module*, not a
   narrative claim and not a test-existence claim: it reads the same code the
   runtime would execute. A later commit that renames, removes, or
   semantically regresses any of these (for example reverting
   ``TRANSACTION_BOUNDARY`` to a chain-wide value) fails this check closed
   automatically, without anyone remembering to re-open the blocker -- even
   though the #200 commit would still be an ancestor forever.

Fail-closed in every direction: ancestry false, ancestry check unavailable
(any subprocess/git error), runtime module import failure, a missing
attribute, a wrong-valued attribute, or a wrong dataclass field set all
return ``confirmed=False`` with a distinct reason code. An unavailable check
is never treated as a passed check.

Scope limits (what this evidence does NOT claim)
------------------------------------------------
This module states only that per-scope *transaction/rollback* isolation is
present. It makes no claim about ``BOOTSTRAP_ORCHESTRATION_BLOCKED``, which
remains active for an independent, still-unresolved reason: the runtime
chain deliberately treats a domain ``BLOCKED`` scope (including a brand-new
scope's expected, transient ``NO_CURRENT_MAP`` state) as a hard stop for the
whole run. See
``docs/ops/native_short_bootstrap_orchestration_blocked_evidence_v1.md``.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
"""

import dataclasses
import importlib
import subprocess
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable, Mapping

from src.market_data.native_short_repository_source_identity_v1 import (
    REPOSITORY_ROOT,
)


ISOLATION_EVIDENCE_CONTRACT_VERSION = "native_short_runtime_isolation_evidence_v1"

# The exact reviewed implementation commit for Issue #200 / PR #274,
# "Add per-scope transaction isolation to native SHORT runtime chain (#200)".
# An ordinary, already-existing, immutable historical commit -- never the
# commit that introduces this module itself, and never compared against HEAD
# for equality (only for ancestry). See module docstring.
ISOLATION_IMPLEMENTATION_COMMIT = "4c4d3c0e8a54250ae957364adb7af4858fe8170e"

RUNTIME_CHAIN_MODULE = "src.market_data.run_native_short_scope_status_chain_v1"

# Exact scalar attribute values #200 established. A rename or a semantic
# regression (e.g. TRANSACTION_BOUNDARY back to a chain-wide value) fails
# closed here.
REQUIRED_RUNTIME_ATTRIBUTE_VALUES: Mapping[str, str] = {
    "TRANSACTION_BOUNDARY": "exact_scope",
    "FAILURE_POLICY": "continue_on_unexpected_stop_on_blocked",
    "SCOPE_STATUS_SUCCEEDED": "SUCCEEDED",
    "SCOPE_STATUS_SKIPPED_NOT_SUPPORTED": "SKIPPED_NOT_SUPPORTED",
    "SCOPE_STATUS_BLOCKED": "BLOCKED",
    "SCOPE_STATUS_UNEXPECTED_FAILED": "UNEXPECTED_FAILED",
}

# Exact per-scope result dataclass shape: one attributable terminal record
# per canonical scope is what makes per-scope outcomes independently
# reportable rather than collapsed into one run-level status.
REQUIRED_SCOPE_RESULT_FIELDS: tuple[str, ...] = ("key", "status", "detail")

# The runtime result must still carry per-scope evidence (a subset check:
# other fields may be added without invalidating the guarantee).
REQUIRED_RUNTIME_RESULT_FIELDS: tuple[str, ...] = ("scope_results",)

# The per-scope evaluation entrypoint the isolated transaction wraps.
REQUIRED_RUNTIME_CALLABLES: tuple[str, ...] = ("evaluate_and_project_scope",)

REASON_IMPLEMENTATION_COMMIT_NOT_ANCESTOR = "IMPLEMENTATION_COMMIT_NOT_ANCESTOR"
REASON_ANCESTRY_CHECK_UNAVAILABLE = "ANCESTRY_CHECK_UNAVAILABLE"
REASON_RUNTIME_MODULE_IMPORT_FAILED = "RUNTIME_MODULE_IMPORT_FAILED"
REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISSING = "RUNTIME_CONTRACT_ATTRIBUTE_MISSING"
REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISMATCH = "RUNTIME_CONTRACT_ATTRIBUTE_MISMATCH"
REASON_EVIDENCE_CONFIRMED = "EVIDENCE_CONFIRMED"


AncestryChecker = Callable[[str], bool]
RuntimeModuleProvider = Callable[[], ModuleType]


def _default_ancestry_checker(commit: str) -> bool:
    """Real git ancestry check: is ``commit`` an ancestor of (or equal to)
    the current ``HEAD``? Fails closed (returns ``False``) on any git or
    subprocess error -- an unavailable check is never treated as a passed
    check.

    Intentionally an exact, independent mirror of
    ``native_short_promotion_bootstrap_evidence_v1._default_ancestry_checker``
    rather than a shared import: these two evidence contracts are deliberately
    independent of each other, and coupling them through a shared helper would
    let a change made for one silently alter the other's fail-closed
    behavior. The duplication is ~15 lines and is the cheaper risk.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "merge-base", "--is-ancestor", commit, "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _default_runtime_module_provider() -> ModuleType:
    """Import the live runtime chain module. Any import failure propagates and
    is converted to a fail-closed result by the caller."""
    return importlib.import_module(RUNTIME_CHAIN_MODULE)


@dataclass(frozen=True)
class RuntimeIsolationEvaluation:
    """Deterministic, read-only evaluation result. Never a decision to act."""

    confirmed: bool
    reason: str
    implementation_commit: str = ISOLATION_IMPLEMENTATION_COMMIT
    detail: str | None = None


def _dataclass_field_names(value: Any) -> tuple[str, ...] | None:
    if not dataclasses.is_dataclass(value):
        return None
    return tuple(field.name for field in dataclasses.fields(value))


def _evaluate_runtime_contract(runtime: ModuleType) -> RuntimeIsolationEvaluation | None:
    """Verify the live runtime module still exposes #200's exact per-scope
    isolation contract surface. Returns ``None`` when every check passes, or a
    fail-closed evaluation naming the first defect found."""
    for name, expected in REQUIRED_RUNTIME_ATTRIBUTE_VALUES.items():
        if not hasattr(runtime, name):
            return RuntimeIsolationEvaluation(
                False, REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISSING, detail=name
            )
        actual = getattr(runtime, name)
        if actual != expected:
            return RuntimeIsolationEvaluation(
                False,
                REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISMATCH,
                detail=f"{name}: expected {expected!r}, found {actual!r}",
            )

    for name in REQUIRED_RUNTIME_CALLABLES:
        if not hasattr(runtime, name):
            return RuntimeIsolationEvaluation(
                False, REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISSING, detail=name
            )
        if not callable(getattr(runtime, name)):
            return RuntimeIsolationEvaluation(
                False,
                REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISMATCH,
                detail=f"{name}: not callable",
            )

    if not hasattr(runtime, "ScopeChainResult"):
        return RuntimeIsolationEvaluation(
            False, REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISSING, detail="ScopeChainResult"
        )
    scope_fields = _dataclass_field_names(runtime.ScopeChainResult)
    if scope_fields is None:
        return RuntimeIsolationEvaluation(
            False,
            REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISMATCH,
            detail="ScopeChainResult: not a dataclass",
        )
    # Exact field set: a per-scope terminal record that gained or lost a field
    # is a contract change that must be re-reviewed, not silently accepted.
    if scope_fields != REQUIRED_SCOPE_RESULT_FIELDS:
        return RuntimeIsolationEvaluation(
            False,
            REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISMATCH,
            detail=(
                f"ScopeChainResult fields: expected {REQUIRED_SCOPE_RESULT_FIELDS!r}, "
                f"found {scope_fields!r}"
            ),
        )

    if not hasattr(runtime, "RuntimeResult"):
        return RuntimeIsolationEvaluation(
            False, REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISSING, detail="RuntimeResult"
        )
    runtime_fields = _dataclass_field_names(runtime.RuntimeResult)
    if runtime_fields is None:
        return RuntimeIsolationEvaluation(
            False,
            REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISMATCH,
            detail="RuntimeResult: not a dataclass",
        )
    # Subset check by design: the run-level result legitimately carries other
    # run accounting; only the per-scope evidence field is contractual here.
    missing = [name for name in REQUIRED_RUNTIME_RESULT_FIELDS if name not in runtime_fields]
    if missing:
        return RuntimeIsolationEvaluation(
            False,
            REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISSING,
            detail=f"RuntimeResult.{','.join(missing)}",
        )

    return None


def evaluate_multi_scope_failure_isolation_evidence(
    *,
    ancestry_checker: AncestryChecker = _default_ancestry_checker,
    runtime_module_provider: RuntimeModuleProvider = _default_runtime_module_provider,
) -> RuntimeIsolationEvaluation:
    """Evaluate whether per-scope runtime failure isolation (#200) is present.

    Fail-closed: returns ``confirmed=False`` unless the reviewed
    implementation commit is an ancestor of the current checkout **and** the
    live runtime chain module still exposes #200's exact per-scope isolation
    contract surface. See the module docstring for why both are required.

    Performs no database access and takes no ``conn``: this is repository and
    import inspection only. It authorizes nothing by itself -- its result only
    feeds one named global blocker's active/closed state.
    """
    try:
        is_ancestor = ancestry_checker(ISOLATION_IMPLEMENTATION_COMMIT)
    except Exception as exc:  # noqa: BLE001 - any ancestry-check failure fails closed.
        return RuntimeIsolationEvaluation(
            False,
            REASON_ANCESTRY_CHECK_UNAVAILABLE,
            detail=f"{type(exc).__name__}: {exc}",
        )
    if not is_ancestor:
        return RuntimeIsolationEvaluation(False, REASON_IMPLEMENTATION_COMMIT_NOT_ANCESTOR)

    try:
        runtime = runtime_module_provider()
    except Exception as exc:  # noqa: BLE001 - any import failure fails closed.
        return RuntimeIsolationEvaluation(
            False,
            REASON_RUNTIME_MODULE_IMPORT_FAILED,
            detail=f"{type(exc).__name__}: {exc}",
        )

    contract_failure = _evaluate_runtime_contract(runtime)
    if contract_failure is not None:
        return contract_failure

    return RuntimeIsolationEvaluation(True, REASON_EVIDENCE_CONFIRMED)


__all__ = [
    "ISOLATION_EVIDENCE_CONTRACT_VERSION",
    "ISOLATION_IMPLEMENTATION_COMMIT",
    "RUNTIME_CHAIN_MODULE",
    "REQUIRED_RUNTIME_ATTRIBUTE_VALUES",
    "REQUIRED_SCOPE_RESULT_FIELDS",
    "REQUIRED_RUNTIME_RESULT_FIELDS",
    "REQUIRED_RUNTIME_CALLABLES",
    "REASON_IMPLEMENTATION_COMMIT_NOT_ANCESTOR",
    "REASON_ANCESTRY_CHECK_UNAVAILABLE",
    "REASON_RUNTIME_MODULE_IMPORT_FAILED",
    "REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISSING",
    "REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISMATCH",
    "REASON_EVIDENCE_CONFIRMED",
    "AncestryChecker",
    "RuntimeModuleProvider",
    "RuntimeIsolationEvaluation",
    "evaluate_multi_scope_failure_isolation_evidence",
]
