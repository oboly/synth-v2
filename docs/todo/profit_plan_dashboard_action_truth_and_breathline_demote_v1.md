# TODO — Profit Plan Dashboard Action Truth and Breathline Demotion V1

## Status

Active v2.22 dashboard correctness / actionability guardrail.

This bundle records the 2026-07-09 manual dashboard review of the Profit Plan / Short Swing cards for LDO and NEAR.

It is not a trading decision, signal, order instruction, or live-ladder enablement task.

## Purpose

Prevent the Profit Plan dashboard from presenting action states that are stronger than the available evidence supports.

The dashboard may remain useful as a diagnostic cockpit, but it must fail closed before it becomes an action cockpit.

## Observed dashboard problems

### LDO card

Observed state:

```text
Action: FIX LADDER
Native map: DATA_UNAVAILABLE
Delta: NO_PREVIOUS_SNAPSHOT
Wallet: placeholder
Position: placeholder
Orders: placeholder / old persisted timestamp
Breath Curve: AVAILABLE
```

Problem:

```text
FIX LADDER is too strong when native-map truth, account/order freshness, and per-level lifecycle truth are unavailable or stale.
```

Required behavior:

```text
Action: REVIEW_CONTEXT
Primary reason: NATIVE_MAP_DATA_UNAVAILABLE and/or STALE_ACCOUNT_DATA and/or LEVEL_STATUS_UNAVAILABLE
Fix ladder: disabled
```

### NEAR card

Observed state:

```text
Action: Map expired
Setup: MAP_COMPLETED
Actionability: NEEDS_RECOMPUTE
Event: MAP EXPIRED
Order ladder: not required
Native map: DATA_UNAVAILABLE
Tier: CURRENT_ACTIVE_MAP
Wallet/Position/Orders/Context: placeholder
Breath Curve: AVAILABLE
```

What is correct:

```text
MAP_EXPIRED / NEEDS_RECOMPUTE is the right high-level action direction.
No Fix Ladder action is shown.
```

What still needs cleanup:

```text
Native map DATA_UNAVAILABLE must not be compressed together with CURRENT_ACTIVE_MAP in a way that implies current active map certainty.
Placeholder account/order panels must drive account-context unavailable or stale state.
Breathline/Breath Curve must not visually imply active action authority.
```

## Hard architecture boundary

```text
selection_engine = unchanged, market-only
reporting = display and fail-closed action-state rendering only
account freshness = Lane A persisted snapshot contract
native current map/level truth = Lane B / Lane B0 read model
Breathline = research context only until separately validated and promoted
```

Forbidden in this bundle:

```text
no live trading
no broker writes
no order submission
no decision_gate changes
no execution_planner changes
no executor changes
no direct broker/private calls from reporting
no automatic ladder repair
no research-to-action shortcut
```

## P0 — Fail-closed action gating

Status: open.

Profit Plan action labels must be derived from a strict precedence chain.

Required rules:

```text
if account_order_snapshot_status != FRESH:
    action = REVIEW_CONTEXT
    reason includes STALE_ACCOUNT_DATA or ACCOUNT_ORDER_DATA_UNAVAILABLE
    fix_ladder_enabled = false

if wallet_or_position_snapshot_status != FRESH:
    action = REVIEW_CONTEXT
    reason includes STALE_ACCOUNT_DATA or ACCOUNT_DATA_UNAVAILABLE
    fix_ladder_enabled = false

if native_map_status != AVAILABLE:
    action = REVIEW_CONTEXT
    reason includes NATIVE_MAP_DATA_UNAVAILABLE
    fix_ladder_enabled = false

if current_per_level_status_model_missing:
    action = REVIEW_CONTEXT
    reason includes LEVEL_STATUS_UNAVAILABLE
    fix_ladder_enabled = false

if map_lifecycle_state in MAP_COMPLETED / MAP_EXPIRED / MAP_INVALIDATED:
    action = MAP_EXPIRED or NEEDS_RECOMPUTE or ROTATE_MAP as appropriate
    fix_ladder_enabled = false
```

`FIX_LADDER` may appear only when all of these are true:

```text
price snapshot is fresh
wallet/balance snapshot is fresh
position snapshot is fresh
open-order snapshot is fresh
native scope-status projection is available and current
current map id and map_cycle_id exist
current per-level status is available
at least one canonical active level is genuinely MISSING or a current order is genuinely STALE
```

No placeholder account panel may coexist with an enabled or recommended ladder repair action.

Acceptance criteria:

```text
LDO-like case renders REVIEW_CONTEXT, not FIX_LADDER.
NEAR MAP_EXPIRED case stays NEEDS_RECOMPUTE / map expired, not FIX_LADDER.
Any placeholder wallet/position/order panel suppresses account-specific action claims.
```

## P0 — Breathline / Breath Curve demotion

Status: open.

The current UI shows Breath Curve as `AVAILABLE`, which gives it too much operational authority while the lane remains research-only / not reliable enough for action.

Required display state:

```text
label: Breathline context
state: RESEARCH_ONLY_DISABLED or CONTEXT_ONLY
visual: greyed out / muted
selection_weight: 0
action_weight: 0
decision_weight: 0
```

Rules:

```text
Breathline may remain visible for diagnostic/research context.
Breathline must not drive FIX_LADDER, BUY/SELL, MAP_EXPIRED, NEEDS_RECOMPUTE, PPP, sorting, or urgency.
`AVAILABLE` must not be used when the feature is disabled for action.
```

Suggested user-facing text:

```text
Breathline: research context only — disabled for actions
```

Acceptance criteria:

```text
Breathline/Breath Curve panel is visibly muted.
Action state does not change when Breathline fields are present or absent.
The card sidebar does not present Breathline as an active forecast or execution input.
```

## P1 — Freshness display cleanup

Status: open / depends on Lane A freshness contract.

Problem:

```text
Static HTML currently shows relative ages such as `0.3 min ago` / `0.4 min ago`.
This resembles the stale-display failure mode from the 2026-07-05 incident.
```

Required direction:

```text
show absolute observed timestamps per data class
show dashboard_generated_ts_utc / local rendered time separately
compute any relative age client-side from absolute timestamps
never bake an authoritative relative freshness string into static HTML
```

Minimum visible fields:

```text
market_price_observed_ts
wallet_observed_ts
position_observed_ts
open_orders_observed_ts
dashboard_generated_ts
freshness status per data class
```

Acceptance criteria:

```text
No server-baked `N min ago` is the only freshness evidence.
Static JSON exposes absolute timestamps and status values.
A stale page cannot visually look fresh after rendering stops.
```

## P1 — Evidence-card semantic normalization

Status: open.

Problem examples:

```text
Native map DATA_UNAVAILABLE + Tier CURRENT_ACTIVE_MAP appears in the same compressed evidence line.
This can be read as contradictory: unavailable but current/active.
```

Required direction:

Split evidence into separate authority rows:

```text
Projection status
Current map selection
Map lifecycle
Level status
Price snapshot
Account/order snapshot
Dashboard render
```

Example:

```text
Projection: FRESH / CURRENT_EVALUATION
Current map: DATA_UNAVAILABLE or MAP_EXPIRED or AVAILABLE
Level status: UNAVAILABLE / ACTIVE / HISTORICAL / COMPLETED
Account orders: FRESH / STALE / MISSING / UNAVAILABLE
Action gate: BLOCKED / REVIEW_CONTEXT / ACTIONABLE
```

Acceptance criteria:

```text
DATA_UNAVAILABLE is never visually paired with CURRENT_ACTIVE_MAP as if both are the same fact.
Reason codes are not truncated before the user can understand the blocking condition.
Each authority row has one owner and one status.
```

## P1 — Numeric formatting cleanup

Status: open.

Problem:

```text
PPP values are displayed with excessive decimal precision, e.g. 13.7868945064256409518429600%.
```

Required formatting:

```text
PPP/PPT/PPV: max 2 decimals in normal UI
raw precision: only in debug JSON or explicit inspect mode
prices: exchange/tick-aware formatting
percent deltas: max 2 decimals unless tiny values require precision
```

Acceptance criteria:

```text
PPP renders as 13.79% or 13.8%, not long raw Decimal output.
The sidebar and card use the same formatting rules.
```

## P2 — NEAR manual context note

Status: recorded as manual context only.

Manual 2026-07-09 chart read:

```text
NEAR is a recompute / wait-for-reclaim case, not a ladder-fix case.
Likely short-term range context: roughly 1.60–1.76 EUR until reclaim or breakdown.
Bullish only after reclaim above roughly 1.76–1.80 EUR.
Below roughly 1.60 EUR risks deeper test toward 1.50–1.52 EUR.
```

This note is not runtime logic, not a forecast source, not advice_engine output, and not an order instruction.

Rules:

```text
Do not encode this manual read into selection/advice/decision/execution.
Use it only as human review context for why MAP_EXPIRED / NEEDS_RECOMPUTE should not become FIX_LADDER.
```

## Dependencies

Lane A:

```text
P0-A host acceptance
linked-profile freshness truth pipeline
absolute timestamp/status contract for price/account/order/dashboard data
```

Lane B0:

```text
native current per-map-level lifecycle/status read model
```

Lane B:

```text
Profit Plan resolver migration to native_short_scope_status_v1
canonical map_cycle_id consumption
deterministic ladder-row identities
```

This bundle must not implement around those missing authorities in reporting.

## Suggested PR split

```text
1. fix: fail closed profit plan action labels on unavailable account/native data
2. ui: demote breathline to research-only context in profit plan
3. ui: normalize profit plan evidence-card authority rows
4. ui: clean profit plan numeric precision
5. ui: replace server-baked relative freshness labels with absolute timestamp/status display
```

## Definition of done

```text
LDO-like stale/unavailable cases no longer show FIX_LADDER.
NEAR-like map-expired cases remain NEEDS_RECOMPUTE / MAP_EXPIRED.
Breathline is visibly research-only and contributes zero action weight.
Evidence rows are separated by authority and cannot imply false freshness.
PPP and percent values are human-readable.
Static freshness display cannot repeat the 2026-07-05 stale-age failure mode.
No broker/private/execution path is touched.
```
