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
invocation, and a sequential rollout stops there. Adding any further symbol
requires its own reviewed repository change to this constant (plus its own
approval document and manifest entry), never a CLI argument.

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
    """One checked-in, reviewed rollout-universe entry."""

    symbol: str
    operation_type: OperationType
    approval_reference: str
    note: str


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


@dataclass(frozen=True)
class RolloutScopeOutcome:
    symbol: str
    operation_type: str
    outcome: AdministrationTransactionOutcome | None
    error: str | None

    @property
    def succeeded(self) -> bool:
        if self.outcome is None:
            return False
        return str(self.outcome.result.result_class) in _SUCCESS_RESULT_CLASSES

    def as_json_dict(self) -> dict[str, Any]:
        if self.outcome is not None:
            return {
                "symbol": self.symbol,
                "operation_type": self.operation_type,
                "error": None,
                **self.outcome.as_json_dict(),
            }
        return {
            "symbol": self.symbol,
            "operation_type": self.operation_type,
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
) -> RolloutOutcome:
    requested_symbols = tuple(entry.symbol for entry in entries)
    completed: list[RolloutScopeOutcome] = []

    for index, entry in enumerate(entries):
        request = build_request(entry)
        try:
            outcome = run_step(request)
        except Exception as exc:  # noqa: BLE001 - stop-and-report, never swallow.
            completed.append(
                RolloutScopeOutcome(
                    symbol=entry.symbol,
                    operation_type=str(entry.operation_type),
                    outcome=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            return RolloutOutcome(
                mode=mode,
                requested_symbols=requested_symbols,
                completed=tuple(completed),
                remaining_symbols=tuple(e.symbol for e in entries[index + 1 :]),
                stopped_early=True,
                stop_reason=(
                    f"exception on symbol={entry.symbol}: {type(exc).__name__}"
                ),
            )

        scope_outcome = RolloutScopeOutcome(
            symbol=entry.symbol,
            operation_type=str(entry.operation_type),
            outcome=outcome,
            error=None,
        )
        completed.append(scope_outcome)

        if not scope_outcome.succeeded:
            return RolloutOutcome(
                mode=mode,
                requested_symbols=requested_symbols,
                completed=tuple(completed),
                remaining_symbols=tuple(e.symbol for e in entries[index + 1 :]),
                stopped_early=True,
                stop_reason=(
                    f"non-success result_class={outcome.result.result_class} "
                    f"result_code={outcome.result.result_code} "
                    f"on symbol={entry.symbol}"
                ),
            )

    return RolloutOutcome(
        mode=mode,
        requested_symbols=requested_symbols,
        completed=tuple(completed),
        remaining_symbols=(),
        stopped_early=False,
        stop_reason=None,
    )


def plan_rollout(
    conn: Any,
    entries: Sequence[RolloutSymbolEntry],
    *,
    build_request: RequestBuilder,
) -> RolloutOutcome:
    """Read-only dry run over every requested entry in order, delegating each
    scope entirely to ``plan_scope_administration``. Stops at the first
    non-success result, mirroring what write mode would do."""
    return _run_rollout(
        entries,
        mode="DRY_RUN",
        build_request=build_request,
        run_step=lambda request: plan_scope_administration(conn, request),
    )


def execute_rollout(
    conn: Any,
    entries: Sequence[RolloutSymbolEntry],
    *,
    build_request: RequestBuilder,
    authorization: Any,
) -> RolloutOutcome:
    """Write mode: process every requested entry in order, one bounded
    transaction per scope via ``execute_scope_administration`` on the same
    connection. Stops immediately on the first scope whose result is not
    SUCCESS/IDEMPOTENT_SUCCESS, or on the first unexpected exception, leaving
    every remaining symbol untouched and unattempted."""
    return _run_rollout(
        entries,
        mode="WRITE",
        build_request=build_request,
        run_step=lambda request: execute_scope_administration(
            conn, request, authorization=authorization
        ),
    )


__all__ = [
    "APPROVED_ROLLOUT_UNIVERSE_V1",
    "RequestBuilder",
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
