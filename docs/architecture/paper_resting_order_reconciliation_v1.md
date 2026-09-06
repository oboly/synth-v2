# PAPER Resting-Order ACTIVE -> FILLED Reconciliation V1 (Issue #753 Phase B8-blocker)

## Purpose

Closes the gap `docs/architecture/automatic_buy_paper_order_placement_adapter_v1.md`
(B5.5) and `docs/status/issue_753_paper_acceptance_blocker_v1.md` documented as
still open: B5.5's PAPER order-placement adapter is explicitly
submission-time-only and never itself returns `FILLED` -- a non-crossing
PAPER order rested `ACTIVE` forever, with no later reconciliation path. This
phase adds exactly that later reconciliation, for PAPER only, and nothing
else. It does not build the B8 exact-path acceptance harness itself (see
"What this does not resolve" below).

## What changed

- `src/executor/paper_resting_order_reconciliation_v1.py` (new) --
  `paper_resting_order_would_fill_through_v1` (pure fill-on-through decision,
  BUY and SELL), `evaluate_paper_resting_order_evidence_v1` (evidence
  validation, fail-closed with typed reasons), and
  `reconcile_paper_resting_order_fill_v1` (the orchestration wrapper that
  evaluates evidence, decides fill-through, and calls the new CAS below).
- `src/executor/execution_leg_v1.py` -- added
  `ExecutionLegRepositoryV1.resolve_paper_resting_fill_v1`, an explicit,
  PAPER-specific-by-naming CAS transition `ACTIVE -> FILLED`. No schema
  change: the existing migration's `trg_eel_immutable` trigger already
  permits `OLD.state='ACTIVE' AND NEW.state IN (...,'FILLED',...)` (see
  `db/migrations/20260815_shared_executor_substrate_v1.sql`).
- `src/executor/paper_order_placement_repository_v1.py` -- added
  `find_placement_created_ts_utc`, a read-only lookup of the existing,
  unchanged `executor_paper_order_placement.created_ts_utc` column. No new
  column, no new table.
- `src/executor/paper_order_adapter_v1.py` -- added
  `find_placement_created_ts_utc` to the existing
  `PaperOrderPlacementRepository` Protocol (the composition contract), so
  callers can type-check against it. No behavior change to the adapter
  itself.
- `src/entry_policy/automatic_buy_paper_fill_execution_v1.py` -- after the
  existing, unchanged submission step, a leg that was already resting
  `ACTIVE` *before* this call's submission attempt gets one resting-fill
  reconciliation attempt through the new module. A leg newly placed `ACTIVE`
  by this same invocation's own submission is never eligible in that same
  call (see "Same-invocation eligibility" below).
- `tests/test_paper_resting_order_reconciliation_v1.py`,
  `tests/test_automatic_buy_paper_fill_execution_v1.py` (extended).

No existing decision_gate or execution_planner file changed.
`src/executor/shared_execution_runtime_v1.py`'s `PAPER_ADAPTER_NOT_CONFIGURED`
guard is untouched.

## The reconciliation contract (V1)

- **Fill-on-through only, never fill-on-touch.** A resting BUY leg fills only
  when the current best ask is *strictly below* its limit price; a resting
  SELL leg fills only when the current best bid is *strictly above* its
  limit price. Equality leaves the leg `ACTIVE` unchanged: this V1 has no
  queue-priority model, so a real resting order exactly at the touch price
  may or may not be next in the book. This is a conservative, deterministic
  PAPER simulation, not broker truth.
- **Full-fill-only**, matching the existing B5.5 adapter: `ExecutionLegV1`
  has no partial-filled-quantity field, and this phase does not add one.
- **Evidence health is not lifecycle state**
  (`docs/ops/state_model_discipline_v1.md`). Missing, malformed, mismatched,
  future-dated, or stale quote evidence -- or a quote no later than the
  leg's own persisted resting-since time -- fails closed by raising
  `PaperMarketEvidenceUnavailableError`. The caller in
  `automatic_buy_paper_fill_execution_v1.py` catches exactly that error and
  leaves the leg's persisted `ACTIVE` state untouched; it never converts a
  temporary evidence-health problem into a lifecycle transition.
- **Resting-since time is `executor_paper_order_placement.created_ts_utc`,
  reused unchanged.** No new schema. The resting-fill quote must be strictly
  later than that placement time, or the evidence fails closed.
- **The only lifecycle mutation is the executor-owned, PAPER-specific CAS**
  `ExecutionLegRepositoryV1.resolve_paper_resting_fill_v1`: idempotent on
  replay for the identical `broker_order_id`, conflicts (never a silent
  overwrite) on any other current state or a different `broker_order_id`,
  and never rewrites `broker_order_id` itself.

## Same-invocation eligibility

A leg is only offered to resting-fill reconciliation if it was already
`ACTIVE` (per `leg_repository.find_by_handoff_and_index`) *before*
`submit_execution_plan` runs in that same call. This is captured up front,
before submission, specifically so a leg this same invocation's own
submission newly places `ACTIVE` can never also fill in that same call --
only a strictly later invocation can observe it as pre-existing and attempt
resting reconciliation. `tests/test_automatic_buy_paper_fill_execution_v1.py`
covers this with a quote provider that would return a fill-through quote on
a second call and asserts that call never happens for a newly-placed leg.

## Idempotency and replay

Once a leg reaches `FILLED` (by either the B5.5 adapter's synthetic
same-call path -- which this phase does not change -- or this phase's later
resting reconciliation), all later calls take the existing
`leg.state == FILLED` branch in
`submit_and_reconcile_automatic_buy_paper_plan_v1` directly: reconciling an
already-`FILLED` leg reproduces the identical `source_snapshot_id` /
`cumulative_filled_base_quantity`, so #752's own replay guarantee returns the
existing fact unchanged and emits no new ownership event. This phase adds no
new idempotency rule; it reuses the existing #753 B5 bridge exactly as
before.

## What this does not resolve

This phase makes a real automatic-BUY PAPER fill reachable end-to-end for
the first time (submission `ACTIVE` -> later price-through -> `FILLED` ->
one ownership event), but it does not itself build B8's exact-path PAPER
acceptance harness, and it does not claim full B8 acceptance. See
`docs/status/issue_753_paper_acceptance_blocker_v1.md` Update 5 for the
current status.

## Layer boundaries respected

```text
executor           -> extended (new resting-reconciliation module + one new
                       PAPER-specific CAS method on the existing leg
                       repository; no schema change)
decision_gate       -> unchanged; only the existing #753 B5 bridge is called
execution_planner   -> unchanged
entry_policy        -> extended composition (same seam as B5.5, now also
                       attempts resting reconciliation for pre-existing
                       ACTIVE legs)
```

## Safety markers

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=unchanged
execution_planner=unchanged
executor=extended (new resting-reconciliation module + new PAPER-specific
    CAS transition; existing leg/placement repositories otherwise unchanged)
production_runtime_activation=0
paper_adapter_not_configured_guard=unchanged (shared_execution_runtime_v1.py)
schema_change=0 (existing trg_eel_immutable transition + existing
    created_ts_utc column both reused unchanged)
```
