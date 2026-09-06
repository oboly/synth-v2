# PAPER Resting-Order ACTIVE -> FILLED Reconciliation V1 (Issue #753 Phase B7.5)

## Purpose

Closes the PAPER resting-order gap explicitly deferred by B5.5. A post-only
order may be accepted and persist as `ACTIVE`; before this phase there was no
truthful later PAPER path from that resting state to `FILLED`.

This phase adds only that executor-owned transition and the automatic-BUY
composition needed to feed the existing #752 fill/ownership bridge. It does
not activate LIVE, call a broker, alter execution planning, or change
`decision_gate` authority.

## Conservative PAPER fill contract

PAPER reconciliation is a deterministic simulation, not broker truth. V1 is
intentionally conservative:

- BUY fills only when a later `best_ask < resting_limit_price`.
- SELL fills only when a later `best_bid > resting_limit_price`.
- Exact equality does **not** fill. Queue priority is unknown, so a mere touch
  cannot prove this resting order traded.
- Fills are full-leg only. `PARTIALLY_FILLED` is not simulated.
- A non-through quote leaves the structural leg state `ACTIVE` unchanged.

Placement-time post-only semantics remain unchanged: a quote that already
crosses when the order is submitted is `REJECTED`, never `FILLED`.

## Authoritative resting-since evidence

A reconciliation may act only on a real persisted PAPER placement.
`PaperOrderPlacementRepositoryV1.find_placement_record(...)` reads the existing
immutable `executor_paper_order_placement` row and exposes:

- market / client order id;
- side / price / quantity;
- original `ACTIVE` acknowledgement and broker order id;
- persisted `created_ts_utc`.

The reconciliation verifies this identity exactly against the `ExecutionLegV1`.
The placement table remains immutable and is never updated by B7.5.

The market quote must be:

- structurally valid and for the same market;
- timezone-aware, not future-dated, and within the configured max age;
- observed **strictly after** the persisted placement `created_ts_utc`.

A missing/conflicting placement, non-`ACTIVE` placement acknowledgement, or a
quote observed at/before placement fails closed. These are evidence-health
conditions, not lifecycle transitions, so the leg remains `ACTIVE`.

## PAPER-only handoff gate

`reconcile_paper_resting_leg_v1(...)` requires the exact
`ExecutionHandoffV1` owning the leg and verifies:

- `executor_mode == PAPER`;
- handoff id;
- trading account;
- venue / market / side.

LIVE, DRY_RUN, or identity-mismatched handoffs cannot use this transition.
No shared LIVE runtime path is modified and `PAPER_ADAPTER_NOT_CONFIGURED`
remains unchanged.

## Executor CAS transition

`ExecutionLegRepositoryV1.mark_active_filled_price_through_v1(...)` is the
single write seam. Its compare-and-swap requires both:

- current state `ACTIVE`;
- current persisted `broker_order_id == expected_broker_order_id`.

On success it writes `FILLED`, the deterministic PAPER reconciliation raw
status, `last_reconciled_ts_utc`, and `updated_ts_utc`. It preserves the
broker order id and order identity. Replay of the same already-`FILLED` leg is
idempotent only when the broker order id still matches; incompatible state or
identity fails closed.

No schema change is required. The existing executor leg transition trigger
already permits `ACTIVE -> FILLED`.

## Automatic-BUY composition

`submit_and_reconcile_automatic_buy_paper_plan_v1(...)` remains the
strategy-aware composition seam because it already owns the automatic-BUY
plan identity required by #752.

Before calling `submit_execution_plan`, it snapshots which leg indices are
already `ACTIVE`. Only those pre-existing ACTIVE legs are eligible for resting
reconciliation after submission. Therefore one invocation cannot both create
a new resting `ACTIVE` order and fill it, even if the quote provider could
change between reads.

On a later invocation:

1. the existing ACTIVE leg is reconciled against post-placement market evidence;
2. strict price-through may CAS it to `FILLED`;
3. `paper_broker_cumulative_fill_evidence_from_leg_v1` converts that persisted
   FILLED leg into canonical #752 cumulative fill evidence;
4. the existing B5 reconciliation bridge persists one strategy-owned BUY event;
5. replay produces no duplicate ownership delta.

## Layer boundaries

```text
market evidence     -> quote provider only
executor            -> PAPER placement read + ACTIVE -> FILLED state transition
decision_gate       -> unchanged #752/B5 ownership reconciliation
execution_planner   -> unchanged
entry_policy        -> composition only; no fill semantics
LIVE/broker runtime -> unchanged / inactive
```

## Acceptance evidence for B7.5

Focused tests cover:

- BUY/SELL strict price-through;
- equality touch remains ACTIVE;
- non-through remains ACTIVE;
- missing/malformed/mismatched/stale/future quote evidence;
- quote timestamp at/before placement;
- missing/conflicting/non-ACTIVE placement evidence;
- non-PAPER and handoff identity mismatch;
- broker-order-id CAS conflict and FILLED replay idempotency;
- first automatic-BUY invocation rests ACTIVE with no ownership event;
- same-invocation quote changes cannot fill a newly-created ACTIVE leg;
- later equality still remains ACTIVE;
- later strict-through reaches FILLED and emits exactly one ownership event;
- replay does not duplicate placement or ownership;
- B5.5 crossed post-only submission remains REJECTED.

## Status

B7.5 makes B8 technically runnable because the exact automatic-BUY PAPER path
can now produce a persisted FILLED leg and a real #752 strategy-owned BUY
event without synthetic fixture mutation.

B7.5 does **not** mean B8 has passed. B8 must still exercise the full #753
exact-path lifecycle, including first-fill map binding, target exits,
invalidation, map immutability, replay/restart, cross-bucket isolation, and
duplicate-cycle idempotency.

## Safety markers

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=unchanged
execution_planner=unchanged
executor=extended (PAPER resting reconciliation only)
production_runtime_activation=0
paper_adapter_not_configured_guard=unchanged
executor_paper_order_placement_mutation=0
```
