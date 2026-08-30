# Multi-Horizon Rotation Research Preregistration v1

Issue: #593
Status: research-only preregistration
Canonical horizon semantics: `docs/architecture/multi_horizon_signal_contract_v1.md`
Production impact: none

## 1. Purpose

Freeze the initial #593 candidate family, comparison baselines, replay rules, evaluation metrics, and promotion discipline before final holdout outcomes are inspected.

This slice does not promote any new Rotation signal and does not authorize schema, reporting, ranking, account, decision, execution, broker, or order changes.

## 2. Existing canonical Rotation V1 owner

Current replayable persisted truth already exists in:

```text
market_rotation_pressure_snapshot_v1
market_rotation_pressure_observation_v1
```

Frozen source model identity:

```text
model_version = 1.0
```

Both sources are point-in-time through `as_of_ts_utc`. Per-asset venue identity is resolved through the parent snapshot.

Therefore #593 must reuse this truth for the broad/regime baseline and history audit. It must not create a second V1 history table.

Canonical #243 mapping for existing Rotation V1:

```text
lookback_horizon: 24h + 168h
effective_horizon: REGIME
observed_lifecycle: empirical only
```

The current V1 algorithm and weights remain unchanged.

## 3. Research question

Test whether one or more faster per-asset market-only Rotation measurements add independent, replay-safe information beyond:

1. existing Rotation Pressure V1;
2. simple comparable-horizon price momentum;
3. replay-safe existing RSI/momentum context where available.

A faster candidate is not useful merely because it turns sooner. It must add incremental out-of-sample information without unacceptable chop, missingness, or instability.

## 4. Frozen candidate family

The discovery family is intentionally small.

### C0 — Rotation V1 regime baseline

Existing `market_rotation_pressure_observation_v1` model version `1.0`.

No changes.

### C1 — Fast relative-flow / rotation impulse

Candidate effective horizon:

```text
VERY_SHORT
```

Target operator timescale:

```text
~15m
```

Conceptual inputs to audit and reuse from canonical market data only:

```text
short-horizon asset return
cross-sectional market-relative return
short-horizon signed relative volume or equivalent canonical flow primitive
short-horizon persistence/continuity evidence
```

This candidate must not copy the Rotation V1 weighting template with shorter windows. Exact transforms and weights, if any, must be frozen in a later candidate-definition revision before holdout inspection.

### C2 — Tactical relative-flow Rotation

Candidate effective horizon:

```text
SHORT
```

Target operator timescale:

```text
~1h
```

Uses the same candidate family concept as C1 but independently calibrated for a tactical horizon. It must not be treated as a resampled C1 output unless research demonstrates equivalence.

### C3 — Swing relative-flow Rotation

Candidate effective horizon:

```text
MID
```

Target operator timescale:

```text
~4h
```

Must demonstrate incremental information beyond both C0 and simple 4h price/momentum context.

### Candidate rejection is a valid outcome

Any of C1/C2/C3 may be rejected if it is redundant, unstable, too noisy, too sparse, or not materially different from simple momentum.

The final retained set may therefore be smaller than `15m + 1h + 4h + regime`.

## 5. Mandatory baselines

Every retained candidate must be compared on the same eligible observations against:

```text
B0: Rotation Pressure V1 only
B1: simple price-return / momentum baseline at comparable horizon
B2: replay-safe canonical RSI/momentum context where available
```

No baseline may use future rows, latest-now fallback, current-only classifications, or different eligibility cohorts.

## 6. Point-in-time and replay rules

For every research observation:

```text
source.asof <= observation_asof
source venue == observation venue
source model/version explicitly frozen
no future candle or future classification leakage
no latest-now fallback
no current taxonomy backfill into history
```

Missing evidence remains missing.

All candidate construction must use canonical market data or canonical persisted primitives. Reporting code is not a source of market truth.

## 7. Horizon contract

Every candidate must expose or be representable by `SignalHorizonV1`:

```text
input_interval
lookback_horizon
effective_horizon
observed_lifecycle
asof_ts
freshness
model_id
model_version
provenance
```

Do not infer:

```text
input_interval -> effective_horizon
input_interval -> observed_lifecycle
lookback_horizon -> observed_lifecycle
```

`observed_lifecycle` is measured from replayed/persisted state transitions and remains `UNMEASURED` or `INSUFFICIENT_DATA` until evidence exists.

## 8. Cross-horizon relation semantics

If relation labels are evaluated after candidate construction, only the canonical #243 enum may be used:

```text
ALIGNED
NESTED
TRANSITIONAL
CONFLICTING
NOT_COMPARABLE
INSUFFICIENT_DATA
```

Sign disagreement alone is insufficient to assign `TRANSITIONAL` or `CONFLICTING`.

Raw numeric horizon values remain primary.

## 9. Chronological data split

Use chronological partitions, never random row shuffling.

Required phases where coverage permits:

```text
discovery
validation
final holdout
```

The final holdout remains untouched until:

- candidate formulas/transforms are frozen;
- baselines are frozen;
- eligibility rules are frozen;
- evaluation metrics are frozen;
- multiple-candidate selection discipline is frozen.

The exact date boundaries must be derived from the broadest defensible replay-safe history and recorded before holdout results are inspected.

## 10. Evaluation metrics

At minimum report per candidate/horizon:

```text
sample_count
coverage / missingness
cross-horizon correlation
correlation versus comparable price momentum
lead/lag around meaningful turns
state/turn persistence
false-turn / chop rate
forward response at 15m / 1h / 4h / 24h
incremental utility versus B0
incremental utility versus B1
incremental utility versus B2 where available
effect size
uncertainty / confidence interval
regime/cohort stability
```

Directional or threshold-based metrics must be defined before final holdout evaluation.

## 11. Multiple-comparison discipline

The frozen family is C1/C2/C3 only for this preregistration version.

Do not create additional variants after viewing holdout results and then select the best result.

If discovery indicates a materially different candidate is justified, create a new preregistration version and a new untouched holdout or walk-forward evaluation boundary where possible.

Use paired comparisons on identical eligible observations. Apply an explicit multiple-comparison correction or equivalent frozen model-selection rule before promotion claims.

No arbitrary `X% better` promotion threshold is authorized.

## 12. Promotion criteria

A candidate may be retained only when all of the following are supported out of sample:

```text
incremental information beyond Rotation V1
incremental information beyond simple comparable-horizon momentum
stable effect across more than one regime/cohort where data permits
acceptable coverage/freshness
no material chop regression
explicit effect size + uncertainty + sample count
replayable deterministic model/version identity
```

A visually attractive faster curve is not sufficient evidence.

## 13. Persistence decision

Before adding any table, audit whether existing canonical Rotation storage can be generalized safely without changing V1 semantics.

Rules:

- existing V1 snapshot/observation tables remain authoritative for V1;
- no parallel duplicate V1 truth;
- accepted faster models require distinct model/version/horizon identity;
- deterministic persistence identity must include `venue + unambiguous asset/market identity + model_id + model_version + effective_horizon + asof_ts`;
- idempotent persistence required;
- ~30d is an operator/live-history target, not the validation period.

Historical validation must use the broadest defensible multi-regime replay-safe history.

## 14. Downstream ownership

If faster variants are ultimately accepted:

```text
raw numeric Rotation values/history -> #297/#315 reporting
cross-horizon semantics -> #243 contract
conviction consumption -> #591/#568 only through their own reviewed research contracts
```

#593 does not build a generic conviction or summary engine.

If an operator summary such as `BULLISH`, `MIXED`, or `TRANSITIONING` is desired and no existing canonical owner covers it, a bounded follow-up issue must own it before #593 closes.

## 15. Safety

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
