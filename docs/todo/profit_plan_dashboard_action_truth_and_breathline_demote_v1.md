# TODO — Profit Plan Dashboard Action Truth and Breathline Demotion V1

## Status

```text
done / parked
```

The v2.22 reporting/action-truth guardrail bundle is complete. It is no longer an active P0 lane.

## Sources

```text
src/reporting/manual_short_trader_profit_plan_v1.py
src/reporting/run_manual_short_trader_profit_plan_v1.py
tests/test_manual_short_trader_profit_plan_v1.py
tests/test_profit_plan_action_truth_v1.py
docs/ops/manual_short_trader_profit_plan_v1.md
```

## Completed implementation

### Actionable PPP and map rollover truth

Completed by PR #78 and follow-up PR #82:

- Planning PPP and Actionable PPP are distinct;
- ranking/sorting uses Actionable PPP only;
- current-cycle activation evidence is required;
- entry above current remains non-actionable;
- unverified map rollover renders `MAP SWITCH REVIEW`;
- expired/completed/invalidated maps cannot produce `FIX_LADDER`;
- target-without-entry extension cases render `WAIT_FOR_ENTRY`/review, not ladder repair.

### Fail-closed action authority

Completed by PR #75, PR #78, and PR #82:

`FIX_LADDER` is suppressed unless required map, level, price, wallet, position, and order authority is current and canonical.

Expected cases are closed:

```text
LDO-like unavailable context -> REVIEW_CONTEXT
NEAR-like terminal map       -> MAP_EXPIRED / NEEDS_RECOMPUTE
RED-like target/no entry      -> WAIT_FOR_ENTRY / REVIEW_ENTRY
```

No placeholder account panel may coexist with an enabled repair action.

### Breathline demotion

Completed by PR #78:

```text
label: Breathline context
state: RESEARCH_ONLY_DISABLED
selection_weight: 0
action_weight: 0
decision_weight: 0
```

Breathline may remain visible for research context but cannot change action, PPP, sorting, urgency, setup, ladder state, or execution permission.

### Evidence authority normalization

Completed by PR #84 and escaping follow-up PR #85:

- normalized independent evidence rows own projection, current map, lifecycle, level, price, wallet, position, open orders, render, and action-gate status;
- HTML/sidebar/JSON consume the same normalized model;
- unavailable projection truth cannot masquerade as confirmed current-map selection;
- reason codes remain inspectable and safely escaped.

### Numeric formatting

Completed by PR #86:

- percent and price display is deterministic and human-readable;
- raw precision remains available in structured fields;
- card, sidebar, selector, zones, and JSON display companions use canonical formatting;
- calculation and action semantics remain unchanged.

## Remaining work ownership

No active implementation remains in this file.

The following former follow-ups are owned elsewhere and must not be duplicated here:

- absolute timestamp and stale-static-page protection:
  `docs/todo/short_swing_linked_profile_freshness_and_disk_reliability_v1.md`
- canonical native scope/map-level consumption and actionable row identity:
  `docs/todo/profit_plan_live_ladder.md`
- IOST target lifecycle/history truth:
  `docs/todo/profit_plan_target_lifecycle_history_truth_v1.md`
- minimum 4% target-room and RSI/MFI entry research:
  `docs/todo/market_intelligence/momentum_flow_scanner_research_v1.md`
- non-blocking evidence-container severity and visual polish:
  `docs/todo/ui_webview.md`

## Standing boundary

```text
reporting = display and fail-closed action-state rendering only
selection_engine = unchanged and market-only
decision_gate = account-aware permission owner
execution_planner = execution-intent owner
executor = order-handling owner
Breathline = research context only
```

Forbidden:

- direct broker/private calls from reporting;
- broker writes or order submission;
- reporting-side permission, sizing, or execution intent;
- research-to-action shortcuts;
- reintroducing independent renderer-specific evidence truth.

## Reopen criteria

Reopen only for a concrete regression in Actionable PPP, action precedence, map-switch proof, Breathline zero authority, evidence-row consistency, escaping, or canonical numeric display.
