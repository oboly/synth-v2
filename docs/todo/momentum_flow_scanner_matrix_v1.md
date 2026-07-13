# TODO — Momentum Flow Scanner Matrix V1

## Status

```text
open P3 research / read-only scanner
non-blocking for Synth v2.23 P1 lanes
```

## Purpose

Build a compact multi-asset, multi-timeframe research scanner that finds candidates worthy of human review without promoting them to trading decisions.

Question owned by this lane:

```text
Which markets have enough target room, acceptable risk context, and supportive reset/momentum/flow evidence to justify research review?
```

Question not owned by this lane:

```text
What should the bot buy or execute now?
```

## Sources

- Existing `feat_candle` RSI, volume-ratio, dollar-volume, OBV, and slope features.
- Native map/target/invalidation context.
- Market price snapshots.
- FFG-style overview as external presentation inspiration only.
- `docs/research/market_rotation_pressure_v1.md` for Synth-native inferred rotation-pressure research.
- Profit Plan Actionable PPP as the current user-facing remaining-target-potential concept.

External labels or curated lists are inputs to research provenance, not execution authority.

## Research contract

Working output:

```text
momentum_flow_scanner_snapshot_v1
```

Candidate fields:

```text
symbol / market / venue
observed timestamps and freshness
price
RSI: 1d / 4h / 1h / 15m
MFI: 1d / 4h / 1h / 15m
volume_ratio_20
dollar_volume_ratio_20
native map status
nearest valid target upside %
actionable_ppp
invalidation downside %
rotation pressure / flow state
trend state
reset / reclaim state
liquidity quality
risk / overextension penalty
opportunity score
entry/reset research state
scanner bucket
reason codes
```

No server-baked relative age may be the sole freshness evidence.

## Minimum target-room gate

User-selected research threshold:

```text
nearest_valid_target_upside_pct >= 4.0
```

This is a minimum upside-to-target gate, not reward/risk.
Risk and invalidation remain separate and can reject a candidate that passes 4% target room.

## Allowed research states

```text
NO_EDGE
WATCH
RESET_READY
ENTRY_CANDIDATE_RESEARCH
OVERHEATED
ACCUMULATION_FLOW
DISTRIBUTION_RISK
DATA_UNAVAILABLE
```

Forbidden states:

```text
BUY_READY
AUTO_BUY
EXECUTE
FIX_LADDER
```

## P3-A — Deterministic MFI feature

Add `mfi_14` only as a market-data feature when this lane is selected for implementation.

Owner split:

```text
feature ETL        = deterministic candle calculation
feat_candle        = persisted feature value
scanner/read-model = read-only aggregation and presentation
```

Minimum tests:

- deterministic fixed fixture;
- zero-volume/flat-window handling;
- warmup nulls;
- bounded 0..100 values when calculable;
- no regression to existing RSI/ATR/volume features.

## P3-B — Read-only scanner builder

Build rows from canonical feature, price, and native-map sources.
Fail closed to `DATA_UNAVAILABLE` or `NO_EDGE` for stale/missing inputs.
Do not reconstruct candle features in reporting when a canonical feature source exists.

## P3-C — Replay/backtest validation

Before any promotion toward `selection_engine`, measure:

- bucket counts;
- forward returns;
- MFE/MAE;
- target-before-invalidation rate;
- time to target;
- false-positive rate;
- symbol/timeframe breakdown;
- random/control comparison;
- incremental value of MFI beyond RSI + volume features + map context;
- effect of the 4% target-room gate.

Any later feature promotion requires a separate explicit proposal and must remain market-only.

## P3-D — Read-only dashboard

Only after the read model and validation exist, add a compact matrix with filters/sorts for bucket, target room, reset readiness, flow, map freshness, and data availability.

## P3-E — Profit Plan Opportunity Rank

Status: accepted product/research direction; implementation and weighting require replay validation.

### Goal

Keep `Actionable PPP` as the primary user scan value while adding one secondary market-only quality measure that answers:

```text
The target room exists, but is this market also receiving participation,
trending constructively, and offering a reasonable entry timing?
```

Use the user-facing name:

```text
Opportunity Rank
```

Do not call this `Profit Advice`.
`Advice` implies account suitability, permission, sizing, or execution authority that this market-only research score does not own.

### Primary scan order

Default Profit Plan ordering remains:

```text
1. cards with Actionable PPP, descending
2. cards without Actionable PPP, after all actionable cards
3. deterministic secondary ordering for equal or unavailable values
```

`Map PPP` / theoretical map potential is display context only and must never promote a card above a card with real Actionable PPP.

When every matching card has unavailable Actionable PPP:

```text
show: 0 actionable candidates
avoid implying that the first source-order card is the best PPP candidate
use an explicitly named secondary order
```

The selector/list view should make Actionable PPP the primary numeric value because users scan many familiar coin cards rapidly.

Suggested compact row:

```text
POL    8.4 | 76
HYPE   6.7 | 84
BTC      — | 61
```

Suggested label/tooltip contract:

```text
ACTIONABLE PPP | OPPORTUNITY  ⓘ
8.4            | 76
```

The existing full card may continue to show `MAP | ACTIONABLE PPP`; Opportunity Rank is a separate scanner/list value and sort option.

### Gate before rank

Opportunity Rank must not rescue invalid or unavailable market truth.

Minimum gate:

```text
actionable target room available
current canonical map/lifecycle available
active target still valid
fresh required market inputs
minimum liquidity coverage available
```

Fail-closed outcomes:

```text
Actionable PPP unavailable -> no actionable promotion
stale/missing map or price  -> DATA_UNAVAILABLE / NO_EDGE
passed/terminal target      -> exclude remaining target room
insufficient liquidity      -> block or penalize explicitly
```

### Opportunity components

Keep the components separate and inspectable before combining them.

#### 1. Remaining opportunity — Actionable PPP

Primary concept:

```text
remaining usable potential from current price to the highest valid active target,
subject to current-cycle activation and lifecycle evidence
```

The scanner must consume one canonical market-opportunity value or persisted read-model field.
It must not independently reimplement Profit Plan PPP semantics in a second renderer-specific path.

#### 2. Participation — Synth Rotation Pressure

Candidate evidence:

```text
24h relative return
7d relative return
signed relative volume
volume acceleration
market-relative strength
persistence
breadth / concentration context where applicable
```

Use the Synth-native persisted rotation-pressure source when available.
Do not label inferred pressure as verified fund inflow.
FFG-like `inflow/outflow` is presentation inspiration, not source truth.

Avoid double counting:

```text
When 24h/7d return and relative volume already contribute to Rotation Pressure,
do not add the same raw measurements again as independent full-weight features.
```

#### 3. Trend quality — moving-average context

Use moving averages as a trend filter, not as a standalone buy signal.

Initial research fields:

```text
4h close versus EMA20
4h EMA20 slope
4h EMA20 versus EMA50
1d trend confirmation
```

Compact derived state:

```text
TREND_SUPPORTIVE
TREND_NEUTRAL
TREND_HOSTILE
DATA_UNAVAILABLE
```

No single MA cross is canonical until replay proves its value by setup family and regime.

#### 4. Timing — reset / reclaim quality

Candidate evidence:

```text
1h and 15m RSI cooled or recovering
1h and 15m MFI stabilizing or turning upward
volume participation returning
short structure reclaim or accepted retest
price not already overextended into target
```

The desired pattern is:

```text
higher-timeframe trend intact
+ lower-timeframe reset
+ renewed participation
```

High RSI by itself is not positive evidence.

#### 5. Risk and tradability

Keep risk as a separate penalty/gate rather than hiding it inside target room.

Candidate evidence:

```text
invalidation distance
ATR-normalized invalidation risk
spread / liquidity quality when canonical data exists
slippage proxy when canonical data exists
distance above recent structure
overextension into target
```

A higher Actionable PPP must not automatically outrank a materially worse invalidation or liquidity profile in the separate Opportunity Rank view.

### Seed weighting for replay only

Initial transparent seed for comparison:

```text
Opportunity Score =
  35% actionable target room
+ 25% rotation pressure
+ 15% trend quality
+ 15% entry timing
+ 10% liquidity quality
- explicit risk / overextension penalty
```

These are experiment weights, not product truth.
Do not ship them as authoritative until ablation and out-of-sample replay show stability.

Required comparisons:

```text
Actionable PPP only
Opportunity Score without MFI
Opportunity Score without MA trend
Opportunity Score without Rotation Pressure
Opportunity Score without risk penalty
equal weights versus seed weights
regime-specific versus global weights
```

### Sort and display behavior

Required sort options:

```text
Actionable PPP high-low      = default
Opportunity Rank high-low   = separate research sort
Rotation Pressure high-low  = diagnostic sort
Target room high-low        = diagnostic sort
```

For the default Actionable PPP sort:

- null/unavailable values always sort last;
- equal values use Opportunity Rank as a secondary tie-break only after validation;
- before validation, use a deterministic neutral tie-break such as symbol/market;
- source order must never silently masquerade as PPP rank;
- display the count of cards with real Actionable PPP.

### Replay and acceptance

Minimum validation:

- forward return distribution by Opportunity Rank decile;
- MFE/MAE by decile;
- target-before-invalidation rate;
- time to target;
- false-positive and missed-opportunity rate;
- calibration by symbol, liquidity, setup, timeframe, and regime;
- stability of score components and weights out of sample;
- incremental value above Actionable PPP alone;
- incremental value above Rotation Pressure alone;
- sensitivity to stale/missing fields;
- proof that duplicate return/volume inputs are not overweighted.

Promotion rule:

```text
read-only research score
-> replay evidence
-> shadow comparison
-> explicit market-only feature-promotion proposal
-> optional selection_engine use
```

Never:

```text
Opportunity Rank
-> decision_gate approval
-> execution plan
-> order
```

### Architecture ownership

```text
canonical market inputs      = market-data / market-model owners
Rotation Pressure            = market-only persisted research/read-model owner
Opportunity Rank research    = research/scanner owner
Profit Plan presentation     = reporting consumes values; does not recompute score
selection_engine             = unchanged until separate validated promotion
decision_gate                = account-aware permission only
execution_planner            = execution intent only
executor / agents            = order handling only
```

Do not create a dependency where `selection_engine` imports the Profit Plan renderer.
If Actionable PPP or its components become shared market features, extract or persist a neutral canonical contract rather than coupling strategy code to presentation code.

## Relationship to FFG / rotation research

FFG-curated universes, external inflow/outflow narratives, and Synth-native rotation pressure may provide research context.
They do not directly set scanner states or trading actions.
Avoid duplicating a separate FFG execution lane; normalize external evidence into this research path or its canonical rotation-pressure source.

## Boundary

```text
research-only
market-only
account-agnostic
selection_engine unchanged unless a later validated promotion is approved
decision_gate unchanged
execution_planner unchanged
executor/agents unchanged
```

Forbidden:

- live trading;
- broker calls or writes;
- order submission;
- account-specific sizing;
- `BUY_READY` or execution language;
- automatic entry promotion;
- research-to-decision or research-to-execution shortcuts.

## Definition of done

- required RSI/MFI fields exist where data supports them;
- rows expose absolute timestamps and availability;
- target room and risk remain distinct;
- Actionable PPP is the primary scan/sort value and unavailable values sort last;
- Opportunity Rank components remain inspectable and avoid double counting;
- MA context is a trend filter, not a standalone action;
- buckets and Opportunity Rank have replay evidence;
- incremental value above Actionable PPP alone is demonstrated before promotion;
- no promotion to selection or execution is implied.
