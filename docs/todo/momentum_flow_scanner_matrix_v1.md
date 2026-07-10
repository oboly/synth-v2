# TODO — Momentum Flow Scanner Matrix V1

## Status

Open research / read-only scanner lane.

This bundle records the 2026-07-10 review of the FFG-style crypto overview showing RSI/MFI-style momentum and money-flow context across lists of coins.

This is not a trading decision, not a signal promotion, not order logic, and not an execution lane.

## Purpose

Build a compact read-only scanner that helps find the best entry candidates across many coins instead of chasing every active map.

The scanner should answer:

```text
Which coins have enough upside-to-target, acceptable risk, and short-timeframe reset/momentum conditions to deserve human review?
```

It must not answer:

```text
What should the bot buy now?
```

## Current Synth coverage

Synth already has candle-level RSI and several volume/flow-like features in `feat_candle`:

```text
rsi_14
volume_ratio_20
volume_zscore_20
obv
obv_slope_5
dollar_volume_ratio_20
```

MFI / Money Flow Index is not currently treated as a first-class feature in the scanner/dashboard contract.

## Target concept

Working name:

```text
MOMENTUM_FLOW_SCANNER_MATRIX_V1
```

Dashboard style:

```text
FFG-style compact matrix
multi-asset
multi-timeframe
read-only
fast visual scan
```

Candidate columns:

```text
symbol
market
price
1d RSI
1d MFI
4h RSI
4h MFI
1h RSI
1h MFI
15m RSI
15m MFI
volume_ratio_20
dollar_volume_ratio_20
native map status
nearest valid target upside %
invalidation downside %
entry/reset state
scanner bucket
reason codes
observed_ts_utc
```

## Minimum upside gate

The user-selected research threshold is:

```text
nearest_valid_target_upside_pct >= 4.0
```

Interpretation:

```text
If there is not at least 4% room from candidate entry/current planning price to the nearest valid target, wait.
```

This is a minimum target-upside gate, not reward/risk.

Risk must remain separate.

Bad candidate example:

```text
target upside: +4.2%
invalidation downside: -9.0%
result: reject or warn; upside gate alone is not enough
```

## Research-only entry candidate logic

Initial candidate rule shape for backtesting only:

```text
candidate_entry_context only if:
- nearest_valid_target_upside_pct >= 4.0
- invalidation is present and not excessive
- current price is not already extended into/near target
- native map is fresh enough for research evaluation
- short timeframe reset or reclaim condition exists
- volume/money-flow condition is supportive or at least not hostile
```

No `BUY_READY` state is allowed in this lane.

Allowed states:

```text
NO_EDGE
WATCH
RESET_READY
ENTRY_CANDIDATE_RESEARCH
OVERHEATED
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

## Suggested buckets

### RESET_READY

Meaning:

```text
Higher timeframe still constructive, lower timeframe cooled down, enough target room remains.
```

Example research shape:

```text
1d RSI: constructive / not broken
1h RSI: cooled down
15m RSI: reset or recovering
MFI: recovering or supportive
nearest valid target upside >= 4.0%
```

### OVERHEATED

Meaning:

```text
Momentum is already hot and target room may be too small for a new entry.
```

Example research shape:

```text
1h/15m RSI high
15m/1h MFI high or exhausted
price close to target
upside-to-target < 4.0%
```

### ACCUMULATION_FLOW

Meaning:

```text
Money-flow improves before price momentum fully responds.
```

Example research shape:

```text
MFI rising
RSI neutral or recovering
volume/dollar-volume supportive
price not yet extended
```

### DISTRIBUTION_RISK

Meaning:

```text
Price momentum is high, but money-flow or volume behavior suggests weakening participation.
```

Example research shape:

```text
RSI high
MFI diverging down or no longer confirming
volume spike exhaustion or weak follow-through
```

### NO_EDGE

Meaning:

```text
No clear entry context, insufficient upside, stale data, conflicting momentum/flow, or map unavailable.
```

## MFI feature scope

Add MFI only as a market-data feature.

Likely feature name:

```text
mfi_14
```

Layer ownership:

```text
src/features/etl_candle_feat.py owns feature calculation
feat_candle owns persisted per-candle feature value
scanner/read-model owns read-only aggregation/presentation
```

MFI must not be added to account-aware layers.

MFI calculation should use candle high/low/close/volume and be deterministic.

Required tests:

```text
MFI deterministic on fixed candle fixture
MFI handles flat/zero-volume windows safely
MFI warmup produces null until enough bars exist
MFI values stay within 0..100 when calculable
existing RSI/ATR/volume features remain unchanged
```

## Scanner read-model scope

The scanner should consume existing candle features and native map context without changing trading policy.

Possible output contract:

```text
momentum_flow_scanner_snapshot_v1
```

Minimum fields:

```text
symbol
venue
market
interval_set
observed_ts_utc
price_observed_ts_utc
feature_observed_ts_utc
map_observed_ts_utc
rsi_1d
mfi_1d
rsi_4h
mfi_4h
rsi_1h
mfi_1h
rsi_15m
mfi_15m
nearest_valid_target_upside_pct
invalidation_downside_pct
entry_context_state
scanner_bucket
reason_codes
```

Freshness:

```text
Each row must expose observed timestamps.
Stale or missing features must render DATA_UNAVAILABLE or NO_EDGE.
No server-baked relative freshness as sole evidence.
```

## Dashboard scope

Add a read-only compact scanner page or section.

Possible title:

```text
Momentum / Flow Scanner
```

Suggested sort options:

```text
Best entry context
Target upside high-low
Reset readiness
Flow improving
Overheated first
Data unavailable last
```

Suggested filters:

```text
bucket
minimum target upside
market
interval completeness
map freshness
RSI/MFI regime
```

Suggested row text:

```text
RESET_READY — target room 5.8%, 1h cooled, 15m recovering, MFI supportive
OVERHEATED — target room 1.2%, 15m RSI/MFI hot
NO_EDGE — target room below 4% threshold
DATA_UNAVAILABLE — missing MFI 15m or stale map
```

## Backtest / validation lane

Before any scanner bucket can influence candidate selection, validate it with replay/backtest.

Required validation questions:

```text
Does target-upside >= 4% improve outcome quality versus all maps?
Do RESET_READY buckets outperform OVERHEATED buckets?
Does MFI add predictive value beyond RSI + volume_ratio_20 + map context?
Which intervals matter most by strategy family?
What is the false-positive rate per bucket?
How often does waiting for 4% target room skip winners versus avoid low-edge trades?
```

Minimum outputs:

```text
bucket counts
forward return distribution
MFE/MAE
hit target before invalidation rate
time-to-target
false positives
symbol/timeframe breakdown
random/control comparison
```

## Hard architecture boundary

```text
selection_engine remains market-only and unchanged unless a later validated promotion explicitly scopes it.
decision_gate remains account-aware and unchanged.
execution_planner remains execution-intent only and unchanged.
executor/agents remain order-handling only and unchanged.
```

Forbidden:

```text
no live trading
no broker calls
no broker writes
no order submission
no decision_gate changes
no execution_planner changes
no executor changes
no account-specific sizing
no BUY_READY label
no automatic entry promotion
no reporting-side candle reconstruction if a canonical feature/read model exists
```

## Dependency notes

Useful upstream sources:

```text
feat_candle RSI/volume/OBV/dollar-volume features
native map / target / invalidation context
market price snapshot
future current per-level status read model where available
```

This lane does not depend on live ladder work.

It may run in parallel as research/read-only work as long as it does not mutate trading policy or execution layers.

## Suggested PR split

```text
1. docs: document momentum/flow scanner matrix contract
2. feat: add deterministic mfi_14 to candle feature ETL and schema migration
3. research: add read-only momentum_flow_scanner_snapshot_v1 builder
4. research: backtest scanner buckets and 4% target-upside threshold
5. ui: add read-only Momentum / Flow Scanner dashboard page
```

## Definition of done

```text
RSI and MFI are available per required interval where data exists.
Scanner exposes compact multi-asset/multi-timeframe rows.
Rows include absolute observed timestamps and data availability status.
Minimum target-upside >= 4.0% is represented as a research gate.
Risk/invalidation remains separate from target-upside.
No BUY_READY or execution implication exists.
Backtest evidence exists before any promotion to candidate selection.
```
