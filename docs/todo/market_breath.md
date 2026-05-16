# TODO — Market Breath

## Status

Active direction.

Main active direction is fully Synth-native Market Breath analysis from market data.

A+ symbolic reports are parked and must not be used as input for Market Breath.

## Sources

- docs/research/market_breath_v1_1_calibration_audit.md
- src/research/run_market_breath_v1_1_calibration_audit.py
- data/research/market_breath_v1_1_calibration_audit/calibration_summary_v1.json
- data/research/market_breath_v1_1_calibration_audit/phase_distribution_by_asof_v1.jsonl

## Current calibration snapshot

sample_count=60
assets_per_sample=41
observations=2460

NEUTRAL_TRANSITION=88.333333%
EXHALE_EXPANSION=6.056911%
COLLAPSE_RESET=3.699187%
OVERBREATH_EXTENSION=1.178862%
INHALE_ACCUMULATION=0.650407%
HOLD_COMPRESSION=0.081301%
INSUFFICIENT_DATA=0.0%

Interpretation:

- Latest collapse-heavy run = likely temporary current 4h market-state skew.
- 60-day audit = not collapse-biased, but strongly neutral-dominant.
- Selective phases = reachable, intentionally conservative, but sparse.

## Done — P0 audit interpretation cleanup

Status: done.

Implemented by:

- d8688f3 Add Market Breath V1.1 sparse phase diagnostics

Resulting diagnostics now report:

- COLLAPSE_RESET not structurally dominant.
- NEUTRAL_TRANSITION structurally dominant.
- HOLD_COMPRESSION sparse / near-unreachable.
- INHALE_ACCUMULATION sparse but reachable.
- OVERBREATH_EXTENSION sparse but reachable.
- EXHALE_EXPANSION present; validate later if sample count is sufficient.
- No Market Breath V1 threshold changes applied.

Boundary preserved:

- No Market Breath V1 threshold changes.
- No outcome validation.
- No strategy logic.
- No runtime promotion.
- No A+ input.
- No PRO input.
- No symbolic labels.
- No selection/advice/decision/execution changes.
- No broker calls.
- No broker writes.
- No order submission.

## P1 — Review neutral rest-bucket role

Status: open.

Questions:

- Is NEUTRAL_TRANSITION intended to absorb most non-clean states?
- Does an 88% neutral rate make later outcome validation too sparse for several phases?
- Should outcome validation first focus on phases with enough sample mass, such as EXHALE_EXPANSION and COLLAPSE_RESET?
- Should HOLD_COMPRESSION be reviewed separately because it appears only 2 times in 2460 observations?

Boundary:

- Review only.
- Do not change thresholds without a separate threshold-calibration patch.

## P2 — Optional threshold-calibration patch

Status: blocked by P1.

Trigger:

Only open this if calibration review confirms that V1 has a measurement problem rather than merely intentionally conservative labels.

Rules:

- Separate patch from audit-output work.
- Research-only.
- Market-only.
- No strategy logic.
- Rerun the same V1.1 distribution audit after any threshold change.

## P3 — Outcome validation

Status: blocked by P1 and optionally P2.

Goal:

Validate whether Market Breath labels have useful future market behavior.

Rules:

- No outcome validation inside V1.1 calibration audit.
- No strategy candidate before outcome validation exists.
- No selection/advice/decision/execution/broker integration.

## Non-goals

- No A+ input.
- No PRO input.
- No symbolic labels.
- No broker calls.
- No broker writes.
- No order submission.
- No runtime promotion.
