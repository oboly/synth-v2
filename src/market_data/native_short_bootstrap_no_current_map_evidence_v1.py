from __future__ import annotations

"""Canonical BOOTSTRAP_ORCHESTRATION_BLOCKED evidence contract.

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
``BOOTSTRAP_ORCHESTRATION_BLOCKED`` was introduced as an unconditionally
hardcoded blocker because of one exact runtime property: a newly promoted
supported scope has no first current map yet, that state classified as a
domain ``BLOCKED`` gate decision, and the runtime chain treats ``BLOCKED`` as
a hard stop -- so promoting one new scope halted evaluation of unrelated,
already-established scopes ordered after it. Refusing every ``PROMOTE_SCOPE``
while that was true was correct.

Issue #298 resolved that as a classification defect rather than by weakening
``BLOCKED``. A projection with no selected current map arises from two
different ledger situations, and only one is an integrity defect:

* zero ``native_short_map_v1`` rows have *ever* existed for the exact
  canonical scope key -- the expected, transient first-map bootstrap state of
  a scope that has never published any map;
* map rows exist historically but none is currently selected (for example an
  established scope whose maps are all SUPERSEDED with no successor) -- an
  *unexpectedly* missing current map, which stays ``BLOCKED``.

Only the first is exempted, through an explicit canonical branch
(``EXPECTED_BOOTSTRAP_NO_CURRENT_MAP``) driven by a pure ledger-existence
predicate: independent of ``as_of_utc``, independent of lifecycle state, and
deliberately not a timing/ordering/grace-window inference. Such a scope
commits its own exact-scope transaction, is recorded as its own attributable
per-scope status (``BOOTSTRAP_PENDING``, never misreported as plain success),
and does not stop the loop.

A hardcoded ``active`` was honest while no evidence source existed, but it is
the wrong shape now: it cannot distinguish "the guarantee is present" from
"nobody updated the constant". This module replaces the hardcoded state with
deterministic, machine-readable evidence, so the blocker closes only while
the guarantee is genuinely present in the code the runtime would execute, and
re-opens by itself the instant that regresses.

What counts as evidence (both are required)
-------------------------------------------
1. **Ancestry** -- the reviewed per-scope transaction isolation commit
   (``PREREQUISITE_IMPLEMENTATION_COMMIT``, Issue #200) must be an ancestor of
   (or equal to) the current ``HEAD``. This bootstrap guarantee is only
   meaningful on top of per-scope transaction isolation: continuing to the
   next scope is worth nothing if that scope's writes share a rollback domain
   with the bootstrap scope's. It is the same weak, non-circular ancestry
   property ``native_short_promotion_bootstrap_evidence_v1`` and
   ``native_short_runtime_isolation_evidence_v1`` already use: a fixed,
   already-existing, immutable historical commit, checked with ``git
   merge-base --is-ancestor``, never compared for equality against ``HEAD``.

   This deliberately does *not* pin the #298 implementation commit itself.
   That commit has no stable SHA at authoring time, and pinning it would add
   nothing: check 2 inspects the live modules directly, which is strictly
   stronger evidence that *this* fix is present than any commit hash.

2. **Structural runtime contract** -- the live modules must actually still
   expose the exact bootstrap-classification surface #298 introduced: the
   canonical branch constant and its exact value, the
   ``never_published_any_map`` gate parameter that carries the ledger
   predicate, the per-scope outcome's ``bootstrap_pending`` evidence field,
   and the runtime chain's ``BOOTSTRAP_PENDING`` per-scope status.

   This is an inspection of the *live imported modules*, not a narrative
   claim and not a test-existence claim: it reads the same code the runtime
   would execute. A later commit that renames, removes, or semantically
   regresses any of these (for example dropping the
   ``never_published_any_map`` parameter, which would collapse the bootstrap
   case back into ``BLOCKED``) fails this check closed automatically, without
   anyone remembering to re-open the blocker.

Fail-closed in every direction: ancestry false, ancestry check unavailable
(any subprocess/git error), module import failure, a missing attribute, a
wrong-valued attribute, a missing signature parameter, or a wrong dataclass
field set all return ``confirmed=False`` with a distinct reason code. An
unavailable check is never treated as a passed check.

Scope limits (what this evidence does NOT claim)
------------------------------------------------
This module states only that the expected first-map bootstrap state is
classified distinctly and does not halt unrelated scopes. It makes no claim
about any scope's actual production readiness, about the approved rollout
universe, about candle freshness, and it does not authorize any promotion.

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
import inspect
import subprocess
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable, Mapping

from src.market_data.native_short_repository_source_identity_v1 import (
    REPOSITORY_ROOT,
)


BOOTSTRAP_EVIDENCE_CONTRACT_VERSION = "native_short_bootstrap_no_current_map_evidence_v1"

# The reviewed per-scope transaction isolation commit for Issue #200 / PR #274,
# "Add per-scope transaction isolation to native SHORT runtime chain (#200)" --
# the prerequisite this bootstrap guarantee stands on. An ordinary,
# already-existing, immutable historical commit; never compared against HEAD
# for equality (only for ancestry). See module docstring.
PREREQUISITE_IMPLEMENTATION_COMMIT = "4c4d3c0e8a54250ae957364adb7af4858fe8170e"

MAP_LEVEL_STATUS_MODULE = "src.market_data.native_short_map_level_status_materializer_v1"
SCOPE_STATUS_MATERIALIZER_MODULE = "src.market_data.native_short_scope_status_materializer_v1"
RUNTIME_CHAIN_MODULE = "src.market_data.run_native_short_scope_status_chain_v1"

INSPECTED_MODULES: tuple[str, ...] = (
    MAP_LEVEL_STATUS_MODULE,
    SCOPE_STATUS_MATERIALIZER_MODULE,
    RUNTIME_CHAIN_MODULE,
)

# Exact scalar attribute values #298 established, per module. A rename or a
# value change is a contract change that must be re-reviewed, not silently
# accepted.
REQUIRED_MODULE_ATTRIBUTE_VALUES: Mapping[str, Mapping[str, str]] = {
    MAP_LEVEL_STATUS_MODULE: {
        "EXPECTED_BOOTSTRAP_NO_CURRENT_MAP": "EXPECTED_BOOTSTRAP_NO_CURRENT_MAP",
    },
    RUNTIME_CHAIN_MODULE: {
        "SCOPE_STATUS_BOOTSTRAP_PENDING": "BOOTSTRAP_PENDING",
    },
}

# The gate function and the exact parameter carrying the ledger-existence
# predicate. Without this parameter the bootstrap case cannot be distinguished
# from a genuine integrity BLOCKED state at all.
GATE_DECISION_CALLABLE = "select_gate_decision"
GATE_DECISION_REQUIRED_PARAMETER = "never_published_any_map"

# The per-scope outcome's attributable bootstrap evidence field (subset check
# by design: the outcome legitimately carries other per-scope accounting).
SCOPE_CHAIN_OUTCOME_DATACLASS = "ScopeChainOutcome"
REQUIRED_SCOPE_CHAIN_OUTCOME_FIELDS: tuple[str, ...] = ("bootstrap_pending",)

REASON_PREREQUISITE_COMMIT_NOT_ANCESTOR = "PREREQUISITE_COMMIT_NOT_ANCESTOR"
REASON_ANCESTRY_CHECK_UNAVAILABLE = "ANCESTRY_CHECK_UNAVAILABLE"
REASON_MODULE_IMPORT_FAILED = "MODULE_IMPORT_FAILED"
REASON_CONTRACT_ATTRIBUTE_MISSING = "CONTRACT_ATTRIBUTE_MISSING"
REASON_CONTRACT_ATTRIBUTE_MISMATCH = "CONTRACT_ATTRIBUTE_MISMATCH"
REASON_CONTRACT_SIGNATURE_PARAMETER_MISSING = "CONTRACT_SIGNATURE_PARAMETER_MISSING"
REASON_CONTRACT_DATACLASS_FIELD_MISSING = "CONTRACT_DATACLASS_FIELD_MISSING"
REASON_EVIDENCE_CONFIRMED = "EVIDENCE_CONFIRMED"


AncestryChecker = Callable[[str], bool]
ModuleProvider = Callable[[str], ModuleType]


def _default_ancestry_checker(commit: str) -> bool:
    """Real git ancestry check: is ``commit`` an ancestor of (or equal to)
    the current ``HEAD``? Fails closed (returns ``False``) on any git or
    subprocess error -- an unavailable check is never treated as a passed
    check.

    Intentionally an exact, independent mirror of the same private helper in
    ``native_short_promotion_bootstrap_evidence_v1`` and
    ``native_short_runtime_isolation_evidence_v1`` rather than a shared
    import: these evidence contracts are deliberately independent of each
    other, and coupling them through a shared helper would let a change made
    for one silently alter another's fail-closed behavior. The duplication is
    ~15 lines and is the cheaper risk.
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


def _default_module_provider(module_name: str) -> ModuleType:
    """Import one live module by name. Any import failure propagates and is
    converted to a fail-closed result by the caller."""
    return importlib.import_module(module_name)


@dataclass(frozen=True)
class BootstrapEvidenceEvaluation:
    """Deterministic, read-only evaluation result. Never a decision to act."""

    confirmed: bool
    reason: str
    prerequisite_commit: str = PREREQUISITE_IMPLEMENTATION_COMMIT
    detail: str | None = None


def _dataclass_field_names(value: Any) -> tuple[str, ...] | None:
    if not dataclasses.is_dataclass(value):
        return None
    return tuple(field.name for field in dataclasses.fields(value))


def _evaluate_attribute_values(
    modules: Mapping[str, ModuleType],
) -> BootstrapEvidenceEvaluation | None:
    for module_name, expected_values in REQUIRED_MODULE_ATTRIBUTE_VALUES.items():
        module = modules[module_name]
        for name, expected in expected_values.items():
            if not hasattr(module, name):
                return BootstrapEvidenceEvaluation(
                    False,
                    REASON_CONTRACT_ATTRIBUTE_MISSING,
                    detail=f"{module_name}.{name}",
                )
            actual = getattr(module, name)
            if actual != expected:
                return BootstrapEvidenceEvaluation(
                    False,
                    REASON_CONTRACT_ATTRIBUTE_MISMATCH,
                    detail=f"{module_name}.{name}: expected {expected!r}, found {actual!r}",
                )
    return None


def _evaluate_gate_signature(
    modules: Mapping[str, ModuleType],
) -> BootstrapEvidenceEvaluation | None:
    module = modules[MAP_LEVEL_STATUS_MODULE]
    if not hasattr(module, GATE_DECISION_CALLABLE):
        return BootstrapEvidenceEvaluation(
            False,
            REASON_CONTRACT_ATTRIBUTE_MISSING,
            detail=f"{MAP_LEVEL_STATUS_MODULE}.{GATE_DECISION_CALLABLE}",
        )
    gate = getattr(module, GATE_DECISION_CALLABLE)
    if not callable(gate):
        return BootstrapEvidenceEvaluation(
            False,
            REASON_CONTRACT_ATTRIBUTE_MISMATCH,
            detail=f"{GATE_DECISION_CALLABLE}: not callable",
        )
    try:
        signature = inspect.signature(gate)
    except (TypeError, ValueError) as exc:
        return BootstrapEvidenceEvaluation(
            False,
            REASON_CONTRACT_SIGNATURE_PARAMETER_MISSING,
            detail=f"{GATE_DECISION_CALLABLE}: {type(exc).__name__}: {exc}",
        )
    if GATE_DECISION_REQUIRED_PARAMETER not in signature.parameters:
        return BootstrapEvidenceEvaluation(
            False,
            REASON_CONTRACT_SIGNATURE_PARAMETER_MISSING,
            detail=f"{GATE_DECISION_CALLABLE}.{GATE_DECISION_REQUIRED_PARAMETER}",
        )
    return None


def _evaluate_scope_chain_outcome(
    modules: Mapping[str, ModuleType],
) -> BootstrapEvidenceEvaluation | None:
    module = modules[SCOPE_STATUS_MATERIALIZER_MODULE]
    if not hasattr(module, SCOPE_CHAIN_OUTCOME_DATACLASS):
        return BootstrapEvidenceEvaluation(
            False,
            REASON_CONTRACT_ATTRIBUTE_MISSING,
            detail=f"{SCOPE_STATUS_MATERIALIZER_MODULE}.{SCOPE_CHAIN_OUTCOME_DATACLASS}",
        )
    outcome_fields = _dataclass_field_names(getattr(module, SCOPE_CHAIN_OUTCOME_DATACLASS))
    if outcome_fields is None:
        return BootstrapEvidenceEvaluation(
            False,
            REASON_CONTRACT_ATTRIBUTE_MISMATCH,
            detail=f"{SCOPE_CHAIN_OUTCOME_DATACLASS}: not a dataclass",
        )
    missing = [name for name in REQUIRED_SCOPE_CHAIN_OUTCOME_FIELDS if name not in outcome_fields]
    if missing:
        return BootstrapEvidenceEvaluation(
            False,
            REASON_CONTRACT_DATACLASS_FIELD_MISSING,
            detail=f"{SCOPE_CHAIN_OUTCOME_DATACLASS}.{','.join(missing)}",
        )
    return None


def evaluate_bootstrap_no_current_map_evidence(
    *,
    ancestry_checker: AncestryChecker = _default_ancestry_checker,
    module_provider: ModuleProvider = _default_module_provider,
) -> BootstrapEvidenceEvaluation:
    """Evaluate whether the expected first-map bootstrap guarantee (#298) is present.

    Fail-closed: returns ``confirmed=False`` unless the prerequisite per-scope
    isolation commit is an ancestor of the current checkout **and** the live
    modules still expose #298's exact bootstrap-classification contract
    surface. See the module docstring for why both are required.

    Performs no database access and takes no ``conn``: this is repository and
    import inspection only. It authorizes nothing by itself -- its result only
    feeds one named global blocker's active/closed state.
    """
    try:
        is_ancestor = ancestry_checker(PREREQUISITE_IMPLEMENTATION_COMMIT)
    except Exception as exc:  # noqa: BLE001 - any ancestry-check failure fails closed.
        return BootstrapEvidenceEvaluation(
            False,
            REASON_ANCESTRY_CHECK_UNAVAILABLE,
            detail=f"{type(exc).__name__}: {exc}",
        )
    if not is_ancestor:
        return BootstrapEvidenceEvaluation(False, REASON_PREREQUISITE_COMMIT_NOT_ANCESTOR)

    modules: dict[str, ModuleType] = {}
    for module_name in INSPECTED_MODULES:
        try:
            modules[module_name] = module_provider(module_name)
        except Exception as exc:  # noqa: BLE001 - any import failure fails closed.
            return BootstrapEvidenceEvaluation(
                False,
                REASON_MODULE_IMPORT_FAILED,
                detail=f"{module_name}: {type(exc).__name__}: {exc}",
            )

    for check in (
        _evaluate_attribute_values,
        _evaluate_gate_signature,
        _evaluate_scope_chain_outcome,
    ):
        failure = check(modules)
        if failure is not None:
            return failure

    return BootstrapEvidenceEvaluation(True, REASON_EVIDENCE_CONFIRMED)


__all__ = [
    "BOOTSTRAP_EVIDENCE_CONTRACT_VERSION",
    "PREREQUISITE_IMPLEMENTATION_COMMIT",
    "MAP_LEVEL_STATUS_MODULE",
    "SCOPE_STATUS_MATERIALIZER_MODULE",
    "RUNTIME_CHAIN_MODULE",
    "INSPECTED_MODULES",
    "REQUIRED_MODULE_ATTRIBUTE_VALUES",
    "GATE_DECISION_CALLABLE",
    "GATE_DECISION_REQUIRED_PARAMETER",
    "SCOPE_CHAIN_OUTCOME_DATACLASS",
    "REQUIRED_SCOPE_CHAIN_OUTCOME_FIELDS",
    "REASON_PREREQUISITE_COMMIT_NOT_ANCESTOR",
    "REASON_ANCESTRY_CHECK_UNAVAILABLE",
    "REASON_MODULE_IMPORT_FAILED",
    "REASON_CONTRACT_ATTRIBUTE_MISSING",
    "REASON_CONTRACT_ATTRIBUTE_MISMATCH",
    "REASON_CONTRACT_SIGNATURE_PARAMETER_MISSING",
    "REASON_CONTRACT_DATACLASS_FIELD_MISSING",
    "REASON_EVIDENCE_CONFIRMED",
    "AncestryChecker",
    "ModuleProvider",
    "BootstrapEvidenceEvaluation",
    "evaluate_bootstrap_no_current_map_evidence",
]
