# Multi-Horizon Rotation Replay v1

Issue: #593
Status: research-only replay implementation
Depends on:
- `docs/research/multi_horizon_rotation_preregistration_v1.md`
- `docs/research/multi_horizon_rotation_candidate_definition_v1.md`
- `docs/architecture/multi_horizon_signal_contract_v1.md`

## Canonical input resolution

The candidate-definition volume gate is resolved from the canonical Bitvavo candle writer implementation.

Bitvavo candle payload position `item[5]` is parsed as the candle's base-asset volume. The ETL validates it as non-negative and persists it to:

```text
obs_market_candle.volume_base
```

The same writer also persists:

```text
volume_quote_eur = volume_base * close_price
```

`volume_quote_eur` is therefore derived and is not used by C1/C2/C3.

Frozen replay input is:

```text
obs_market_candle
venue = requested venue
interval_code = 15m
close_ts_utc
close_price
volume_base
```

No reporting-layer value, current snapshot, synthetic volume, account state, or broker/private source is permitted.

## Engine

`src/research/multi_horizon_rotation_replay_v1.py` implements the frozen C1/C2/C3 candidate family.

Key fail-closed rules:

```text
asof_ts exactly on 15m close grid
all W0..W8 boundaries exactly on grid
exact start boundary close required
exact end boundary close required
all internal 15m closes required
no stale <= boundary fallback
no interpolation
no future candle usage
minimum same-venue eligible cohort = 20
all three normalized components required
```

A missing/gapped asset is excluded from the eligible cross-sectional cohort for that as-of/candidate and receives `INSUFFICIENT_DATA`.

## Read-only runner

`src/research/run_multi_horizon_rotation_replay_v1.py` evaluates one explicit historical `--asof` without inspecting future outcomes.

It selects canonical 15m candles from `obs_market_candle` over the maximum frozen lookback and reconstructs the cohort from assets that actually have candle data in that historical window. It does not filter historical observations by today's `asset.is_enabled` state.

The runner:

```text
writes no database state
submits no orders
uses no account state
changes no selection_engine production state
changes no decision_gate state
changes no execution_planner state
```

This slice does not inspect validation/final-holdout performance and does not change candidate formulas or weights.

## Next validation slice

Still separate:

1. freeze chronological discovery / validation / final-holdout boundaries;
2. attach B0 Rotation Pressure V1 point-in-time observations;
3. calculate B1 comparable-horizon price-only baseline;
4. attach B2 only where canonical replay-safe RSI/momentum history exists;
5. measure preregistered coverage, correlation, lead/lag, persistence, chop, forward response, effect size and uncertainty;
6. do not inspect final holdout until model-selection rules and validation decisions are frozen.
