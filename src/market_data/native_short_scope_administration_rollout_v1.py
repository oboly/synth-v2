from __future__ import annotations

"""Deterministic multi-symbol Native SHORT scope-administration rollout
orchestrator.

Boundary: this module owns explicit-universe iteration and per-scope
delegation only. It creates no database connection, no writer, no service, no
timer, and no direct SQL. Every scope-level decision, lock, transaction,
revalidation, and mutation is delegated unchanged to
``native_short_scope_administration_transaction_v1`` -- the sole canonical
transaction owner (``plan_scope_administration`` /
``execute_scope_administration``). This module never calls
``evaluate_current_global_blockers`` or ``decide_administration`` itself and
never performs writer-capability authorization: it accepts an
already-validated ``WriterMutationAuthorization`` from its caller and passes
it straight through to ``execute_scope_administration`` for every scope,
exactly as the existing single-scope CLI
(``run_native_short_scope_administration_v1.py``) does.

Approved rollout universe:

The initial approved rollout universe is exactly
``APPROVED_ROLLOUT_UNIVERSE_V1`` below -- a checked-in, reviewed, ordered
tuple. It is never inferred from wallet holdings, Profit Plan cards, account
state, or ``selection_engine`` output. CLI input (``--only-symbol``) may
*select a subset* of this checked-in universe; it can never add a symbol that
is not already present here. Adding a new approved symbol (e.g. SOL, ETH, or
XRP per the sequential review queue in
``docs/todo/native_short_multi_asset_rollout_contract_v1.md``) requires its
own reviewed repository change to this constant, not a CLI argument.

Current state: BTC is a legacy scope (``support_generation=NULL``,
``scope_admin_operation_id=NULL``, support event reason
``MIGRATION_BACKFILL``). The universe below adopts it via
``ADOPT_LEGACY_SCOPE`` into administration generation 1 so its lineage is no
longer silently mixed legacy/managed.

SOL was promoted directly through the single-scope CLI
(``run_native_short_scope_administration_v1.py``), outside this
orchestrator, under the reviewed SOL bootstrap approval -- see
``docs/ops/native_short_sol_promotion_operational_acceptance_v1.md``. It is
deliberately **not** added as an entry here: this module's operation UUID
for any entry is derived only from ``(operation_type, scope_key)``
(``deterministic_operation_uuid``), which would not match SOL's real,
already-committed ``operation_uuid``, and SOL's scope row already exists
(no longer ``NO_SCOPE``), so a synthesized SOL entry here would simply be
rejected by the unchanged ``GLOBAL_BLOCKERS_ACTIVE`` gate (the bootstrap
exception only ever applies to a scope's genuine first-ever attempt) --
harmless, but pointless, and it would needlessly stop a sequential run
before reaching ETH/XRP. ETH and XRP, by contrast, are genuinely
``NO_SCOPE`` today, so their entries below reach the bootstrap-evidence
path exactly as SOL's manual CLI invocation did.

ETH and XRP are approved for exactly one ``PROMOTE_SCOPE`` each, per
``docs/ops/native_short_eth_bootstrap_promotion_approval_v1.md`` and
``docs/ops/native_short_xrp_bootstrap_promotion_approval_v1.md``, and their
own entries in
``native_short_promotion_bootstrap_manifest_v1.json``. This module performs
no bypass of the existing gate -- a ``PROMOTE_SCOPE`` entry for any symbol
without accepted bootstrap or post-hoc acceptance evidence is simply
rejected with ``GLOBAL_BLOCKERS_ACTIVE``, exactly like a manually run CLI
invocation. Adding any further symbol requires its own reviewed repository
change to this constant (plus its own approval document and manifest entry),
never a CLI argument.

SUI, SHIB, PEPE, HBAR, AAVE, BNB, ICP, LDO, XPL, VET, ALGO, CC, HOT, FLOKI,
HNT, and MOG were reviewed and approved together as a single bounded batch of
16 readiness-qualified, previously unapproved scopes. Each still has its own
independent ``docs/ops/native_short_<symbol>_bootstrap_promotion_approval_v1.md``
approval document and its own independently digested manifest entry -- the
batch is a bounded, atomically-landed repository change, not a wildcard or a
shared approval. No entry here authorizes anything beyond its own named
symbol.

Per-scope failure isolation (Issue #276):

Every entry is always attempted, in the checked-in order, regardless of any
other entry's rejection or unexpected exception. A rejected or unready scope
is recorded on its own ``RolloutScopeOutcome`` and never suppresses,
invalidates, or rolls back an unrelated qualified scope -- each entry's
transaction is independently owned by
``native_short_scope_administration_transaction_v1``. This replaces the
earlier stop-at-first-failure policy, under which one ineligible symbol left
every later approved symbol silently unattempted. Reruns stay idempotent via
``deterministic_operation_uuid`` (see below), so a repeated run replays
already-completed entries as ``IDEMPOTENT_SUCCESS`` instead of duplicating
any mutation.

Restartability without extra state: each entry's operation UUID is derived
deterministically from only the operation type and the exact canonical scope
key (see ``deterministic_operation_uuid``). A rerun of the same entry always
reaches the same operation-ledger row, so
``native_short_scope_administration_transaction_v1.decide_operation_replay``
provides idempotent-restart behavior with no separate orchestrator-side
run-state file.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
map_materialization=0
snapshot_materialization=0
profit_plan_writes=0
reporting_writes=0
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from src.market_data.native_short_scope_administration_v1 import (
    CANONICAL_FIB_TRADING_HORIZON,
    CANONICAL_PRIMARY_INTERVAL,
    CANONICAL_QUOTE_CURRENCY,
    CANONICAL_SUPPORTING_INTERVAL,
    CANONICAL_VENUE,
    NativeShortScopeAdministrationKey,
    NativeShortScopeAdministrationOperationType as OperationType,
    NativeShortScopeAdministrationProvenance,
    NativeShortScopeAdministrationRequest,
)
from src.market_data.native_short_multi_asset_audit_v1 import (
    ROLLOUT_STATUS_ALREADY_SUPPORTED,
    ROLLOUT_STATUS_BLOCKED,
    ROLLOUT_STATUS_READY,
    ROLLOUT_STATUS_SKIPPED_NOT_READY,
)
from src.market_data.native_short_scope_administration_transaction_v1 import (
    AdministrationTransactionOutcome,
    execute_scope_administration,
    plan_scope_administration,
)


class RolloutConfigurationError(ValueError):
    pass


_SUCCESS_RESULT_CLASSES = frozenset({"SUCCESS", "IDEMPOTENT_SUCCESS"})


@dataclass(frozen=True)
class RolloutSymbolEntry:
    """One rollout entry: exactly one operation for exactly one canonical
    scope. ``approval_reference``/``note`` are optional free-text provenance
    carried through into ``canonical_metadata`` (see
    ``build_request_for_entry``) -- default to empty for a caller (e.g. a
    readiness-derived rollout) that has no per-symbol approval document to
    cite; ``APPROVED_ROLLOUT_UNIVERSE_V1`` below still populates them."""

    symbol: str
    operation_type: OperationType
    approval_reference: str = ""
    note: str = ""


# --------------------------------------------------------------------------- #
# Checked-in approved rollout universe (v1)                                   #
# --------------------------------------------------------------------------- #

APPROVED_ROLLOUT_UNIVERSE_V1: tuple[RolloutSymbolEntry, ...] = (
    RolloutSymbolEntry(
        symbol="BTC",
        operation_type=OperationType.ADOPT_LEGACY_SCOPE,
        approval_reference=(
            "docs/todo/native_short_multi_asset_rollout_contract_v1.md"
            "#promotion-acceptance-contract"
        ),
        note=(
            "Adopt the existing legacy MIGRATION_BACKFILL BTC scope into "
            "administration generation 1."
        ),
    ),
    RolloutSymbolEntry(
        symbol="ETH",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_eth_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for ETH, authorized via its own "
            "explicit bootstrap-evidence manifest entry. Processed after "
            "BTC; SOL is not an entry in this universe (see module "
            "docstring) but was already promoted before ETH."
        ),
    ),
    RolloutSymbolEntry(
        symbol="XRP",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_xrp_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for XRP, authorized via its own "
            "explicit bootstrap-evidence manifest entry. Processed after "
            "ETH in this universe's checked-in order."
        ),
    ),
    RolloutSymbolEntry(
        symbol="SUI",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_sui_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for SUI, one of 16 readiness-qualified "
            "symbols approved together in a bounded batch, each with its own "
            "independent approval document and manifest entry. Processed "
            "after XRP in this universe's checked-in order."
        ),
    ),
    RolloutSymbolEntry(
        symbol="SHIB",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_shib_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for SHIB, one of 16 readiness-qualified "
            "symbols approved together in a bounded batch, each with its own "
            "independent approval document and manifest entry. Processed "
            "after SUI in this universe's checked-in order."
        ),
    ),
    RolloutSymbolEntry(
        symbol="PEPE",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_pepe_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for PEPE, one of 16 readiness-qualified "
            "symbols approved together in a bounded batch, each with its own "
            "independent approval document and manifest entry. Processed "
            "after SHIB in this universe's checked-in order."
        ),
    ),
    RolloutSymbolEntry(
        symbol="HBAR",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_hbar_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for HBAR, one of 16 readiness-qualified "
            "symbols approved together in a bounded batch, each with its own "
            "independent approval document and manifest entry. Processed "
            "after PEPE in this universe's checked-in order."
        ),
    ),
    RolloutSymbolEntry(
        symbol="AAVE",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_aave_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for AAVE, one of 16 readiness-qualified "
            "symbols approved together in a bounded batch, each with its own "
            "independent approval document and manifest entry. Processed "
            "after HBAR in this universe's checked-in order."
        ),
    ),
    RolloutSymbolEntry(
        symbol="BNB",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_bnb_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for BNB, one of 16 readiness-qualified "
            "symbols approved together in a bounded batch, each with its own "
            "independent approval document and manifest entry. Processed "
            "after AAVE in this universe's checked-in order."
        ),
    ),
    RolloutSymbolEntry(
        symbol="ICP",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_icp_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for ICP, one of 16 readiness-qualified "
            "symbols approved together in a bounded batch, each with its own "
            "independent approval document and manifest entry. Processed "
            "after BNB in this universe's checked-in order."
        ),
    ),
    RolloutSymbolEntry(
        symbol="LDO",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_ldo_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for LDO, one of 16 readiness-qualified "
            "symbols approved together in a bounded batch, each with its own "
            "independent approval document and manifest entry. Processed "
            "after ICP in this universe's checked-in order."
        ),
    ),
    RolloutSymbolEntry(
        symbol="XPL",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_xpl_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for XPL, one of 16 readiness-qualified "
            "symbols approved together in a bounded batch, each with its own "
            "independent approval document and manifest entry. Processed "
            "after LDO in this universe's checked-in order."
        ),
    ),
    RolloutSymbolEntry(
        symbol="VET",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_vet_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for VET, one of 16 readiness-qualified "
            "symbols approved together in a bounded batch, each with its own "
            "independent approval document and manifest entry. Processed "
            "after XPL in this universe's checked-in order."
        ),
    ),
    RolloutSymbolEntry(
        symbol="ALGO",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_algo_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for ALGO, one of 16 readiness-qualified "
            "symbols approved together in a bounded batch, each with its own "
            "independent approval document and manifest entry. Processed "
            "after VET in this universe's checked-in order."
        ),
    ),
    RolloutSymbolEntry(
        symbol="CC",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_cc_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for CC, one of 16 readiness-qualified "
            "symbols approved together in a bounded batch, each with its own "
            "independent approval document and manifest entry. Processed "
            "after ALGO in this universe's checked-in order."
        ),
    ),
    RolloutSymbolEntry(
        symbol="HOT",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_hot_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for HOT, one of 16 readiness-qualified "
            "symbols approved together in a bounded batch, each with its own "
            "independent approval document and manifest entry. Processed "
            "after CC in this universe's checked-in order."
        ),
    ),
    RolloutSymbolEntry(
        symbol="FLOKI",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_floki_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for FLOKI, one of 16 readiness-qualified "
            "symbols approved together in a bounded batch, each with its own "
            "independent approval document and manifest entry. Processed "
            "after HOT in this universe's checked-in order."
        ),
    ),
    RolloutSymbolEntry(
        symbol="HNT",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_hnt_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for HNT, one of 16 readiness-qualified "
            "symbols approved together in a bounded batch, each with its own "
            "independent approval document and manifest entry. Processed "
            "after FLOKI in this universe's checked-in order."
        ),
    ),
    RolloutSymbolEntry(
        symbol="MOG",
        operation_type=OperationType.PROMOTE_SCOPE,
        approval_reference="docs/ops/native_short_mog_bootstrap_promotion_approval_v1.md",
        note=(
            "First-ever PROMOTE_SCOPE for MOG, one of 16 readiness-qualified "
            "symbols approved together in a bounded batch, each with its own "
            "independent approval document and manifest entry. Processed "
            "after HNT in this universe's checked-in order (last of the "
            "batch)."
        ),
    ),
)


def resolve_rollout_entries(
    only_symbols: Sequence[str] | None,
    *,
    universe: Sequence[RolloutSymbolEntry] = APPROVED_ROLLOUT_UNIVERSE_V1,
) -> tuple[RolloutSymbolEntry, ...]:
    """Return the ordered rollout entries to process for this run.

    ``only_symbols`` is ``None`` -> the complete checked-in universe, in
    checked-in order. Otherwise the checked-in universe filtered to exactly
    the requested symbols (order and de-duplication follow the checked-in
    universe, not the caller's argument order). Any requested symbol absent
    from the checked-in universe is a hard configuration error: CLI input may
    select a subset of the checked-in universe, it can never add to it.
    """
    if only_symbols is None:
        return tuple(universe)
    requested = {s.strip().upper() for s in only_symbols}
    invalid = sorted(requested - {entry.symbol for entry in universe})
    if invalid:
        raise RolloutConfigurationError(
            "ROLLOUT_SYMBOL_NOT_IN_APPROVED_UNIVERSE symbols=" + ",".join(invalid)
        )
    return tuple(entry for entry in universe if entry.symbol in requested)


_ROLLOUT_UUID_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "native_short_scope_administration_rollout_v1"
)


def _canonical_scope_key(entry: RolloutSymbolEntry) -> NativeShortScopeAdministrationKey:
    return NativeShortScopeAdministrationKey(
        venue=CANONICAL_VENUE,
        symbol=entry.symbol,
        quote_currency=CANONICAL_QUOTE_CURRENCY,
        fib_trading_horizon=CANONICAL_FIB_TRADING_HORIZON,
        primary_interval=CANONICAL_PRIMARY_INTERVAL,
        supporting_interval=CANONICAL_SUPPORTING_INTERVAL,
    )


def deterministic_operation_uuid(entry: RolloutSymbolEntry) -> str:
    """Stable operation UUID derived only from the operation type and the
    exact canonical scope key. Identical across every rerun/restart for the
    same entry -- see the module docstring for why this makes the rollout
    idempotent and restartable without separate orchestrator-side state."""
    scope_key = _canonical_scope_key(entry)
    identity = f"{entry.operation_type}:{tuple(sorted(scope_key.as_dict().items()))}"
    return str(uuid.uuid5(_ROLLOUT_UUID_NAMESPACE, identity))


def build_request_for_entry(
    entry: RolloutSymbolEntry,
    *,
    actor_type: str,
    actor_id: str,
    trigger_type: str,
    request_source: str,
    reason: str,
    requested_at_utc: datetime,
    repository_sha: str,
    schema_version: str,
    metadata: Mapping[str, Any],
) -> NativeShortScopeAdministrationRequest:
    """Build the immutable per-entry administration request. All fields other
    than symbol/operation_type are constant for one rollout invocation; the
    entry's own approval metadata is folded into ``canonical_metadata`` so it
    is part of the immutable request identity/digest."""
    provenance = NativeShortScopeAdministrationProvenance(
        operation_uuid=deterministic_operation_uuid(entry),
        actor_type=actor_type,
        actor_id=actor_id,
        trigger_type=trigger_type,
        request_source=request_source,
        reason=reason,
        requested_at_utc=requested_at_utc,
        repository_sha=repository_sha,
        schema_version=schema_version,
    )
    entry_metadata: dict[str, Any] = {
        **dict(metadata),
        "rollout_universe_version": "native_short_scope_administration_rollout_v1",
        "rollout_entry_note": entry.note,
        "rollout_entry_approval_reference": entry.approval_reference,
    }
    return NativeShortScopeAdministrationRequest(
        operation_type=entry.operation_type,
        scope_key=_canonical_scope_key(entry),
        provenance=provenance,
        canonical_metadata=entry_metadata,
    )


RequestBuilder = Callable[[RolloutSymbolEntry], NativeShortScopeAdministrationRequest]
_ScopeStep = Callable[[NativeShortScopeAdministrationRequest], AdministrationTransactionOutcome]
RevalidationCheck = Callable[[RolloutSymbolEntry], "tuple[bool, str]"]


@dataclass(frozen=True)
class RolloutScopeOutcome:
    symbol: str
    operation_type: str
    outcome: AdministrationTransactionOutcome | None
    error: str | None
    preclassified_status: str | None = None

    @property
    def succeeded(self) -> bool:
        if self.preclassified_status == ROLLOUT_STATUS_ALREADY_SUPPORTED:
            return True
        if self.outcome is None:
            return False
        return str(self.outcome.result.result_class) in _SUCCESS_RESULT_CLASSES

    @property
    def status(self) -> str:
        """This entry's outcome in the canonical per-scope rollout vocabulary
        (Issue #276), imported from the readiness authority
        ``native_short_multi_asset_audit_v1`` so the audit and the rollout
        report in one shared vocabulary.

        Derived purely from the administration transaction's own already-
        returned result class -- this module still never evaluates blockers or
        decides anything itself:

        - ``SUCCESS`` (the mutation just executed) -> ``READY``
        - ``IDEMPOTENT_SUCCESS`` (replay of an already-completed operation, or
          an already-supported/already-adopted scope) -> ``ALREADY_SUPPORTED``
        - ``BLOCKED`` (e.g. ``GLOBAL_BLOCKERS_ACTIVE``,
          ``LEGACY_ADOPTION_NOT_AUTHORIZED``) -> ``BLOCKED``
        - anything else (``CONFLICT``, ``CORRUPT_STATE``, ``RETRYABLE``, or an
          unexpected exception recorded in ``error``) -> ``SKIPPED_NOT_READY``
        """
        if self.preclassified_status is not None:
            return self.preclassified_status
        if self.outcome is None:
            return ROLLOUT_STATUS_SKIPPED_NOT_READY
        result_class = str(self.outcome.result.result_class)
        if result_class == "SUCCESS":
            return ROLLOUT_STATUS_READY
        if result_class == "IDEMPOTENT_SUCCESS":
            return ROLLOUT_STATUS_ALREADY_SUPPORTED
        if result_class == "BLOCKED":
            return ROLLOUT_STATUS_BLOCKED
        return ROLLOUT_STATUS_SKIPPED_NOT_READY

    def as_json_dict(self) -> dict[str, Any]:
        if self.preclassified_status is not None:
            return {
                "symbol": self.symbol,
                "operation_type": self.operation_type,
                "rollout_status": self.status,
                "error": self.error,
                "no_op": True,
                "detail": "scope is already SUPPORTED; PROMOTE_SCOPE not invoked",
            }
        if self.outcome is not None:
            return {
                "symbol": self.symbol,
                "operation_type": self.operation_type,
                "rollout_status": self.status,
                "error": None,
                **self.outcome.as_json_dict(),
            }
        return {
            "symbol": self.symbol,
            "operation_type": self.operation_type,
            "rollout_status": self.status,
            "error": self.error,
        }


@dataclass(frozen=True)
class RolloutOutcome:
    mode: str
    requested_symbols: tuple[str, ...]
    completed: tuple[RolloutScopeOutcome, ...]
    remaining_symbols: tuple[str, ...]
    stopped_early: bool
    stop_reason: str | None

    def as_json_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "requested_symbols": list(self.requested_symbols),
            "completed": [c.as_json_dict() for c in self.completed],
            "completed_symbols": [c.symbol for c in self.completed if c.succeeded],
            "remaining_symbols": list(self.remaining_symbols),
            "stopped_early": self.stopped_early,
            "stop_reason": self.stop_reason,
            "all_succeeded": (
                not self.stopped_early
                and not self.remaining_symbols
                and all(c.succeeded for c in self.completed)
            ),
        }


def _run_rollout(
    entries: Sequence[RolloutSymbolEntry],
    *,
    mode: str,
    build_request: RequestBuilder,
    run_step: _ScopeStep,
    revalidate: RevalidationCheck | None = None,
) -> RolloutOutcome:
    requested_symbols = tuple(entry.symbol for entry in entries)
    completed: list[RolloutScopeOutcome] = []

    # Per-scope isolation policy (Issue #276): every entry in the checked-in
    # order is always attempted, regardless of any other entry's rejection or
    # crash. One rejected or unready scope must never suppress an unrelated
    # qualified scope. This is purely a loop policy: each entry's own decision,
    # lock, transaction, and rollback remain wholly owned by
    # native_short_scope_administration_transaction_v1, which already gives
    # every entry an independent transaction, so continuing past a failure
    # cannot widen any failure's blast radius.
    first_failure_reason: str | None = None

    for entry in entries:
        # Optional immediately-before-transaction revalidation: the ledger
        # snapshot execute_scope_administration reads is always fresh (it
        # reads at call time), but market/readiness eligibility is not
        # something the transaction layer checks at all -- that determination
        # comes entirely from whatever produced this entry list, evaluated
        # once, before the loop started. For a long-running multi-entry
        # rollout, a scope's market eligibility can change between that
        # initial evaluation and this entry's actual turn. When a caller
        # supplies `revalidate`, it is consulted here, immediately before
        # each entry's own transaction, so staleness cannot silently persist
        # across a long batch. `revalidate` decides nothing about ledger
        # state or blockers -- those remain exclusively
        # native_short_scope_administration_transaction_v1's job.
        if revalidate is not None:
            still_eligible, reason = revalidate(entry)
            if (
                still_eligible
                and reason == ROLLOUT_STATUS_ALREADY_SUPPORTED
                and entry.operation_type == OperationType.PROMOTE_SCOPE
            ):
                completed.append(
                    RolloutScopeOutcome(
                        symbol=entry.symbol,
                        operation_type=str(entry.operation_type),
                        outcome=None,
                        error=None,
                        preclassified_status=ROLLOUT_STATUS_ALREADY_SUPPORTED,
                    )
                )
                continue
            if not still_eligible:
                completed.append(
                    RolloutScopeOutcome(
                        symbol=entry.symbol,
                        operation_type=str(entry.operation_type),
                        outcome=None,
                        error=f"REVALIDATION_FAILED: {reason}",
                    )
                )
                if first_failure_reason is None:
                    first_failure_reason = (
                        f"revalidation failed on symbol={entry.symbol}: {reason}"
                    )
                continue

        request = build_request(entry)
        try:
            outcome = run_step(request)
        except Exception as exc:  # noqa: BLE001 - record-and-continue, never swallow.
            completed.append(
                RolloutScopeOutcome(
                    symbol=entry.symbol,
                    operation_type=str(entry.operation_type),
                    outcome=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            if first_failure_reason is None:
                first_failure_reason = (
                    f"exception on symbol={entry.symbol}: {type(exc).__name__}"
                )
            continue

        scope_outcome = RolloutScopeOutcome(
            symbol=entry.symbol,
            operation_type=str(entry.operation_type),
            outcome=outcome,
            error=None,
        )
        completed.append(scope_outcome)

        if not scope_outcome.succeeded and first_failure_reason is None:
            first_failure_reason = (
                f"non-success result_class={outcome.result.result_class} "
                f"result_code={outcome.result.result_code} "
                f"on symbol={entry.symbol}"
            )

    # remaining_symbols is always empty and stopped_early always False under
    # the continue-always policy: nothing is ever left unattempted. Both fields
    # are retained (rather than removed or repurposed) so existing consumers
    # keep working and keep reading them with their original meaning. They are
    # not a success claim -- `all_succeeded` below still reports honestly, and
    # stop_reason still surfaces the first failure for operator triage.
    return RolloutOutcome(
        mode=mode,
        requested_symbols=requested_symbols,
        completed=tuple(completed),
        remaining_symbols=(),
        stopped_early=False,
        stop_reason=first_failure_reason,
    )


def plan_rollout(
    conn: Any,
    entries: Sequence[RolloutSymbolEntry],
    *,
    build_request: RequestBuilder,
    revalidate: RevalidationCheck | None = None,
) -> RolloutOutcome:
    """Read-only dry run over every requested entry in order, delegating each
    scope entirely to ``plan_scope_administration``. Attempts every entry
    regardless of any other entry's result, mirroring what write mode does.

    ``revalidate`` is optional and defaults to ``None`` (no change from prior
    behavior for any existing caller). See ``_run_rollout``."""
    return _run_rollout(
        entries,
        mode="DRY_RUN",
        build_request=build_request,
        run_step=lambda request: plan_scope_administration(conn, request),
        revalidate=revalidate,
    )


def execute_rollout(
    conn: Any,
    entries: Sequence[RolloutSymbolEntry],
    *,
    build_request: RequestBuilder,
    authorization: Any,
    revalidate: RevalidationCheck | None = None,
) -> RolloutOutcome:
    """Write mode: process every requested entry in order, one bounded
    transaction per scope via ``execute_scope_administration`` on the same
    connection.

    Every entry is always attempted. A scope rejected with a non-success
    result, or one that raises unexpectedly, is recorded on its own
    ``RolloutScopeOutcome`` and the run continues to the next entry -- one
    unready scope never suppresses an unrelated qualified scope. Each entry's
    transaction remains fully isolated inside
    ``execute_scope_administration``, so a later entry's work is never
    entangled with an earlier entry's rollback.

    ``revalidate`` is optional and defaults to ``None`` (no change from prior
    behavior for any existing caller, including ``APPROVED_ROLLOUT_UNIVERSE_V1``'s
    small, individually-approved batch). See ``_run_rollout``."""
    return _run_rollout(
        entries,
        mode="WRITE",
        build_request=build_request,
        run_step=lambda request: execute_scope_administration(
            conn, request, authorization=authorization
        ),
        revalidate=revalidate,
    )


__all__ = [
    "APPROVED_ROLLOUT_UNIVERSE_V1",
    "RequestBuilder",
    "RevalidationCheck",
    "RolloutConfigurationError",
    "RolloutOutcome",
    "RolloutScopeOutcome",
    "RolloutSymbolEntry",
    "build_request_for_entry",
    "deterministic_operation_uuid",
    "execute_rollout",
    "plan_rollout",
    "resolve_rollout_entries",
]
