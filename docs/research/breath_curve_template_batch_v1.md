# Breath Curve Template Batch Runner v1

Status: research-only  
Layer: market-only / account-agnostic  
DB writes: none  
Orders: none  

## Purpose

Run the Breath Curve Template Matcher v1 across multiple symbols and anchor dates.

The batch runner only measures waveform alignment and pivot-match quality. It does not define downstream use.

## Inputs

- symbols
- anchor dates
- venue
- interval
- cycle_days
- phase offset grid
- tolerance_hours

## Outputs

Local research files:

    data/research/breath_curve_template_matcher_v1/*.csv
    data/research/breath_curve_template_matcher_v1/*.jsonl

CSV contains compact best-result summaries.

JSONL contains detailed offset-level matcher output.

## Usage

Single anchor:

    python -m src.research.run_breath_curve_template_batch_v1 \
      --anchors 2026-03-01

Multiple anchors:

    python -m src.research.run_breath_curve_template_batch_v1 \
      --anchors 2026-03-01,2026-03-22,2026-04-12

Custom symbols:

    python -m src.research.run_breath_curve_template_batch_v1 \
      --symbols BTC,ETH,TAO,RENDER,FIL,HBAR,XLM,PEPE \
      --anchors 2026-03-01

## Boundary

Allowed:

    research review
    waveform alignment measurement
    pivot-match quality comparison
    historical validation planning

Out of scope:

    buy/sell decisions
    target execution
    selection_engine modifiers
    decision_gate rules
    execution_planner logic
