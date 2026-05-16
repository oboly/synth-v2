# Market Breath Outcome Validation V1 Findings

## Status

Status: complete first-pass findings review.

This document reviews the generated Market Breath outcome validation V1 dry-run outputs. It does not add code, change thresholds, create strategy logic, or promote anything to runtime.

## Input data

Reviewed output:

```text
data/research/market_breath_outcome_validation_v1/outcome_summary_v1.json
data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl
```

Scope:

```text
venue=bitvavo
interval=4h
sample_count=60
row_count=2460
outcome_available_count=2135
```

Boundary:

```text
research-only
market-only
account-agnostic
no A+ input
no PRO input
no symbolic labels
no threshold changes
no strategy logic
no runtime promotion
```

## Outcome summary

24-candle outcome summary from the first dry run:

| Phase | Bucket | Count | Available | Avg 24c | Median 24c | Positive rate 24c |
|---|---:|---:|---:|---:|---:|---:|
| EXHALE_EXPANSION | PRIMARY | 165 | 145 | -0.619549% | -2.330056% | 37.241379% |
| COLLAPSE_RESET | SECONDARY | 89 | 77 | 2.712149% | 3.409656% | 77.922078% |
| OVERBREATH_EXTENSION | EXPLORATORY | 29 | 25 | -0.975624% | -2.773642% | 36.0% |
| INHALE_ACCUMULATION | EXPLORATORY | 16 | 8 | -0.821763% | 0.354712% | 62.5% |
| HOLD_COMPRESSION | EXCLUDED_LOW_SAMPLE | 4 | 1 | -3.382801% | -3.382801% | 0.0% |
| NEUTRAL_TRANSITION | BASELINE_REST_BUCKET | 2157 | 1879 | 0.628198% | 0.070389% | 50.399148% |

## First-pass interpretation

The first-pass results do not support treating `EXHALE_EXPANSION` as a naive 24-candle continuation entry label. In this sample, `EXHALE_EXPANSION` underperformed the `NEUTRAL_TRANSITION` baseline on average 24-candle return, median 24-candle return, and 24-candle positive rate.

`COLLAPSE_RESET` outperformed the neutral baseline in this first dry run. It had the strongest 24-candle average return, strongest median 24-candle return, and highest 24-candle positive rate among phases with enough sample mass for limited review.

This suggests Market Breath V1 may currently be more useful as a market-state and risk-timing classifier than as a direct continuation classifier. In plain terms:

```text
EXHALE_EXPANSION may often describe a late/extended state rather than a clean continuation entry.
COLLAPSE_RESET may describe a reset/bounce-prone state in the sampled regime.
NEUTRAL_TRANSITION remains the rest-bucket baseline.
```

This is only first-pass outcome measurement. It is not a trading edge claim.

## Phase-specific findings

### EXHALE_EXPANSION

Finding:

```text
avg_fwd_return_24c=-0.619549%
median_fwd_return_24c=-2.330056%
positive_rate_24c=37.241379%
outcome_available_count=145
```

Interpretation:

`EXHALE_EXPANSION` is not validated as a simple 24-candle continuation label in this run. Its negative median and low positive rate suggest that the label may often identify already-late expansion, local exhaustion, or volatile post-expansion churn.

Next review should bucket this phase by symbol, regime, confidence, momentum, and relative strength before making any threshold decision.

### COLLAPSE_RESET

Finding:

```text
avg_fwd_return_24c=2.712149%
median_fwd_return_24c=3.409656%
positive_rate_24c=77.922078%
outcome_available_count=77
```

Interpretation:

`COLLAPSE_RESET` is the strongest first-pass finding. It may identify oversold/reset conditions that bounced in the sampled 4h market regime.

This should not be interpreted as a strategy yet. It needs regime and symbol bucketing to determine whether the effect is broad, regime-specific, or driven by a few high-beta assets.

### OVERBREATH_EXTENSION

Finding:

```text
avg_fwd_return_24c=-0.975624%
median_fwd_return_24c=-2.773642%
positive_rate_24c=36.0%
outcome_available_count=25
```

Interpretation:

`OVERBREATH_EXTENSION` behaves consistently with a late-risk or exhaustion-state label in this first pass. Sample size is small, so it remains exploratory only.

### INHALE_ACCUMULATION

Finding:

```text
avg_fwd_return_24c=-0.821763%
median_fwd_return_24c=0.354712%
positive_rate_24c=62.5%
outcome_available_count=8
```

Interpretation:

`INHALE_ACCUMULATION` has too little available sample mass for strong conclusions. The positive rate and median are not enough to offset the low count and negative average. Treat as weak exploratory only.

### HOLD_COMPRESSION

Finding:

```text
outcome_available_count=1
```

Interpretation:

`HOLD_COMPRESSION` is excluded from conclusions. Its reachability remains a separate calibration/reachability question.

### NEUTRAL_TRANSITION

Finding:

```text
avg_fwd_return_24c=0.628198%
median_fwd_return_24c=0.070389%
positive_rate_24c=50.399148%
outcome_available_count=1879
```

Interpretation:

`NEUTRAL_TRANSITION` is a reasonable baseline rest bucket. Specific phases should be compared against this baseline rather than interpreted in isolation.

## Decision

Do not change Market Breath V1 thresholds yet.

Do not promote Market Breath labels to strategy logic or runtime behavior.

Keep threshold calibration blocked for now. The first-pass result points more toward follow-up bucketing than immediate threshold edits.

## Recommended next step

Open a second dry research pass that buckets outcome validation by pre-measurable context:

```text
Market Breath outcome validation V1
-> outcome findings review
-> symbol/regime bucket analysis
-> then decide whether threshold calibration remains blocked or becomes necessary
```

Recommended bucket dimensions:

- symbol
- BTC / broad-market regime proxy
- market breadth regime
- Market Breath state
- confidence band
- momentum score band
- relative strength score band
- expansion score band
- reset/reversal-pressure band

Priority questions for the next pass:

- Is `COLLAPSE_RESET` broadly positive or driven by specific symbols/regimes?
- Does `EXHALE_EXPANSION` work only for high-confidence/high-relative-strength cases, or is it generally late-risk?
- Is `OVERBREATH_EXTENSION` consistently an exhaustion warning?
- Can `INHALE_ACCUMULATION` become useful with more history or different regime filters?
- Is `HOLD_COMPRESSION` worth reachability calibration, or should it remain rare by design?

## Boundaries

- Research-only.
- Market-only.
- Account-agnostic.
- No A+ input.
- No PRO input.
- No symbolic labels.
- No Market Breath V1 threshold changes.
- No strategy logic.
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

- Do not declare strategy edge.
- Do not recommend buys or sells.
- Do not derive position sizing.
- Do not add candidate promotion.
- Do not alter thresholds from first-pass outcomes alone.
- Do not use `COLLAPSE_RESET` as a live mean-reversion trigger.
