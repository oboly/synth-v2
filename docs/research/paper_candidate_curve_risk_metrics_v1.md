# Paper Candidate Curve Risk Metrics V1

## Purpose

`run_paper_candidate_curve_risk_metrics_v1.py` evaluates whether a staged paper candidate has a risk-adjusted or exposure-adjusted advantage versus passive benchmark holding.

It complements `run_paper_candidate_curve_compare_v1.py`.

## Boundary

Allowed:

    read staged paper candidate rows through the curve compare helper
    read research/backtest eval rows through the curve compare helper
    compute strategy-vs-benchmark risk metrics
    print table or JSON output

Forbidden:

    no database writes
    no decision_state writes
    no execution_plan writes
    no live orders
    no account balance mutation

## Metrics

    strategy_return_pct
    strategy_max_drawdown_pct
    benchmark_return_pct
    benchmark_max_drawdown_pct
    benchmark_beaten_count
    benchmark_beaten_symbols
    strategy_rank_by_return
    excess_return_vs_best_benchmark_pct
    time_in_market_fraction
    max_active_notional_eur
    gross_notional_eur
    return_per_gross_notional_pct
    return_per_max_active_notional_pct

## Benchmark handling

Benchmarks are generic.

The tool accepts any comma-separated benchmark list available in the eval table.

Examples:

    BTC,ETH
    XRP,ADA,VET,HOT
    XRP,SUI,SOL,TAO,RENDER

BTC/ETH-specific comparison keys are only emitted when those symbols are included.

## Research-only warning

This tool intentionally uses simulated future returns and forward prices.

It must remain in the research/backtest namespace only.
