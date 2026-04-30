# Paper Candidate Promotion Criteria V1

## Purpose

Define when a research-only paper candidate may move from diagnostic preview into structured paper simulation.

This does not grant live execution permission.

## Boundary

Allowed:

    classify research paper candidates
    compare staged batches across regimes
    use simulated research/backtest returns
    use benchmark and exposure diagnostics

Forbidden:

    no live trading approval
    no decision_state writes
    no execution_plan writes
    no account balance mutation
    no future-return fields outside research/backtest namespace

## Candidate states

### LOW_EXPOSURE_ALPHA_CANDIDATE

A candidate may hold this state when:

    return is positive
    max drawdown is controlled
    capital exposure is low
    return per max active notional is strong
    benchmark underperformance is explainable by lower exposure or lower drawdown

This state means:

    useful tactical sleeve candidate
    not a passive benchmark replacement
    not live approved

### PAPER_SIMULATION_READY

A candidate may be promoted to structured paper simulation when all are true:

    tested on at least 2 distinct market windows or regimes
    total simulated return > 0
    strategy max drawdown >= -5%
    return_per_max_active_notional_pct >= 10%
    return_per_gross_notional_pct > 0
    ledger return mismatch rows = 0
    exposure capacity state = PASS
    no boundary leakage detected

And at least one is true:

    beats average benchmark return for the selected peer group
    beats most benchmarks in a weak/sideways market
    materially reduces drawdown versus benchmark group
    shows strong capital efficiency despite lower absolute return

### REJECT_OR_REWORK

A candidate should be rejected or reworked when any are true:

    negative total simulated return
    max drawdown < -5%
    return_per_max_active_notional_pct < 10%
    exposure capacity fails
    future-return fields leak outside research/backtest namespace
    results only work in one narrow historical window

## Current tactical 24h candidate assessment

Candidate:

    policy_name: swing_pullback_recovery_v5_24h_tactical
    policy_version: arena_v2_bridge_v1
    sleeve: TACTICAL_PULSE
    horizon: 24h

Current state:

    LOW_EXPOSURE_ALPHA_CANDIDATE

Reason:

    2021 did not beat passive alt-beta benchmarks in absolute return.
    2026 beat 4 of 5 selected alt-beta benchmarks.
    Drawdown stayed very low in both windows.
    Capital efficiency remained strong.
    Live execution permission remains NOT_GRANTED.

Next required step:

    Add more market windows before promotion to PAPER_SIMULATION_READY.
