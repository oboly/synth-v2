# V1 strategy capital sleeves and strategy-owned position quantities (Issue #752)

## Problem

Capital sleeves are logical configuration on one broker account, not
separate broker wallets (#752 design freeze). Before this change, current
main had two structural gaps confirmed by audit:

1. `strategy_bucket_account_config_v1` (#279) owned absolute EUR ceilings
   (`max_bucket_amount_eur`, `max_position_amount_eur`) and a per-asset
   exposure percentage (`max_asset_exposure_pct`), but had no
   percentage-of-account-equity allocation concept at all.
2. No table anywhere carried `strategy_bucket_id`/`strategy_id`/`setup_id`
   as queryable columns on a fill/order row. `account_position_snapshot`
   (reconciliation's broker-wallet truth) is a raw per-symbol balance with
   no strategy dimension, and `AutomaticBuyGateDecisionV1` dropped
   `strategy_bucket_id` after gate evaluation, so it never reached
   `AutomaticBuyPlanV1`. If two strategies ever held the same asset, nothing
   in the repository could tell one strategy's quantity apart from
   another's, or from unattributed/manual inventory.

## Layer ownership (unchanged, extended in place)

```text
selection_engine   -> market-only, account-agnostic. Untouched by #752
                       (see the architecture guard test below).
decision_gate      -> owns strategy-bucket config (#279, extended here),
                       capacity computation (new), and strategy-owned
                       inventory ownership/SELL-authority (new).
execution_planner  -> carries strategy_bucket_id through the #399
                       automatic-BUY plan; computes no allocation/capacity
                       policy itself.
executor           -> unchanged; computes no allocation/capacity policy.
```

## Capital sleeve configuration (extends #279, does not replace it)

`strategy_bucket_account_config_v1` gains three new nullable columns via
`db/migrations/20260905_strategy_bucket_allocation_pct_v1.sql`:

- `allocation_target_pct` -- **advisory only**. Never forces deployment,
  never read by any block/permit decision. It exists purely as operator
  context (e.g. "we intend to run this bucket around 20% of equity").
- `allocation_max_pct` -- hard percentage-of-account-equity ceiling.
- `max_position_pct_of_bucket` -- optional per-position ceiling as a
  fraction of this bucket's own effective ceiling.

All three are nullable so every config row created before #752 remains
valid unchanged: `NULL` means "no percentage-of-equity policy configured",
and the effective ceiling then reduces to #279's original absolute-only
behavior. `src/decision_gate/strategy_bucket_account_config_contract_v1.py`
validates `0 <= allocation_target_pct <= allocation_max_pct <= 1` and
`0 < max_position_pct_of_bucket <= 1` when configured, alongside the
existing #279 field validation it already performed.

### Effective bucket ceiling

`src/decision_gate/strategy_bucket_capacity_v1.py` (new, decision_gate-only,
pure functions, no DB/broker/market-ranking access) computes:

```text
effective_bucket_ceiling_eur = MIN(
    account_equity_eur * allocation_max_pct,   # if configured
    max_bucket_amount_eur,                     # if configured (#279)
)
```

If only one of the two is configured, that one alone is the ceiling; if
neither is configured, there is no ceiling and `validate_new_entry_within_
capacity_v1` does not block (mirroring #279's original "no ceiling
configured means no block" behavior exactly). `remaining_capacity_eur =
effective_bucket_ceiling_eur - owned_exposure_eur - active_reservations_eur`,
where the caller supplies already-observed owned exposure and reservation
totals from canonical existing sources (e.g.
`automatic_buy_account_allocation_evidence_contract_v1`) -- this module
never recomputes or duplicates reservation accounting itself.

### Aggregate fail-closed policy

`validate_aggregate_sleeve_allocation_policy_v1` sums `allocation_max_pct`
across every **enabled** bucket that configures it. If the sum exceeds 100%
of account equity, it raises `AGGREGATE_SLEEVE_ALLOCATION_MAX_PCT_EXCEEDS_
ACCOUNT_POLICY` -- a fail-closed configuration error an operator must fix.
This module never renormalizes percentages and never authorizes borrowing
unused capacity across sleeves; unused capacity may remain cash/reserve.

### Enforcement in the real automatic-BUY gate path

`allocation_max_pct`/aggregate capacity is not only a standalone helper --
it is called from inside the actual canonical account-aware decision
function, `evaluate_automatic_buy_candidate_permission_v1` in
`src/decision_gate/automatic_buy_gate_v1.py`, the same function
`src/entry_policy/automatic_buy_runtime_orchestrator_v1.py` invokes at
runtime for every candidate. `AutomaticBuyGateContextV1` gained three new
fields: `account_equity_eur`, `strategy_owned_exposure_eur` (both
`Decimal | None`, default `None`), and `active_buy_reservations_eur`
(default `Decimal("0")`, since no canonical BUY-side EUR reservation source
exists in this repository today -- only SELL-side reservations do, via
`sell_reservation_v1`).

After the existing #279 bucket-participation check passes, the gate:

1. Resolves every distinct bucket id present in the caller's own
   account-scoped `strategy_bucket_config_rows` (already loaded account-wide,
   never a new query) and calls `validate_aggregate_sleeve_allocation_policy_v1`
   -- a misconfigured *sibling* bucket's aggregate violation blocks this
   candidate's NEW exposure too, matching the aggregate policy's
   account-wide intent.
2. Re-resolves the candidate's own bucket config (deterministic, from the
   same rows already validated by the #279 participation check) and, only
   if it configures `allocation_max_pct`, requires `account_equity_eur` and
   `strategy_owned_exposure_eur` to be present -- fails closed
   (`STRATEGY_BUCKET_CAPACITY_EVIDENCE_MISSING`) for NEW exposure otherwise.
   A legacy `allocation_max_pct is None` config is never affected by a
   missing value here, preserving #279's original behavior exactly.
3. Computes `strategy_bucket_capacity_v1` capacity and calls
   `validate_new_entry_within_capacity_v1` against the same final
   gate-approved notional ceiling (`ceiling`, after the existing
   `free_quote_balance_eur`/`max_automatic_buy_notional_eur` reductions) --
   never against the raw unbounded request.

None of this ever runs for a reducing/protective exit: the automatic-BUY
gate only ever evaluates `REQUEST_KIND_NEW_ENTRY` requests; SELL/exit
authority is `strategy_owned_inventory_ledger_v1.validate_sell_authority_v1`
alone, which this module never calls.

Real evidence source: `strategy_owned_exposure_eur` is queried from the
ledger (`strategy_owned_inventory_ledger_v1.compute_bucket_owned_exposure_eur_v1`
over `strategy_owned_inventory_ledger_repository_v1.load_strategy_owned_fill_events_for_bucket_v1`)
inside `automatic_buy_account_allocation_evidence_repository_v1.py` (#474),
the same decision-gate-owned repository that already computes
`account_equity_eur` (exposed verbatim from its existing internal `nav_eur`
= positions + free quote balance -- not a parallel computation). These flow
`evidence -> AutomaticBuyRuntimeInputV1 -> AutomaticBuyGateContextV1` exactly
the way every other account-owned field on the runtime input already does
in `automatic_buy_runtime_repository_v1.build_runtime_item_v1`
(`dataclasses.replace`, overwriting any placeholder the persisted row
carried). A separate, older lane
(`automatic_buy_source_runtime_input_writer_v1.py`, a placeholder-based
DRY_RUN acceptance harness pre-dating #474/#752) does not call this evidence
repository at all and so never supplies real values for these three fields;
its rows fall back to the new fields' `0`/`None` defaults, which is a
pre-existing, orthogonal gap in that harness (not introduced or worsened by
#752) rather than a #752 defect.

## Strategy-owned inventory ledger (new; no canonical existing owner fit)

`db/migrations/20260905_strategy_owned_inventory_ledger_v1.sql` adds
`strategy_owned_inventory_ledger_v1`: an append-only, event-sourced table of
attributed BUY/SELL fill events. This is deliberately new persistence, not a
parallel broker-position-truth model:

```text
broker wallet balance   = reconciliation fact (account_position_snapshot,
                           unchanged by this table)
strategy-owned quantity = allocation/position ownership fact (this table)
```

Ownership is never derived after the fact by heuristically splitting a
wallet balance; it exists only as the deterministic sum of explicitly
attributed fill events.

### Lineage identity

```text
(trading_account_id, venue, market, strategy_bucket_id, strategy_id,
 strategy_version, setup_id)
```

Two lineages differing only in strategy/trade identity may both own
quantity in the identical `(trading_account_id, venue, market)` without
collision -- each is tracked and summed independently. Example from the
task contract: broker wallet SOL = 100. `LONG_TERM_MOONSHOT` owns 60,
`AUTO_SHORTTF_FIB` owns 40. `AUTO_SHORTTF_FIB`'s exit may reduce at most its
own 40; a request for 41 fails closed and the long-term 60 is never touched
by evaluating it.

### Ownership invariant and idempotence

`src/decision_gate/strategy_owned_inventory_ledger_v1.py` (pure functions):

```text
owned_qty(lineage) = SUM(attributed BUY fills) - SUM(attributed SELL fills)
```

deduplicated first by canonical `order_identity` (e.g. `client_order_id`, or
`client_order_id:leg_index` for a multi-leg plan) so a duplicate
reconciliation event -- at-least-once delivery, or a restart replay -- never
double-counts. A duplicate `order_identity` whose recorded fields disagree
with the first occurrence fails closed (`CONFLICTING_DUPLICATE_ORDER_
IDENTITY`) rather than silently accepting either value. Because the table is
append-only and ownership is always recomputed from source fill identity
(never a separately maintained mutable counter), a service restart cannot
lose or corrupt ownership -- reloading the same persisted events and
recomputing yields the identical result regardless of iteration order.

`src/decision_gate/strategy_owned_inventory_ledger_repository_v1.py` is the
sole DB-facing writer/reader. Because the table's own triggers reject any
`UPDATE` (append-only, matching every other #279/#399 immutable-fact table
in this repository), idempotent duplicate handling cannot use `ON DUPLICATE
KEY UPDATE` (it would fire the trigger and always fail); instead a plain
`INSERT` is attempted and the DB's own unique-key rejection on
`(trading_account_id, venue, market, order_identity)` is the idempotency
signal, re-read and compared field-for-field before being treated as a
no-op.

### SELL authority

`validate_sell_authority_v1(events, lineage=..., requested_reduce_base_
quantity=...)` fails closed unless `requested_reduce_qty <= owned_qty
(lineage)` for the exact lineage requested. Broker wallet total balance is
never consulted and can never increase this authority -- only events
matching the exact lineage are summed. This function **never** consults
`allocation_max_pct`/bucket capacity: crossing the allocation ceiling blocks
**new** exposure only (`strategy_bucket_capacity_v1.validate_new_entry_
within_capacity_v1`, called for `NEW_ENTRY` requests); a valid reducing or
protective exit remains permitted even when the bucket's allocation ceiling
is already exceeded, per the #752 design freeze.

### Legacy / unattributed inventory

Any quantity never recorded through an explicit attributed BUY fill has no
lineage a caller can query, so `validate_sell_authority_v1` structurally has
nothing to authorize for it (`owned_qty` resolves to 0 for that lineage, and
any positive reduction request fails closed). This is the default and
requires no special-case code -- it falls directly out of the ownership
invariant above. No adoption/attribution UI or workflow is implemented in
this issue; attributing pre-existing/manual inventory to a strategy lineage
remains a future, explicit, separately reviewed action.

## #399 identity propagation fix

Audit found `strategy_bucket_id` lived on `AutomaticBuyGateContextV1` but
was dropped by `AutomaticBuyGateDecisionV1` -- so it never reached
`AutomaticBuyPlanV1`, even though `strategy_id`/`strategy_version`/
`setup_id` already did. This change adds `strategy_bucket_id` to
`AutomaticBuyGateDecisionV1` (`src/decision_gate/automatic_buy_gate_v1.py`)
and `AutomaticBuyPlanV1` (`src/execution_planner/automatic_buy_planner_v1.py`),
and includes it in the handoff adapter's plan-identity hash payload
(`src/execution_planner/automatic_buy_execution_handoff_adapter_v1.py`), so
a caller building a `StrategyOwnedFillEventV1` from an approved automatic-BUY
plan has the complete lineage available. This PR does not add
`strategy_bucket_id`/`strategy_id`/`setup_id` columns to the shared
`executor_execution_handoff`/`executor_execution_leg` tables or to the
shared `ApprovedExecutionPlanV1` (#206) contract -- those are used by manual
execution as well, and extending them is deliberately out of scope for this
V1-minimum change; wiring the ledger's `record_strategy_owned_fill_event_v1`
into the live #399 executor/reconciliation handoff path is a follow-on
integration task.

## Interaction with #279 / #399 / #753

- #279 remains the sole owner of `strategy_bucket_account_config_v1`; this
  change only adds columns and a capacity-computation module layered on top.
- #399's automatic-BUY gate/planner/handoff pipeline behavior is unchanged
  for any bucket that does not configure `allocation_max_pct` (verified by
  the full existing #279/#399 regression suite passing unmodified); the
  identity-propagation gap above was closed, and the gate now additionally
  enforces sleeve capacity for a bucket that does configure it.
- #753 (Fib/Elliott automatic-exit policy) is expected to be the first
  automated SELL/exit path; it must call `validate_sell_authority_v1` (and,
  for a NEW entry, `validate_new_entry_within_capacity_v1`) rather than
  reading broker wallet total balance, and must call
  `record_strategy_owned_fill_event_v1` to attribute its own fills. This
  document does not implement #753 itself.

## Safety markers

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=extended (config + capacity + ledger, no order placement)
execution_planner=extended (identity propagation only, no policy)
executor=none
```
