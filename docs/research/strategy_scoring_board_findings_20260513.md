# Strategy Scoring Board Findings — 2026-05-13

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Document the first research-only strategy scoring board for Breath Curve composite candidates.

This board converts validated research outputs into explicit, deterministic strategy research scores.

It does not create live or paper strategy permissions.

## Source

Runner:

    python -m src.research.run_strategy_scoring_board_v1

Input:

    data/research/breath_curve_broader_history_v1/breath_curve_broader_history_v1_20260513T173451Z/aggregate_comparison_summary.csv

Run:

    python -m src.research.run_strategy_scoring_board_v1 \
      --output table

Boundary:

    db_writes = 0
    broker_calls = 0
    broker_writes = 0
    order_submission = 0
    selection_engine = none
    decision_gate = none
    execution_planner = none
    executor = none

## Board result

| strategy | status | score | real eligible | random eligible | edge to 1.000 | real worst | random worst | blockers |
|---|---|---:|---:|---:|---:|---:|---:|---|
| breath_curve.minus8_core_symbols.v1 | VALIDATION_CANDIDATE | 61.93 | 13 | 59 | 6.9376 | 2.5578 | 0.8000 | NEEDS_NON_OVERLAPPING_VALIDATION, REAL_ELIGIBLE_LT_20 |
| breath_curve.minus8_core_btc_eth_bear.v1 | VALIDATION_CANDIDATE | 61.60 | 13 | 51 | 7.0251 | 2.5578 | 0.8000 | NEEDS_NON_OVERLAPPING_VALIDATION, REAL_ELIGIBLE_LT_20 |
| breath_curve.early_band_core_bear_or_volume.v1 | VALIDATION_CANDIDATE | 60.01 | 15 | 149 | 7.5752 | 2.5578 | -4.1306 | NEEDS_NON_OVERLAPPING_VALIDATION, REAL_ELIGIBLE_LT_20 |
| breath_curve.minus8_volume_expansion.v1 | RESEARCH_ONLY | 52.28 | 8 | 29 | 10.5866 | 2.5578 | 1.9253 | NEEDS_NON_OVERLAPPING_VALIDATION, REAL_ELIGIBLE_LT_20, RANDOM_ELIGIBLE_LT_50 |
| breath_curve.minus8_core_volume_expansion.v1 | RESEARCH_ONLY | 50.20 | 7 | 12 | 11.7508 | 2.5578 | 1.9253 | NEEDS_NON_OVERLAPPING_VALIDATION, REAL_ELIGIBLE_LT_20, RANDOM_ELIGIBLE_LT_50 |
| breath_curve.minus8_all.v1 | RESEARCH_ONLY | 49.39 | 24 | 142 | 2.4034 | 2.2444 | 0.8000 | NEEDS_NON_OVERLAPPING_VALIDATION |

## Ranking interpretation

### Primary validation candidate

    breath_curve.minus8_core_symbols.v1

Meaning:

    0.618 selected -8
    + symbol in [BTC, ETH, FIL, TAO]
    -> early pulse-to-1.000 research candidate

This is the cleanest balanced candidate.

It remains blocked from paper because:

    cohorts overlap
    real eligible sample count is below 20

### Context-confirming candidate

    breath_curve.minus8_core_btc_eth_bear.v1

This confirms that the current -8 pulse behaves more like a bearish-context rebound / early rotation pulse than a bull-continuation setup.

It scores slightly below the primary candidate because it overlaps heavily with the same real sample set.

### Recall candidate

    breath_curve.early_band_core_bear_or_volume.v1

This remains interesting, but it includes selected -7.

Because selected -7 was previously demoted as a standalone candidate, this strategy receives a structural cleanliness penalty.

It should not outrank the clean selected -8 candidate.

### Precision candidates

    breath_curve.minus8_volume_expansion.v1
    breath_curve.minus8_core_volume_expansion.v1

These have strong edge but thin sample counts.

They remain RESEARCH_ONLY until broader / non-overlapping validation increases sample size.

## Scoring correction

A structural cleanliness penalty was added.

Reason:

    raw score over-rewarded the recall variant
    recall variant includes selected -7
    selected -7 was demoted as standalone
    clean selected -8 candidate should remain primary unless larger validation proves otherwise

Current structural penalties:

    minus8_core_symbols: 0
    minus8_core_btc_eth_bear: small context-duplication penalty
    early_band_core_bear_or_volume: larger recall / demoted-minus7 penalty
    minus8_all: baseline looseness penalty

## Current promotion state

No candidate is PAPER_CANDIDATE.

Current highest allowed status:

    VALIDATION_CANDIDATE

Reason:

    non-overlapping validation is still missing
    sample count remains below paper threshold for the strongest clean candidate

## Required next gate

Next step:

    non-overlapping / older-history validation

Goal:

    remove overlapping-cohort blocker
    increase real eligible sample size
    test older regimes
    verify whether minus8_core_symbols.v1 remains primary

Candidate paper threshold:

    real eligible >= 20
    random eligible >= 50
    non-overlapping validation complete
    positive edge to 1.000
    positive real worst to 1.000
    no leakage blockers

## Architecture boundary

These findings are not strategy rules.

Forbidden downstream use:

    selection_engine modifier
    decision_gate rule
    execution_planner instruction
    executor/order logic
    live or paper execution trigger

Correct path:

    research validation
    -> strategy scoring board
    -> non-overlapping / older-history validation
    -> optional paper-candidate contract
    -> decision_gate permission layer
    -> execution_planner
    -> paper executor
    -> live only after hard safety gates
