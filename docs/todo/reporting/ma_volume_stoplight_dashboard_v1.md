# MA + Volume Stoplight Dashboard V1

## GitHub Issue migration

Status: migrated

Operational status/priority is owned by GitHub Issues.

Section ownership:
- feature research, classification design, historical validation -> Issue #310
- dashboard/stoplight rendering -> Issue #315

Unmigrated executable scope:
- none

Status: TODO
Scope: research + reporting only
Priority: P3 / Lane D
Runtime impact: none
Broker access: none
Order authority: none

## Purpose

Add explainable trend and volume indicators to Synth so an operator can see at a glance whether an asset is structurally aligned, recovering, extended, damaged, consolidating, or breaking out with real participation.

The initial focus is on 4H and 1D moving-average context around SMA50, SMA150, and SMA200, combined with existing volume confirmation data.

This is not a buy/sell engine.

## Core principle

A moving average is context, not authority.

Allowed path:

```text
market candles
-> deterministic feature calculation
-> selection_engine market classification
-> read-only dashboard presentation
```

Forbidden path:

```text
price above SMA150
-> BUY
```

or:

```text
price below SMA150
-> SELL
```

The decision_gate remains the account-aware permission layer. The execution_planner owns execution intent only. Executors/agents remain the only order-handling layer.

## Proposed market-only feature set

Per asset and timeframe:

- sma_50
- sma_150
- sma_200
- close_vs_sma_50_pct
- close_vs_sma_150_pct
- close_vs_sma_200_pct
- sma_50_slope_pct
- sma_150_slope_pct
- sma_200_slope_pct
- sma_50_vs_sma_150_pct
- sma_150_vs_sma_200_pct
- bars_above_sma_150
- bars_below_sma_150
- recent_sma150_cross_direction
- recent_sma150_reclaim_state
- trend_extension_pct
- data_freshness_state

Initial timeframes:

- 4H for swing trend, pullbacks, and momentum recovery
- 1D for structural bull/bear context

1H may later be used for entry timing research, but must not define market regime.

## Existing volume inputs to reuse

Synth already has deterministic volume confirmation features based on daily candles:

- volume_ratio
- volume_zscore
- current_volume_quote_eur
- avg_volume_quote_eur
- std_volume_quote_eur

Do not duplicate this logic. Extend or generalize only when validation requires 4H support.

## Proposed trend classifications

- TREND_ALIGNED
- TREND_RECOVERY
- MA_RECLAIM_PENDING
- TREND_EXTENDED
- TREND_DAMAGED
- TREND_UNCERTAIN
- DATA_STALE
- INSUFFICIENT_DATA

Example semantics:

### TREND_ALIGNED

- close above SMA150
- SMA150 slope positive
- preferably SMA50 above SMA150
- multiple consecutive closes above the baseline

### TREND_RECOVERY

- recent reclaim of SMA150
- slope flat-to-positive
- limited confirmation history

### MA_RECLAIM_PENDING

- price near or just above SMA150
- reclaim not yet confirmed by consecutive closes or participation

### TREND_EXTENDED

- price materially above SMA150
- positive trend remains intact
- pullback risk elevated

### TREND_DAMAGED

- price below falling SMA150
- failed reclaim or persistent closes below baseline

## Proposed volume lifecycle classifications

- NORMAL
- CONTRACTING
- DRY_UP
- EXPANSION
- BREAKOUT_CONFIRMED
- BREAKOUT_UNCONFIRMED
- SELLING_PRESSURE
- EXHAUSTION_SPIKE
- DATA_STALE
- INSUFFICIENT_DATA

Low volume must not automatically be negative.

A controlled DRY_UP during consolidation can be constructive when followed by renewed expansion on breakout.

## Stoplight presentation

### 150MA trend light

| Light | Meaning |
|---|---|
| Green | Price above a rising SMA150 with confirmation |
| Yellow | Price near SMA150, trend flat, or recovery still unconfirmed |
| Red | Price below a falling SMA150 or failed reclaim |
| Grey | Stale or insufficient data |

### Volume light

| Light | Meaning |
|---|---|
| Green | Volume expansion confirms the price move |
| Yellow | Normal participation; no confirmation |
| Red | Breakout lacks volume or selling pressure dominates |
| Blue | Controlled volume dry-up during consolidation |
| Grey | Stale or insufficient data |

Color must always be accompanied by a machine-readable label and a human-readable reason.

## Compact dashboard row

Example only:

```text
ENA | 4H trend GREEN | 1D trend YELLOW | volume GREEN | structure BREAKOUT | target room 18%
```

## Expandable explanation panel

Example fields:

```text
4H close vs SMA150:      +6.2%
4H SMA150 slope:         +0.31%
4H candles above:        19
1D trend state:          TREND_RECOVERY
Volume ratio 14d:        1.74
Volume z-score:          1.58
Volume lifecycle:        BREAKOUT_CONFIRMED
Freshness:               FRESH
```

## Composite research patterns

### Healthy breakout

```text
close > resistance
close > SMA150
SMA150 slope > 0
volume_ratio elevated
volume_zscore positive
```

### Constructive pullback

```text
close remains above SMA150
SMA150 rising
pullback volume contracts
recovery candle volume expands
```

### Weak breakout

```text
close > resistance
volume participation weak
SMA150 flat or falling
```

These patterns may affect market-only confidence or ranking only after deterministic validation. They must not directly create permission or execution intent.

## Validation questions

Research must determine:

1. whether SMA150 adds predictive value beyond existing market structure, support/resistance, RSI, Fibonacci room, and rotation pressure;
2. whether 4H or 1D provides more stable signal quality per asset class;
3. whether slope and consecutive-close confirmation reduce whipsaws;
4. whether volume contraction followed by expansion improves breakout quality;
5. whether the feature works across BTC, ETH, majors, mid-caps, and thin altcoins;
6. whether thresholds should be volatility-normalized rather than fixed percentages;
7. whether the stoplight remains stable enough for operator use without excessive color flipping;
8. whether the feature improves selection ranking in non-overlapping historical validation.

## Promotion path

```text
research specification
-> deterministic feature prototype
-> historical validation
-> strategy scoring board
-> optional selection_engine feature
-> read-only dashboard presentation
```

No paper or live execution work is authorized by this TODO.

## Acceptance criteria

- deterministic SMA and slope calculations documented;
- 4H and 1D semantics explicit;
- freshness and insufficient-data handling fail closed;
- every color maps to a stable label and reason code;
- no hidden account state in market classification;
- no broker calls;
- no decision_gate bypass;
- no execution_planner or executor coupling;
- historical validation compares against the existing baseline;
- UI shows both compact status and expandable evidence.

## Non-goals

- automatic buying above SMA150;
- automatic selling below SMA150;
- hardcoded one-size-fits-all stop-losses;
- replacing market structure or Fibonacci maps;
- using reporting colors as execution instructions;
- duplicating existing volume confirmation logic.
