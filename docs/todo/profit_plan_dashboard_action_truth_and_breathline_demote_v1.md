# TODO — Profit Plan Dashboard Action Truth and Breathline Demotion V1

## Status

Active v2.22 dashboard correctness / actionability guardrail.

This bundle records the 2026-07-09 manual dashboard review of the Profit Plan / Short Swing cards for LDO and NEAR.

It is not a trading decision, signal, order instruction, or live-ladder enablement task.

## Implementation status (2026-07-10)

Branch `fix/profit-plan-actionable-ppp-map-rollover-review-v1` — reporting-only:

- DONE — PPP v2: split into Planning PPP (reference) and Actionable PPP
  (current price → highest active target, gated by current-cycle entry-activation
  evidence). `PPP high-low` sort and ranking use Actionable PPP only; cards with
  no Actionable PPP sort behind. Planning PPP may display but never promotes.
- DONE — HOT-like map-switch review gate: an indicated rollover (newer/replacement
  reason or `CASE_A_*` state) that is not verifiable from previous/current
  `map_cycle_id` + completion evidence, or with `native_map_status=DATA_UNAVAILABLE`,
  renders `MAP SWITCH REVIEW` / `Review map`, disables Fix ladder and suppresses
  Actionable PPP.
- DONE — Fail-closed FIX_LADDER: `FIX LADDER` only when native scope-status is
  available, account/order snapshot is `FRESH`, the map cycle is current/active,
  the rollover is verified/not-applicable, the map is not expired/completed/
  invalidated, the entry is loaded and activated, and a genuine level is missing or
  order stale. Otherwise `REVIEW CONTEXT` / `WAIT FOR ENTRY` / `MAP SWITCH REVIEW`.
  Since account/native truth is still placeholder in this runner, FIX_LADDER stays
  suppressed in production until Lane A/Lane B are wired in.
- DONE — Breathline demotion: rendered as muted `Breathline context`
  (`RESEARCH_ONLY_DISABLED`, weights 0). Proven to not affect action, PPP, sorting,
  urgency, setup state or ladder state.
- DEFERRED (separate PRs) — P1 freshness display (Lane A absolute-timestamp
  contract), P1 evidence-row authority normalization, P1 numeric precision, and the
  P2 future best-entry (>=4% upside) research lane. This PR depends on the Lane A
  absolute timestamp/status contract for real account/order freshness and on the
  Lane B native scope-status projection to ever enable FIX_LADDER.

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

### RED extension card

Observed state:

```text
Setup: EXTENSION_SETUP
Badge: EXTENSION RUNNER
Target zone: present
Invalidation: present
Re-entry zone: No levels loaded
PPP/PPT/PPV: empty
Action text still includes FIX LADDER
```

What is correct:

```text
Extension context appears to recompute target and invalidation without inventing entry levels.
No re-entry level is loaded, and PPP remains empty.
```

What needs cleanup:

```text
FIX LADDER is too strong when the user is looking for an entry and no re-entry levels are loaded.
A target without a sell order is not automatically a broken ladder.
```

Required behavior:

```text
Action: WAIT_FOR_ENTRY or REVIEW_ENTRY
Target: open / no sell order at target
Re-entry: unavailable
Fix ladder: disabled unless the user explicitly chooses target-order repair later
```

## Hard architecture boundary

```text
selection_engine = unchanged, market-only
reporting = display and fail-closed action-state rendering only
account freshness = Lane A persisted snapshot contract
native current map/level truth = Lane B / Lane B0 read model
Breathline = research context only until separately validated and promoted
entry filter research = future measured candidate lane, not BUY_READY
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

if setup_type == EXTENSION_SETUP and re_entry_levels_missing:
    action = WAIT_FOR_ENTRY or REVIEW_ENTRY
    reason includes ENTRY_LEVELS_UNAVAILABLE
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
RED EXTENSION_SETUP with target/invalidation but no re-entry levels renders WAIT_FOR_ENTRY or REVIEW_ENTRY, not FIX_LADDER.
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

## P2 — Future entry candidate filter research note

Status: recorded as future research/design only.

User preference from 2026-07-10:

```text
Do not treat every possible setup as an entry.
Wait for entries with at least 4% upside to the nearest valid target.
Across dozens of coins, the system should be selective enough that something better should exist.
```

Important terminology:

```text
4% is a minimum upside-to-target gate, not a reward/risk ratio.
```

Future research concept:

```text
BEST_ENTRY_FILTER_V1
```

Candidate rule for research/backtest only:

```text
candidate_entry only if:
- nearest_valid_target_upside_pct >= 4.0
- entry is not already too close to target
- invalidation is clear
- price is not already extended without reclaim/pullback confirmation
- native map and per-level status are fresh/canonical
- account/order freshness is available only later in decision_gate context
```

Do not remove risk controls. Minimum 4% upside is necessary but not sufficient.
A candidate with 4% upside and excessive downside remains unattractive.

Architecture boundary:

```text
entry candidate research -> backtest -> replay-safe validation -> paper candidate -> decision_gate -> execution_planner -> trading agent/executor
```

Not:

```text
manual dashboard context -> BUY_READY
4% upside -> direct order
research filter -> execution
```

Suggested dashboard wording for RED-like cases:

```text
WAIT FOR ENTRY
Target open
No re-entry levels loaded
Current upside-to-target below entry threshold or entry unavailable
```

This note is not runtime logic, not a signal, not advice_engine output, and not an order instruction.

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

Future entry filter lane:

```text
BEST_ENTRY_FILTER_V1 research/backtest
minimum target-upside threshold >= 4.0%
no BUY_READY without validation and downstream account-aware gates
```

This bundle must not implement around those missing authorities in reporting.

## Suggested PR split

```text
1. fix: fail closed profit plan action labels on unavailable account/native data
2. ui: demote breathline to research-only context in profit plan
3. ui: normalize profit plan evidence-card authority rows
4. ui: clean profit plan numeric precision
5. ui: replace server-baked relative freshness labels with absolute timestamp/status display
6. research: design best entry filter validation with min target upside threshold
```

## Definition of done

```text
LDO-like stale/unavailable cases no longer show FIX_LADDER.
NEAR-like map-expired cases remain NEEDS_RECOMPUTE / MAP_EXPIRED.
RED-like extension cases with no re-entry levels show WAIT_FOR_ENTRY / REVIEW_ENTRY, not FIX_LADDER.
Breathline is visibly research-only and contributes zero action weight.
Evidence rows are separated by authority and cannot imply false freshness.
PPP and percent values are human-readable.
Static freshness display cannot repeat the 2026-07-05 stale-age failure mode.
Future entry filtering records minimum target upside >= 4.0% as research/backtest input, not BUY_READY.
No broker/private/execution path is touched.
```
