# BTC ↔ RENDER Breathline relationship study v1.0.1

Issue: #418

Status: pre-analysis amendment. Independent BTC and RENDER #417 ledgers have been frozen, but no BTC↔RENDER relationship statistic has been inspected when this amendment is committed.

## Why v1.0.1 exists

Registry v1.0.0 froze the symbols, interval, pairing principle, chronological split, null controls, permutation count, seed, multiple-comparison method, PIT anti-leakage rules and hypothesis names. It did not yet make every hypothesis' exact test statistic, minimum sample support and deterministic verdict rule explicit enough for outcome analysis.

That ambiguity is corrected before the first cross-symbol statistic is computed. This is a methodology completion, not outcome-driven tuning.

## Unchanged from v1.0.0

```text
reference = BTC
alt = RENDER
venue = bitvavo
interval = 4h
discovery_fraction = 0.70
null_permutations = 2000
random_seed = 418001
multiple_comparison_method = holm_bonferroni
alpha = 0.05
```

Unchanged architecture:

```text
research_only=true
market_only=true
account_awareness=0
selection_engine_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_calls=0
broker_writes=0
order_submission=0
production_schema_changes=0
runtime_activation=0
```

The #417 tracker remains unchanged. The independent evidence run already produced 111 BTC cycles and 39 RENDER cycles with exact #417 tracker provenance and `relationship_analysis_performed=false`.

## Frozen minimum support

```text
paired cycles per split             >= 8
event comparisons per split         >= 5
sequence cycles per split           >= 5
binary rows per split               >= 10
positive and negative rows per split >= 3 each
prior RENDER outcomes for PIT baseline >= 8
significant lag events for LEADING/LAGGING >= 2
```

A hypothesis that fails its minimum support returns `INSUFFICIENT_EVIDENCE`. Minimums are not lowered after outcome inspection.

## Exact Lane A statistics

### PHASE_LOCK

At each RENDER `recognition`, `ignition`, `main_pulse` or `extension` timestamp that lies inside both paired completed cycles, compute realized phase for both cycles and retain:

```text
signed_phase_delta = render_phase - btc_phase
absolute_phase_delta = abs(signed_phase_delta)
```

Split statistic:

```text
mean absolute_phase_delta
```

Lower is more phase-locked. Null: within-split BTC cycle-pair permutation.

Support is structural only and requires discovery observed mean below its null median plus holdout observed mean below null median with holdout p < 0.05.

### LEADING / LAGGING

Inferential events:

```text
recognition
ignition
main_pulse
extension
```

Per event:

```text
mean signed same-event lag days
```

Positive means RENDER lags BTC. Negative means RENDER leads BTC. Discovery fixes the candidate sign. Holdout uses a one-sided within-split BTC event-timing permutation in that frozen direction. Holm correction spans the four event tests.

At least two sufficient event tests must survive Holm and all significant events must agree on direction.

### CONVERGING / DIVERGING

For each paired cycle with at least two comparable retained phase checkpoints:

```text
net_abs_phase_delta_change = last_absolute_phase_delta - first_absolute_phase_delta
```

Mean across cycles is the split statistic. Negative favors `CONVERGING`; positive favors `DIVERGING`. Discovery and holdout signs must agree and holdout permutation p must be < 0.05.

### DETACHED / RELOCK

No magnitude threshold is introduced.

`DETACHED` sequence:

```text
at least two consecutive positive changes in absolute phase delta
```

`RELOCK` sequence:

```text
a DETACHED sequence followed later in the same cycle by at least one negative change in absolute phase delta
```

Each sequence rate is tested against within-split BTC pair permutation. Holm correction spans DETACHED and RELOCK.

### SHARED_EXTENSION

Split statistic:

```text
P(RENDER extension | BTC extension) - P(RENDER extension | no BTC extension)
```

Positive is favorable. Null: within-split BTC extension-label permutation. Discovery and holdout differences must both be positive and holdout p < 0.05.

## Exact Lane B statistic

PIT rows exist only at RENDER recognition and ignition confirmation timestamps.

Allowed BTC features:

```text
btc_main_pulse_recency_score = -days since latest BTC main-pulse confirmation available at feature_as_of_ts
btc_extension_recency_score = -days since latest BTC extension confirmation available at feature_as_of_ts
```

Higher means more recent. Missing prior events remain missing; no future BTC cycle end or retrospective maximum-overlap pairing is used.

Outcomes:

```text
RENDER main_pulse_confirmed
RENDER extension_confirmed
```

Each checkpoint × BTC feature × outcome combination uses tie-aware ROC AUC. Holdout null permutes BTC event timing within split. Holm correction spans all 2 × 2 × 2 = 8 holdout tests.

No-BTC baseline:

```text
expanding prior RENDER outcome probability
```

Only prior RENDER cycles whose `outcome_as_of_ts < feature_as_of_ts` may contribute, with at least 8 prior outcomes required. The time-varying prior probability is scored by AUC on the same matched rows.

`ROTATION_CANDIDATE` requires at least one preregistered test with:

```text
discovery AUC > 0.5
holdout AUC > 0.5
holdout BTC AUC > matched no-BTC baseline AUC
Holm-adjusted holdout permutation p < 0.05
```

## Overall verdict

```text
SHARED_EXTENSION or ROTATION_CANDIDATE supported
    -> POSITIVE_RESEARCH_EVIDENCE

only retrospective/structural hypothesis supported
    -> STRUCTURAL_EVIDENCE_ONLY

no supported hypothesis with sufficient testing
    -> UNRELATED

hypothesis lacks frozen minimum support
    -> INSUFFICIENT_EVIDENCE for that hypothesis
```

No result from #418 has production authority. Any later promotion remains a separate reviewed issue with independent replication and incremental-value evidence.
