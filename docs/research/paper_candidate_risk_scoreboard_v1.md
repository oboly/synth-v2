# Paper Candidate Risk Scoreboard V1

## Purpose

`run_paper_candidate_risk_scoreboard_v1.py` compares staged paper-candidate batches using return, drawdown, benchmark excess return, and capital-efficiency metrics.

It is the compact promotion view for multiple staged batches.

## Boundary

Allowed:

    read staged paper candidate batches
    reuse read-only curve risk metrics
    compare batches on return, drawdown, exposure, and benchmark excess return
    print table or JSON output

Forbidden:

    no database writes
    no decision_state writes
    no execution_plan writes
    no live orders
    no account balance mutation

## Risk states

    REJECT_RETURN
    REJECT_DRAWDOWN
    WATCH_LOW_EFFICIENCY
    LOW_EXPOSURE_ALPHA_CANDIDATE
    STRONG_BEATS_BENCHMARKS

## Benchmark handling

Benchmarks are generic, not hardcoded to BTC/ETH.

Useful benchmark groups:

    BTC,ETH
    XRP,ADA,VET,HOT
    XRP,SUI,SOL,TAO,RENDER

## Example

    python -m src.research.run_paper_candidate_risk_scoreboard_v1 \
      --database synth_bt \
      --policy-name swing_pullback_recovery_v5_24h_tactical \
      --signal-status PROMOTION_CANDIDATE \
      --batch-id-values arena_v2_24h_tactical_2021,arena_v2_24h_tactical_2026 \
      --account-equity-eur 1000 \
      --target-fraction 0.03300000 \
      --hold-hours 24 \
      --benchmark-symbols XRP,ADA,VET,HOT \
      --output table

## Research-only warning

This tool consumes research/backtest paper-candidate outputs.

It must remain in the research/backtest namespace only.
