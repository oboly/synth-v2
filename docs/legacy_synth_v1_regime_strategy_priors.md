# Synth v1 legacy regime/strategy priors

## Status

This document captures confirmed Synth v1 strategy evidence for use as research priors in Synth v2.

It is not a live-trading configuration.

## Core finding

Synth v1 did not only have separate MTF and no-MTF strategies. It also had an ADAPTIVE:<threshold> mechanism.

Confirmed interpretation:

    ADAPTIVE:<threshold>
    = ADX-based regime selector
    + strategy-family selector

Synth v1 rule:

    1h ADX(14) >= threshold  -> TREND -> use no-MTF
    1h ADX(14) <  threshold  -> CHOP  -> use MTF
    NaN ADX                  -> MTF fallback

For Synth v2, this must be split cleanly:

    regime_selector:
      input: market data only
      output: TREND / CHOP / UNKNOWN

    strategy_selector:
      input: asset_id + regime_group
      output: strategy_family

Do not port the old combined ADAPTIVE mechanism directly.

## Confirmed v1 evidence files

    services/adaptive_switch.py
    tools/adaptive_compare.py
    results/strategy_matrix/strategy_matrix_summary.csv
    results/adaptive/adaptive_summary.csv
    configs/strategy_matrix.yaml.A
    configs/strategy_matrix.yaml
    configs/mtf_dual_flow_v1.yaml
    strategies/mtf_filter.py
    results/*trades*.csv

## ADX regime logic

Synth v1 computed ADX(14) on 1h OHLC data using exponential smoothing:

    EWM alpha = 1 / 14

Trade labeling used merge_asof(..., direction="backward") against entry_time.

That is important: it avoids future leakage because the regime value is the latest known ADX at or before trade entry.

## Strategy families confirmed from v1

    FIBO_MTF
    FIBO_NO_MTF
    MTF_DUAL_FLOW_5M_1H
    NO_MTF_RSI_EMA_15M
    SCALPER_5M
    ADAPTIVE_ADX_REGIME_SELECTOR

Important distinction:

    ADAPTIVE is not a strategy family.
    ADAPTIVE is a regime/strategy routing mechanism.

## Minimal v2 model

Keep this simple first:

    asset_id + regime_group -> strategy_family

Do not introduce asset_profile yet as a required runtime concept.

Reason:

    v1 proves asset-specific + regime-specific behavior.
    v1 does not yet prove profile-specific abstraction.

asset_profile can be introduced later if multiple assets show stable shared behavior.

## Initial v2 selector rule shape

Recommended minimal fields:

    asset_id
    regime_group
    strategy_family
    adx_threshold
    confidence
    source
    enabled
    notes

Example research-prior rules:

    LINK-EUR | ANY   | FIBO_NO_MTF | null | HIGH
    XLM-EUR  | ANY   | FIBO_NO_MTF | null | HIGH

    HBAR-EUR | CHOP  | FIBO_MTF    | 30   | HIGH
    HBAR-EUR | TREND | FIBO_NO_MTF | 30   | HIGH

    HOT-EUR  | CHOP  | FIBO_MTF    | 16   | MEDIUM
    HOT-EUR  | TREND | FIBO_NO_MTF | 16   | MEDIUM

    HYPE-EUR | ANY   | FIBO_MTF    | null | MEDIUM

    XRP-EUR  | ANY   | RETEST      | 17   | LOW
    SUI-EUR  | ANY   | DISABLED    | null | LOW
    DEEP-EUR | ANY   | DISABLED    | null | LOW

## Legacy result interpretation

### Strong no-MTF candidates

    LINK-EUR
    XLM-EUR

Reason:

    LINK no-MTF strongly outperformed MTF.
    XLM no-MTF strongly outperformed MTF.
    Adaptive degraded both versus no-MTF base.

### Adaptive candidates

    HBAR-EUR
    HOT-EUR

Reason:

    HBAR adaptive threshold 30 improved meaningfully over base-best.
    HOT adaptive threshold 16 improved meaningfully over base-best.

### MTF / weak adaptive candidate

    HYPE-EUR

Reason:

    MTF strongly beat no-MTF.
    Adaptive uplift was tiny.
    Treat as MTF candidate or retest candidate, not as strong adaptive evidence.

### Disable or retest

    SUI-EUR
    DEEP-EUR
    XRP-EUR

Reason:

    SUI negative across tested variants.
    DEEP low trade count and negative.
    XRP weak/unstable; adaptive improved slightly but still not strong.

## Important v2 corrections

Do not copy v1 fallback behavior blindly.

Old v1 behavior:

    NaN ADX -> MTF

Preferred v2 behavior:

    NaN ADX -> UNKNOWN regime
    UNKNOWN -> disabled unless explicitly configured fallback exists

Missing regime data is a data-quality state, not a market regime.

## Architecture boundary

Correct v2 ownership:

    ADX computation                 -> regime_selector
    TREND / CHOP classification     -> regime_selector
    asset + regime -> strategy      -> strategy_selector
    strategy signal generation      -> strategy module / signal layer
    market-only ranking             -> selection_engine
    balance / positions / sleeves   -> decision_gate
    order intent                    -> execution_planner
    order placement                 -> executor / agents

Do not mix these again.

## Legacy artifacts not to port directly

    configs/strategy_matrix.yaml
    tools/live_step.py
    live_trader.py
    services/strategy_matrix.py

Reason:

    They mix strategy selection, regime selection, routing, risk, runtime, and execution concerns.
    They are useful evidence, not v2 architecture.

## Next extraction target

Build a v2 research dataset from old trades:

    trade CSV
    + strategy_family
    + entry_time
    + ADX at entry
    + regime_group
    + threshold used
    + pnl
    + R

Target table or export concept:

    legacy_v1_trade_regime_label

Purpose:

    Measure performance by:
    asset_id
    + regime_group
    + strategy_family

This is the bridge from:

    "v1 worked"

to:

    "v2 knows when a strategy works"

## Design principle

Use v1 as evidence.

Do not rebuild v1.

Synth v2 should preserve the edge while removing the spaghetti.
