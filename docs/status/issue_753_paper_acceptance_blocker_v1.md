# Issue #753 — exact-path PAPER acceptance: blocked on PAPER ACTIVE -> FILLED reconciliation

## Status

B5.5 (the PAPER order-placement adapter gap), B6 (the
`fib_map_bound_trade_v1` repository), B7 (the first-fill binding adapter),
and now B7.5 (resting-order `ACTIVE -> FILLED` reconciliation) are resolved
-- see Update 5 below. B8 (the exact-path PAPER acceptance harness) is now
**technically runnable**: a real automatic-BUY PAPER order can reach
`FILLED` end-to-end for the first time. B8 itself is **not yet built or
run** and is not accepted by this update -- see Update 5 for exactly what is
and is not proven.
Documenting the precise remaining gap instead of inventing a shortcut, per
task contract and `AGENTS.md` (do not fabricate ownership from wallet
balance, do not invent parallel logic, do not revive #707/#723).

**Update:** gaps 1 and 2 below (`AutomaticBuyPlanV1` identity) are resolved
by Phase B4, see
`docs/architecture/automatic_buy_trade_lineage_identity_v1.md`. Gap 3
(fill -> ownership wiring) is partially resolved by Phase B5, see
`docs/architecture/automatic_buy_paper_fill_reconciliation_v1.md`: the
reconciliation bridge (including the RE_ENTER lineage-continuity decision B4
deferred) is built and tested, but B5 also surfaced a **new, deeper blocker**
-- no PAPER order-placement adapter exists anywhere in the shared executor
handoff path automatic-BUY plans flow through, so there is still no real
`BrokerCumulativeFillEvidenceV1` to call the new bridge with.

**Update 2:** the B5.5 PAPER order-placement adapter this new blocker called
for is now built, tested, and wired to the B5 bridge -- see
`docs/architecture/automatic_buy_paper_order_placement_adapter_v1.md`. Gap 3
is resolved for PAPER only up to a real `FILLED` leg: automated PR review
(`gh pr view 776`) found the initial version falsely treated a crossed
post-only quote as an instant fill and left a resting `ACTIVE` leg with no
reconciliation path back to `FILLED`. Both are now fixed: a crossing quote is
`REJECTED` (matching real post-only exchange behavior) and a non-crossing
quote rests `ACTIVE` with the adapter explicitly documented and enforced as
submission-time-only -- this V1 adapter never returns `FILLED`. A real
automatic-BUY PAPER fill therefore still requires a later phase that adds
resting-order (`ACTIVE -> FILLED`) reconciliation before B8's harness can
exercise one end-to-end. Gap 4 (`fib_map_bound_trade_v1` repository) is now
resolved by B6.

**Update 3:** B6 (`src/decision_gate/fib_map_bound_trade_repository_v1.py`)
is built and tested: insert-at-first-fill semantics, exact-lineage load
(`uq_fib_map_bound_trade_lineage`), exact-source-fill load
(`uq_fib_map_bound_trade_source_fill`), deterministic row conversion with
`Decimal`-fidelity JSON target levels and UTC-aware timestamp restoration,
and fail-closed conflict errors for lineage/source-fill/binding-id reuse
with different immutable content. No schema change was needed; the existing
migration's unique keys were sufficient. B8 (the exact-path PAPER acceptance
harness this document was originally about) remains a separate, not-yet-
started phase, now additionally blocked on the B5.5-documented
`ACTIVE -> FILLED` PAPER reconciliation gap (see Update 4).

**Update 4:** B7
(`src/decision_gate/fib_map_bound_trade_first_fill_binding_adapter_v1.py`) is
built and tested: `CanonicalFibMapEvidenceV1` (a narrow, explicit
caller-supplied canonical map evidence contract mirroring existing
native-map field names, no parallel geometry), pure
`build_fib_map_bound_trade_v1_from_first_fill` (deterministic `binding_id`,
`bound_ts_utc` always the fill's own `occurred_ts_utc`, fail-closed on
identity mismatch / non-BUY source fill / stale or future map evidence), and
`bind_fib_map_bound_trade_on_first_fill_v1` which persists through the
unchanged B6 repository. First-fill ordering is now verified explicitly
against history loaded directly from the canonical persisted #752 repository
using deterministic `(occurred_ts_utc, event_id)` ordering; build/bind accept only a
`VerifiedFirstBuyFillV1`. B6 unique keys remain the independent replay and
no-rebind backstop. The full target ladder is frozen verbatim -- B7 never
filters to currently-active or unconsumed targets. See
`docs/architecture/fib_map_bound_trade_first_fill_binding_adapter_v1.md`.
At the time of Update 4, B8 remained BLOCKED because B7 only closes the
construct+persist path from a real `StrategyOwnedInventoryEventV1` to a
`FibMapBoundTradeV1`; it could not yet produce the real automatic-BUY PAPER
fill B8's harness needs. That specific gap is closed by Update 5 below.

**Update 5:** B7.5 (`src/executor/paper_resting_order_reconciliation_v1.py`) is built and tested. The B5.5 resting-order gap is closed with conservative PAPER-only semantics: BUY fills only after a later `best_ask < resting price`, SELL only after `best_bid > resting price`; equality remains `ACTIVE` because queue priority is unknown. Reconciliation requires the exact PAPER handoff, an identity-matching persisted `ACTIVE` placement from `executor_paper_order_placement`, and a valid quote observed strictly after that placement. Temporary/missing/conflicting evidence never changes structural `ACTIVE` state. The executor leg write is an explicit broker-order-id-guarded CAS `ACTIVE -> FILLED`; placement history remains immutable. `automatic_buy_paper_fill_execution_v1.py` reconciles only legs that were already ACTIVE before the current submission call, then routes a resulting persisted FILLED leg through the unchanged #752/B5 ownership bridge. Replay emits no duplicate ownership event. See `docs/architecture/paper_resting_order_active_fill_reconciliation_v1.md`.

**B8 is now technically runnable, but explicitly NOT accepted by Update 5.** A real automatic-BUY PAPER path can now produce persisted `FILLED` plus strategy-owned inventory without fixture mutation. B8 still must build and run the single exact-path acceptance lifecycle required by #753; do not treat B7.5 as that acceptance having passed.

**Update 6:** B7.6 is merged via PR #807. `src/orchestration/fib_map_bound_exit_paper_fill_execution_v1.py` now provides the missing production PAPER SELL composition: a pre-existing resting SELL leg may reconcile `ACTIVE -> FILLED` only on strict post-placement price-through, then the exact Fib-bound lineage is reduced through decision_gate-owned #752 reconciliation. Reduction authorization plus reconciliation fact and optional SELL inventory event are atomic under exact-lineage `FOR UPDATE` serialization. Failure rolls back the whole mutation; concurrent reductions cannot both authorize against stale owned quantity. Existing bounded Fib exit plan references preserve their legacy identity; oversized new identities fall back to a deterministic persistence-safe hash. No LIVE/broker/wallet authority was added.

**Update 7:** PR #806 now contains the complete B8 exact-path PAPER acceptance matrix. The canonical test starts at market-only setup -> automatic BUY candidate -> decision_gate -> BUY planner -> real PAPER ACTIVE -> later strict-through FILLED -> #752 BUY ownership -> authoritative first-fill verification -> immutable B6/B7 Fib binding. It then exercises real PAPER target SELL fills through the merged B7.6 production bridge, deterministic next-target order, invalidation precedence, target-fill then invalidation of only the exact remaining owned quantity, immutable old-map binding under newer maps, restart/replay preservation, stale/missing/conflicting evidence fail-closed, same-asset cross-bucket isolation, and duplicate-cycle idempotency. The acceptance test contains no direct `reconcile_cumulative_fill_v1`/fact-append shortcut and no synthetic FILLED fixture mutation. Focused+adjacent B8 suite: 146 passed; py_compile + `git diff --check` PASS. B8 is technically PASS on the current #806 branch, but #753 must not be treated as technically complete until #806 itself clears review and is merged.

## What already composes safely (reviewed, unit-tested, no changes needed)

- B1 `src/decision_gate/fib_map_bound_trade_v1.py` — `FibMapBoundTradeV1`
  (frozen dataclass) + `validate_fib_map_bound_trade_v1` +
  `assert_fib_map_binding_set_immutable_v1`. Pure in-memory structural
  validation over caller-supplied identity/geometry.
- B2 `src/decision_gate/fib_map_bound_exit_decision_v1.py` —
  `evaluate_fib_map_bound_exit_decision_v1(binding, owned_position,
  progression, market_evidence, evaluation_ts_utc, max_price_age_seconds)`.
  Pure function; invalidation-wins-over-target and next-unconsumed-target
  semantics are already correct and tested.
- B3 `src/execution_planner/fib_map_bound_exit_planner_v1.py` +
  `fib_map_bound_exit_execution_handoff_adapter_v1.py` +
  `..._application_v1.py` — builds a single-leg SELL plan from a B2 decision,
  adapts it to the shared `ApprovedExecutionPlanV1`, and submits it through
  the same `ExecutionHandoffRepositoryV1` (`src/executor/execution_handoff_v1.py`)
  used by the BUY side. Deterministic `plan_reference_id` prevents duplicate
  handoff on replay.
- B6 `src/decision_gate/fib_map_bound_trade_repository_v1.py` —
  `FibMapBoundTradeRepositoryV1.record_fib_map_bound_trade_v1` (insert-at-
  first-fill, idempotent replay) + `load_by_binding_id` / `load_by_lineage` /
  `load_by_source_fill` against the existing
  `db/migrations/20260906_fib_map_bound_trade_v1.sql` unique keys.
- B7 `src/decision_gate/fib_map_bound_trade_first_fill_binding_adapter_v1.py`
  — `build_fib_map_bound_trade_v1_from_first_fill` / `bind_fib_map_bound_trade_on_first_fill_v1`.
  Verifies the earliest BUY against authoritative persisted #752 history,
  then constructs and persists one `FibMapBoundTradeV1` from that verified
  fill plus caller-supplied `CanonicalFibMapEvidenceV1`, through B6.
- B7.5 `src/executor/paper_resting_order_reconciliation_v1.py` +
  `ExecutionLegRepositoryV1.mark_active_filled_price_through_v1` —
  conservative, fail-closed PAPER `ACTIVE -> FILLED` reconciliation with
  persisted placement identity/time proof, strict price-through semantics,
  PAPER-handoff enforcement, and broker-order-id CAS. Wired into
  `automatic_buy_paper_fill_execution_v1.py` only for pre-existing ACTIVE
  legs ahead of its existing FILLED-leg -> #752 bridge loop.

The B1→B2→B3 chain, given a `FibMapBoundTradeV1` and a
`StrategyOwnedInventoryPositionV1`, already produces a correct, idempotent,
layer-respecting exit path. This part does not need new code.

## The missing bridge

There is no reviewed path from a real automatic_buy (#399) PAPER fill to the
identity that B1/B2 require. Four concrete gaps, each its own architectural
decision:

1. ~~**`AutomaticBuyPlanV1` carries no `trade_id`.**~~ RESOLVED by B4:
   `AutomaticBuyPlanV1.trade_id` is now bound deterministically by the
   planner at APPROVED-decision time, per
   `docs/architecture/automatic_buy_trade_lineage_identity_v1.md`. Note the
   documented open follow-on: this V1 rule mints a genesis id per accepted
   decision and does not yet resolve RE_ENTER continuity onto an
   already-open position — that remains B5's job.

2. ~~**`strategy_bucket_id` is computed at gate time and dropped before the
   plan.**~~ RESOLVED by B4: `AutomaticBuyGateDecisionV1.strategy_bucket_id`
   is copied exactly from `AutomaticBuyGateContextV1.strategy_bucket_id` on
   every APPROVED decision, and `AutomaticBuyPlanV1.strategy_bucket_id`
   copies it again from the decision. Both flow into the shared execution
   handoff's identity payload.

3. ~~**No code creates a `StrategyOwnedInventoryEventV1` from a BUY fill.**~~
   PARTIALLY RESOLVED by B5:
   `src/decision_gate/automatic_buy_fill_reconciliation_v1.py` and
   `..._persistence_v1.py` now bridge a caller-supplied automatic-BUY plan
   identity + `BrokerCumulativeFillEvidenceV1` into a persisted
   `StrategyOwnedInventoryEventV1`, resolving RE_ENTER continuity via #752's
   inventory projection. See
   `docs/architecture/automatic_buy_paper_fill_reconciliation_v1.md`. What
   remains open: nothing in reviewed code produces a real
   `BrokerCumulativeFillEvidenceV1` for an automatic-BUY PAPER order --
   `src/executor/shared_execution_runtime_v1.py` explicitly raises
   `PAPER_ADAPTER_NOT_CONFIGURED` for PAPER mode, and no other seam exists.
   That PAPER order-placement adapter is its own unresolved architectural
   decision, out of scope for B5.

4. **`fib_map_bound_trade_v1` has a DB schema
   (`db/migrations/20260906_fib_map_bound_trade_v1.sql`) but zero Python
   repository.** No module reads or writes that table; the binding is
   in-memory-dataclass-only today. A restart/replay acceptance test needs a
   repository that does not yet exist.

`tests/test_fib_map_bound_trade_v1.py`'s `_binding()` helper builds
`FibMapBoundTradeV1` from hardcoded literals (`"trade-1"`, `"fill-1"`,
`"plan-1"`) — synthetic identity, not identity produced by any real
automatic_buy fill. No test file imports both `automatic_buy_*` and
`fib_map_bound_*` together (`grep` confirms zero matches either direction).

## Why this is not safe to bridge inside this bounded slice

Each gap is a production-code decision on already-merged, reviewed contracts:

- adding `trade_id` (and deciding its generation rule — new value at first
  fill vs. reuse of `setup_id`/`candidate_evidence_id`) to `AutomaticBuyPlanV1`
  and its handoff payload;
- propagating `strategy_bucket_id` through the same path;
- wiring automatic_buy's PAPER fill handling to call #752's reconciliation
  and persist a `StrategyOwnedInventoryEventV1`;
- writing a new `fib_map_bound_trade_v1` repository and deciding the
  "bind at first fill" transaction boundary against the existing unique keys
  (`uq_fib_map_bound_trade_lineage`, `uq_fib_map_bound_trade_source_fill`).

None of these choices are settled by the existing #399/#752/#753 threads.
Fabricating them here — e.g. inventing a `trade_id` convention or writing a
new adapter that silently derives ownership from a BUY plan without a
reviewed contract — would be exactly the kind of parallel/shortcut logic the
task contract prohibits, and would risk masking real ownership-attribution
bugs behind a harness that only proves synthetic identities compose (which
the existing B1/B2/B3 unit tests already prove).

## Recommended next bounded slices (for separate review/PRs)

1. ~~`#753 B4` — add `trade_id` + `strategy_bucket_id` to `AutomaticBuyPlanV1`
   and the automatic_buy execution handoff payload; document the `trade_id`
   generation rule.~~ DONE, see
   `docs/architecture/automatic_buy_trade_lineage_identity_v1.md`.
2. ~~`#753 B5` — wire automatic_buy PAPER fill handling to #752
   reconciliation so a real fill produces a `StrategyOwnedInventoryEventV1`.~~
   PARTIALLY DONE, see
   `docs/architecture/automatic_buy_paper_fill_reconciliation_v1.md`: the
   reconciliation bridge is built, tested, and reusable, but B5 surfaced that
   no PAPER order-placement adapter exists to actually trigger it.
2b. ~~`#753 B5.5` — design and build a reviewed PAPER order-placement
   adapter for the shared executor handoff path (decide the truthful-fill
   simulation contract), then wire it to call the B5 bridge.~~ DONE
   (post-only-correct: crossed = `REJECTED`, non-crossed = `ACTIVE`,
   submission-time-only, never `FILLED`), see
   `docs/architecture/automatic_buy_paper_order_placement_adapter_v1.md`.
3. ~~`#753 B6` — add a `fib_map_bound_trade_v1` repository
   (insert-at-first-fill, load-by-lineage) matching the existing migration's
   unique keys. Independent of B5.5.~~ DONE, see
   `src/decision_gate/fib_map_bound_trade_repository_v1.py`.
4. ~~`#753 B7` — adapter that constructs a `FibMapBoundTradeV1` from a
   strategy-owned inventory position + canonical Fib map evidence at first
   fill, using B4-B6.~~ DONE, see
   `src/decision_gate/fib_map_bound_trade_first_fill_binding_adapter_v1.py`.
4b. ~~`#753 B7.5` — resting-order `ACTIVE -> FILLED` PAPER reconciliation,
   the gap B5.5 explicitly deferred and B7's own status update named as
   still blocking B8.~~ DONE, see
   `docs/architecture/paper_resting_order_active_fill_reconciliation_v1.md`.
5. `#753 B8` — the exact-path PAPER acceptance harness this task was asked to
   build: now technically runnable given B7.5's real fill path, but not yet
   built or run. Do not treat B7.5 as B8 having passed.

## Safety markers

Markers below are for the original (pre-B4) blocked state. See
`docs/architecture/automatic_buy_trade_lineage_identity_v1.md` for B4's own
safety markers.

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=unchanged
execution_planner=unchanged
executor=unchanged
production_code_changed=0
```

## Update 6 — B7.6 PAPER SELL fill ownership bridge

B8 hardening exposed a real missing production seam: a FILLED PAPER SELL leg
could be converted to cumulative fill evidence, and #752 reconciliation was
side-neutral, but no reviewed application path connected those two for
Fib-map-bound exits. A test-only direct call to generic reconciliation would
not count as exact-path acceptance.

B7.6 closes that gap with:

- `src/decision_gate/fib_map_bound_exit_fill_reconciliation_v1.py` — exact
  SELL lineage + current-owned-quantity authorization before any emitted
  reduction delta;
- `src/decision_gate/fib_map_bound_exit_fill_reconciliation_persistence_v1.py`
  — append-only/replay-safe #752 persistence;
- `src/orchestration/fib_map_bound_exit_paper_fill_execution_v1.py` — PAPER-only
  composition of existing handoff, placement, resting reconciliation, FILLED
  evidence, and decision_gate persistence.

No execution-planner or executor policy was moved or duplicated. No LIVE or
broker-private path is activated. B8 remains NOT accepted until PR #806 is
updated to exercise this merged production bridge across all ten acceptance
cases without test-only ownership mutation.

**B7.6 review hardening:** SELL reduction persistence is atomic and serialized.
The exact #752 lineage rows are locked `FOR UPDATE`; authorization, reconciliation
fact append, and optional SELL inventory-event append share one transaction.
Failure rolls back both writes. Concurrent reductions against the same lineage
serialize, so the later transaction observes the earlier committed reduction
before authorization. Regression coverage includes the fact/event crash window
and competing reductions whose combined quantity exceeds current ownership.
