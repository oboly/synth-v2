# Fib Leg Pair Multiplier Research V1

## 1. Why This Document Exists

This document resets the fib research direction for Synth v2 after reviewing
Synth v1.

Synth v1 did useful fib backtest work, but it was mainly a
strategy/trade-oriented workbench with fixed fib assumptions and mostly ASCII
dashboard output. That history is useful as research prior. It is not the v2
starting point.

The v2 starting point is simpler:

```text
Do not choose fib targets up front.
Measure what the market actually did as a multiplier.
```

The first research question is not:

```text
Which target should we use?
```

It is:

```text
What realized_multiplier values actually occur?
```

## 2. What Synth V1 Taught Us

Synth v1 produced useful prior research.

Relevant lessons:

- v1 used rolling swing low/high as a simple anchor baseline
- v1 used fixed fib levels, retraces, and extensions
- v1 backtested strategy/trades, not pure multiplier observations
- v1 compared MTF versus no-MTF variants
- v1 used ADX adaptive regime selection
- v1 explored support/resistance confluence ideas
- v1 produced trade and metrics outputs that are still useful as prior evidence

The distinction needs to stay explicit:

- v1 = strategy/backtest workbench
- v2 = measurement/research engine first

V1 history helps define hypotheses. It should not define the base v2
observation model.

## 3. Why V2 Does Not Start With Fixed Fib Targets

If the measurement step starts by assuming preferred levels such as `1.272`,
`1.618`, or `2.618`, then the research is already biased toward those levels.

That is the wrong order for v2.

The correct order is:

1. observe leg pairs
2. measure realized multipliers
3. plot the distributions
4. inspect whether any values cluster
5. compare those clusters afterward against fibo values and other numeric
   families

This keeps the measurement step neutral.

V2 should not force fibo levels into the observation model before the data shows
that they matter.

## 4. Leg-Pair Measurement Model

The core observation unit is a leg pair.

### Leg 1

- `leg1_start_ts_utc`
- `leg1_start_price`
- `leg1_finish_ts_utc`
- `leg1_finish_price`

### Leg 2

- `leg2_start_ts_utc`
- `leg2_start_price`
- `leg2_finish_ts_utc`
- `leg2_finish_price`

### Derived On The Fly

- `leg1_move_abs = abs(leg1_finish_price - leg1_start_price)`
- `leg2_move_abs = abs(leg2_finish_price - leg2_start_price)`
- `realized_multiplier = leg2_move_abs / leg1_move_abs`
- `leg1_direction`
- `leg2_direction`
- `same_direction`
- `opposite_direction`
- `leg1_duration_candles`
- `leg2_duration_candles`

This is enough for the base research model.

The measurement unit is the pair of raw legs plus point-in-time context. The
multiplier is derived from those raw points when queried.

## 5. Raw Fields Versus Derived Fields

The base observation layer should store raw leg points and point-in-time context
only.

Base observation content:

- symbol
- interval
- raw leg timestamps
- raw leg prices
- context fields that were valid at observation time

Derived fields should be computed on the fly unless a later performance cache is
needed.

Important rules:

- do not store simple derived values as source truth unless later needed for a
  performance cache
- do not store `anchor_move_abs`
- do not store `highest_multiplier` in the base observation table
- do not predefine `target_t1`, `target_t2`, or `target_extension`
- do not force fibo levels into the measurement step

Suggested future tables, documentation only:

### `fib_leg_pair_observation_v1`

Stores raw leg points and context only.

### `fib_leg_pair_multiplier_result_v1`

Optional derived/cache output only if repeated multiplier queries become
expensive.

The base observation table is source truth. Any later result/cache table is
derived convenience only.

## 6. What Gets Plotted Later

Later analysis should plot:

- `realized_multiplier` distributions
- distributions by symbol
- distributions by interval
- distributions by regime/context
- distributions by leg direction relation

Later analysis may also inspect:

- duration versus multiplier relationships
- move-size versus multiplier relationships

Only after those plots exist should the research compare clusters against:

- fibo values
- natural constants
- primes
- whole numbers
- half numbers

Do not assume fibo values are important before the data shows clustering.

## 7. Context Grouping Ideas

Grouping should happen after raw observations exist.

Useful grouping axes include:

- symbol
- interval
- regime
- context
- `same_direction` versus `opposite_direction`
- leg1 direction
- leg2 direction
- leg1 duration bucket if later analysis needs it
- leg2 duration bucket if later analysis needs it

These are analysis groupings. They are not targets, trades, or execution
instructions.

## 8. What Is Explicitly Not Included

This document does not include:

- fixed fib targets
- target ladders
- target labels
- target extensions
- strategy rules
- trade entry rules
- trade exit rules
- dashboard advice language
- dashboard modifications
- runner code
- migrations
- table implementation

This document also does not change:

- `canonical_fib_zone_map_v1.`
- `selection_engine`
- `decision_gate`
- `execution_planner`
- `executor`
- broker, account, or order logic

No new fancy names are introduced here.
No new target buckets are introduced here.

## 9. Future Implementation Path

The implementation path should stay narrow:

1. define the raw observation contract for `fib_leg_pair_observation_v1`
2. store raw leg points and point-in-time context only
3. query `realized_multiplier` as a derived value
4. plot multiplier distributions by symbol, interval, regime, and direction
   relation
5. inspect cluster behavior before making any fibo claim
6. add an optional derived/cache result table only if repeated analysis queries
   are too expensive

That keeps v2 aligned with the Synth architecture:

```text
measurement first
-> analysis second
-> hypothesis comparison afterward
```

It also keeps v2 separate from the v1 pattern of embedding fixed target
assumptions into the starting model.
