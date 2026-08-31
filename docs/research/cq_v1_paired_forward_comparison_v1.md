# CQ v1 paired forward comparison v1

Issue: #623
Parent: #568
Status: research-only, frozen-model evaluation

## Purpose

Pair the immutable Phase 2D2 CQ v1 score artifact with the already-preregistered `entry_quality_forward_validation_v1` labels and produce bounded cross-sectional ranking evidence.

This stage may inspect outcomes. It may not change the frozen CQ v1 family.

## Frozen inputs

Score input is supplied as `cq_v1_scores.jsonl` and is content-addressed by SHA-256 in the output summary.

Forward labels are supplied as `forward_outcomes_v1.jsonl` from registry version `1.0.0`, with canonical 15m candles and horizons exactly `1h`, `4h`, `24h`. The outcome file is also content-addressed by SHA-256.

Join identity is exact:

```text
shadow_id
asset_id
venue
observation as-of
evidence_key
cq_model_version
cq_v0 equality
```

A missing score row, duplicate `(shadow_id,horizon)`, identity mismatch or CQ v0 mismatch fails the comparison.

## Metrics

The fixed metric set is:

```text
ppp_only
trade_quality_score
selection_score
cq_v0
cq_v1_mrp_balanced_v1
cq_v1_mrp_anchor_v1
ppp_x_cq_v0
ppp_x_cq_v1_mrp_balanced_v1
ppp_x_cq_v1_mrp_anchor_v1
```

Missing values remain missing. Candidate `INSUFFICIENT_DATA` / `BLOCKED` scores are never imputed.

For each horizon and outcome (`forward_return_pct`, `mfe_pct`, `mae_pct`) the report includes Pearson, Spearman and five deterministic rank buckets. Bucket assignment sorts by `(metric_value, shadow_id)` and divides ordinal ranks into five fixed buckets.

## Identical-cohort comparisons

Every direct comparison uses only the intersection where:

```text
label_status == COMPLETE
left metric available
right metric available
outcome available
```

Both sides are then recomputed on that exact same row set. This prevents missingness from manufacturing a win.

## Interpretation

The current source population is one as-of cross-section. Therefore this runner always emits:

```text
bounded_cross_sectional_only=true
final_phase2_recommendation=RESEARCH_FURTHER
```

This artifact can inform the next temporal/walk-forward phase, but it cannot by itself justify production promotion.

## Outputs

```text
paired_rows.jsonl
comparison_summary.json
```

The summary pins both input hashes and preserves per-horizon label status counts, metric coverage/reason counts, standalone metrics and identical-cohort pairwise metrics.

## Boundaries

```text
research_only=1
market_only=1
db_reads=0
db_writes=0
frozen_model_changed=0
production_ranking_changes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
runtime_activation=0
```
