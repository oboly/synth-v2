# Breath Curve Research Policy Backtest v1 Findings

Status: research-only  
Scope: market-only / account-agnostic  
Orders: none  
Broker calls: none  
DB writes: none  

## Input

Source:

    breath_curve_partial_to_full_v1

Sample:

    8 assets
    3 anchors
    2 checkpoints
    48 partial-to-full rows

## Policy A: 0.618 early-recognition policy

Configuration:

    checkpoint = 0.618
    min_partial_score = 0.70
    TP1 = 1.000, weight 50%
    TP2 = 1.272, weight 50%
    cost_bps = 20
    require_offset_match = false

Observed result:

    trades = 24
    avg_return_pct = +6.8411
    median_return_pct = +4.6582
    positive_rate_pct = 91.67
    best_return_pct = +27.8754
    worst_return_pct = -2.9005

By symbol:

    TAO    avg +15.1226%, positive 100.00%
    PEPE   avg +9.8261%,  positive 100.00%
    ETH    avg +8.6512%,  positive 100.00%
    FIL    avg +6.4442%,  positive 100.00%
    RENDER avg +6.3596%,  positive 100.00%
    BTC    avg +6.2032%,  positive 100.00%
    HBAR   avg +2.4017%,  positive 100.00%
    XLM    avg -0.2792%,  positive 33.33%

## Policy B: 0.786 extension-confirmation policy

Configuration:

    checkpoint = 0.786
    min_partial_score = 0.70
    TP1 = 1.000, weight 25%
    TP2 = 1.272, weight 75%
    cost_bps = 20
    require_offset_match = false

Observed result:

    trades = 24
    avg_return_pct = +4.3659
    median_return_pct = +3.9665
    positive_rate_pct = 58.33
    best_return_pct = +33.5925
    worst_return_pct = -19.9009

By symbol:

    FIL    avg +11.4426%, positive 66.67%
    TAO    avg +8.4815%,  positive 66.67%
    PEPE   avg +4.9944%,  positive 66.67%
    RENDER avg +3.8090%,  positive 33.33%
    BTC    avg +2.6377%,  positive 66.67%
    XLM    avg +2.1473%,  positive 66.67%
    ETH    avg +0.7891%,  positive 66.67%
    HBAR   avg +0.6255%,  positive 33.33%

## Initial interpretation

The 0.618 checkpoint remains the cleaner early-recognition policy in this small sample.

The 0.786 checkpoint has larger upside tails but weaker reliability and a much worse downside tail.

Current interpretation:

    0.618 = stronger early recognition / primary research entry checkpoint
    0.786 = later extension/overshoot confirmation, not yet reliable as standalone

## Caveats

This is not a live strategy.

The sample is small and label-based:

    no random anchor baseline
    no buy-and-hold baseline
    no regime filter
    no volume filter
    no liquidity/spread model
    no path-aware stop logic
    no slippage model beyond simple cost_bps

## Next validation targets

Required before any downstream use:

    random-anchor baseline
    buy-and-hold baseline
    regime split
    BTC/ETH phase-lock context
    relative strength vs BTC
    volume confirmation
    liquidity/spread guard
    4h path-aware simulation
