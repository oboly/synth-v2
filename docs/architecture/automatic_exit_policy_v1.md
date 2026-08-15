# Automatic exit policy V1

## Boundary

The automatic exit-policy candidate evaluator belongs in the narrow,
account-aware `exit_policy` package. It needs a held-position identity, which
market-only layers cannot receive, and it determines exit-policy intent:
target/invalidation trigger semantics, `REDUCE` versus `EXIT`, fraction
candidate, and urgency. Those are not account permission decisions.

```text
position + market exit context
-> exit_policy.automatic_exit_candidate_v1
-> decision_gate permission/risk/conflict validation
-> execution_planner immutable SELL ladder
-> executor
```

`selection_engine` remains market-only and account-agnostic. `decision_gate`
answers only whether the proposed candidate may proceed for the account.
Reporting stays read-only. The evaluator never writes state, builds broker
payloads, resolves base quantity, creates a manual request, calls the
planner/executor, or grants permission.

## V1 contract

`evaluate_automatic_exit_candidate_v1` takes explicit position and market
exit-context observations plus an explicit evaluation timestamp. It returns
exactly one of:

- `NO_ACTION`: no held quantity or no target/invalidation condition is met.
- `NON_ACTIONABLE`: position/profile evidence is stale, missing, malformed,
  mismatched, or policy fractions are unsafe.
- `CANDIDATE`: a typed `REDUCE` or `EXIT` candidate carrying only a bounded
  reduction-fraction candidate, urgency, reason, position identity, and
  target/profile evidence.

V1 uses a 25% reduction candidate when the active target is reached and a
100% candidate when invalidation is breached. These are candidates only;
`decision_gate` must validate live account availability, reservations, risk,
and conflicts before any planner call. No final base quantity exists in this
contract.

Freshness is explicit and defaults to fifteen minutes for both input classes.
The passed evaluation timestamp makes same-input/same-output deterministic.
Missing required profile provenance or an invalid price fails closed to
`NON_ACTIONABLE`. All timestamps must be timezone-aware UTC instants; naïve
timestamps fail closed to `NON_ACTIONABLE` rather than being assumed UTC.

## Phase 2: account permission boundary

`decision_gate.automatic_exit_gate_v1` now provides a pure, caller-assembled
permission contract from `AutomaticExitCandidateV1` to
`AutomaticExitGateDecisionV1`. It has no persistence, runtime wiring,
manual-execution request/approval dependency, planner, executor, or broker
dependency.

The context binds the exact account, position reference, venue, asset, and
market; identifies the position snapshot; supplies held/free quantity,
reservation-or-open-order conflict state, account mode and explicit lane
permission; and gives explicit timestamps and freshness limits. Ambiguous,
missing, mismatched, naïve, future, or stale evidence is `NON_ACTIONABLE`.
Explicit policy prohibitions (disabled account/lane, non-paper or LIVE fact,
blocking conflict, zero free quantity) are `DENIED`. Only healthy matching
facts yield `APPROVED`.

An approved result preserves the candidate object and its fraction/provenance
unchanged. Its `approved_quantity_ceiling_base` is not a strategy rewrite: it
is `min(candidate fraction × fresh held quantity, fresh free quantity,
optional account risk cap)`. It exists so a later planner cannot bypass
account safety; it contains no ladder, prices, broker payload, or order.

## Phase 3: approved gate to immutable planner seam

`execution_planner.automatic_exit_planner_v1` accepts only an
`AutomaticExitGateDecisionV1` in `APPROVED` state plus explicit current public
market/venue facts. Raw candidates cannot enter this planner. The planner
rechecks exact account/position/venue/asset/market identity and preserves the
candidate action (`REDUCE` or `EXIT`), evidence/profile provenance, gate reason,
approved fraction, and approved quantity ceiling in its immutable plan.

The gate remains the account-risk quantity-bound owner. The planner owns the
final executable quantity: it rounds that ceiling down once through
`execution_planner.canonical_rounding_v1.round_quantity_down`, then validates
the final result and allocates it deterministically. The same canonical module
is the only price/leg rounding and post-round minimum-validation owner. No leg
may redefine exposure; the immutable leg sum must equal the final quantity and
must not exceed the gate ceiling.

V1 has an explicitly fixed execution-only two-leg passive SELL profile: equal
base quantity at reference price and reference plus 25 bps. It does not choose
an exit action, alter the policy fraction, inspect target or invalidation
conditions, or adapt strategy. Any invalid/stale venue fact, rounding-to-zero,
minimum violation, identity mismatch, or impossible allocation fails closed.
The planner requires canonical venue metadata to support `limit` and `GTC`
case-insensitively, and independently checks the metadata timestamp against
the canonical metadata-age bound at planning time. Post-only capability is not
represented by the canonical venue constraints contract, so it is explicitly
deferred rather than inferred or modeled by a planner-local field.

This phase is pure and read-only: no persistence, scheduler, reservations,
executor wiring, broker calls, credentials, LIVE authority, or order submission
exists. Those runtime phases remain separately reviewed work.

## Phase 4A: persisted input and evidence contracts

Phase 4A adds only contracts required to make a later runtime mechanical.
`automatic_exit_account_permission_v1` is an append-only, account-scoped
`planning_enabled` opt-in; no row is disabled, overlapping effective rows fail
closed, and it is neither LIVE nor order authority. `automatic_exit_profile_v1`
is an append-only market-level V1 policy input shared across accounts. Exactly
one effective profile must provide a profile ID/version, target and/or
invalidation, evidence provenance, and observed timestamp; absent, conflicting,
stale, or unsupported profiles are non-actionable.

`automatic_exit_evaluation_audit_v1` is the sole Phase-4 staging boundary. It
records append-only candidate/gate/planner evidence and an immutable plan JSON
when planning succeeds; it is not executor input and has no mutable order state.
Its unique idempotency hash is SHA-256 over canonical sorted JSON of account and
position identity plus the exact position, balance, open-order, price,
permission, profile, and venue-constraint identities. Runtime version is audit
provenance only and never changes a logical evidence identity. Those
captured identifiers make a later replay independent of mutable latest state.

Phase 4B must consume only a fresh `COMPLETE` `account_state_snapshot_run_v1`
bundle. The bundle binds exact same-refresh position and balance evidence to a
matching `account_open_order_snapshot_run_v1` COMPLETE header; the latter is
required to prove an authoritative zero open-order result. Missing, stale,
ambiguous, cross-account, cross-venue, or component-mismatched evidence fails
closed. The producer independently validates the referenced header's account,
normalized venue, timestamp, canonical source, `COMPLETE` state, and exact
count before emitting the account-state header. The canonical producer is the Odroid
`ACCOUNT_STATE_SNAPSHOT_REFRESH` wallet path; it performs the existing two
private reads and commits the complete persisted bundle atomically. Phase 4B
itself never resolves credentials or calls a broker.

The later `AUTOMATIC_EXIT_POLICY_RUNTIME` owner remains `UNASSIGNED`: the
repository has no reviewed account-policy runtime host decision yet, and the
new account-runtime ownership registry deliberately grants it neither private
read nor execution authority. No automatic-exit service, timer, deployment, or
execution authority is introduced by this prerequisite.

## Phase 4B: runtime orchestrator

Phase 4B (issue #392) implements the mechanical, DB-local orchestrator that
Phase 4A only made possible. It performs no strategy, permission, or execution
decision itself: it loads persisted evidence, calls the existing candidate
evaluator, gate, and planner in sequence, and appends exactly one
`automatic_exit_evaluation_audit_v1` row per evaluated position.

**Owner**: `AUTOMATIC_EXIT_POLICY_RUNTIME` is assigned to **gurkdb** in
`deploy/ownership/account_runtime_capability_ownership_v1.json`
(`activation_status: PLANNED` -- implemented and tested, not yet deployed).
gurkdb is DB-centric orchestration, hosts the canonical persisted market/account
truth, and needs no colocation with Odroid's private snapshot acquisition;
Phase 4B never resolves credentials or calls a broker, so it does not require
private-account-credential authority. This keeps evidence *acquisition*
(Odroid, `ACCOUNT_STATE_SNAPSHOT_REFRESH`) and policy *orchestration* (gurkdb,
`AUTOMATIC_EXIT_POLICY_RUNTIME`) on separate hosts with separate authority.
gurkdb also hosts unrelated public market-data writer capabilities
(`public_price_snapshot`, `public_candle_freshness`); per
`docs/ops/runtime_chain_ownership_v1.md` the structural rule runs one
direction only -- "no consumer, reporting, or account runtime may run a public
market-data writer or repair path" -- so an account runtime being hosted
alongside an existing market-data writer is not itself a boundary violation.

**Source tables** (all read-only, DB-local):

- `account_state_snapshot_run_v1` + `account_open_order_snapshot_run_v1`: the
  aligned `COMPLETE` account-state bundle (Phase 4A alignment contract).
- `account_position_snapshot`, `trading_account_balance_snapshot`,
  `account_open_order_snapshot`: the bundle's exact position, balance, and
  open-order component rows.
- `market_price_snapshot`, `automatic_exit_profile_v1`,
  `automatic_exit_account_permission_v1`, `venue_execution_constraint`: the
  same canonical market/policy/permission/venue facts Phases 1-3 already
  depend on, resolved through their existing `resolve_*` functions only.

**Orchestration sequence** (`evaluate_automatic_exit_runtime_item_v1`, one
independent unit per positive held position):

```text
persisted evidence (repository loaders)
-> AutomaticExitCandidateV1 evaluation (existing Phase 1 evaluator)
-> [NO_ACTION | NON_ACTIONABLE]: audit, stop
-> AutomaticExitGateContextV1 -> decision_gate (existing Phase 2 gate)
-> [DENIED | NON_ACTIONABLE]: audit, stop
-> AutomaticExitPlanningContextV1 -> execution_planner (existing Phase 3 planner)
-> [rejected]: audit fail-closed reason, stop
-> [staged]: serialize immutable plan JSON, audit, stop
```

The orchestrator performs no target/invalidation comparison, no REDUCE/EXIT
choice, no fraction/quantity/ceiling calculation, no ladder construction, and
no venue rounding -- all of that stays in the modules it calls
(`tests/test_automatic_exit_runtime_architecture_guards_v1.py` enforces this
by AST inspection). `AUTOMATIC_EXIT_POLICY_RUNTIME` performs no broker
calls, no credential resolution, and no broker writes.

**Idempotency and replay**: every audit row's `idempotency_key` is computed by
the existing `automatic_exit_idempotency_key_v1()` over the same 14 identity
fields defined in Phase 4A, resolved by the repository before any
candidate/gate/planner call. Two permission/venue-constraint edge cases have no
underlying DB row when absent (permission disabled by absence; venue
constraints `MISSING`); the repository substitutes a stable sentinel identity
(`NO_PERMISSION_ROW`, `NO_VENUE_CONSTRAINT_ROW`) so the idempotency contract's
required non-null fields still hold, and the sentinel itself changes if a real
row is later added. Re-running identical evidence returns the existing audit
row (`idempotent_existing`) rather than inserting a duplicate. A duplicate key
with a different recorded candidate/gate/planner decision is treated as
`IdempotencyPayloadConflictError` and fails closed rather than silently
coexisting -- this is the signal that a runtime logic change produced a
different outcome for the same immutable evidence.

**Market identity**: the runtime resolves every held position through exactly
one account-bound `account_asset -> venue_market` row scoped to the runtime
account, venue, and base asset. This binding supplies only the canonical market
identity; it never reads account-asset strategy flags and does not grant
permission. Zero or multiple usable bindings fail closed. The exact canonical
market is used for price, profile, constraint, conflict, candidate, gate,
planner, idempotency, and audit inputs; the runtime never constructs a market
from a symbol or assumes an EUR quote.

**Append-only staging**: `automatic_exit_evaluation_audit_v1` rows are only
ever inserted, never updated. `source_evidence_json` contains immutable
source/replay evidence only; `runtime_version` remains audit-row provenance.
`source_evidence_json` and `immutable_plan_json`
use one deterministic canonical serializer (`sort_keys=True`, compact
separators, ASCII-safe, `Decimal` as plain string, UTC datetimes as
`...Z`-suffixed ISO strings, no floats).

**Locking**: a host-local nonblocking `fcntl.flock` at
`~/.local/state/synth/runtime/locks/automatic-exit-policy-runtime.lock`.
`/tmp` and `/var/tmp` are forbidden regardless of the unit's `PrivateTmp`
setting because they are not canonical runtime lock locations. A second
concurrent invocation observes the held lock, performs no evaluation, and
fails the cycle (`result=lock_unavailable`, nonzero exit).

**Item vs cycle failures**: one cycle enumerates every enabled, venue-matching
`trading_account` and, per account, its latest fresh `COMPLETE` bundle and
positive positions. A single item's evidence-loading or evaluation failure
(missing balance row, stale price, conflicting profile, etc.) is recorded in
the cycle's failure list and does not abort other items or other accounts --
an item that fails before a complete evidence identity exists is not written
to the append-only audit table (its `idempotency_key` cannot be honestly
computed), but is logged with whatever identity was resolved. A cycle-global
failure (DB unavailable, ownership mismatch, unexpected schema error, lock
unavailable) aborts the whole cycle with a nonzero exit code.

**Cadence**: 5 minutes, safely below the ~15-minute freshness windows already
enforced by the candidate evaluator, gate, and profile/permission resolvers,
and aligned with the existing `ACCOUNT_STATE_SNAPSHOT_REFRESH` timer's
`OnUnitActiveSec=5min` cadence -- there is no value in polling faster than the
upstream evidence actually refreshes, and idempotency makes repeated
evaluation of unchanged evidence a no-op rather than a correctness risk.

**Terminal boundary (unchanged from the issue #392 architecture)**: Phase 4B
ends at an immutable `AutomaticExitPlanV1` staged as an append-only audit row.
It is explicitly not executor handoff, not submission intent, not a broker
payload, not an order, not a reservation, and not LIVE authority. Any future
phase that hands a staged plan to `executor` is separately scoped, separately
authorized work.

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=automatic_exit_gate_v1 (called, not bypassed)
execution_planner=automatic_exit_planner_v1 (called, not bypassed)
executor=none
```
