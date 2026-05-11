# Breath Curve Phase Offset Analysis v1

Status: research-only  
Scope: market-only / account-agnostic  
Downstream use: undefined until historical validation  

## Purpose

Analyze variation in `best_phase_offset_days` from Breath Curve Template batch output.

This analysis is separate from the matcher itself. The matcher measures waveform alignment and pivot-match quality. This offset analysis looks for phase cohorts, drift, convergence, and half-phase splits.

## Concepts

### Offset transition

Tracks how an asset's best offset changes across cycle anchors.

Example:

    BTC: -7.0 -> +5.0 -> 0.0

### Delta versus BTC

Measures whether an asset leads or lags BTC within the same anchor cycle.

Formula:

    delta_vs_btc = asset_best_offset - btc_best_offset

Example:

    TAO cycle 2:
    asset_offset = -7.0
    btc_offset   = +5.0
    delta_vs_btc = -12.0

A delta near 10.5 days may indicate a half-phase split.

### Phase cohort

Groups assets by shared best offset within the same anchor.

Example:

    anchor 2026-04-12
    offset 0.0: BTC, ETH, TAO, RENDER

This may indicate phase convergence.

## First observed patterns

From the first multi-anchor batch:

    anchors = 2026-03-01, 2026-03-22, 2026-04-12

### BTC and ETH phase lock

BTC and ETH had identical offset transitions:

    BTC: -7.0 -> +5.0 -> 0.0
    ETH: -7.0 -> +5.0 -> 0.0

Initial interpretation:

    ETH was phase-locked to BTC in this sample.

### TAO and RENDER convergence

TAO and RENDER converged toward BTC/ETH by the 2026-04-12 anchor:

    BTC:    -7.0 -> +5.0 -> 0.0
    ETH:    -7.0 -> +5.0 -> 0.0
    TAO:    -7.0 -> -7.0 -> 0.0
    RENDER: -5.0 -> -7.0 -> 0.0

Initial interpretation:

    TAO and RENDER may have had separate phase behavior earlier, then converged into the BTC/ETH core phase.

### FIL late drift

FIL showed the cleanest late-drift pattern:

    FIL: 0.0 -> +3.0 -> +7.0

Initial interpretation:

    FIL drifted later by roughly 3-4 days per tested cycle.

### PEPE early-to-late shift

PEPE shifted from early to late phase:

    PEPE: -5.0 -> +5.0 -> +7.0

Initial interpretation:

    PEPE moved from leading/early phase into lagging/late phase.

### HBAR and XLM instability

HBAR and XLM were less stable:

    HBAR: -5.0 -> +3.0 -> -7.0
    XLM:  +3.0 -> +5.0 -> -10.5

XLM ended at the edge of the V1 offset grid with the lowest score in the sample.

Initial interpretation:

    XLM may be unstable, poorly anchored, or experiencing a half-phase/regime shift.

## Half-phase split candidate

In the 2026-03-22 anchor:

    BTC / ETH / PEPE: +5.0
    TAO / RENDER:     -7.0

Difference:

    12.0 days

Since half of a 21-day cycle is:

    10.5 days

This may represent a half-phase split candidate.

## Important limitations

This is a small sample.

Do not infer stable per-asset phase behavior from three anchors.

V1 uses a discrete offset grid. V2 should support fine search:

    range: -10.5 to +10.5 days
    step: 0.5 day or 1 candle

V1 is retrospective full-cycle analysis, not live prediction.

## Script

Use:

    python -m src.research.analyze_breath_curve_offsets_v1 \
      --csv data/research/breath_curve_template_matcher_v1/<batch>.csv

## Boundary

Allowed:

    research review
    offset behavior analysis
    phase-cohort discovery
    historical validation planning

Out of scope:

    direct buy/sell logic
    execution targets
    decision_gate behavior
    execution_planner behavior
    executor behavior
