# Bullish Breathline Tracker v1

**Status:** RESEARCH_ONLY_IMPLEMENTATION

**Issue:** #417

## Purpose

This v1 tracks one symbol's bullish Breathline continuously from observed market structure. It does not rediscover a fresh line every 21 days and does not create trading authority.

The nominal 21-day period is retained only as a phase-reference prior for expected-node timing and ratio calibration. Cycle boundaries are created from observed, point-in-time-confirmed pivot transitions.

## Frozen v1 rules

Model version:

```text
bullish-breathline-tracker-v1.0.0
```

Bullish recognition sequence:

```text
observed start low
-> first high
-> first low
-> second high / retest
-> higher low recognition
```

The higher low is valid only when it is above the first low and below the second high. The next confirmed high is ignition evidence. A later confirmed high above the second high confirms a main pulse. A later confirmed high above the main-pulse high is extension evidence.

These are descriptive research states, not BUY/SELL rules.

### Recognition ratio grid

Frozen before outcome evaluation:

```text
0.55, 0.58, 0.60, 0.618, 0.64, 0.66, 0.68, 0.70, 0.72
```

### Ignition ratio grid

Frozen before outcome evaluation:

```text
0.72, 0.74, 0.76, 0.786, 0.80, 0.82
```

### Normal phase-offset grid

```text
-9, -7, -5, -3, 0, +3, +5, +7, +9
```

`±10.5` is intentionally excluded from the normal offset grid. `10.5d` is retained only as the future `HALF_PHASE_SPLIT` research concept.

## Point-in-time / no-lookahead contract

Local high/low pivots are not observable at the pivot candle. A pivot becomes available only after its configured right-side confirmation bars exist. The tracker therefore stores both:

```text
pivot_ts
confirmed_at_ts
```

Checkpoint features use confirmed information available at or before the checkpoint's `feature_as_of_ts`. Later main-pulse and extension observations are outcome fields and are never checkpoint predictors.

Ratio selection uses chronological discovery cycles only. Holdout cycles are excluded from candidate selection. Walk-forward evidence repeatedly selects on earlier cycles and evaluates the next cycle.

No best-full offset, later drift label, extension outcome, or future clean/dirty label is an input to checkpoint classification.

## Continuous cycle ledger

The runner writes an append-only JSONL cycle ledger. Cycle identity is deterministic from:

```text
model_version
symbol
observed start timestamp
observed recognition timestamp
```

An identical replay appends nothing. Reusing an existing `cycle_id` with different content is a hard failure rather than an overwrite.

Each record retains at least:

- cycle and previous-cycle identity;
- observed start/end and observed duration;
- current/previous phase offset and drift;
- observed node timestamps/prices;
- expected baseline node timestamps and timing errors;
- recognition/ignition ratio used;
- recognition/ignition/extension-runner state;
- higher-low, main-pulse and extension confirmation;
- checkpoint-time volume snapshots when volume exists;
- reset/phase-shift reason;
- feature and outcome as-of timestamps.

Failures and unclear cycles remain ledger evidence. They are not silently removed.

## Calibration evidence

For each frozen candidate ratio the runner records:

```text
matched_count
continuation_probability
extension_probability
false_extension_rate
mean_mfe_pct
mean_mae_pct
mean_time_to_main_pulse_days
mean_time_to_extension_days
```

The default chronological split uses 70% discovery and 30% holdout. Candidate selection occurs only on discovery evidence. A candidate needs the configured minimum discovery sample before it can be selected.

The runner also emits expanding-window walk-forward rows.

A repository test fixture proves the mechanics on multiple non-21-day observed cycles. That fixture is a regression/control fixture, not market-performance evidence. Real historical RENDER or TAO candles must be supplied to the runner and the resulting `summary.json` + `cycle_ledger.jsonl` reviewed before any claim of empirical predictive value or later promotion.

## Runner

```text
python -m src.research.run_bullish_breathline_tracker_v1 \
  --csv <point-in-time-candle.csv> \
  --symbol RENDER \
  --out-dir data/research/bullish_breathline_tracker_v1/render
```

Accepted timestamp columns include `ts`, `timestamp`, `ts_utc`, `open_time`, and `candle_ts_utc`. OHLC aliases support both compact (`open`, `high`, `low`, `close`) and canonical price names (`open_price`, etc.). Optional volume aliases are `volume`, `volume_base`, and `base_volume`.

Outputs:

```text
cycle_ledger.jsonl     append-only cycle evidence
latest_cycles.json     current replay convenience view
summary.json           frozen config, discovery/holdout calibration, walk-forward evidence
```

## Architecture boundary

```text
research_only=true
account_awareness=0
selection_engine_changes=0
decision_gate=none
execution_planner=none
executor=none
broker_calls=0
broker_writes=0
order_submission=0
```

The implementation performs no production DB mutation, broker call, account read, decision permission, planning, runtime activation, or order submission.

## Promotion boundary

This issue creates research evidence only. No ratio, offset, extension-runner state, or cycle result may become selection, decision, planning, execution, or broker authority without separate reviewed validation and promotion work.
