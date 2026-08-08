# Synth v2 — Coin Analysis / Golden Cases Bundle v1

> **Migration pointer — PARTIAL migration only.** This file is **not**
> wholly owned by an Issue.
>
> - GitHub Issue
>   [#242 — Implement market-state classes and golden regression fixtures](https://github.com/oboly/synth-v2/issues/242)
>   owns **only** priority items 1-5 from the "Priority order" section below:
>   `MarketNavigationState` always emitted, `BreathlineState`,
>   `ImpulseHealthState`, `TimingState`, and the golden regression fixtures
>   for the seven named cases (SXT, CRV, HOT, ONDO, VET, NEAR, CC). Current
>   execution status, priority, blockers, acceptance criteria, next action,
>   and closure **for that priority-1-5 scope only** belong to Issue #242.
> - The completed SXT emergency-rebuild / FibNavigationMap work ("Current
>   status → Already implemented/live", §1 SXT) is already-shipped historical
>   scope and is not migrated by #242; it is retained here as regression
>   reference only.
> - Priority items 7-8 (ladder preview dry-run, manual ladder submit safety)
>   are not distinct scope: they describe the same canonical manual-execution
>   ladder capability already tracked by #203 (execution_planner ladder
>   construction/leg validation — covers "preview dry-run") and #202/#206
>   (request idempotency, audit, and credential/executor boundary — covers
>   "manual submit safety"). This file must not spawn a second ladder
>   submission pipeline; items 7-8 are superseded by, and fold into, the
>   canonical #202/#203/#206 lane.
> - This file must not become a parallel status board for the migrated
>   scope: do not update status, priority, blockers, or next action for
>   priority items 1-5 here — that lives in Issue #242 only. The historical
>   SXT record may still be edited as design/historical content, but not
>   represented as having Issue-backed execution status.
> - See `docs/development/github_issues_workflow.md`,
>   `docs/todo/MIGRATION_FREEZE.md`, and
>   `docs/development/github_issues_batch_2c_migration_v1.md`.
>
> ## GitHub Issue migration
>
> Status: migrated
>
> Operational status/priority is owned by GitHub Issues.
>
> Section ownership:
> - Priority items 1-5 (state classes, golden regression fixtures) -> Issue #242
> - Priority item 7 (manual ladder preview dry-run) -> Issue #203 (execution_planner ladder construction/leg validation is the same canonical preview capability)
> - Priority item 8 (manual submit with broker_writes/idempotency/audit) -> Issue #202 (request idempotency/audit) and Issue #206 (credential/executor boundary)
> - §1 SXT record -> no Issue required; already-shipped historical/regression reference
>
> Unmigrated executable scope:
> - none

## Purpose

Real observed coin cases to use as regression tests, backtest scenarios, and design references.

Not trading recommendations.

Targets:
- MarketNavigationState
- FibNavigationMap
- BreathlineState
- ImpulseHealthState
- TimingState
- ladder planning
- manual ladder preview
- UI card clarity

## Current status

Already implemented/live:
- SXT emergency/candle-driven FibNavigationMap rebuild
- NAVIGATION_ONLY display mode
- fib_nav_context in live Profit Plan JSON

Still TODO:
- MarketNavigationState always emitted
- BreathlineState
- ImpulseHealthState
- TimingState
- regression fixture set
- backtest matrix
- ladder preview dry-run
- manual ladder submit safety

---

## 1. SXT — Emergency Fib Rebuild / Spike Pullback

Observed issue:
- no native SHORT fib context
- legacy context reference only
- all mapped sell targets historically passed
- no upcoming levels
- LADDER NOT REQUIRED
- MANUAL REVIEW

Problem:
Old/legacy targets were exhausted, but Synth did not rebuild a fresh map from candles.

Observed structure:
- low approx `0.006571`
- high approx `0.010127`
- current approx `0.009588`

Expected retracement supports:
- `0.009288`
- `0.008768`
- `0.008349`
- `0.007930`
- `0.007332`
- `0.006571`

Expected extension targets:
- `0.011094`
- `0.011599`
- `0.012325`
- `0.013683`
- `0.014650`
- `0.015155`
- `0.015881`
- `0.017239`
- `0.021635`

Expected:
- FibNavigationMap.state = EMERGENCY_REBUILT or FALLBACK
- old_map_state = EXHAUSTED if legacy map exists
- no collapse to "No upcoming levels"

Status:
- implemented in PR #1 / main `d7c57af`
- keep as regression fixture

Second SXT behavior:
- spike retraced after pump
- position approx `18,447 SXT`
- current around `0.0079`
- estimated average entry around `0.00859`

Expected classifications:
- BreathlineState = TESTING_BREATHLINE or RECLAIMING_BREATHLINE
- ImpulseHealthState = SECOND_BUMP_POSSIBLE or COOLING_PULLBACK
- TimingState = WAIT_FOR_RECLAIM or PULLBACK_ENTRY_ZONE
- if vertical extension: NO_CHASE_EXTENDED

Important levels:
- `0.00785` breathline / 61.8-ish decision zone
- `0.00823` reclaim
- `0.00859–0.00861` break-even rescue zone
- `0.00905–0.00915` relief trim
- `0.00980–0.00990` spike high retest
- `0.00730` weaker support
- `0.00660` hard risk / day low

Golden tests:
- SXT_EMERGENCY_FIB_REBUILD
- SXT_SPIKE_PULLBACK_SECOND_BUMP
- SXT_NO_CHASE_EXTENDED
- SXT_RESCUE_LADDER_PREVIEW

---

## 2. CRV — Breakout High / Partial Trim + Runner

Observed:
- CRV reached resistance around `0.2233`
- user sold near high, then price continued

Visible structure:
- low approx `0.18091`
- high approx `0.22331`
- current near `0.22262`, later `0.2233+`

Pullback supports:
- 23.6% `0.21330`
- 38.2% `0.20711`
- 50.0% `0.20211`
- 61.8% `0.19711`
- 78.6% `0.18998`

Extension targets:
- 1.272 `0.23484`
- 1.414 `0.24086`
- 1.618 `0.24951`
- 2.000 `0.26571`
- 2.618 `0.29191`

Expected:
- resistance hit creates partial trim + runner plan
- full exit only on rejection/invalidation
- breakout above high activates extensions

Golden tests:
- CRV_BREAKOUT_RUNNER
- CRV_PARTIAL_TRIM_NOT_FULL_EXIT
- CRV_RETEST_ZONE_AFTER_BREAKOUT

---

## 3. HOT — Spike Asset / Blow-Off / Low Follow-Through

Observed:
- large spike/bult
- often sideways/bleeding afterward
- low follow-through unless volume/catalyst returns

Expected:
- ImpulseHealthState = BLOW_OFF_SPIKE or DISTRIBUTION_RISK
- BreathlineState = SPIKE_COOLING if below falling breathline
- TimingState = NO_CHASE_EXTENDED or FAILED_RECLAIM
- no blind DCA after spike unless deep support/reclaim setup exists

Golden tests:
- HOT_BLOW_OFF_SPIKE
- HOT_FAILED_RECLAIM
- HOT_SPIKE_COOLING

---

## 4. ONDO — Rebuy Zone Already Hit But Not Detected

Observed:
- 5m chart showed rebuy zone touched and price bounced
- Profit Plan still said rebuy zone not reached

Problem:
- zone hit detection likely checked current/close instead of candle high/low range

Expected:
- use candle high/low range
- if candle low touches rebuy zone:
  - zone_hit = true
  - record hit timestamp
  - record lowest touch
  - update TimingState to RECLAIM_PENDING or RECLAIM_CONFIRMED

Golden tests:
- ONDO_REBUY_ALREADY_HIT
- ONDO_WICK_TOUCH_DETECTED
- ONDO_ZONE_HIT_THEN_RECLAIM_CHECK

---

## 5. VET — Rebuy Too Shallow / Missing Intermediate Target

Observed:
- rebuy zone looked too shallow
- expected deeper around `0.00413–0.00416`
- possible missing intermediate target around `0.00434`

Expected:
- pullback ladder includes shallow, normal, deep zones
- avoid clustering buys too close to current
- include intermediate sell target when local structure supports it

Golden tests:
- VET_DEEP_REBUY_AND_INTERMEDIATE_TARGET
- VET_REBUY_ZONE_DEPTH_CLASSIFICATION
- VET_INTERMEDIATE_RESISTANCE_TARGET

---

## 6. NEAR — Stale Map / Refresh Timing

Observed:
- unclear when NEAR receives a new map

Expected card fields:
- map_state
- generated_at
- source
- freshness
- refresh_reason
- next_refresh_trigger if possible

Refresh triggers:
- stale candles
- stale map age
- all targets passed
- price outside map coverage
- new high/low with volume
- price below invalidation
- impulse move > ATR multiple

Golden tests:
- NEAR_STALE_MAP_REFRESH
- NEAR_PRICE_OUTSIDE_COVERAGE_REFRESH
- NEAR_UI_SHOWS_MAP_FRESHNESS

---

## 7. CC — Bad Labels / Timing State Replacement

Bad labels:
- WAIT
- REENTRY_WAIT
- No recent dip detected
- watching for pullback
- Secondary: order too far or stale
- Missing sell at ...
- Ladder not required without useful explanation

Expected replacement:
- TimingState:
  - WAIT_FOR_PULLBACK
  - WAIT_FOR_RECLAIM
  - WAIT_FOR_BREAKOUT
  - PULLBACK_ENTRY_ZONE
  - RECLAIM_CONFIRMED
  - BREAKOUT_CONFIRMED
  - NO_CHASE_EXTENDED
  - TOO_LATE
  - FAILED_RECLAIM
  - LOW_CONFIDENCE
  - NO_DATA
  - STALE

Order/ladder state is separate:
- LADDER_PREVIEW_AVAILABLE
- LADDER_NOT_SAFE
- LADDER_BLOCKED_BY_DECISION_GATE
- LADDER_DISABLED_BROKER_WRITES
- LADDER_STALE_INTENT
- LADDER_SUBMITTED
- LADDER_PARTIAL_FAILURE

Golden tests:
- CC_TIMING_LABEL_REPLACEMENT
- CC_NO_RECENT_DIP_TO_WAIT_FOR_PULLBACK
- CC_ORDER_TOO_FAR_STRUCTURED_WARNING

---

## Cross-coin lessons

Always separate:
- map/navigation
- timing
- account permission
- execution intent
- broker execution
- UI display

Always emit market navigation, even when:
- manual review
- ladder not required
- broker writes disabled
- no open orders
- no native context
- legacy context only

Rules:
- do not chase vertical candles
- use partial trim + runner at resistance
- detect zone touches by candle range
- breathline is needed to judge if trend is alive
- spike profiles need special handling
- rescue ladders should be preview-only until decision_gate and user confirmation

## Desired UI card style

Compact top:
- Fib
- Breath
- Impulse
- Timing
- Mode

Expanded:
- supports
- targets
- breathline value/slope/distance
- impulse health/volume/pullback depth
- timing trigger/invalidation
- warnings

Avoid:
- WAIT
- REENTRY_WAIT
- No recent dip detected
- No upcoming levels when fallback exists
- Ladder not required without explanation

## Priority order

1. MarketNavigationState always emitted
2. FibNavigationMap emergency rebuild — implemented, keep as regression
3. BreathlineState
4. ImpulseHealthState
5. TimingState
6. golden regression/backtest fixtures
7. manual ladder preview dry-run
8. manual submit with broker_writes/idempotency/audit
9. UI refinement after backend contracts are stable

## Live Safety

Do not:
- deploy to Odroid
- restart services
- write to `/var/www/html`
- overwrite live dashboard
- enable broker writes
- submit orders

Use:
- feature branch
- local tests
- docs update
- preview page / feature flag
- dry-run first
