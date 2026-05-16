# TODO — Market Breath

## Status

Active direction.

Main active direction is fully Synth-native Market Breath analysis from market data.

A+ symbolic reports are parked and must not be used as input for Market Breath.

## Sources

- docs/research/market_breath_v1_1_calibration_audit.md
- docs/research/market_breath_v1_1_neutral_rest_bucket_review.md
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

- 1794f7c Add Market Breath V1.1 sparse phase diagnostics

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

Status: done.

Result:

- `NEUTRAL_TRANSITION` is structurally dominant and should remain the conservative rest bucket for now.
- The 88.333333% neutral rate constrains validation design but does not by itself prove that Market Breath V1 thresholds are wrong.
- Later validation should not treat all phases equally.
- `EXHALE_EXPANSION` and `COLLAPSE_RESET` are the first reasonable validation candidates.
- `OVERBREATH_EXTENSION` is sparse but reachable and should be exploratory only.
- `INHALE_ACCUMULATION` is very sparse and should be weak exploratory only.
- `HOLD_COMPRESSION` is near-unreachable and should not drive validation conclusions unless a separate threshold-calibration patch is opened.

Boundary:

- Review only.
- Do not change thresholds without a separate threshold-calibration patch.
- No outcome validation was performed.
- No strategy logic or runtime promotion was added.

## P2 — Optional threshold-calibration patch

Status: blocked.

Trigger:

Only open this if limited validation or a separate reachability review confirms that V1 has a measurement problem rather than merely intentionally conservative labels.

Rules:

- Separate patch from audit-output work.
- Research-only.
- Market-only.
- No strategy logic.
- Rerun the same V1.1 distribution audit after any threshold change.

## P3 — Outcome validation

Status: next recommended step.

Goal:

Run a limited Market Breath outcome-validation dry lane for sufficient-sample phases.

Recommended scope:

- Primary: `EXHALE_EXPANSION`.
- Secondary: `COLLAPSE_RESET`.
- Exploratory readout only: `OVERBREATH_EXTENSION`.
- Weak exploratory readout only: `INHALE_ACCUMULATION`.
- Exclude from conclusions: `HOLD_COMPRESSION`.
- Baseline/rest bucket: `NEUTRAL_TRANSITION`.

Rules:

- No outcome validation inside V1.1 calibration audit.
- No strategy candidate before outcome validation exists.
- No selection/advice/decision/execution/broker integration.
- No A+ input.
- No PRO input.
- No symbolic labels.

## Non-goals

- No A+ input.
- No PRO input.
- No symbolic labels.
- No broker calls.
- No broker writes.
- No order submission.
- No runtime promotion.
