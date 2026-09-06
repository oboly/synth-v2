# Automatic BUY Plan/Handoff Lineage Identity V1 (Issue #753 Phase B4)

## Purpose

Closes the identity bridge gap documented in
`docs/status/issue_753_paper_acceptance_blocker_v1.md` gaps 1 and 2: a real
automatic-BUY (#399) plan carried no `trade_id`, and the gate-validated
`strategy_bucket_id` was dropped before reaching `AutomaticBuyPlanV1` and the
shared executor handoff. #752's `StrategyOwnedFillLineageV1` and B1's
`FibMapBoundTradeV1` both require exactly these two fields; without them
there is no reviewed path from a PAPER fill to ownership/exit identity.

This is plumbing plus one narrow, reviewed identity-genesis contract. It does
**not** wire automatic-BUY fills to #752 reconciliation (B5), does not add a
`fib_map_bound_trade_v1` repository (B6), and does not touch the exact-path
PAPER acceptance harness (B8).

## What changed

- `src/decision_gate/automatic_buy_gate_v1.py` -- `AutomaticBuyGateDecisionV1`
  gained `strategy_bucket_id: str | None`, copied **exactly** from
  `AutomaticBuyGateContextV1.strategy_bucket_id` (never inferred, never
  recomputed) on every `APPROVED` decision, and cleared back to `None` on
  every decision that is not (or is downgraded away from) `APPROVED` --
  including the two protection-driven `APPROVED -> DENIED` downgrade paths in
  `evaluate_automatic_buy_candidate_permission_v1`, which previously would
  have silently left a stale `APPROVED`-era bucket id on a `DENIED` decision.
- `src/execution_planner/automatic_buy_planner_v1.py` -- `AutomaticBuyPlanV1`
  gained `strategy_bucket_id: str` (copied from `decision.strategy_bucket_id`,
  fails closed with `GATE_DECISION_STRATEGY_BUCKET_ID_MISSING` if absent/empty)
  and `trade_id: str` (bound by the planner itself via
  `derive_automatic_buy_trade_id_v1`, see below).
- `src/execution_planner/automatic_buy_execution_handoff_adapter_v1.py` --
  both fields are required non-empty (`PLAN_IDENTITY_LINEAGE_FIELD_EMPTY`) and
  are included in the identity payload hashed into `plan_reference_id`, so a
  change to either changes the derived handoff identity. The contract version
  used in that hash was bumped
  (`automatic_buy_execution_handoff_adapter_v1_b4`) since the payload shape
  changed; no old `plan_reference_id` is reproducible under the new version,
  which is intentional -- it is a derived identity, not stored truth.
- `src/entry_policy/automatic_buy_runtime_audit_writer_v1.py` -- the
  append-only `immutable_plan_json` audit payload includes both fields.

No change was needed to `AutomaticBuyGateContextV1`, the automatic-BUY
runtime input contract, migrations, or
`automatic_buy_runtime_orchestrator_v1.py`: `strategy_bucket_id` was already
present as validated context evidence, and `trade_id` requires no new
evidence source (see contract below).

## `trade_id` generation contract (V1, genesis-only)

`derive_automatic_buy_trade_id_v1` in `automatic_buy_planner_v1.py` binds a
`trade_id` deterministically from the exact identity of one `APPROVED` gate
decision:

```text
trading_account_id, venue, asset_id, market, strategy_bucket_id,
strategy_id, strategy_version, setup_id, candidate_action,
candidate_evidence_id
```

hashed (sha256 of canonical JSON) into
`automatic_buy_trade_id_v1:{trading_account_id}:{digest}`.

Guarantees this rule actually provides:

- **Idempotent replay.** Re-running the exact same `APPROVED` decision (a
  crash/restart re-processing the same runtime input row) always derives the
  same `trade_id`, hence the same `plan_reference_id`, hence the same
  duplicate-safe handoff row.
- **No cross-lineage collision.** Any change to account/venue/asset/market,
  `strategy_bucket_id`, strategy identity, `setup_id`, `candidate_action`, or
  `candidate_evidence_id` changes the id. It never aliases `setup_id` or
  `candidate_evidence_id` directly as the `trade_id` value -- both are mixed
  into a distinct namespace instead, so nothing downstream can mistake a
  `trade_id` for a `setup_id` or vice versa.
- Execution_planner is the layer that binds this id, per the architecture
  contract's explicit allowance that "`execution_planner` ... may bind/forward
  identity only after gate approval" -- unlike `strategy_bucket_id`, which the
  same contract requires to be copied, never inferred, `trade_id` did not
  exist anywhere upstream to copy from (blocker-doc gap 1), so the planner is
  the first and only correct point to mint it.

## Explicitly deferred: RE_ENTER lineage continuity

This rule mints a **new** genesis `trade_id` for every accepted decision,
including a `RE_ENTER` candidate. It does **not** attempt to detect whether a
`RE_ENTER` is adding to an already-open strategy-owned position (in which
case #752's `StrategyOwnedInventoryPositionV1` accumulation and B1's
`uq_fib_map_bound_trade_lineage` both assume the *same* `trade_id` should be
reused) versus opening a genuinely new position under the same setup after a
prior full exit (a genuinely distinct `trade_id`).

Deciding that requires querying the current open/closed state of
`StrategyOwnedInventoryPositionV1` for this lineage -- state this pure,
DB-free planner does not have, and that no automatic-BUY code path yet
produces (blocker-doc gap 3). Fabricating an answer here in either direction
would repeat the exact mistake the blocker doc's task contract prohibits:

- reusing `setup_id` (or any candidate-cycle-stable field) as `trade_id`
  outright would risk **merging** two genuinely distinct historical trades
  under one lineage if a setup is fully exited and later re-entered, corrupting
  `project_strategy_owned_inventory_v1`'s accumulation and violating B1's
  one-binding-per-lineage unique key; the unsafe direction.
- silently trying to "look up" continuation state without a reviewed
  repository/reconciliation contract would be exactly the invented shortcut
  the blocker doc calls out.

This V1 genesis rule chooses the conservative failure mode: it may
**fragment** what should conceptually be one continued trade into multiple
adjacent `trade_id`s (safe, inspectable, never silently wrong) rather than
risk merging two distinct trades under one id (unsafe, silently wrong). B5
("wire automatic-BUY PAPER fill handling to #752 reconciliation") must
resolve RE_ENTER continuity using the inventory projection before any code
depends on cross-cycle `trade_id` reuse; until then, callers must not assume
a `RE_ENTER` shares a `trade_id` with a prior `ENTER` of the same setup.

## Layer boundaries respected

```text
entry_policy (candidate)  -> market-only, account-agnostic; does not carry
                              strategy_bucket_id or trade_id (unchanged)
decision_gate              -> owns strategy_bucket_id evidence; copies it
                              onto the decision verbatim, never inferred
execution_planner          -> owns immutable BUY intent; binds trade_id only
                              after STATE_APPROVED, forwards strategy_bucket_id
executor                   -> unchanged; transports the plan, does not read
                              or interpret trade_id/strategy_bucket_id
```

## Safety markers

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=extended (strategy_bucket_id copy-through only)
execution_planner=extended (trade_id genesis binding only)
executor=unchanged
production_runtime_activation=0
```

## Next slice (B5) -- done

Phase B5 wired automatic-BUY PAPER fill handling to #752's
`reconcile_cumulative_fill_v1` and resolved the RE_ENTER continuity decision
above using the inventory projection. See
`docs/architecture/automatic_buy_paper_fill_reconciliation_v1.md`. B5 also
surfaced that no PAPER order-placement adapter exists yet to actually trigger
that bridge with a real fill -- tracked as `#753 B5.5` in
`docs/status/issue_753_paper_acceptance_blocker_v1.md`.
