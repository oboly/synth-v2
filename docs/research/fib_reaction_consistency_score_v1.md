## Fib Reaction Consistency Score V1

`fib_reaction_consistency_score_v1` is a research-only summary layer on top of
`multi_horizon_fib_backtest_v1`.

It measures how consistently a `symbol + fib_trading_horizon + interval_code +
interval_role` historically reacts to canonical fib levels.

Safety boundary:

- market-only
- account-agnostic
- DB writes = `0`
- broker calls = `0`
- broker writes = `0`
- order submission = `0`
- decision gate = `none`
- execution planner = `none`
- executor = `none`

It must not be used directly in:

- selection
- advice
- decision
- execution

## Explicit Scope

This runner intentionally exposes:

- `fib_reaction_consistency_score`
- `fib_reaction_consistency_status`

It intentionally does not expose:

- `fib_reaction_consistency_class`
- generic quality or confidence wrappers

Every score component and every weight stays visible in the output rows.

## Input Contract

Default input directory:

```text
data/research/multi_horizon_fib_backtest_v1/
```

Required input files:

- `fib_level_outcomes_v1.csv`
- `manifest_v1.json`

The score is computed from `fib_level_outcomes_v1.csv` because that file keeps
the raw fib-level observation counts needed for transparent recomputation.

## Output Files

Default output directory:

```text
data/research/fib_reaction_consistency_score_v1/
```

Generated outputs:

- `fib_reaction_consistency_rows_v1.csv`
- `fib_reaction_consistency_context_rows_v1.csv`
- `score_component_distribution_v1.csv`
- `manifest_v1.json`

Generated outputs are research artifacts and must not be committed by default.

## Visible Components

Every scored row keeps these visible components:

- `sample_count`
- `touch_rate`
- `reaction_success_rate`
- `fakeout_rate`
- `invalidation_rate`
- `next_extension_hit_rate`
- `regime_stability`
- `breath_stability`

It also keeps:

- each component weight
- requested context
- resolved fallback tier
- resolved context
- requested sample count
- resolved sample count

## Formula

The score is bounded to `0..100`.

Validity gate:

- `fib_reaction_consistency_status = VALID` when `sample_count >= 12`
- `fib_reaction_consistency_status = INSUFFICIENT_SAMPLE` otherwise

Sample count gates validity only. It does not increase the numeric score.

Formula:

```text
fib_reaction_consistency_score =
100 * (
    0.16 * touch_rate
  + 0.34 * reaction_success_rate
  + 0.12 * (1 - fakeout_rate)
  + 0.18 * (1 - invalidation_rate)
  + 0.12 * next_extension_hit_rate
  + 0.05 * regime_stability
  + 0.03 * breath_stability
)
```

Why these weights:

- current broad `profile_stats_v1.csv` inspection showed `sample_count` thin
  below roughly `8..10`, median `16`, p90 `41`
- `reaction_success_rate` is the most direct positive reaction measure, so it
  gets the largest weight
- `invalidation_rate` and `fakeout_rate` are explicit negative consistency
  components, so their complements stay visible and weighted separately
- `touch_rate` and `next_extension_hit_rate` matter, but the current broad data
  shows a very sparse `hit_rate` distribution with median `0`
- regime and breath context coverage are currently dominated by `UNKNOWN`, so
  their weights stay intentionally small and visible

## Stability Components

`regime_stability` and `breath_stability` are not hidden confidence multipliers.
They are explicit score components.

`regime_stability`:

- computed per `symbol + horizon + interval_code + interval_role`
- compares regime-bucket `reaction_success_rate` values against the same base
  row rate
- uses sample-weighted absolute deviation
- normalizes with a fixed max deviation of `0.35`
- falls back to neutral `0.5` when fewer than two valid regime buckets exist

`breath_stability`:

- computed per `symbol + horizon + interval_code + interval_role`
- compares breath-bucket `reaction_success_rate` values against the same base
  row rate
- uses sample-weighted absolute deviation
- normalizes with a fixed max deviation of `0.35`
- falls back to neutral `0.5` when fewer than two valid breath buckets exist

## Context Fallback

Thin context buckets do not disappear silently.

Fallback order:

1. `symbol + horizon + regime + breath`
2. `symbol + horizon + regime`
3. `symbol + horizon`
4. `horizon baseline`

The output row keeps:

- requested context
- resolved context tier
- resolved context used for the score

`UNKNOWN` context remains `UNKNOWN`.

## CLI

```bash
python -m src.research.run_fib_reaction_consistency_score_v1 \
  --input-dir data/research/multi_horizon_fib_backtest_v1 \
  --output-dir data/research/fib_reaction_consistency_score_v1 \
  --write-files \
  --output summary
```

Bounded smoke example:

```bash
python -m src.research.run_fib_reaction_consistency_score_v1 \
  --input-dir /tmp/multi_horizon_fib_backtest_v1_smoke \
  --output-dir /tmp/fib_reaction_consistency_score_v1_smoke \
  --symbols WLD,ONDO,NEAR \
  --horizons SHORT,MEDIUM,LONG \
  --write-files \
  --output summary
```
