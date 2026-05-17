# Watchlist Feature / Signal Status V1

## Purpose

Document the market-only feature and signal status for the APT, KITE, and SXT watchlist assets after candle backfill.

This is a research/status note only. It does not promote any asset to trading, portfolio, runtime, selection, advice, decision, execution, broker, or order paths.

## Boundary

APT, KITE, and SXT are enabled for market-data / analysis ingestion only:

```text
is_enabled=1
is_tradeable=0
is_portfolio=0
```

This means market-data, feature, signal, and research inspection are allowed. It does not mean runtime permission.

## Feature / signal backfill status

Candles were fetched for all three symbols on:

```text
1h
4h
1d
```

`feat_candle` was generated for APT, KITE, and SXT on all three intervals.

`signal_engine_state` was generated where snapshot alignment allowed it.

## Latest observed signal state

### APT

| Interval | Signal timestamp UTC | Trend | Phase | Relative | Setup | Risk | Confidence | Note |
|---|---:|---|---|---|---|---|---:|---|
| 1d | 2026-05-15 00:00 | TREND_UP_STRONG | PHASE_EXPANSION_COHERENT | RELSTR_LEADING | SETUP_WATCH_ONLY | RISK_OK | 0.633750 | Higher-timeframe strength present. |
| 1h | 2026-05-16 23:00 | TREND_DOWN_STRONG | PHASE_RESET | RELSTR_LAGGING | SETUP_WATCH_ONLY | RISK_CONFLICTING_SIGNALS | 0.173940 | Lower-timeframe reset / lagging. |
| 4h | 2026-05-16 16:00 | TREND_DOWN_STRONG | PHASE_RESET | RELSTR_LAGGING | SETUP_WATCH_ONLY | RISK_CONFLICTING_SIGNALS | 0.173940 | Lower-timeframe reset / lagging. |

Interpretation:

APT has a constructive daily read but weak/reset lower-timeframe reads in this snapshot. Treat as research-watchlist context only.

### KITE

| Interval | Signal timestamp UTC | Trend | Phase | Rotation | Relative | Setup | Risk | Confidence | Reason | Note |
|---|---:|---|---|---|---|---|---|---:|---|---|
| 1d | 2026-05-15 00:00 | TREND_UP_STRONG | PHASE_EXPANSION_COHERENT | ROTATION_READY | RELSTR_LEADING | SETUP_ARMED | RISK_OK | 0.943750 | ROTATION_TRIGGER_ACTIVE | Strongest current watchlist read. |
| 1h | 2026-05-16 23:00 | TREND_UP_WEAK | PHASE_INTEGRATION | ROTATION_NONE | RELSTR_IMPROVING | SETUP_WATCH_ONLY | RISK_CONFLICTING_SIGNALS | 0.421170 | NEUTRAL | Short-timeframe integration with risk conflict. |
| 4h | 2026-05-16 16:00 | TREND_UP_STRONG | PHASE_EXPANSION_COHERENT | ROTATION_NONE | RELSTR_LEADING | SETUP_WATCH_ONLY | RISK_OK | 0.633750 | NEUTRAL | Strong context, not a runtime signal. |

Interpretation:

KITE is the strongest current watchlist read from these signals, especially on the daily interval. It still carries low-liquidity / sparse-candle caution and remains non-tradeable and non-portfolio.

### SXT

| Interval | Signal timestamp UTC | Trend | Phase | Relative | Setup | Risk | Confidence | Note |
|---|---:|---|---|---|---|---|---:|---|
| 1d | 2026-05-15 00:00 | TREND_DOWN_STRONG | PHASE_RESET | RELSTR_LAGGING | SETUP_WATCH_ONLY | RISK_OK | 0.308800 | Reset / lagging. |
| 4h | 2026-05-16 16:00 | TREND_DOWN_STRONG | PHASE_RESET | RELSTR_LAGGING | SETUP_WATCH_ONLY | RISK_OK | 0.308800 | Reset / lagging. |
| 1h | not available | not available | not available | not available | not available | not available | not available | Missing due to sparse candle snapshot alignment. |

Interpretation:

SXT remains reset/lagging on available daily and 4h signal rows. The missing 1h signal is explained by sparse exchange candle behavior and snapshot alignment, not by a failed feature backfill.

## Sparse candle diagnostics

Sparse candle diagnostics were run for APT, KITE, and SXT on 1h, 4h, and 1d.

### 1h

| Symbol | Classification | Coverage | Missing candles | Gap events | Median quote volume | Reason |
|---|---|---:|---:|---:|---:|---|
| SXT | ILLIQUID_MARKET | 0.870833 | 93 | 66 | 304.479589 | Sparse coverage / frequent gaps consistent with weak market activity. |
| KITE | NO_TRADE_GAP | 0.954167 | 33 | 23 | 3877.650497 | Isolated missing candles likely caused by no trades in those intervals. |
| APT | NO_TRADE_GAP | 0.963889 | 26 | 19 | 3406.690815 | Isolated missing candles likely caused by no trades in those intervals. |

### 4h

| Symbol | Classification | Coverage | Missing candles | Gap events | Median quote volume | Reason |
|---|---|---:|---:|---:|---:|---|
| SXT | NO_TRADE_GAP | 0.998148 | 1 | 1 | 3074.287097 | Isolated missing candles likely caused by no trades in those intervals. |
| APT | HEALTHY | 1.000000 | 0 | 0 | 26604.510103 | Continuous candles in diagnostic window. |
| KITE | HEALTHY | 1.000000 | 0 | 0 | 79210.446930 | Continuous candles in diagnostic window. |

### 1d

| Symbol | Classification | Coverage | Missing candles | Gap events | Median quote volume | Reason |
|---|---|---:|---:|---:|---:|---|
| KITE | SHORT_HISTORY | 0.493151 | 0 | 0 | 192211.847070 | Limited observed history inside diagnostic window without internal gaps. |
| SXT | DATA_GAP | 0.945205 | 0 | 0 | 34876.836138 | Missing candles despite meaningful observed quote volume. |
| APT | HEALTHY | 1.000000 | 0 | 0 | 164638.764378 | Continuous candles in diagnostic window. |

## SXT 1h snapshot-alignment note

The signal runner selected the global 1h snapshot:

```text
2026-05-16 23:00 UTC
```

SXT had 1h `feat_candle` rows at:

```text
2026-05-17 00:00 UTC
2026-05-16 22:00 UTC
2026-05-16 21:00 UTC
2026-05-16 20:00 UTC
```

It did not have a `feat_candle` row at the selected global snapshot `2026-05-16 23:00 UTC`.

Direct public Bitvavo inspection showed SXT-EUR 1h candles for open timestamps:

```text
2026-05-16 20:00 UTC
2026-05-16 21:00 UTC
2026-05-16 23:00 UTC
```

and no candle for:

```text
2026-05-16 22:00 UTC
```

That missing exchange candle corresponds to the missing local close timestamp needed by the global signal snapshot. This is a sparse / no-trade exchange-candle alignment issue, not an interrupted backfill.

## Do not materialize fake signals

Do not manually insert or fake an SXT 1h signal row.

If sparse/no-trade candles are ever materialized later, use a separate reviewed ETL policy with explicit source/quality marking such as:

```text
SYNTHETIC_NO_TRADE_GAP
OHLC = previous close
volume_base = 0
volume_quote_eur = 0
```

Without explicit source/quality marking, synthetic candles should not be written into `obs_market_candle`.

## Current watchlist interpretation

```text
KITE = strongest current watchlist read, low-liquidity / sparse caution, no runtime promotion
APT  = daily strength with lower-timeframe reset / lagging, no runtime promotion
SXT  = reset / lagging and sparse-sensitive, no runtime promotion
```

## Next possible follow-up

Optional, separate lane only:

```text
sparse candle materialization policy v1
```

or:

```text
signal runner snapshot fallback review
```

Both are research/data-infrastructure questions, not strategy or execution work.

## Safety markers

```text
broker_calls=0
broker_writes=0
order_submission=0
live_orders=0
selection_engine_changes=0
advice_engine_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
runtime_promotion=0
```
