# Multi-Horizon Signal Contract v1

Status: Permanent architecture contract
Canonical location: `docs/architecture/multi_horizon_signal_contract_v1.md`
Scope: canonical identity, timing, provenance, lifecycle, and cross-horizon relation semantics for market signals/features
Runtime impact: none
Issue: #243

## 1. Purpose

Synth combines market observations that operate on different candle intervals, lookback windows, effective market horizons, and observed lifecycles. This contract prevents those concepts from being collapsed into one ambiguous timeframe label or opaque aggregate.

The core invariant is:

```text
input_interval != lookback_horizon != effective_horizon != observed_lifecycle
```

Equality may occur for a particular model by evidence or definition, but it must never be inferred automatically.

In particular:

```text
4h input candles
```

must never imply:

```text
4h effective signal horizon
4h lifecycle duration
```

without an explicit model contract and empirical lifecycle evidence.

This document is the canonical owner of generic multi-horizon semantics. Domain-specific producers retain ownership of their own market calculations.

## 2. Architecture boundaries

Required ownership remains:

```text
market data / feature owners
-> market-only signal or feature outputs
-> optional market-only strategy interpretation / selection
-> decision_gate
-> execution_planner
-> executor / agents
```

Hard boundaries:

- `selection_engine` remains market-only and account-agnostic;
- `decision_gate` remains the sole account-aware permission layer;
- `execution_planner` owns execution intent only;
- executor/agents own order handling only;
- reporting is a read-only consumer;
- this contract grants no market-ranking, account, execution, broker, or order authority.

No consumer may recompute an upstream signal merely to attach horizon metadata or cross-horizon labels.

## 3. Canonical `SignalHorizonV1`

Every signal or feature that participates in multi-horizon composition must be representable by the following semantic contract.

```text
SignalHorizonV1
- input_interval
- lookback_horizon
- effective_horizon
- observed_lifecycle
- asof_ts
- freshness
- model_id
- model_version
- provenance
```

### 3.1 `input_interval`

The source sampling/candle/snapshot granularity used by the producer.

Examples:

```text
5m
15m
1h
4h
1d
multi-interval
```

A producer using multiple intervals must expose that fact explicitly rather than choosing one representative interval.

### 3.2 `lookback_horizon`

The historical span or spans used to compute the observation.

Examples:

```text
24h
168h
50 bars @ 4h
SMA200 @ 1d
24h + 168h
```

This is computation history, not necessarily the market move the signal is intended to describe.

### 3.3 `effective_horizon`

The semantic market horizon the producer intends the signal to describe.

Canonical values are intentionally coarse and semantic:

```text
VERY_SHORT
SHORT
MID
LONG
REGIME
MULTI_HORIZON
UNKNOWN
```

Domain-specific display aliases such as `TACTICAL`, `SWING`, or `BROAD_REGIME` may exist, but canonical machine contracts must map deterministically to one of the values above or remain `UNKNOWN` until reviewed.

`effective_horizon` is producer-owned metadata. Reporting must not infer it from `input_interval`.

### 3.4 `observed_lifecycle`

Empirical duration characteristics of the produced state/map/wave/signal when historical evidence is available.

It must remain explicitly separate from input and lookback timing.

Recommended representation:

```text
observed_lifecycle:
  status: MEASURED | UNMEASURED | INSUFFICIENT_DATA
  sample_count: integer | null
  p25_seconds: integer | null
  p50_seconds: integer | null
  p75_seconds: integer | null
  p90_seconds: integer | null
  censoring_method: string | null
  analysis_ref: string | null
```

Requirements:

- do not invent typical durations when they have not been measured;
- active/incomplete lifecycles must be treated as censored rather than silently completed;
- empirical lifecycle statistics may be model-version and regime dependent;
- a producer may emit `UNMEASURED` while a deterministic measurement plan exists elsewhere.

### 3.5 `asof_ts` and `freshness`

`asof_ts` identifies the market-data/evidence timestamp represented by the signal.

Freshness must be explicit and producer-owned. At minimum the contract must allow:

```text
FRESH
STALE
INSUFFICIENT_DATA
UNKNOWN
```

A renderer must not silently convert stale evidence into current truth.

### 3.6 Model identity and provenance

Every signal must expose deterministic provenance sufficient to reproduce its meaning:

```text
model_id
model_version
source owner
source row/run/snapshot references where applicable
```

Changing model semantics requires a version change. Renaming a UI label does not.

## 4. Canonical `CrossHorizonRelationV1`

Cross-horizon classification is a relation between two or more already-produced market observations. It is not a replacement signal and it does not create trading authority.

Canonical enum:

```text
ALIGNED
NESTED
TRANSITIONAL
CONFLICTING
NOT_COMPARABLE
INSUFFICIENT_DATA
```

### 4.1 `ALIGNED`

Signals with meaningfully different or comparable horizons point in the same directional/contextual interpretation and no material timing contradiction is present.

Example:

```text
SHORT positive
MID positive
LONG positive
```

Alignment must be based on each producer's canonical meaning, not merely on matching display colors.

### 4.2 `NESTED`

A faster-horizon move occurs inside a slower-horizon structure without evidence that the slower thesis has ended.

Examples:

```text
SHORT pullback inside LONG uptrend
SHORT rebound inside REGIME negative context
```

`NESTED` is not intrinsically bullish or bearish. The relation describes structure between horizons.

### 4.3 `TRANSITIONAL`

A faster horizon has materially changed while a slower comparable horizon has not yet confirmed the same change, and the model semantics support interpreting this as a possible phase transition rather than simple noise.

Example:

```text
VERY_SHORT positive
SHORT positive
REGIME negative
```

This state must not be emitted solely because signs differ. Producers/derived relation logic must have sufficient evidence and freshness.

### 4.4 `CONFLICTING`

Signals intended to describe comparable market questions/horizons disagree materially in a way that cannot be explained as nested structure or normal transition lag.

A disagreement between a tactical timing signal and a multi-week structural trend is not automatically `CONFLICTING`.

### 4.5 `NOT_COMPARABLE`

Signals answer materially different questions or their horizon semantics do not permit a meaningful directional relation.

Examples may include:

- a liquidity-quality state versus a directional trend state;
- execution timing evidence versus a long-term structural thesis;
- two features whose directional scales are not semantically compatible.

Preserve both observations separately. Do not force consensus.

### 4.6 `INSUFFICIENT_DATA`

The relation cannot be determined safely because one or more required observations lack coverage, freshness, provenance, comparable semantics, or minimum evidence.

`INSUFFICIENT_DATA` must remain distinct from `NOT_COMPARABLE`:

- `NOT_COMPARABLE` = valid data, incompatible questions;
- `INSUFFICIENT_DATA` = insufficient evidence to decide the relation.

## 5. Relation evaluation requirements

Any future canonical implementation of `CrossHorizonRelationV1` must be deterministic, versioned, and inspectable.

It must consume upstream facts such as:

```text
signal identity/version
SignalHorizonV1 metadata
raw numeric/state value
as-of/freshness
coverage/data quality
producer-owned directional/context semantics
```

It must not:

- recompute upstream indicators;
- infer market direction from UI color;
- average unrelated horizons;
- treat sign mismatch alone as `TRANSITIONAL` or `CONFLICTING`;
- read account state;
- emit BUY/SELL permission;
- create execution intent.

Where deterministic relation semantics have not yet been validated for a producer pair, preserve the raw signals and emit `NOT_COMPARABLE` or `INSUFFICIENT_DATA` as appropriate.

## 6. Precedence and composition rules

There is no universal all-horizon consensus score.

Forbidden patterns:

```text
mean(SHORT, MID, LONG, REGIME)
weighted opaque consensus without a separate reviewed owner
slow signal universally vetoes fast signal
fast signal automatically invalidates slow signal
reporting derives hidden thresholds
```

Allowed pattern:

```text
canonical horizon-specific observations
-> optional versioned cross-horizon relation
-> optional separately-owned strategy/conviction interpretation
-> read-only reporting
```

A downstream strategy may assign different roles to horizons, but those roles belong to that strategy's own reviewed contract. For example, `LONG = thesis`, `MID = exposure`, `SHORT = entry timing` is a strategy interpretation, not a generic truth created by this contract.

## 7. Signal inventory and current canonical interpretation

This section records current known lanes so downstream issues do not invent duplicate semantics.

### 7.1 Market Rotation Pressure V1

Owner: existing Rotation Pressure market-only lane.

Current composition includes:

```text
24h return                         25%
24h signed relative volume         20%
168h return                        15%
168h signed relative volume        10%
24h-vs-168h acceleration           15%
market-relative factor             10%
persistence                         5%
```

A valid pressure snapshot requires both 24h and 168h observations.

Canonical horizon interpretation for this contract:

```text
input_interval: producer-specific/current implementation metadata
lookback_horizon: 24h + 168h
effective_horizon: REGIME
observed_lifecycle: UNMEASURED unless backed by persisted empirical analysis
```

The `REGIME` classification identifies broad context only. It does not relabel the current model as a 1h/4h signal and does not change V1 weights.

Issue #593 owns research into faster per-asset Rotation variants and persistent history. It must consume this contract and give each retained variant separate model/version/horizon identity.

### 7.2 Native SHORT Fibonacci context

Owner: canonical Native SHORT Fibonacci/map lifecycle lane.

Known structural scope:

```text
primary context: 4h
supporting context: 1h
```

The map/wave's actual lifecycle is empirical and must not be inferred from those candle intervals.

Any 1h/4h/multi-horizon Fib opportunity remains separately identifiable with its own provenance and lifecycle. #557 and Fib-related lanes must not collapse horizon-specific opportunities merely to simplify ranking.

### 7.3 Strategy Proposal Contract v1

`docs/architecture/strategy_proposal_contract_v1.md` currently defines strategy horizons `SHORT`, `MID`, and `LONG` as semantic horizons rather than direct candle mappings.

That remains valid. When a strategy proposal consumes lower-level market signals, its strategy `horizon` is strategy-owned meaning and must not overwrite the underlying `SignalHorizonV1` metadata of its inputs.

### 7.4 RSI / structure / confirmation

Existing canonical owners remain authoritative for calculation and state meaning.

Before participating in generic cross-horizon relations, each retained variant must expose or map to `SignalHorizonV1`. This contract does not recalculate RSI, structure, or confirmation.

### 7.5 MA / volume trend-flow

Issue #310 owns feature research and classification. Issue #315 owns read-only presentation of accepted outputs.

Any accepted MA/volume feature must expose explicit timing metadata before generic cross-horizon composition. This contract does not define MA/volume thresholds.

### 7.6 Breathline

Breathline remains research context unless separately promoted. It gains no production authority from being listed here.

Any future promoted Breathline signal must satisfy the same horizon/provenance/lifecycle requirements as any other market signal.

## 8. Observed lifecycle measurement contract

Lifecycle analysis must use persisted/replayable state where available. Presentation snapshots are not sufficient evidence.

For stateful signals, measure contiguous state/event lifecycles from canonical history where possible.

Recommended statistics:

```text
sample_count
p25
p50
p75
p90
active/censored count
analysis period
asset cohort
regime cohort where applicable
model version
missingness/coverage
```

For incomplete active lifecycles, use an explicit censoring treatment. If available history cannot support defensible estimates, keep `observed_lifecycle.status = UNMEASURED` or `INSUFFICIENT_DATA` and document a deterministic replay plan.

### 8.1 Rotation Pressure measurement targets

Where canonical persisted history permits, measure:

- `ROTATION_IN` duration;
- `ROTATION_OUT` duration;
- strong-state duration where those states are canonical;
- neutral/mixed duration;
- transition time across meaningful thresholds;
- relation between faster 24h components and broader 168h confirmation without claiming causality.

### 8.2 Native SHORT Fibonacci measurement targets

Where canonical history permits, measure:

- map publication to completion/invalidation/supersession;
- anchor to first target;
- anchor to later targets;
- re-entry to target where provenance supports that relationship;
- duration by asset and regime where sample size permits.

## 9. Reporting contract

Reporting must expose timescale, provenance, freshness, and raw values without creating market authority.

Good:

```text
Rotation
15m       +62
1h        +48
4h        +12
Regime    -40
```

Good when a canonical upstream relation exists:

```text
Cross-TF  TRANSITIONAL
```

Forbidden:

```text
Rotation +21   # hidden average of unrelated horizons
```

Rules:

- numeric/raw state is primary where the producer exposes one;
- color is secondary visual encoding only;
- reporting may display `CrossHorizonRelationV1` but may not calculate thresholds or relations itself;
- missing or stale horizon data must remain visible;
- operator detail must preserve model/version and as-of provenance.

## 10. Downstream ownership

This contract is the gate for generic multi-horizon semantics used by:

- #593: multi-horizon per-asset Rotation research/history;
- #591: Multi-TF Conviction research;
- #297 / #315: read-only signal/market-context presentation;
- Fib multi-horizon research and dashboards;
- #557: horizon-specific market opportunities competing only later at `decision_gate`.

Required dependency direction:

```text
#243 canonical horizon semantics
-> domain-specific market observations/research
-> optional strategy/conviction interpretation
-> reporting
```

Not:

```text
reporting/CQ/decision_gate
-> recompute or redefine upstream horizon truth
```

## 11. Guard requirements

Future schema/code/contracts that introduce multi-horizon composition should be reviewed against these invariants:

1. no account fields in market-only signal horizon metadata;
2. no inference of `effective_horizon` from `input_interval` alone;
3. no inference of `observed_lifecycle` from candle interval or lookback;
4. no opaque averaging of unrelated horizons;
5. no reporting-owned relation thresholds;
6. explicit model/version/provenance;
7. stale/insufficient evidence cannot silently become active truth;
8. `NOT_COMPARABLE` and `INSUFFICIENT_DATA` remain distinct;
9. domain-specific calculation remains with the canonical producer;
10. downstream authority layers remain unchanged.

Repository guard tests should be added when a concrete typed/runtime implementation of this contract is introduced. Documentation-only consumers must reference this canonical document rather than create duplicate enums.

## 12. Migration / compatibility guidance

Existing contracts are not required to rewrite all historical rows immediately.

When an existing signal becomes a multi-horizon consumer/producer:

1. inventory current timing/provenance fields;
2. map them explicitly to `SignalHorizonV1` semantics;
3. leave unknown fields unknown rather than infer them;
4. version any semantic changes;
5. add persistence only in the owning domain issue if required;
6. update downstream reporting after canonical outputs exist.

No schema migration is authorized by this document alone.

## 13. Acceptance implications for #243

#243 is satisfied when:

- this contract is reviewed and accepted as the sole generic multi-horizon semantic owner;
- signal inventory and ownership are explicit;
- the four time concepts remain separate;
- Rotation Pressure V1 24h/168h composition is documented accurately without changing its model;
- Native SHORT 4h/1h scope is separated from observed lifecycle;
- lifecycle measurement requirements and censored-data handling are explicit;
- `CrossHorizonRelationV1` semantics are frozen;
- precedence rules prohibit opaque horizon collapse;
- reporting remains read-only;
- architecture boundaries remain intact;
- no runtime/trading behavior changes are introduced.

## 14. Safety

```text
architecture_contract_only=1
market_ranking_changes=0
account_awareness_added=0
decision_permission_changes=0
execution_planning_changes=0
executor_changes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
production_deploy=0
```

## 15. Related documents / issues

- `docs/architecture/strategy_proposal_contract_v1.md`
- #243 canonical multi-horizon architecture and semantics
- #593 multi-horizon per-asset Rotation research/history
- #591 Multi-TF Conviction
- #297 Signal Matrix Static Dashboard
- #310 MA/volume trend-flow feature research
- #315 MA/volume/reporting presentation
- #449 Rotation Flip research
- #557 wallet-triggered opportunity investment loop
