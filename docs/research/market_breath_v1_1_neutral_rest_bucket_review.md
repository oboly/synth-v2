# Market Breath V1.1 Neutral Rest-Bucket Review

## Status

Status: complete.

This is a research-only interpretation review of the existing Market Breath V1.1 calibration audit outputs. It does not add outcome validation, strategy logic, runtime integration, or Market Breath V1 threshold changes.

Conclusion: `NEUTRAL_TRANSITION` is structurally dominant. This does not prove that Market Breath V1 thresholds are wrong, because V1 was intentionally conservative and `NEUTRAL_TRANSITION` is expected to absorb non-clean states. However, later outcome validation should not treat all phases equally. `EXHALE_EXPANSION` and `COLLAPSE_RESET` are the first reasonable validation candidates; `HOLD_COMPRESSION` should not drive conclusions until either more samples exist or threshold calibration is explicitly opened.

## Input data

Reviewed files:

- `data/research/market_breath_v1_1_calibration_audit/calibration_summary_v1.json`
- `data/research/market_breath_v1_1_calibration_audit/phase_distribution_by_asof_v1.jsonl`
- `docs/research/market_breath_v1_1_calibration_audit.md`
- `docs/todo/market_breath.md`

Input scope:

- venue: `bitvavo`
- interval: `4h`
- sample_count: 60
- assets_per_sample: 41
- total observations: 2460
- from_ts: `2026-03-17T12:00:00Z`
- to_ts: `2026-05-16T12:00:00Z`

## Distribution summary

Aggregate phase distribution:

```text
NEUTRAL_TRANSITION=88.333333%
EXHALE_EXPANSION=6.056911%
COLLAPSE_RESET=3.699187%
OVERBREATH_EXTENSION=1.178862%
INHALE_ACCUMULATION=0.650407%
HOLD_COMPRESSION=0.081301%
INSUFFICIENT_DATA=0.0%
```

Aggregate counts:

```text
NEUTRAL_TRANSITION=2173
EXHALE_EXPANSION=149
COLLAPSE_RESET=91
OVERBREATH_EXTENSION=29
INHALE_ACCUMULATION=16
HOLD_COMPRESSION=2
INSUFFICIENT_DATA=0
```

Per-day presence from the existing JSONL output:

```text
days_with_exhale=38 of 60
days_with_collapse=23 of 60
days_with_overbreath=19 of 60
days_with_inhale=9 of 60
days_with_hold=2 of 60
days_neutral_gt_75pct=54 of 60
days_neutral_gt_90pct=44 of 60
neutral_transition_pct_min=31.707317
neutral_transition_pct_max=100.0
```

## Interpretation

`NEUTRAL_TRANSITION` is functioning as the large rest bucket. It is the most common phase on 56 of 60 sampled days, above 75% on 54 sampled days, and above 90% on 44 sampled days.

That dominance is not automatically a defect. The V1 thresholds were intentionally selective during setup, and neutral is the expected destination for observations that do not cleanly satisfy accumulation, compression, expansion, extension, or reset gates. A large neutral bucket is therefore consistent with a conservative classifier.

The dominance is still material for validation design. An 88.333333% neutral rate means the audit is mostly measuring the rest bucket, while several specific phases have limited sample mass. Later validation should be phase-aware and should not interpret sparse phase results as equally reliable.

Current evidence supports this reading:

- `COLLAPSE_RESET` is not structurally dominant at 3.699187%, with only one sampled day above 50%.
- `EXHALE_EXPANSION` is present with 149 observations across 38 sampled days.
- `OVERBREATH_EXTENSION` is sparse but reachable with 29 observations across 19 sampled days.
- `INHALE_ACCUMULATION` is very sparse with 16 observations across 9 sampled days.
- `HOLD_COMPRESSION` is near-unreachable in this audit window with 2 observations across 2 sampled days.

This does not yet answer whether the labels predict later market behavior. No future outcomes were reviewed here.

## Phase-by-phase validation readiness

`EXHALE_EXPANSION`: first reasonable validation candidate. It has 149 observations and appears on 38 of 60 sampled days. This is enough for an initial limited dry validation lane, while still requiring caution around sample size and regime coverage.

`COLLAPSE_RESET`: reasonable limited review candidate. It has 91 observations and appears on 23 of 60 sampled days. It is not structurally dominant, so it can be reviewed without the latest collapse-heavy run distorting the entire calibration conclusion.

`OVERBREATH_EXTENSION`: exploratory only. It is sparse but reachable with 29 observations. It can be included as a secondary readout, but it should not carry primary conclusions.

`INHALE_ACCUMULATION`: very sparse. It has 16 observations and appears on 9 sampled days. Validation can record it, but any phase-specific conclusion should be considered weak until more sample mass exists or a separate threshold-calibration patch is opened.

`HOLD_COMPRESSION`: not ready for outcome conclusions. It has 2 observations and appears on 2 sampled days. It should be reviewed separately for reachability before it is used as a meaningful validation bucket.

`NEUTRAL_TRANSITION`: useful as the rest bucket baseline, not as a specific breath-cycle signal. Its dominance should be visible in validation output, but it should not be allowed to drown out sparse phase interpretation.

## Decision

Do not change Market Breath V1 thresholds yet.

`NEUTRAL_TRANSITION` should remain the large conservative rest bucket for now. The 88.333333% neutral rate is high enough to constrain later validation, but it does not by itself prove that the classifier is too conservative or incorrectly calibrated.

The next step should be a limited outcome-validation dry lane for sufficient-sample phases, focused first on `EXHALE_EXPANSION` and `COLLAPSE_RESET`. Sparse phases should be reported as exploratory only. `HOLD_COMPRESSION` should not drive validation conclusions unless a separate threshold-calibration patch is opened and rerun through the same calibration audit.

## Recommended next step

Proceed to P3 limited Market Breath outcome validation for sufficient-sample phases:

- primary: `EXHALE_EXPANSION`
- secondary: `COLLAPSE_RESET`
- exploratory readout only: `OVERBREATH_EXTENSION`
- weak exploratory readout only: `INHALE_ACCUMULATION`
- exclude from conclusions: `HOLD_COMPRESSION`
- baseline/rest bucket: `NEUTRAL_TRANSITION`

Keep P2 threshold calibration available but blocked unless the limited validation dry lane or a separate reachability review shows that neutral dominance prevents useful measurement.

## Boundaries

- Research-only.
- Market-only.
- Account-agnostic.
- No A+ input.
- No PRO input.
- No symbolic labels.
- No future outcomes in this review.
- No outcome validation in this review.
- No strategy logic.
- No Market Breath V1 threshold changes.
- No selection engine changes.
- No advice engine changes.
- No decision gate changes.
- No execution planner changes.
- No executor or order changes.
- No broker calls.
- No broker writes.
- No order submission.
- No `run_chain_4h.sh` changes.
- No DB writes.
- No runtime promotion.

## Non-goals

- Do not decide predictive value.
- Do not measure returns, hit rate, drawdown, continuation, reversal, or profitability.
- Do not promote Market Breath to runtime logic.
- Do not rebalance phase thresholds inside this review.
- Do not use `NEUTRAL_TRANSITION` dominance as a strategy permission or denial rule.
