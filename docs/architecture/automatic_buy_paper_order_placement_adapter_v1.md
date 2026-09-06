# Automatic BUY PAPER Order-Placement Adapter V1 (Issue #753 Phase B5.5)

## Purpose

Closes the blocker `docs/architecture/automatic_buy_paper_fill_reconciliation_v1.md`
("What remained blocked (resolved by B5.5)") and
`docs/status/issue_753_paper_acceptance_blocker_v1.md` gap 3 documented: no
PAPER order-placement adapter existed anywhere in the shared executor
handoff path automatic-BUY plans flow through, so #753 Phase B5's
reconciliation bridge had no real `BrokerCumulativeFillEvidenceV1` to call.

This phase does **not** add a `fib_map_bound_trade_v1` repository (B6), does
not build the exact-path PAPER acceptance harness (B8), does not touch LIVE
composition, and does not weaken or bypass `PAPER_ADAPTER_NOT_CONFIGURED` in
`src/executor/shared_execution_runtime_v1.py`.

## What changed

- `src/executor/paper_order_adapter_v1.py` (new) -- `PaperMarketQuoteV1`
  (one caller-supplied/repository-backed current price for one market),
  `PaperMarketQuoteProviderV1` (a `Protocol`, so any repository-backed source
  can supply quotes without this module depending on a concrete one),
  `PaperMarketEvidenceUnavailableError`, `PaperOrderPlacementAdapterV1` (the
  `OrderPlacementAdapter` implementation), and
  `paper_broker_cumulative_fill_evidence_from_leg_v1` (pure function: FILLED
  `ExecutionLegV1` -> canonical `BrokerCumulativeFillEvidenceV1`).
- `src/entry_policy/automatic_buy_paper_fill_execution_v1.py` (new) --
  `submit_and_reconcile_automatic_buy_paper_plan_v1`: submits one approved
  `AutomaticBuyPlanV1` through the existing, unchanged
  `submit_execution_plan` with the new PAPER adapter, then for each leg that
  reaches `FILLED`, builds the identity #753 B5 requires
  (`AutomaticBuyFillPlanIdentityV1`, copied verbatim from the plan) and calls
  the existing, unchanged `reconcile_and_persist_automatic_buy_paper_fill_v1`.
- `src/executor/paper_order_placement_repository_v1.py` (new, PR #776 review
  fix) -- `PaperOrderPlacementRepositoryV1`: durable, replay-safe store for
  this adapter's own `ACTIVE`/`REJECTED` placement decisions, keyed by
  `(market, client_order_id)`. See "Crash-window recovery" below.
- `db/migrations/20260906_paper_order_placement_v1.sql` (new, PR #776 review
  fix) -- schema for `executor_paper_order_placement`; schema only, not yet
  applied.
- `tests/test_paper_order_adapter_v1.py`, `tests/test_automatic_buy_paper_fill_execution_v1.py`
  (new).

No existing file changed. `src/executor/execution_submission_orchestrator_v1.py`,
`src/executor/execution_leg_v1.py`, `src/executor/execution_handoff_v1.py`,
`src/executor/shared_execution_runtime_v1.py`,
`src/decision_gate/automatic_buy_fill_reconciliation_v1.py`, and
`src/decision_gate/automatic_buy_fill_reconciliation_persistence_v1.py` are
all unchanged.

## The truthful-fill simulation contract (V1)

**Update (post-review fix):** the initial version of this phase treated a
crossed/marketable quote as an immediate `FILLED`. Automated review
(`gh pr view 776`) correctly flagged this as false: every leg this adapter
ever receives is post-only (every planner in this repository hardcodes
`post_only=True`; none ever sets it `False`), and a real exchange rejects a
crossing post-only order outright rather than filling it. The corrected V1
contract below reflects that fix; see `src/executor/paper_order_adapter_v1.py`
for the enforced rule.

Deliberately the smallest deterministic rule that is honest about what PAPER
mode can know:

- **A leg fills fully or not at all; `PARTIALLY_FILLED` is never returned.**
  `ExecutionLegV1` has no partial-filled-quantity field; simulating partial
  fills would require either fabricating one (a new, undiscussed persisted
  field, out of scope) or tracking fill state only in adapter memory (hidden
  state this phase must avoid).
- **Every order is modeled as post-only, because every order that reaches
  this adapter is post-only.** A quote that would cross the book on arrival
  (a BUY leg whose limit price is at or above the best ask; a SELL leg whose
  limit price is at or below the best bid) is `REJECTED`, matching the real exchange
  behavior for a crossing post-only order. `place_order` never returns
  `FILLED`: a post-only order cannot fill synchronously at placement, so V1
  does not invent one.
- **A non-crossing quote is not a failure.** The leg legitimately stays
  `ACTIVE`, exactly like a real passive limit order resting on the book. This
  is a **submission-time-only snapshot decision**: this V1 adapter does not
  later re-poll or re-evaluate a resting `ACTIVE` PAPER leg against fresh
  market evidence to transition it to `FILLED` -- there is no persisted or
  polled reconciliation path for `ACTIVE` legs anywhere in the shared
  executor for any mode today (`execution_order_reconciliation_v1.py` only
  ever re-resolves `SUBMISSION_UNCERTAIN`/`RECONCILIATION_REQUIRED` legs, and
  the leg repository's own transition set has no `ACTIVE -> FILLED` path to
  reconcile into). Building one would be a new, shared, TEST/LIVE-affecting
  state-machine capability, not a bounded PAPER-only slice, so it is
  deliberately deferred to a later phase (B6/B7/B8) rather than fabricated
  here. Consequence: in V1, an automatic-BUY PAPER submission either
  `REJECTED`s immediately (crossed) or rests `ACTIVE` forever (not crossed);
  it never reaches `FILLED` through this adapter alone.
- **Crossing uses explicit spread evidence.** `PaperMarketQuoteV1` carries validated `best_bid` and `best_ask`; BUY compares only with best ask and SELL only with best bid. Inverted spreads fail closed.
- **Missing, mismatched, future-dated, or stale evidence fails closed.**
  `place_order` raises `PaperMarketEvidenceUnavailableError` rather than
  guessing. The existing, unchanged submission orchestrator already turns an
  adapter exception into `SUBMISSION_UNCERTAIN`, and this adapter's
  `find_order_by_client_order_id` truthfully reports no order when placement
  raised (no broker order was ever really placed), so the leg then resolves
  to `RECONCILIATION_REQUIRED` -- the same reviewed terminal safety state
  already used for a real ambiguous broker failure, not a new bespoke state.
- **Every acknowledged `ACTIVE`/`REJECTED` placement is durably recorded and
  recoverable (post-review fix, PR #776).** `place_order` writes its
  acknowledgement to `src/executor/paper_order_placement_repository_v1.py`
  (`executor_paper_order_placement`, migration
  `db/migrations/20260906_paper_order_placement_v1.sql`) *before* returning
  it, keyed by the already-globally-unique, deterministic `client_order_id`.
  `find_order_by_client_order_id` reads that same record. See "Crash-window
  recovery" below.

`paper_broker_cumulative_fill_evidence_from_leg_v1` is preserved unchanged as
a pure FILLED-leg -> fill-evidence converter for forward compatibility with a
later phase that persists a real FILLED PAPER leg (e.g. a B6/B7 ladder/
reprice/fill-on-touch mechanism); this V1 adapter itself never produces the
`FILLED` state that would trigger it. `executor_execution_leg` remains the
repository-backed PAPER fill-quantity read authority for whenever that
happens: once a leg is persisted `FILLED`, its immutable `quantity` is, by
this contract, the full cumulative filled amount, and
`source_snapshot_id` is a stable hash of the leg's own persisted
identity/state/quantity so replaying the same persisted leg always yields
the same snapshot id and quantity -- the idempotent-replay input #752's
`reconcile_cumulative_fill_v1` requires.

## Why this composes in `entry_policy`, not `executor` or the shared runtime

`src/executor/shared_execution_runtime_v1.py` documents its own topology
constraint: the fully decoupled, side-neutral shared-executor runtime "does
not import a planner, policy, decision gate, automatic BUY/SELL producer."
It has no per-plan strategy identity (`strategy_bucket_id`, `strategy_id`,
`strategy_version`, `trade_id`) available to reconcile ownership with, since
that identity lives only on the in-memory `AutomaticBuyPlanV1` the producer
already holds -- it is never persisted independently of the plan's content
hash. The composition seam still belongs in the same call that already holds that
plan identity, exactly like the existing DRY_RUN/LIVE *intake* seam
(`src/entry_policy/automatic_buy_execution_handoff_application_v1.py`). This
B5.5 adapter itself never produces `FILLED`: fill reconciliation remains
unreachable until a later reviewed PAPER `ACTIVE -> FILLED` reconciliation
path exists.
`src/entry_policy/automatic_buy_paper_fill_execution_v1.py` adds the missing
*submission + reconciliation* step for PAPER only, using only the existing
public `submit_execution_plan` and `reconcile_and_persist_automatic_buy_paper_fill_v1`
APIs. `src/executor/shared_execution_runtime_v1.py`'s
`PAPER_ADAPTER_NOT_CONFIGURED` guard is untouched and still governs the
fully decoupled runtime path, which this phase does not compose.

This also means automatic-BUY is never routed onto the legacy per-plan
`execution_plan`/`fill_passive_plan_paper` PAPER simulator in
`src/executor/repository.py`; only the shared
`executor_execution_handoff`/`executor_execution_leg` contract B3/B4 already
use is exercised.

## Crash-window recovery (PR #776 review fix)

Automated review correctly flagged: `PaperOrderPlacementAdapterV1` could
return an `ACTIVE` acknowledgement while `find_order_by_client_order_id`
always reported `None`. If the process crashed after that acknowledgement
but before `execution_submission_orchestrator_v1.py` persisted it onto
`executor_execution_leg`, the leg stayed `SUBMISSION_UNCERTAIN`, and the next
attempt's reconciliation lookup found nothing -- silently dead-lettering an
already-acknowledged `ACTIVE` order to `RECONCILIATION_REQUIRED`.

Fix: `place_order` now durably records its `ACTIVE`/`REJECTED`
acknowledgement into `PaperOrderPlacementRepositoryV1` before returning it,
and `find_order_by_client_order_id` reads that same durable record instead
of always reporting `None`. This is executor-owned bookkeeping of what this
adapter itself already decided -- not a broker call, not a second leg-state
machine, and it never produces or transitions `FILLED`/`PARTIALLY_FILLED`.

- **Deterministic identity, no new uniqueness scheme.** `client_order_id` is
  already a globally unique, deterministic UUIDv5
  (`derive_execution_client_order_id`); the new table's unique key is
  `(market, client_order_id)`.
- **Immutable, no-delete.** The migration's triggers forbid `UPDATE`/`DELETE`
  on `executor_paper_order_placement`, matching `executor_execution_leg`'s
  own identity-immutability convention.
- **Idempotent replay.** Re-placing the identical
  `(market, client_order_id, side, price, quantity)` returns the
  already-recorded acknowledgement rather than re-evaluating against
  possibly different current market evidence or writing a duplicate row.
- **Fail-closed on identity reuse.** Reusing `(market, client_order_id)` for
  a *different* order identity raises `PaperOrderPlacementConflictError`
  instead of guessing; the shared submission orchestrator's existing
  generic-exception handling already turns that into no state change /
  `SUBMISSION_UNCERTAIN`, never a silent overwrite.
- **Regression coverage:** `tests/test_paper_order_adapter_v1.py` covers
  crash-window recovery of an acknowledged `ACTIVE` order, recovery of a
  `REJECTED` order, identical-identity idempotency, and conflicting-identity
  fail-closed behavior directly on the adapter.
  `tests/test_automatic_buy_paper_fill_execution_v1.py` covers the same
  crash window through the real shared `submit_execution_plan` orchestrator:
  a simulated crash between the `ACTIVE` acknowledgement and
  `executor_execution_leg` persistence, followed by a retry that recovers
  the identical order (same `broker_order_id`) with no second `place_order`
  call and no `RECONCILIATION_REQUIRED` dead end.

## Idempotency and replay

`submit_and_reconcile_automatic_buy_paper_plan_v1` is safe to call more than
once for the same plan/handoff:

- Submission itself is the existing, unchanged, claim-guarded
  `submit_execution_plan`; a second call for an already-resolved leg makes no
  duplicate placement.
- Reconciling an already-`FILLED` leg again reproduces the identical
  `source_snapshot_id`/`cumulative_filled_base_quantity`, so #752's own
  replay guarantee returns the existing fact unchanged and emits no new
  ownership event.

## Layer boundaries respected

```text
executor           -> unchanged; only its existing public submit_execution_plan
                       is called; no strategy/ownership logic added there
decision_gate       -> unchanged; only its existing public B5 bridge is called
execution_planner   -> unchanged
entry_policy        -> new composition (owns automatic-BUY plan identity,
                        exactly like the existing intake seam)
```

## Safety markers

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=unchanged
execution_planner=unchanged
executor=extended (new PAPER adapter only; shared submission orchestrator unchanged)
production_runtime_activation=0
paper_adapter_not_configured_guard=unchanged (shared_execution_runtime_v1.py)
```

## Next slice

B6 (`fib_map_bound_trade_v1` repository) and B7 (binding adapter) remain
next per `docs/status/issue_753_paper_acceptance_blocker_v1.md`'s original
sequencing and do not depend on this phase. Note the post-review scope correction above: this V1 adapter never returns
`FILLED` at all (a crossing quote is `REJECTED`; a non-crossing quote rests
`ACTIVE` with no later reconciliation), so B8 (the exact-path PAPER
acceptance harness) cannot exercise a real automatic-BUY PAPER fill
end-to-end until a later phase adds real resting-order (`ACTIVE -> FILLED`)
reconciliation for PAPER.
