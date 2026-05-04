# Market Structure Progress

Status: active status note  
Scope: Synth v2.5 market-structure / zone-fib validation  
Live trading permission: NOT_GRANTED

---

## Current conclusion

The current replay/eval chain is complete and clean enough for research validation.

The strongest recent structural signal is not coming from generic selection labels or paper-candidate filters.

The strongest recent structural signal is coming from:

    execution_zone_context
        -> zone touch
        -> conservative forward return after touch

Zone/Fib execution context shows preliminary edge, especially when:

    profile_regime_label = TREND_UP
    and the expected entry zone is touched after the context candle

This is a research result only.

It is not a live rule.

It is not a paper-trading rule yet.

---

## Replay/eval status

Replay/eval horizon v2 was refreshed successfully.

Observed eval table status:

| Metric | Value |
|---|---:|
| rows_total | 237228 |
| distinct_replay_rows | 237228 |
| duplicate_rows | 0 |
| snapshots | 13107 |
| first_ts | 2021-01-01 01:00:00 |
| last_ts | 2026-05-01 00:00:00 |

Current interpretation:

- replay/eval data is usable for research diagnostics
- no duplicate replay rows were observed
- paper candidate staging should not proceed from generic selection context alone
- 2026 selection contexts are weak overall

---

## Paper candidate status

Paper candidate staging is currently paused.

Reason:

2026 selection/policy contexts do not show enough current edge.

Rejected for now:

| Candidate | Status | Reason |
|---|---|---|
| tactical_range_v1 | not staged | recent 2026 performance weak |
| swing_pullback_v5_legacy_probe | not staged | weak/negative diagnostics |
| NO_TRADE experimental contexts | not staged | not a trade signal by definition |

Important rule:

    NO_TRADE may be analyzed as a regime/context observation.
    NO_TRADE must not be converted into a trade policy.

---

## Zone/Fib data status

Current useful tables/views:

| Object | DB | Type | Status |
|---|---|---|---|
| zone_observation_v2 | synth | table | current zone observation table |
| fib_observation_v2 | synth | table | current fib observation table |
| fib_observation | synth | view | compatibility view over fib_observation_v2 |
| execution_zone_context | synth | table | current execution-zone context table |
| v_execution_zone_forward_4h | synth | view | forward 4h close return from context |
| v_execution_zone_touch_forward_4h | synth | view | zone-touch aware forward view |
| v_execution_zone_touch_with_volatility | synth | view | touch view enriched with volatility bucket |
| strategy_signal_context | synth | table | older/parallel context table; currently stale for this lane |

Observed issue:

    zone_observation does not exist as a compatibility view.
    fib_observation does exist as a compatibility view.

This matters because some older market_structure code still references:

    zone_observation
    fib_observation

The fib path may work through the compatibility view.

The zone path may break or silently drift unless adapted to v2 naming.

---

## Conservative Zone/Fib touch retest

A conservative read-only retest was run on 2026-04 4h data.

Rules used:

    future_start = open_ts_utc > asof_ts_utc
    future_order = ORDER BY open_ts_utc ASC
    return = close of candle after first future touch vs touch reference
    no current-candle leakage

Input:

| Field | Value |
|---|---|
| venue | bitvavo |
| interval | 4h |
| from_ts | 2026-04-01 00:00:00 |
| to_ts | 2026-05-01 00:00:00 |
| context_rows | 317 |
| evaluated_rows | 317 |

Result by regime:

| Regime | Rows | Touched | Touch rate | Avg bonus | Avg return after touch | Winrate after touch |
|---|---:|---:|---:|---:|---:|---:|
| TREND_UP | 141 | 92 | 0.652482 | 0.043272 | 0.007318 | 0.728261 |
| TREND_DOWN | 123 | 79 | 0.642276 | 0.022750 | 0.003232 | 0.594937 |
| RANGE | 51 | 45 | 0.882353 | 0.144052 | -0.000569 | 0.622222 |
| UNKNOWN | 2 | 2 | 1.000000 | 0.000000 | -0.019297 | 0.000000 |

Interpretation:

- TREND_UP + touched zone is the strongest preliminary signal.
- TREND_DOWN + touched zone is mildly positive, possibly bounce/mean-reversion behavior.
- RANGE has high touch rate but weak/negative average return after touch.
- LOW volatility should be treated cautiously.
- MID/HIGH volatility look more promising than LOW volatility.

---

## Asset-level hints from conservative retest

The sample size is small.

Most symbols had only around 8 context rows in this specific test.

Therefore these are hints, not conclusions.

Preliminary stronger hints:

| Symbol | Comment |
|---|---|
| BTC | positive after touch in sample |
| HBAR | positive after touch in sample |
| VET | positive after touch in sample |
| PEPE | positive after touch in sample |
| SOL | positive after touch in sample |
| TAO | positive after touch in sample |
| HOT | positive after touch in sample |
| RENDER | positive after touch in sample |
| FIL | positive after touch in sample |

Preliminary weak or suspicious hints:

| Symbol | Comment |
|---|---|
| XPL | weak despite high touch count |
| CRV | weak |
| FET | weak |
| RLC | weak |
| QNT | weak |
| HYPE | weak average despite decent winrate |
| ALGO | weak average despite high touch rate |

Do not promote asset-level rules from this sample.

---

## Runner status

Current useful research runner:

    src/research/run_zone_fib_overlay_eval_v1.py

Current status:

    useful probe
    not canonical yet

Reasons it is not canonical yet:

- it includes the current context candle in future lookup
- it lacks explicit ORDER BY in future candle lookup
- it computes return from zone mid to final candle, not from true touch reference
- it opens a new DB connection per row
- it reports useful high-level summaries, but not yet enough diagnostic dimensions

Required before canonical status:

1. remove current-candle leakage
2. add ORDER BY open_ts_utc ASC
3. compute touch-aware returns explicitly
4. use one DB connection per run
5. include regime / touch / volatility / symbol diagnostics
6. keep the runner read-only
7. document assumptions in the runner header

---

## Legacy / suspect paths

Do not treat the following as canonical until reviewed and adapted:

    src/market_structure/context_builder.py
    src/market_structure/run_market_structure_skeleton.py

Reason:

They reference old names such as:

    zone_observation
    fib_observation

Current real tables are:

    zone_observation_v2
    fib_observation_v2

The market_structure skeleton also writes to operational context tables, so it must not be run casually during research diagnostics.

---

## Current canonical research direction

Preferred research path:

    zone_observation_v2
        -> fib_observation_v2
        -> execution_zone_context
        -> v_execution_zone_touch_forward_4h
        -> leak-free conservative zone/fib touch evaluation

Current research hypothesis:

    Zone touch after context, especially in TREND_UP regime, may provide better entry-quality information than selection_state alone.

This should be tested across:

- 2026-03
- 2026-04
- broader 2021-2026 windows
- 4h first
- later 1h and 1d
- volatility buckets
- asset profile classes
- market regimes
- touched vs not touched
- touch timing
- adverse excursion after touch

---

## Architecture boundaries

Zone/Fib validation belongs in research/evaluation.

It must not write to:

- decision_state
- execution_plan
- orders
- account
- balance
- positions
- live executor state

It may read from:

- obs_market_candle
- feat_candle
- signal_engine_state
- execution_zone_context
- zone/fib observation tables
- replay/eval tables

Future promotion path:

    research/eval result
        -> documented invariant
        -> replay validation
        -> paper-candidate contract
        -> decision gate preview
        -> execution planner preview
        -> paper/live only after explicit permission

---

## Immediate next steps

1. Refactor `src/research/run_zone_fib_overlay_eval_v1.py` into a leak-free read-only evaluator.
2. Preserve the current simple runner behavior only if still useful as a probe.
3. Run the conservative logic across 2026-03 and 2026-04.
4. Compare:
   - TREND_UP touched
   - TREND_DOWN touched
   - RANGE touched
   - MID/HIGH/LOW volatility buckets
5. Only after that decide whether a zone/fib paper-candidate policy is worth designing.

Current recommendation:

    Zone/Fib touch evaluation should become the next core strategy-validation lane.
    Paper staging remains paused until the leak-free evaluator confirms broader edge.
