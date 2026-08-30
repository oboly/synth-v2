# Multi-Horizon Rotation Candidate Definition v1

Issue: #593
Status: research-only candidate definition
Depends on: `docs/research/multi_horizon_rotation_preregistration_v1.md`
Canonical horizon semantics: `docs/architecture/multi_horizon_signal_contract_v1.md`
Production impact: none

## 1. Purpose

Freeze the exact first-pass C1/C2/C3 candidate construction before validation/final-holdout results are inspected.

This document intentionally chooses a small, deterministic, low-degree-of-freedom formulation. It does not tune candidate weights against outcomes and it does not change Rotation Pressure V1.

The research question remains whether a faster per-asset relative-flow measurement adds information beyond existing Rotation Pressure V1 and simple price momentum. Candidate rejection is a valid result.

## 2. Canonical source boundary

Candidate construction consumes canonical market candles only.

Current repository research already resolves point-in-time 15m candles from:

```text
obs_market_candle
```

with identity:

```text
asset_id
venue
interval_code = 15m
close_ts_utc
```

C1/C2/C3 therefore use 15m as the frozen `input_interval`. Longer candidate windows are computed from contiguous completed 15m observations; they are not sourced from reporting code and are not inferred from current snapshots.

Required candle fields:

```text
close_ts_utc
close_price
canonical non-negative volume measure
```

The replay implementation must resolve the existing canonical candle-volume column/semantic before it runs. It must not create a synthetic or renderer-owned volume source. If no replay-safe canonical volume field is available, the candidate-definition version must be revised before validation rather than silently dropping or replacing the flow component.

## 3. Candidate horizons

Frozen mappings:

```text
C1
  model_id: multi_horizon_rotation_relative_flow
  model_version: 1.0.0-c1
  input_interval: 15m
  lookback_horizon: current 15m window + previous 8 completed 15m windows
  effective_horizon: VERY_SHORT
  operator alias: 15m

C2
  model_id: multi_horizon_rotation_relative_flow
  model_version: 1.0.0-c2
  input_interval: 15m
  lookback_horizon: current 1h window + previous 8 completed 1h windows
  effective_horizon: SHORT
  operator alias: 1h

C3
  model_id: multi_horizon_rotation_relative_flow
  model_version: 1.0.0-c3
  input_interval: 15m
  lookback_horizon: current 4h window + previous 8 completed 4h windows
  effective_horizon: MID
  operator alias: 4h
```

The operator aliases do not imply lifecycle duration.

## 4. Point-in-time eligible cohort

At each candidate `asof_ts`, the comparison cohort is the set of same-venue assets for which all required completed 15m candles exist for the candidate's current and prior windows.

Rules:

```text
same venue only
no candle after asof_ts
no latest-now fallback
no current-universe backfill requirement
no future listing/delisting information
minimum eligible cohort size = 20 assets
asof_ts must align exactly to the canonical 15m close grid
```

If `asof_ts` is not exactly aligned to a canonical 15m close boundary, the candidate observation is `INSUFFICIENT_DATA`.

If fewer than 20 assets satisfy the candidate coverage requirements, the candidate observation is `INSUFFICIENT_DATA`.

The cohort is reconstructed from data that actually existed at that as-of. No future/current asset label may be used to manufacture historical coverage.

## 5. Window definitions

Let candidate horizon length be `H`:

```text
C1 H = 15m
C2 H = 60m
C3 H = 240m
```

For asset `i` and as-of `t`, define the current completed window:

```text
W0 = (t-H, t]
```

and previous non-overlapping completed windows:

```text
W1 = (t-2H, t-H]
...
W8 = (t-9H, t-8H]
```

Every `t-kH` boundary used by W0..W8 must itself align exactly to the canonical 15m close grid. A return may only use candles whose `close_ts_utc` exactly equals the required start and end boundary. The implementation must not use a stale close from before a boundary.

A window is valid only when both conditions hold:

```text
1. exact start-boundary close exists
2. expected contiguous 15m candle count inside the window is present
```

Expected in-window candle counts:

```text
C1: 1 candle/window
C2: 4 candles/window
C3: 16 candles/window
```

A missing exact boundary close, an off-grid as-of/window boundary, or any gap in the expected 15m sequence makes that asset/window unavailable and therefore yields `INSUFFICIENT_DATA` for the affected candidate observation.

No partial-window scaling or interpolation is allowed.

## 6. Primitive definitions

### 6.1 Horizon return

For window `Wk`, use the close exactly at the window start boundary and the close exactly at the window end boundary:

```text
r_i,k = ln(close_i,end_boundary / close_i,start_boundary)
```

Both boundaries are exact canonical 15m close timestamps. A candle merely earlier than the required start boundary is invalid and must never be substituted.

If either exact boundary close is missing, either price is non-positive, or the required contiguous in-window 15m sequence is incomplete, that asset/window is unavailable.

### 6.2 Cross-sectional relative return

For each window `Wk`, calculate across the eligible same-venue cohort:

```text
m_k = median_i(r_i,k)
rr_i,k = r_i,k - m_k
```

This is market-relative return, not BTC-relative strength.

### 6.3 Robust cross-sectional normalization

For any cross-sectional value `x_i` at one as-of/window:

```text
center = median_i(x_i)
mad = median_i(abs(x_i - center))
```

If `mad <= 1e-12`, the normalized component is unavailable for that as-of.

Otherwise:

```text
robust_z_i = (x_i - center) / (1.4826 * mad)
unit_i = clip(robust_z_i / 3, -1, +1)
```

The clipping constant and divisor are frozen. No percentile or sigma threshold tuning is allowed in this candidate version.

### 6.4 Window volume

For each valid `Wk`:

```text
vol_i,k = sum(canonical candle volume over Wk)
```

Volume must be non-negative. A zero median reference volume makes the flow component unavailable.

### 6.5 Volume surprise

Use only prior completed windows as the reference:

```text
vol_ref_i = median(vol_i,1 ... vol_i,8)
volume_log_ratio_i = ln((vol_i,0 + eps) / (vol_ref_i + eps))
```

with frozen:

```text
eps = 1e-12
```

Normalize `volume_log_ratio_i` cross-sectionally using section 6.3.

The volume surprise becomes directional only by multiplying it by the sign of the current market-relative return:

```text
signed_flow_raw_i = sign(rr_i,0) * volume_surprise_unit_i
```

If `rr_i,0 == 0`, sign is `0`.

### 6.6 Relative-return acceleration

Define:

```text
accel_raw_i = rr_i,0 - rr_i,1
```

Normalize `accel_raw_i` cross-sectionally using section 6.3.

This represents change in relative movement, not absolute price acceleration.

## 7. Frozen candidate components

At each horizon the candidate has exactly three unit components:

```text
relative_return_unit      in [-1,+1]
signed_flow_unit          in [-1,+1]
relative_acceleration_unit in [-1,+1]
```

Where:

```text
relative_return_unit = robust_normalize(rr_i,0)
signed_flow_unit = sign(rr_i,0) * robust_normalize(volume_log_ratio_i)
relative_acceleration_unit = robust_normalize(rr_i,0 - rr_i,1)
```

No RSI, Fib, Breathline, sector label, account state, CQ value, strategy state, or Rotation V1 component is allowed inside C1/C2/C3.

## 8. Frozen score formula

All three components receive equal weight by design:

```text
rotation_score_raw = (
    relative_return_unit
  + signed_flow_unit
  + relative_acceleration_unit
) / 3

rotation_score = round(100 * rotation_score_raw, 6)
```

Expected bounded scale:

```text
-100 <= rotation_score <= +100
```

There is no threshold-based `BULLISH`/`BEARISH` state in this candidate-definition version.

The equal weighting is not a claim that the three primitives are equally predictive. It is a low-degree-of-freedom starting candidate chosen before outcome inspection. If research later justifies different transforms/weights, that requires a new preregistration/candidate version and untouched evaluation boundary where possible.

## 9. Missingness and quality

A candidate observation is emitted as numeric only when all three components are available.

Otherwise:

```text
rotation_score = null
freshness/data_quality = INSUFFICIENT_DATA
```

Do not renormalize weights over the remaining components. That would create a different model under missingness.

Minimum requirements include:

```text
asof_ts exactly on canonical 15m close grid
all W0..W8 boundaries exactly on canonical 15m close grid
exact start/end boundary close for every required return
complete current window
complete W1 for acceleration
complete W1..W8 volume reference
minimum same-venue cohort = 20
non-degenerate robust normalization for all required cross-sectional components
```

## 10. SignalHorizonV1 mapping

Every emitted research row must carry:

```text
venue
asset_id and/or unambiguous market identity
asof_ts
model_id
model_version
input_interval
lookback_horizon
effective_horizon
observed_lifecycle
freshness
data_quality
provenance
```

`observed_lifecycle` remains:

```text
UNMEASURED
```

until replayed state/turn persistence has been measured. The 15m/1h/4h aliases are not lifecycle values.

Deterministic persistence identity, if/when persistence is accepted, is:

```text
venue
asset_or_market_identity
model_id
model_version
effective_horizon
asof_ts
```

## 11. Baselines remain separate

The replay must compare C1/C2/C3 against the frozen preregistered baselines on paired eligible observations:

```text
B0 Rotation Pressure V1 model 1.0
B1 simple comparable-horizon price momentum
B2 replay-safe canonical RSI/momentum context where available
```

B1 must not reuse `rotation_score` components beyond the raw comparable-horizon price return needed for the baseline.

The candidate must beat its price-only baseline through evidence, not through naming.

## 12. Cross-horizon relations are not produced here

This candidate-definition slice freezes numeric horizon-specific observations only.

It does not assign:

```text
ALIGNED
NESTED
TRANSITIONAL
CONFLICTING
```

Those relations require separately validated deterministic comparison logic under the canonical #243 contract. Sign mismatch alone remains insufficient.

## 13. Validation implementation contract

The next implementation slice may add research-only code/tests to:

1. resolve canonical 15m candles and volume semantics;
2. require exact 15m grid alignment for `asof_ts` and every W0..W8 boundary;
3. require exact start/end boundary closes plus contiguous completed 15m windows;
4. calculate C1/C2/C3 deterministically;
5. attach existing Rotation V1 PIT observations;
6. calculate B1 and available B2 on the same observation cohort;
7. produce replay artifacts, never production truth;
8. measure coverage/correlation/lead-lag/persistence/chop/forward response;
9. freeze chronological discovery/validation/holdout boundaries before final holdout inspection.

It must not:

```text
write production selection state
change Rotation V1
change CQ
change decision_gate
change execution_planner
write broker/order state
publish dashboard authority
```

## 14. Safety

```text
research_only=1
market_only=1
account_awareness=0
selection_engine_production_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
production_runtime_activation=0
```
