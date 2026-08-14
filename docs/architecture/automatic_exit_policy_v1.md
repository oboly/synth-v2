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
permission, profile, venue-constraint, and runtime-version identities. Those
captured identifiers make a later replay independent of mutable latest state.

Phase 4B may read persisted `trading_account_balance_snapshot` and
`account_open_order_snapshot` plus a matching
`account_open_order_snapshot_run_v1` COMPLETE header only when all are fresh
and mutually resolvable; the header is required to prove an authoritative zero
open-order result. Missing, stale, or ambiguous snapshots fail closed. Their
separately owned producers may perform authenticated private reads, but Phase
4B never resolves credentials or calls a broker. Runtime host ownership remains unassigned in
Phase 4A: the current ownership registry covers public/market-only writer
capabilities and does not authorize an account-runtime capability. No service,
timer, deployment, or execution authority is introduced here.
