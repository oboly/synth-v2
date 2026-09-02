# Manual Trader Dashboard V1 — Freeze Contract (Issue #558)

## Purpose

This document freezes the current **Profit Plan** (`manual_short_trader_profit_plan_v1`)
as **Manual Trader Dashboard V1**: a stable, versioned reference implementation of
the read-only, manual-trader advisory dashboard.

Profit Plan is a non-technical, scenario-based HTML/JSON dashboard that shows a
manual short trader *what to watch next* per symbol. It is not an order dump,
not a permission surface, and not an execution surface.

"Freeze" does not mean the code may never change again. It means:

- input/output semantics are versioned by this contract;
- regressions in those semantics are detectable via the golden fixtures in
  `tests/test_manual_trader_dashboard_v1_golden.py`;
- future work on Issue #557 (automatic wallet-triggered loop) must not
  silently change the semantics this contract describes;
- an intentional change to the semantics below requires an explicit update to
  this document's contract/version section, not just a code diff.

This is a documentation + regression-hardening contract. It introduces no new
strategy functionality, no account allocation, no execution authority, and no
broker access.

## Canonical upstream owners

Profit Plan composes read-only context from named upstream owners. It does not
recompute or fabricate any of them:

| Concern | Canonical owner |
|---|---|
| Selected/current native SHORT map identity | `src/market_data/native_short_fib_context_v1.py` (`NativeShortContextRow`), joined by `run_manual_short_trader_profit_plan_v1.py::load_zone_contexts()` |
| Map lifecycle (`ACTIVE_4H_EXTENSION`, `MAP_COMPLETED`, rollover, etc.) | Native SHORT snapshot row / `CardEvidence.lifecycle_state` |
| Fibonacci levels (reload/re-entry, target/sell, invalidation) | Native SHORT row extension/reload/invalidation fields, or the canonical `1d` fib-map bridge as reference-only fallback |
| Current price / freshness | Account-scoped DB context (`load_account_scoped_short_dashboard_context()`) + `classify_market_prices_by_market()`; direct ticker fetching is intentionally excluded from the production runner |
| Actionable PPP / ranking | `_actionable_ppp()` / `_actionable_ppp_eligible()` in `manual_short_trader_profit_plan_v1.py`, using canonical native map truth + lifecycle authority only |
| Action/timing reason | `_entry_wait_label()`, `_format_actionable_ppp()`, `card.reasons`, all derived deterministically from the same evidence the card already carries |

Planning PPP provenance (which authority produced the entry vs. target level)
is owned by `PlanningProvenance` / `make_planning_provenance()`, attributed
exclusively by `load_zone_contexts()` — see
`docs/architecture/profit_plan_planning_ppp_provenance_v1.md` (Issue #457).

## Advice / actionability semantics

Every card carries a canonical `actionability_state`:

```text
CARD_ACTIONABILITY_ACTIVE                = "ACTIVE_TRADE_SETUP"
CARD_ACTIONABILITY_NAVIGATION_ONLY       = "NAVIGATION_ONLY"
CARD_ACTIONABILITY_HISTORICAL_REFERENCE  = "HISTORICAL_REFERENCE"
CARD_ACTIONABILITY_NEEDS_RECOMPUTE       = "NEEDS_RECOMPUTE"
CARD_ACTIONABILITY_INVALIDATED           = "INVALIDATED"
CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE   = "CONTEXT_UNAVAILABLE"
```

`action_label` (e.g. `TAKE_PROFIT_NEAR`, `REBUY_ZONE_NEAR`, `WAIT`,
`WAIT_FOR_NEW_MAP`, `REVIEW_CONTEXT`) is always non-empty and is mapped to
review-language display text (see `docs/ops/manual_short_trader_profit_plan_v1.md`
§ "Action label display mapping"). It is display-only: it is never an order
instruction and never bypasses `decision_gate`/`execution_planner`/`executor`.

## Actionable PPP / ranking semantics

`_actionable_ppp(card)` returns the signed percent distance from
`current_price` to the highest active target, or `None`. It is only numeric
when `_actionable_ppp_eligible(card)` is `True`, which requires (Issue #457
hardening):

- current price fresh (not `STALE_CURRENT_PRICE`/`MISSING_CURRENT_PRICE`);
- `actionability_state == CARD_ACTIONABILITY_ACTIVE`;
- canonical native map truth available (`_canonical_native_map_truth_available`);
- an available map cycle id, no unverified rollover requiring map-switch review;
- lifecycle authority present and not blocking (`_map_lifecycle_blocks_action`
  fails closed on `DATA_UNAVAILABLE`/`NONE`/`NULL`/empty lifecycle, never
  passes by omission);
- an available highest active target.

`selected_map_tier` (legacy retired bridge metadata, Issue #550/#496) carries
**no authority** and must never gate Actionable PPP — see golden scenarios 9/10
below.

Sort/ranking (`data-sort-ppp`, `_workflow_sort_bucket`,
`sort_cards_two_timeline`) reads **Actionable PPP only**. Planning PPP never
influences ranking, including a hybrid or high-value Planning PPP with no
Actionable PPP (see `docs/architecture/profit_plan_planning_ppp_provenance_v1.md`).

## Waiting/timing semantics

When a card is `CARD_ACTIONABILITY_ACTIVE` but Actionable PPP is unavailable,
`_format_actionable_ppp()` always renders `"— · " + _entry_wait_label(card)"`,
never a bare `"—"`. `_entry_wait_label()` returns one of:

- `"Review map"` — an unverified rollover requires map-switch review;
- `"Entry above current — wait for reclaim"` — the reload/entry ladder is
  priced above current price;
- `"WAIT FOR ENTRY"` — otherwise.

This is the canonical timing-reason contract: an active setup with no numeric
Actionable PPP must always carry one of the three reasons above, never an
unexplained blank.

## Lifecycle/freshness semantics

Per-target lifecycle (`TargetLevelStatus.lifecycle_state`) is one of
`UPCOMING`, `NEAR`, `REACHED`, `PASSED`, `COMPLETED`, and is monotonic: it
never regresses from `REACHED`/`PASSED`/`COMPLETED` back to `NEAR`/`UPCOMING`
on a price pullback. When every mapped sell target is historically passed,
`scenario_type=MAP_COMPLETED`, `action_label=WAIT_FOR_NEW_MAP`,
`all_sell_targets_completed=True`, and `active_target` is cleared — see golden
scenario 8.

Price freshness (`CardEvidence.price_freshness_state`,
`current_price_status`) fails closed: `STALE_CURRENT_PRICE` and
`MISSING_CURRENT_PRICE` force `actionability_state=CONTEXT_UNAVAILABLE`,
`action_label=REVIEW_CONTEXT`, and hide percentage-distance/action-style
output. See golden scenarios 5/6.

## Unavailable/stale fail-closed semantics

Fail-closed is the default posture everywhere in this contract:

- unresolved/absent lifecycle authority blocks Actionable PPP, it does not
  pass by omission;
- a mixed-source (native + canonical-4h) Planning PPP composition renders
  **unavailable with a precise reason**, never a fabricated blended number;
- missing zone context, missing price, or missing native SHORT context all
  produce an explicit machine-readable reason code plus a human-readable
  entry in `card.reasons` — never a silent empty card.

## HTML/JSON consistency contract

The HTML card renderer (`render_plan_card`/`render_full_html`) and the JSON
snapshot (`build_json_snapshot`) are both views over the same
`ProfitPlanCard`/`CardEvidence` model. They must agree on:

| Field | JSON | HTML |
|---|---|---|
| Actionable PPP | `symbols[i].actionable_ppp_pct`, `.actionable_ppp_available` | `data-actionable-ppp`, `data-sort-ppp` |
| Planning PPP + provenance | `symbols[i].planning_ppp_pct`, `.planning_provenance` | `data-planning-ppp`, `data-planning-reference-source`, `data-planning-entry-source`, `data-planning-target-source`, `data-planning-hybrid-reference-only` |
| Action/wait state | `symbols[i].action_label`, `.actionability_state` | `data-filter-action`, `data-filter-action-label` — both derived from the single canonical `_effective_workflow_action()` |
| Freshness/unavailable state | `symbols[i].current_price_status`, `.evidence.price_freshness_state` | `data-price-freshness-state` |
| Lifecycle/map state | `symbols[i].evidence.lifecycle_state`, `.evidence.selected_map_tier`, `.evidence.native_map_status` | `data-map-lifecycle-state`, `data-selected-map-tier`, `data-native-map-status` |
| Re-entry/target levels | `symbols[i].reload_reentry_zone_display`, `.target_exit_zone_display` (no discrete HTML attribute carries this list; proven by exact display-string presence in the rendered fib-section text) | rendered ladder/fib-section price text |
| No-action reason | `symbols[i].reasons` | `<ul class='reasons'>` list items |

`tests/test_manual_trader_dashboard_v1_golden.py::test_html_json_agreement_core_fields`
proves this parity across all ten frozen golden scenarios.

## Stable JSON/read-model contract (minimal frozen field set)

This freeze does not introduce a parallel model. The fields below are the
existing canonical `ProfitPlanCard` / `build_json_snapshot()` fields the
dashboard renderer consumes, named explicitly so a future change to any of
them is a contract change, not an incidental refactor:

```text
symbol, market                              symbol/asset identity
fib_trading_horizon                         currently "SHORT"
actionability_state                         presentation/actionability state
action_label                                action label
reasons                                     up to 3 plain-language reasons (action/no-action reason)
scenario_type, setup_state, event_state     setup/event classification
planning_ppp_pct, planning_ppp_unavailable_reason, planning_provenance
                                             planning PPP + provenance
actionable_ppp_pct, actionable_ppp_available
                                             Actionable PPP (ranking input)
current_price, current_price_display, current_price_status, current_price_age_min
                                             current price/status
evidence.native_map_status, evidence.map_cycle_id, evidence.selected_map_tier,
evidence.lifecycle_state, evidence.rollover_state
                                             map availability/lifecycle
buy_zone, reload_reentry_zone, target_exit_zone, active_target,
target_level_statuses, invalidation_level   Fib level / re-entry / target semantics
evidence.price_freshness_state, evidence.price_ts_utc
                                             evidence freshness
short_context_input_status, short_context_coverage_status,
short_context_display_state                 missing/unavailable reason/provenance
*_display fields (current_price_display, target_exit_zone_display, ...)
                                             rendered/display companion fields
is_relevant, relevance_reasons, ladder_states
                                             operator-attention surfacing
render_id, writer_instance_id               per-render/per-run identity (not content)
```

## Explicit non-authority

Manual Trader Dashboard V1 has **no authority** over, and must never gain
authority over, any of the following without a separate, explicitly reviewed
contract change:

```text
account allocation
decision_gate permission
execution planning
executor / order handling
broker / order submission
```

It is read-only reporting. It never calls a broker, never writes to the
database, never creates `decision_gate` permission or `execution_planner`
intent, and never enables `executor`.

## Relationship to Issue #557 (automatic wallet-triggered loop)

Issue #557's automatic wallet-triggered loop is a separate, account-aware,
execution-adjacent lane. It may read the same upstream canonical sources
(native SHORT context, market prices) that this dashboard reads, but:

- it must not change the semantics frozen in this document as a side effect
  of its own implementation;
- it must not repurpose `ProfitPlanCard`/`build_json_snapshot()` fields for a
  different (automatic-execution) meaning;
- any field this contract also depends on that #557 needs to change must go
  through an explicit version bump of this document first.

This dashboard remains the manual, read-only reference surface regardless of
whether #557 ships.

## Change / version policy after freeze

This is **Manual Trader Dashboard V1** (contract version `1.0`).

- Bug fixes and additive fields that preserve the semantics above do not
  require a version bump, but should update the relevant section of this
  document.
- A change to the meaning of an existing field, a change to fail-closed
  behavior, or a change to HTML/JSON parity requires bumping the contract
  version noted here and updating the golden fixtures in
  `tests/test_manual_trader_dashboard_v1_golden.py` deliberately (not merely
  making them pass again).
- Issue #557 and any future automatic-execution lane must treat this contract
  as a read boundary: consume it, do not silently redefine it.

## Accepted baseline

```text
manual_trader_dashboard_v1_baseline_parent_sha=5ae73df9b534f578acecccabf4c2b6e15caf63de
```

This is the exact `origin/main` SHA the freeze branch
(`freeze/558-manual-trader-dashboard-v1`) is rebased onto (superseding the
prior `7e760316...` baseline after the branch was rebased past the merge of
PR #710). If this PR is
merged via a merge commit, the resulting merge SHA on `origin/main` becomes
the canonical accepted Manual Trader Dashboard V1 baseline going forward; this
document intentionally does not self-reference that not-yet-created SHA to
avoid a self-referential baseline problem. Record the merge SHA in the PR
description and in a follow-up doc note if a future contract revision needs
to cite it.

## Golden regression fixtures

`tests/test_manual_trader_dashboard_v1_golden.py` freezes ten deterministic
scenarios exercising this contract:

1. valid immediate/actionable setup (numeric Actionable PPP, `ACTIVE`)
2. valid "wait for entry" reload setup with numeric Actionable PPP
   (`REENTRY_WAIT` / `REBUY_ZONE_NEAR`)
3. wait-for-reclaim equivalent (entry above current price, no Actionable PPP,
   deterministic `"Entry above current — wait for reclaim"` reason)
4. invalidated setup (`CARD_ACTIONABILITY_INVALIDATED`)
5. stale evidence (`STALE_CURRENT_PRICE`)
6. unavailable evidence (missing current price / zone context)
7. active map with complete Fibonacci levels
8. completed/passed levels — `MAP_COMPLETED` reference state
9. FET-like contradiction case from Issue #550 (retired `selected_map_tier`
   metadata must not block Actionable PPP)
10. TAO-like contradiction case from Issue #550 (same contradiction shape,
    proven per-symbol)

Each scenario is checked for: determinism (two independent builds produce
identical HTML/JSON modulo per-render UUIDs), the advice-presence invariant
(Section D below), and HTML/JSON field agreement (Section E below).

### Advice-presence invariant

`test_advice_presence_invariant_no_silent_empty_advice` proves that when all
canonical required evidence is present/valid, operator advice
(`action_label` plus at least one reason, or an explicit PPP-unavailable
reason) never silently disappears. A context-unavailable card must carry a
non-empty `reasons` tuple; an active card with no numeric Actionable PPP must
carry a deterministic, non-blank formatted reason
(`_format_actionable_ppp(card) != "—"`).

### HTML/JSON agreement evidence

`test_html_json_agreement_core_fields` (parametrized over all ten scenarios)
proves Actionable PPP, action/wait state, freshness/unavailable state,
lifecycle/map state, re-entry/target levels, and no-action reasons all agree
between the JSON read-model and the rendered HTML.

## Safety markers

```text
manual_dashboard_only=1
account_allocation_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_writes=0
order_submission=0
live_orders=0
production_live_activation=0
```
