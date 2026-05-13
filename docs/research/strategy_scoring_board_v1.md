# Strategy Scoring Board v1

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Create a first strategy scoring board for research candidates.

This is a research scoring cockpit, not a live strategy controller.

The initial board scores Breath Curve composite candidates using broader-history validation output.

## Input

Default input:

    latest data/research/breath_curve_broader_history_v1/*/aggregate_comparison_summary.csv

The board also reads sibling:

    all_cohort_comparison_rows.csv

when present, to calculate cohort stability.

## Initial strategies

The first board includes:

    breath_curve.minus8_all.v1
    breath_curve.minus8_core_symbols.v1
    breath_curve.minus8_core_volume_expansion.v1
    breath_curve.minus8_core_btc_eth_bear.v1
    breath_curve.minus8_volume_expansion.v1
    breath_curve.early_band_core_bear_or_volume.v1

## Scoring model

The v1 score is deterministic and explicit.

Components:

    edge_score
    positive_score
    worst_case_score
    sample_score
    cohort_stability_score
    selection_quality_score

Penalties:

    overlapping cohorts
    leakage risk
    thin real sample
    thin random sample
    negative real worst-case
    non-positive edge
    structural cleanliness penalty

Structural cleanliness examples:

    baseline candidates get a small penalty because they are less selective
    recall candidates that include demoted -7 get a larger penalty
    context-only variants get a small penalty when they duplicate the primary candidate

## Promotion statuses

Possible statuses:

    RESEARCH_ONLY
    VALIDATION_CANDIDATE
    PAPER_CANDIDATE
    REJECTED
    MISSING_SOURCE

Current default is conservative.

Because the broader-history cohorts overlap, candidates can become VALIDATION_CANDIDATE but should not become PAPER_CANDIDATE unless run with non-overlapping validation.

## Runner

Default:

    python -m src.research.run_strategy_scoring_board_v1 --output table

Explicit input:

    python -m src.research.run_strategy_scoring_board_v1 \
      --input-csv data/research/breath_curve_broader_history_v1/<run>/aggregate_comparison_summary.csv \
      --output table

For non-overlapping validation output:

    python -m src.research.run_strategy_scoring_board_v1 \
      --non-overlapping \
      --output table

## Output

Generated files are written under:

    data/research/strategy_scoring_board_v1/

This path should remain ignored by git.

## Boundary

Allowed:

    research scoring
    market-only validation scoring
    CSV output
    promotion recommendation labels

Forbidden:

    selection_engine modifier
    decision_gate rule
    execution_planner instruction
    executor/order logic
    broker API call
    broker write
    live or paper execution trigger

## Correct path

    research validation
    -> strategy scoring board
    -> non-overlapping / older-history validation
    -> optional paper-candidate contract
    -> decision_gate permission layer
    -> execution_planner
    -> paper executor
    -> live only after hard safety gates

## Incorrect path

    good research score
    -> BUY_READY
    -> order

That bypasses the Synth architecture.
