# Breath Curve Broader-History Validation v1

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Run a broader-history validation for the calibrated Breath Curve composite candidates.

This is an orchestration/reporting runner. It executes existing research-only runners over multiple rolling 21-day anchor cohorts and aggregates composite preview results.

## Pipeline

For each cohort:

    random-anchor baseline v2
    -> symbol/regime validation v1 with DB context
    -> composite preview v1
    -> aggregate comparison report

## Default anchors

Default anchor grid:

    2026-01-18
    2026-02-08
    2026-03-01
    2026-03-22
    2026-04-12

Default rolling cohorts:

    2026-01-18, 2026-02-08, 2026-03-01
    2026-02-08, 2026-03-01, 2026-03-22
    2026-03-01, 2026-03-22, 2026-04-12

Default random windows use a 28-day pre-pad and 0-day post-pad.

This avoids sampling random anchors after the latest real cohort anchor, reducing forward-data incompleteness risk.

## Candidate composites

The aggregate report focuses on the existing composite preview outputs, especially:

    minus8_all_v1
    minus8_core_symbols_v1
    minus8_volume_expansion_v1
    minus8_core_and_btc_eth_bear_v1
    early_band_core_and_bear_or_volume_v1

## Runner

Dry run:

    python -m src.research.run_breath_curve_broader_history_v1 \
      --dry-run \
      --output table

Default run:

    python -m src.research.run_breath_curve_broader_history_v1 \
      --output table

Optional broader run:

    python -m src.research.run_breath_curve_broader_history_v1 \
      --start-anchor 2025-11-16 \
      --end-anchor 2026-04-12 \
      --random-window-pre-pad-days 28 \
      --random-window-post-pad-days 0 \
      --random-count-per-symbol 50 \
      --output table

## Output

Generated files are written under:

    data/research/breath_curve_broader_history_v1/

This path should remain ignored by git.

Outputs include:

    cohort manifest
    all cohort comparison rows
    aggregate comparison summary
    per-cohort child runner outputs

## Boundary

Allowed:

    research-only orchestration
    DB reads through existing symbol/regime runner
    generated CSV outputs
    aggregate comparison reporting

Forbidden:

    selection_engine modifier
    decision_gate rule
    execution_planner instruction
    executor/order logic
    broker API call
    broker write
    live or paper execution trigger

## Interpretation rule

This runner is the robustness gate.

A composite candidate remains interesting only if it survives:

    multiple cohorts
    same-symbol random baselines
    different market contexts
    reasonable sample size

Passing this runner still does not make it a strategy.

Correct path:

    broader-history validation
    -> optional market-only feature proposal

Incorrect path:

    broader-history validation
    -> BUY_READY

That would bypass the architecture.
