# Market Breath Outcome Bucket Analysis V1

## Purpose

Market Breath outcome bucket analysis V1 reviews existing outcome validation rows to determine whether first-pass findings are broad, symbol-specific, regime-like, or score-band-specific.

This is analysis of generated research output only. It does not query the database, rerun Market Breath labels, recompute outcomes from candles, change thresholds, add strategy logic, or promote anything to runtime.

## Why this follows outcome validation findings

Market Breath outcome validation V1 found:

- `EXHALE_EXPANSION` underperformed the `NEUTRAL_TRANSITION` baseline in first-pass 24-candle validation.
- `COLLAPSE_RESET` outperformed the neutral baseline in first-pass 24-candle validation.
- `OVERBREATH_EXTENSION` behaved like late-risk / exhaustion.
- `INHALE_ACCUMULATION` and `HOLD_COMPRESSION` had low sample mass.

Bucket analysis is the next dry research step because it checks whether those findings are broad or concentrated in specific symbols, states, or score bands before any threshold-calibration discussion.

## Input files

The analyzer reads:

```text
data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl
data/research/market_breath_outcome_validation_v1/outcome_summary_v1.json
```

It writes:

```text
data/research/market_breath_outcome_bucket_analysis_v1/bucket_rows_v1.jsonl
data/research/market_breath_outcome_bucket_analysis_v1/bucket_summary_v1.json
```

No DB reads are used.

## Bucket dimensions

The output includes these bucket dimensions:

- phase
- phase + symbol
- phase + market_breath_state
- phase + confidence_band
- phase + momentum_band
- phase + relative_strength_band
- phase + expansion_band
- phase + reversal_pressure_band
- phase + btc_alignment_band
- phase + breadth_alignment_band

## Banding rules

`market_breath_confidence`:

- `CONF_LOW`: `< 40`
- `CONF_MID`: `>= 40 and < 70`
- `CONF_HIGH`: `>= 70`

`momentum_score`:

- `MOM_NEG_HIGH`: `< -25`
- `MOM_NEG`: `>= -25 and < 0`
- `MOM_FLAT`: `>= 0 and < 20`
- `MOM_POS`: `>= 20 and < 50`
- `MOM_POS_HIGH`: `>= 50`

`relative_strength_score`:

- `RS_WEAK`: `< -20`
- `RS_NEG`: `>= -20 and < 0`
- `RS_NEUTRAL`: `>= 0 and < 20`
- `RS_STRONG`: `>= 20 and < 50`
- `RS_LEADER`: `>= 50`

`expansion_score`:

- `EXP_LOW`: `< 35`
- `EXP_MID`: `>= 35 and < 65`
- `EXP_HIGH`: `>= 65`

`reversal_pressure_score`:

- `REV_LOW`: `< 25`
- `REV_MID`: `>= 25 and < 45`
- `REV_HIGH`: `>= 45`

`btc_alignment_score`:

- `BTC_DIVERGENT`: `< -20`
- `BTC_WEAK`: `>= -20 and < 0`
- `BTC_NEUTRAL`: `>= 0 and < 20`
- `BTC_ALIGNED`: `>= 20 and < 50`
- `BTC_STRONGLY_ALIGNED`: `>= 50`

`breadth_alignment_score`:

- `BREADTH_WEAK`: `< -20`
- `BREADTH_NEG`: `>= -20 and < 0`
- `BREADTH_NEUTRAL`: `>= 0 and < 20`
- `BREADTH_ALIGNED`: `>= 20 and < 50`
- `BREADTH_STRONGLY_ALIGNED`: `>= 50`

## Metrics

Each bucket row contains:

- bucket dimension and key
- phase
- count
- outcome available count
- average forward returns at 1c, 3c, 6c, 12c, 18c, and 24c
- median 24c forward return
- 24c positive rate
- average max runup over 24 candles
- average max drawdown over 24 candles
- difference versus `NEUTRAL_TRANSITION` average 24c return
- difference versus `NEUTRAL_TRANSITION` 24c positive rate
- sample status
- interpretation hint

Sample status:

- `SUFFICIENT`: `outcome_available_count >= min_count`
- `LOW_SAMPLE`: otherwise

Default `min_count` is 20.

Interpretation hints:

- `OUTPERFORMS_BASELINE`: sufficient sample, average 24c return at least 1.0 percentage point above neutral, and positive rate at least 5 percentage points above neutral.
- `UNDERPERFORMS_BASELINE`: sufficient sample, average 24c return at least 1.0 percentage point below neutral, and positive rate at least 5 percentage points below neutral.
- `MIXED_OR_FLAT`: sufficient sample without clear outperformance or underperformance.
- `LOW_SAMPLE`: insufficient sample.

## Interpretation rules

- Do not declare strategy edge.
- Do not recommend buys or sells.
- Do not promote to runtime.
- Use "candidate for further review", not "signal".
- Compare phase buckets against the `NEUTRAL_TRANSITION` baseline.
- Treat low-sample buckets as `LOW_SAMPLE`, not meaningful.

## First-pass findings from generated output

Input size:

```text
row_count=2460
outcome_available_count=2135
min_count=20
bucket_rows=282
```

Neutral baseline:

```text
avg_fwd_return_24c=0.628198
median_fwd_return_24c=0.070389
positive_rate_24c=50.399148
outcome_available_count=1879
```

`COLLAPSE_RESET` has several sufficient buckets that outperform the neutral baseline. The strongest generated buckets include:

```text
COLLAPSE_RESET|BREADTH_NEUTRAL available=32 avg_24c=4.493879 positive_rate_24c=90.625
COLLAPSE_RESET|RS_NEG available=36 avg_24c=4.203188 positive_rate_24c=94.444444
COLLAPSE_RESET|BTC_ALIGNED available=31 avg_24c=3.995335 positive_rate_24c=93.548387
COLLAPSE_RESET|EXP_HIGH available=65 avg_24c=2.878595 positive_rate_24c=78.461538
COLLAPSE_RESET available=77 avg_24c=2.712149 positive_rate_24c=77.922078
```

Interpretation: `COLLAPSE_RESET` is not only a single-symbol artifact in this pass. It has broad phase-level outperformance and several score-band buckets that remain above baseline. This is a candidate for further review, not a live signal.

`EXHALE_EXPANSION` has sufficient underperforming buckets and no sufficient outperforming buckets in this pass. The weakest generated buckets include:

```text
EXHALE_EXPANSION|BTC_DIVERGENT available=22 avg_24c=-3.298573 positive_rate_24c=27.272727
EXHALE_EXPANSION|EXP_MID available=31 avg_24c=-2.393043 positive_rate_24c=29.032258
EXHALE_EXPANSION|FORMING available=48 avg_24c=-1.99302 positive_rate_24c=35.416667
EXHALE_EXPANSION|MOM_POS available=27 avg_24c=-1.192625 positive_rate_24c=33.333333
EXHALE_EXPANSION|RS_LEADER available=51 avg_24c=-1.150299 positive_rate_24c=31.372549
```

Interpretation: there is no generated evidence here that high confidence or high relative strength rescues `EXHALE_EXPANSION` as a 24-candle continuation candidate. In this pass it remains more consistent with late-risk / post-expansion churn than clean continuation.

`OVERBREATH_EXTENSION` has sufficient but small sample buckets that underperform the neutral baseline:

```text
OVERBREATH_EXTENSION available=25 avg_24c=-0.975624 positive_rate_24c=36.0
OVERBREATH_EXTENSION|LATE available=25 avg_24c=-0.975624 positive_rate_24c=36.0
OVERBREATH_EXTENSION|MOM_POS_HIGH available=25 avg_24c=-0.975624 positive_rate_24c=36.0
OVERBREATH_EXTENSION|EXP_HIGH available=25 avg_24c=-0.975624 positive_rate_24c=36.0
OVERBREATH_EXTENSION|REV_HIGH available=25 avg_24c=-0.975624 positive_rate_24c=36.0
```

Interpretation: this remains consistent with an exhaustion-like or late-risk state. Sample mass is still limited, so it remains exploratory.

`INHALE_ACCUMULATION` and `HOLD_COMPRESSION` remain too sparse for meaningful bucket conclusions. Their bucket rows are marked `LOW_SAMPLE` and should not drive threshold decisions.

## Primary questions

1. Is `COLLAPSE_RESET` broadly positive or driven by specific symbols/regimes/bands?

Answer: it is broad enough for further review in this pass. Phase-level, state, confidence, momentum, expansion, breadth, BTC alignment, and relative-strength buckets all include sufficient outperforming rows. This is not a strategy claim.

2. Does `EXHALE_EXPANSION` work only in high-confidence or high-relative-strength buckets?

Answer: not in this generated pass. `EXHALE_EXPANSION|RS_LEADER` and several other sufficient buckets underperform the neutral baseline. No sufficient outperforming exhale bucket was generated.

3. Is `EXHALE_EXPANSION` generally late-risk?

Answer: the generated bucket analysis supports that interpretation for this sample. It should be described as a candidate late-risk / churn state until longer-history validation says otherwise.

4. Is `OVERBREATH_EXTENSION` consistently exhaustion-like?

Answer: yes, within this small but sufficient generated bucket set. It remains exploratory because count is limited.

5. Are sparse phases too low-sample to discuss?

Answer: yes for conclusions. `INHALE_ACCUMULATION` and `HOLD_COMPRESSION` can be listed, but their bucket findings should not drive decisions.

6. Should threshold calibration remain blocked after bucket analysis?

Answer: yes. Bucket analysis does not justify immediate threshold changes. The next step is review and possible longer-history validation before deciding whether threshold calibration becomes necessary.

## Limitations

- File-derived only from existing outcome validation outputs.
- No DB reads.
- No label reruns.
- No outcome recomputation from candles.
- No future outcome is used to change labels or thresholds.
- Bucketed samples can become small quickly.
- `LOW_SAMPLE` buckets are not meaningful conclusions.
- This is not a strategy validation.

## Next recommended step

Review the bucketed findings manually, then decide whether threshold calibration remains blocked. If additional confidence is needed, run longer-history validation before opening any threshold-calibration patch.

No runtime promotion should follow from this pass.

## No threshold changes

No Market Breath V1 threshold logic is changed.

Threshold calibration remains blocked unless review of bucketed findings or longer-history validation shows a measurement problem that cannot be handled as interpretation.

## No strategy/runtime promotion

This output is not:

- a trading signal
- a buy or sell recommendation
- a selection modifier
- advice
- a decision permission layer
- execution intent
- an order plan
- a broker instruction
- a runtime feature

Safety markers:

```text
broker_calls=0
broker_writes=0
order_submission=0
live_orders=0
db_reads=0
db_writes=0
selection_engine_changes=0
advice_engine_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```

## CLI

Compile check:

```bash
python -m py_compile src/research/run_market_breath_outcome_bucket_analysis_v1.py
```

Dry run:

```bash
python -m src.research.run_market_breath_outcome_bucket_analysis_v1 \
  --output table
```

Write files:

```bash
python -m src.research.run_market_breath_outcome_bucket_analysis_v1 \
  --write-files \
  --output table
```
