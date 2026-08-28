# BTC ↔ RENDER Breathline relationship study v1

Issue: #418

Status: preregistered research protocol. No BTC↔RENDER relationship outcome has been inspected when this document is committed.

## Purpose

Test whether independently observed bullish Breathline cycles from the unchanged #417 tracker show a reproducible BTC-to-RENDER phase relationship that survives chronological holdout and randomized controls.

This study does not assume BTC controls RENDER, that a relationship exists, or that any #533 harmonic duration/ratio is true.

## Hard architecture boundary

```text
research_only=true
market_only=true
account_awareness=0
selection_engine_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_calls=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
live_trading_permission=0
production_db_writes=0
production_schema_changes=0
runtime_activation=0
```

The #417 tracker implementation and configuration are not modified to create a cross-symbol relationship.

## Phase 0: independent ledgers first

Before cross-symbol analysis:

1. Extract canonical Bitvavo 4h BTC candles with the same read-only source semantics used for #534.
2. Run the exact unchanged #417 bullish tracker on BTC.
3. Use the existing independently generated RENDER #417 ledger from #534, or regenerate RENDER only if a matched source window is explicitly required and provenance-bound.
4. Record per-symbol source hashes, tracker source hashes, analysis commit, row counts, gaps and ledger hashes.
5. Do not inspect BTC↔RENDER relationship statistics before both independent ledgers are frozen.

Synthetic fixture cycles are mechanics-only and cannot satisfy this evidence phase.

## Frozen symbols and interval

```text
reference = BTC
alt = RENDER
venue = bitvavo
interval = 4h
```

RENDER is selected for v1 because it has the larger existing #534 observed-cycle sample and exhibited the clearest retrospective structural signals in #533. That selection does not promote a #533 result into relationship truth.

## Lane A: retrospective relationship description

Lane A may use completed cycle start/end timestamps because it makes no predictive claim.

### Pairing

For each completed RENDER cycle, pair to the completed BTC cycle with maximum wall-clock overlap:

```text
overlap = max(0, min(render_end, btc_end) - max(render_start, btc_start))
```

Tie-break order:

1. largest overlap;
2. smallest absolute start-time lag;
3. earliest BTC start timestamp;
4. lexical BTC cycle id.

A zero-overlap RENDER cycle remains `UNPAIRED`. Do not force a nearest BTC cycle. A BTC cycle may pair to more than one RENDER cycle.

### Retrospective normalized phase

For timestamp `t` inside a completed cycle:

```text
realized_phase = (t - start_ts) / (end_ts - start_ts)
```

This realized phase uses future-known `end_ts` and therefore belongs only in Lane A.

At retained shared wall-clock event timestamps:

```text
signed_phase_delta = RENDER_realized_phase - BTC_realized_phase
absolute_phase_delta = abs(signed_phase_delta)
```

No modulo wrapping is applied.

### Same-event wall-clock lag

When both paired cycles contain the same named event:

```text
event_lag_days = (RENDER_event_ts - BTC_event_ts) / 86400
```

Positive means RENDER occurs later than BTC; negative means RENDER leads BTC.

Events:

```text
start
recognition
ignition
main_pulse
extension
end
```

### Convergence and divergence

For successive comparable checkpoints, retain the continuous change in absolute phase delta:

```text
delta_abs_phase_error = later_abs_phase_delta - earlier_abs_phase_delta
```

Negative values are convergence; positive values are divergence. No post-hoc `close enough` threshold is introduced.

## Lane B: point-in-time predictive validation

Prediction rows are formed only at RENDER:

```text
recognition
ignition
```

Use the checkpoint's confirmation timestamp as `feature_as_of_ts` when available.

At `feature_as_of_ts`, BTC information is allowed only if its own event/state availability timestamp is at or before the RENDER checkpoint.

Forbidden predictor inputs include:

```text
future BTC cycle end/duration
future RENDER cycle end/duration
future BTC/RENDER main-pulse or extension outcome
future reset/phase-shift state
retrospective maximum-overlap pairing requiring a future end
future realized phase progress
holdout-derived relationship labels or thresholds
```

Later RENDER main-pulse confirmation, extension confirmation and event timing are outcomes only.

A relationship feature must beat both randomized controls and simpler no-BTC historical baselines before it can be called predictive evidence.

## Chronological split

Order by RENDER cycle `start_ts`.

```text
discovery = first floor(70%)
holdout = remaining cycles
```

Walk-forward uses expanding history. At each checkpoint, only evidence available at or before that checkpoint may enter a predictor.

Do not tune on holdout.

## Frozen relationship hypotheses

The following labels are hypotheses, not states to force:

```text
PHASE_LOCK
LEADING
LAGGING
CONVERGING
DIVERGING
DETACHED
RELOCK
SHARED_EXTENSION
ROTATION_CANDIDATE
UNRELATED
INSUFFICIENT_EVIDENCE
```

`UNRELATED` is the default evidence outcome when preregistered holdout/null criteria are not met. `INSUFFICIENT_EVIDENCE` is used when sample support is too small to evaluate a relationship.

No label may be assigned from a visually attractive retrospective chart alone.

## Null controls

Freeze 2000 deterministic permutations with seed `418001`.

Controls:

```text
within_split_btc_cycle_pair_permutation
within_split_btc_event_timing_permutation
within_split_btc_extension_label_permutation
```

Permutations stay inside discovery or holdout to preserve split membership and gross chronology/sample composition.

P-values use:

```text
(1 + count(null statistic at least as favorable as observed)) / (2000 + 1)
```

Multiple comparisons use Holm-Bonferroni at alpha `0.05` within each preregistered relationship-test family.

## Hypothesis evidence rules

### PHASE_LOCK

Requires a prespecified continuous phase-delta statistic to be materially tighter than shuffled BTC pairing in discovery and retain the same direction in holdout. Retrospective significance alone is not predictive authority.

### LEADING / LAGGING

Uses signed event-lag distributions. Direction must be consistent across discovery and holdout and outperform shuffled timing/pair controls. Do not derive a lag threshold from holdout.

### CONVERGING / DIVERGING

Uses continuous change in absolute phase delta across retained checkpoints. Evidence must survive holdout and relevant shuffled controls.

### DETACHED / RELOCK

Must be inferred from preregistered sequential changes in continuous phase-distance evidence, not hand-labelled chart segments. If the sample cannot support a stable sequential rule, return `INSUFFICIENT_EVIDENCE` rather than inventing thresholds.

### SHARED_EXTENSION

Test co-occurrence/association of independently observed extension outcomes against within-split shuffled BTC extension labels. Preserve missing extensions and failed/reset cycles.

### ROTATION_CANDIDATE

Test whether prior-confirmed BTC main-pulse/extension events improve prediction of later RENDER recognition/ignition continuation relative to no-BTC historical baselines and shuffled BTC timing. Temporal ordering is required. Same-sample discovery and promotion is forbidden.

## Required outputs

At minimum retain:

```text
input ledger identities and SHA256
source candle provenance
tracker source SHA256
analysis commit SHA
registry source SHA256
split assignment
paired/unpaired cycle rows
wall-clock overlap
start/end lag
same-event lag distributions
retrospective normalized phase deltas
convergence/divergence continuous deltas
extension co-occurrence evidence
checkpoint-level PIT predictor rows
no-BTC baseline metrics
shuffled-null metrics and p-values
Holm-adjusted p-values
per-hypothesis verdict
UNRELATED / INSUFFICIENT_EVIDENCE outcomes
```

Negative findings are permanent evidence and must not be filtered out.

## Explicit non-goals

- modifying #417 to fit BTC/RENDER;
- using the #533 3/6/9/21 family as relationship truth;
- fixed `anchor + 21d` chains;
- account-aware logic;
- `selection_engine` promotion;
- BUY/SELL intent, sizing or execution;
- production DB/schema writes;
- runtime/timer/service activation.

## Promotion boundary

Even a positive #418 result remains research-only. Any production use requires a separate reviewed promotion issue with independent replication, incremental value over simpler market features, deterministic provenance and preserved architecture boundaries.
