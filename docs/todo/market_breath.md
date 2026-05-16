# TODO — Market Breath

## Status

Active direction.

Main active direction is fully Synth-native Market Breath analysis from market data.

A+ symbolic reports are parked and must not be used as input for Market Breath.

## Sources

- docs/research/market_breath_v1_1_calibration_audit.md
- docs/research/market_breath_v1_1_neutral_rest_bucket_review.md
- docs/research/market_breath_outcome_validation_v1.md
- docs/research/market_breath_outcome_validation_v1_findings.md
- docs/research/market_breath_outcome_bucket_analysis_v1.md
- src/research/run_market_breath_v1_1_calibration_audit.py
- src/research/run_market_breath_outcome_validation_v1.py
- src/research/run_market_breath_outcome_bucket_analysis_v1.py
- data/research/market_breath_v1_1_calibration_audit/calibration_summary_v1.json
- data/research/market_breath_v1_1_calibration_audit/phase_distribution_by_asof_v1.jsonl
- data/research/market_breath_outcome_validation_v1/outcome_summary_v1.json
- data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl
- data/research/market_breath_outcome_bucket_analysis_v1/bucket_summary_v1.json
- data/research/market_breath_outcome_bucket_analysis_v1/bucket_rows_v1.jsonl

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

Only open this if limited validation, bucket analysis, or a separate reachability review confirms that V1 has a measurement problem rather than merely intentionally conservative labels.

Rules:

- Separate patch from audit-output work.
- Research-only.
- Market-only.
- No strategy logic.
- Rerun the same V1.1 distribution audit after any threshold change.

## P3 — Outcome validation

Status: done for V1 dry runner.

Goal:

Run a limited Market Breath outcome-validation dry lane for sufficient-sample phases.

Implemented by:

- Market Breath outcome validation V1 dry runner.

Initial output:

- sample_count=60
- row_count=2460
- outcome_available_count=2135
- `EXHALE_EXPANSION`: primary bucket, count=165, outcome_available_count=145.
- `COLLAPSE_RESET`: secondary bucket, count=89, outcome_available_count=77.
- `OVERBREATH_EXTENSION`: exploratory bucket, count=29, outcome_available_count=25.
- `INHALE_ACCUMULATION`: exploratory bucket, count=16, outcome_available_count=8.
- `HOLD_COMPRESSION`: excluded low-sample bucket, count=4, outcome_available_count=1.
- `NEUTRAL_TRANSITION`: baseline rest bucket, count=2157, outcome_available_count=1879.

Rules:

- No strategy candidate before outcome validation exists.
- No selection/advice/decision/execution/broker integration.
- No A+ input.
- No PRO input.
- No symbolic labels.

## Done — P4 outcome validation findings review

Status: done.

Finding:

- `EXHALE_EXPANSION` underperformed the neutral baseline in first-pass 24-candle outcome validation.
- `COLLAPSE_RESET` outperformed the neutral baseline in first-pass 24-candle outcome validation.
- `OVERBREATH_EXTENSION` behaved like late-risk / exhaustion in the first pass.
- `INHALE_ACCUMULATION` and `HOLD_COMPRESSION` have too little sample mass for strong conclusions.
- Market Breath V1 currently looks more like a market-state / risk-timing classifier than a direct continuation-entry classifier.

Decision:

- Keep Market Breath V1 thresholds unchanged.
- Keep threshold calibration blocked for now.
- Do not declare strategy edge.
- Do not promote to runtime.

## P5 — Bucketed outcome analysis

Status: done.

Goal:

Determine whether the first-pass findings are broad, symbol-specific, regime-specific, or score-band-specific.

Implemented by:

- Market Breath outcome bucket analysis V1.

Initial output:

- row_count=2460
- outcome_available_count=2135
- bucket_rows=282
- min_count=20
- neutral baseline avg_fwd_return_24c=0.628198
- neutral baseline positive_rate_24c=50.399148
- `COLLAPSE_RESET` has sufficient outperforming buckets and remains a candidate for further review, not a signal.
- `EXHALE_EXPANSION` has sufficient underperforming buckets and no sufficient outperforming buckets in this pass.
- `OVERBREATH_EXTENSION` remains consistent with late-risk / exhaustion, with limited sample mass.
- `INHALE_ACCUMULATION` and `HOLD_COMPRESSION` remain too sparse for meaningful bucket conclusions.
- Threshold calibration remains blocked pending manual review or longer-history validation.

Recommended bucket dimensions:

- symbol
- BTC / broad-market regime proxy
- market breadth regime
- Market Breath state
- confidence band
- momentum score band
- relative strength score band
- expansion score band
- reset / reversal-pressure band

Priority questions:

- Is `COLLAPSE_RESET` broadly positive or driven by specific symbols/regimes?
- Does `EXHALE_EXPANSION` work only for high-confidence/high-relative-strength cases, or is it generally late-risk?
- Is `OVERBREATH_EXTENSION` consistently an exhaustion warning?
- Can `INHALE_ACCUMULATION` become useful with more history or different regime filters?
- Is `HOLD_COMPRESSION` worth reachability calibration, or should it remain rare by design?

Rules:

- Research-only.
- Market-only.
- Account-agnostic.
- No threshold changes.
- No strategy logic.
- No selection/advice/decision/execution/broker integration.
- No DB reads.

## P6 — Review bucketed findings

Status: next recommended step.

Goal:

Review `data/research/market_breath_outcome_bucket_analysis_v1/bucket_summary_v1.json` and decide whether threshold calibration remains blocked.

Rules:

- Do not declare strategy edge.
- Do not recommend buys or sells.
- Do not promote to runtime.
- Consider longer-history validation only if needed for stability.
- Keep any threshold calibration as a separate research patch.

## Non-goals

- No A+ input.
- No PRO input.
- No symbolic labels.
- No broker calls.
- No broker writes.
- No order submission.
- No runtime promotion.
