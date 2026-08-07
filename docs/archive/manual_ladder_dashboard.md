# TODO — Manual Ladder Dashboard

```text
Status: Archived historical record
Active ownership: none
Current work: see canonical documentation / GitHub Issues
Archived by: docs/TODO cleanup Batch 4B
```

Current owners for the substantive scope below:

- P0 dashboard implementation: `src/reporting/run_manual_ladder_static_dashboard_v1.py`, `docs/research/manual_ladder_dashboard_v1.md`
- Successor strategy/regime/zone dashboard: `docs/research/breath_fibo_strategy_static_dashboard_v1.md` (`src/reporting/run_breath_fibo_strategy_static_dashboard_v1.py`), built on `docs/research/canonical_fib_zone_map_v1.md`
- Active ladder lane: `docs/todo/profit_plan_live_ladder.md`
- Manual execution ladder request/planner/credential scope: GitHub Issues #202, #203, #206
- `docs/todo/README.md` already carried this file's disposition as "historical source / superseded" prior to this archive move.

The body below is preserved unmodified from the original TODO and reflects historical status language (e.g. "Active next dashboard lane") that is no longer current.

## Status

Active next dashboard lane for Synth v2.14.

This document is the canonical TODO for the new Breath-Fibo-Regime manual dashboard direction. The new chat bundle is the source of truth for this lane. Older `docs/todo/*` files may contain useful historical context, but many of them were written around the now-parked Paper Advice dashboard and should not drive this task.

## Core direction

```text
Breath/Fibo first
Regime as first Synth interpretation layer
Synth confirmation second
Manual ladder/action review third
Execution remains off
```

The old Entry/Paper Advice dashboard is parked as a debug/review tool. Do not cosmetically tune it into the new main trading dashboard.

## Primary dashboard reading order

```text
1. Breathline / A+ phase and prognosis
2. Fibo + external zone map
3. Regime as the first Synth interpretation layer
4. Price position inside the map
5. Synth confirmation sensors
6. Manual ladder / review state
7. Debug details
```

Interpretation:

```text
Breath + Fibo = where are we on the map?
Regime = what kind of playbook is valid here?
Synth sensors = is price confirming?
Manual ladder = what levels matter now?
```

## P0 — Breath-Fibo-Regime Manual Dashboard v1

Implementation target:

```text
src/reporting/run_manual_ladder_static_dashboard_v1.py
docs/research/manual_ladder_dashboard_v1.md
```

Smoke output:

```text
/tmp/manual_ladder_dashboard_v1.html
```

Later Odroid publish path:

```text
/var/www/html/synth/manual-ladders.html
```

## Required scope

```text
reporting/dashboard only
static HTML
market-only
account-agnostic
manual review only
```

## Hard boundaries

```text
No broker private calls
No broker writes
No order submission
No decision_gate changes
No execution_planner changes
No executor changes
No live trading
No selection_engine behavior changes
No setup_filter behavior changes
No old advice/entry policy labels as primary state
No BUY/SELL command language
```

All ladder output is suggested/manual context only. The user places/cancels orders manually.

## Required display per symbol

Show:

```text
symbol
current price
price freshness
Breathline / A+ phase or prognosis if available
Fibo / external map source
regime state/context if available
current leg direction
invalidation level
distance to invalidation
support / reaction / rebuy zone
distance to support / reaction zone
T1 / first reaction target
T1 touched status
next target
runner target if available
sell ladder levels
rebuy ladder levels
distance to each ladder level
manual-only note
debug details collapsed/secondary
```

## Neutral dashboard state labels

Allowed headline/context labels:

```text
NEAR_T1
T1_TOUCHED
WAIT_RETEST
REBUY_ZONE_NEAR
INVALIDATION_NEAR
NO_MAP
FIB_MAP_UNKNOWN
MANUAL_ONLY
```

Avoid headline labels from the old dashboard:

```text
AVOID
BUY_READY
SETUP_FAIL
NO_EDGE_PERMISSION
POLICY_WATCH_ONLY
SELECTION_STATE_NOT_ELIGIBLE
```

Those may only appear in debug/details if the source data already contains them.

## Fibo and external zones

Fibo and external zones are priority map inputs for this dashboard.

External zones should be treated as high-value calculated map levels, not as direct trade commands.

Correct handling:

```text
external zones = high-value map input
external zones != direct order instruction
```

Useful map fields:

```text
source_name
source_date
zone_role
zone_low
zone_high
target_low
target_high
invalidation
precision/freshness
distance_to_zone
status: near / touched / held / lost
```

Required display principle:

```text
Do not hide next target after first target is touched.
Show first target touched, next target, and runner target separately if data exists.
```

## Regime layer

Regime belongs in dashboard v1 immediately because strategy interpretation is regime-dependent.

Regime is the first Synth interpretation layer after Breath/Fibo.

Example interpretation hints:

```text
BULL / ROTATION:
  continuation ladders and partial TP are useful

RANGE:
  reaction-zone / rebuy ladder is more important

DAMAGE / CRASH:
  no chasing, only deep support / reclaim review

SUPER_BULL / GOD-CANDLE risk:
  do not over-trim too early; runner target remains visible
```

Regime is context, not permission.

```text
regime context != order instruction
regime context != decision_gate permission
```

## Manual ladder examples

### ALGO-style row

Known manual plan:

```text
current around 0.113
sell ladder: 0.114 / 0.120
rebuy ladder: 0.106 / 0.101
```

Dashboard should show:

```text
ALGO / Manual Ladder
Current price: 0.113067

Sell ladder:
T1 0.114  distance about +0.8%
T2 0.120  distance about +6.1%

Rebuy ladder:
R1 0.106  distance about -6.2%
R2 0.101  distance about -10.7%

State:
Near T1
Partial TP context active
Wait for sell fill or retest
Manual only
```

### WLD-style row

Known map:

```text
price around 0.2568 initially
entry/reaction zone: 0.286849..0.299955
upside target: 0.355490
invalidation: 0.244420
```

After price reached around 0.300, the first reaction zone was touched. The old dashboard obscured the higher target.

Correct display:

```text
WLD / Breath-Fibo Reload
Current: about 0.300

First reaction zone:
0.286849..0.299955
Status: touched

Invalidation:
0.244420

Next target:
0.355490

State:
First target touched.
Do not chase.
Wait retest / hold above 0.286-0.300.
Runner target still visible.
Manual only.
```

## P0 implementation tasks

```text
1. Find existing fib/zone/map data sources.
2. Find available regime source/status fields.
3. Find current price source.
4. Build deterministic display model.
5. Render clean static HTML.
6. Include ALGO/WLD-style behavior if real data is incomplete.
7. Do not touch execution/decision/planner/executor.
```

## P1 — External zone ingestion/display as map source

After dashboard v1 exists, add or normalize external zones as dashboard map inputs.

Goal:

```text
external PRO/A+/Martee/RV zones -> structured map source -> dashboard display -> later validation
```

Not:

```text
external zones -> direct BUY_READY
external zones -> order creation
external zones -> decision_gate bypass
```

## P2 — Cleaner regime strategy interpretation labels

After dashboard v1 renders regime context, define clearer regime-to-playbook labels.

Possible examples:

```text
CONTINUATION_LADDER_CONTEXT
REACTION_RELOAD_CONTEXT
DEEP_RECLAIM_ONLY_CONTEXT
RUNNER_PROTECTION_CONTEXT
NO_CHASE_CONTEXT
```

These remain dashboard interpretation labels only.

## Parked

Do not prioritize unless explicitly reopening the old dashboard or research lane:

```text
old Paper Advice dashboard tuning
old UI cockpit usability TODO stack
Market Breath calibration
Breath Curve runtime promotion
paper candidate adapter
execution ladder automation
```

## Future only

```text
paper_candidate_contract -> decision_gate adapter
execution_planner ladder integration
executor/order path
```

These require separate validation, architecture review, and explicit permission.

## Codex implementation prompt

```text
Repo: ~/projects/synth-v2

Task:
Create Manual Ladder Dashboard v1, but structure it as the first Breath-Fibo-Regime dashboard.

Current source of truth:
The new chat bundle is valid. Older docs/todo files mostly belong to the parked Paper Advice dashboard and should not drive this task.

Goal:
Build a static, reporting-only dashboard where the reading order is:

1. Breathline / A+ phase and prognosis
2. Fibo + external zone map
3. Regime as the first Synth interpretation layer
4. Price position inside the map
5. Synth confirmation sensors
6. Manual ladder / review state
7. Debug details

Important:
Regime is not a later research-only dashboard. It belongs in this dashboard immediately because strategy interpretation depends on regime.

Fibo and external zones are priority inputs. External zones should be treated as high-value calculated map levels, not as direct order instructions.

Rules:
- Reporting/dashboard only
- Market-only
- Account-agnostic
- No broker private calls
- No broker writes
- No order submission
- No decision_gate changes
- No execution_planner changes
- No executor changes
- No selection_engine behavior changes
- No setup_filter behavior changes
- Do not tune the old Paper Advice dashboard
- Do not make old advice/policy labels primary state
- No BUY/SELL command language
- Manual-only review levels

Implement:
- src/reporting/run_manual_ladder_static_dashboard_v1.py
- docs/research/manual_ladder_dashboard_v1.md

Output:
- /tmp/manual_ladder_dashboard_v1.html

Dashboard row/card should show:
- symbol
- current price
- price freshness
- Breathline/A+ phase/prognosis if available
- Fibo/external map source
- regime state/context if available
- current leg direction
- invalidation
- distance to invalidation
- support/reaction/rebuy zone
- distance to support/reaction zone
- T1 / first reaction target
- T1 touched status
- next target
- runner target if available
- sell ladder levels
- rebuy ladder levels
- distance to each ladder level
- manual-only note
- debug details collapsed/secondary

Hard display rule:
Do not hide next target after first target is touched.
Show first target touched, next target, and runner target separately if available.

Acceptance:
- ALGO-style ladder can show sell levels 0.114 / 0.120 and rebuy levels 0.106 / 0.101 if available or equivalent derived map levels.
- WLD-style row shows first reaction zone touched but preserves next target 0.355490 if available.
- Regime is visible as a first Synth interpretation layer.
- No order/execution/decision/planner/executor files changed.
- py_compile passes.
- Smoke render works.
- Safety markers printed:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  executor=none
  account_awareness=0

Checks:
python -m py_compile src/reporting/run_manual_ladder_static_dashboard_v1.py
python -m src.reporting.run_manual_ladder_static_dashboard_v1 --venue bitvavo --quote EUR --interval 4h --limit 80 --output-html /tmp/manual_ladder_dashboard_v1.html --output summary
git diff --check
git status -sb
git diff --stat
```
