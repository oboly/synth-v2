# CQ v1 Holdout Comparison v1

Issue: #620
Parent: #568

## Purpose

This lane performs the first outcome inspection after the CQ v1 model family was frozen in Phase 2D1 and materialized in Phase 2D2. It is research-only and cannot change production ranking or any account/execution authority.

## Why this is a cross-sectional holdout

The frozen Phase 2C population contains 419 observations from one market cross-section at `2026-08-26T20:15:47Z`. A chronological 60/20/20 split is therefore not identifiable without pretending that asset order is time. The protocol explicitly rejects that fiction.

Because the CQ v1 transforms, weights, support rules and two candidate definitions were frozen before any forward outcomes were inspected, the complete frozen cross-section is treated as the first untouched **cross-sectional holdout**. This supports a ranking-usefulness test across assets at one market instant. It does **not** establish temporal generalization across regimes. A later multi-date/walk-forward population remains necessary before production promotion if this first holdout is favorable.

## Frozen inputs and population binding

The runner consumes only immutable research artifacts and their summaries:

```text
entry_quality_forward_validation_v1/forward_outcomes_v1.jsonl
entry_quality_forward_validation_v1/summary_v1.json
cq_v1_score_materialization_v1/cq_v1_scores.jsonl
cq_v1_score_materialization_v1/summary.json
```

It performs no DB queries and no market-data recomputation.

The protocol pins the pre-outcome population facts already established by Phase 2C/D1:

```text
score rows = 419
last shadow_id = 619
outcome rows = 419 × 3 = 1257
rows per horizon = 419
observation as-of = 2026-08-26T20:15:47Z
coverage artifact SHA-256 = f09a515535dd72c5422cbfea7ad449163132b298d1759f32701f0152c78aff2d
model family version = 1.0.0
```

The score summary must report `FINISHED`, the same sample count/last identity, model-family version and pinned coverage artifact. The forward summary must report 1257 rows and 419 observations. The JSONL population must contain every score identity exactly once and exactly one row for each required horizon. A truncated or substituted subset therefore cannot receive a promotion verdict.

Artifacts are joined by:

```text
shadow_id
asset_id
venue
evidence_key
cq_model_version
```

The observation timestamp must equal the frozen cross-section timestamp. Duplicate score identities, duplicate `(shadow_id, horizon)` labels, identity mismatches, unexpected horizons, and non-finite numeric values fail closed.

Only forward-label rows with `status=COMPLETE` enter metric calculations. Incomplete horizon coverage remains excluded evidence, never a zero return, while the frozen artifact still must contain the horizon row so missingness is explicit.

## Identical-sample comparison

For each frozen CQ v1 candidate and horizon, the evaluator first intersects rows where all of these exist:

```text
trade_quality_score
selection_score
CQ v0
that CQ v1 candidate
complete forward label
```

Every score in that comparison is then evaluated on that exact same set. Missing CQ v1 support therefore cannot make a candidate look better by changing the baseline population.

The frozen candidates are:

```text
cq_v1_mrp_balanced_v1
cq_v1_mrp_anchor_v1
```

## PPP and Entry Strength

PPP remains target geometry, not probability. `Entry Strength = PPP × CQ` is evaluated only where canonical PPP already exists in the frozen observation.

`PLANNING_PPP` and `ACTIONABLE_PPP` are separate cohorts. The evaluator never combines PPP kinds into one comparison. If no canonical PPP is present, PPP/Entry Strength output is explicitly absent rather than reconstructed from later prices.

Target-hit and time-to-target remain unavailable because the Phase 1/2 frozen evidence does not carry a canonical target-price/reference-price pair. The evaluator must not derive a target price from PPP percentage.

## Metrics

For each horizon (`1h`, `4h`, `24h`) and score family the evaluator reports:

- sample count;
- Pearson correlation with forward return;
- Spearman rank correlation with forward return;
- five deterministic score buckets, with ties secondarily ordered by `shadow_id`;
- mean forward return, MFE and MAE per bucket.

The primary question remains ranking usefulness, not probability calibration.

## Frozen promotion rule

The rule is frozen in `config/research/cq_v1_holdout_comparison_v1.yaml` before this lane opens aggregate outcome results.

`RANKING_PROMOTION_CANDIDATE` requires at least 100 identical-sample observations on all three horizons, a material Spearman improvement of at least `0.02` versus both CQ v0 and `selection_score` on every horizon, and non-negative top-bucket mean forward return on every horizon.

`CQ_V1_SHADOW_ACCEPTED` requires sufficient sample on all horizons and positive Spearman improvement versus CQ v0 on at least two of three horizons.

`REJECT` requires both frozen candidates to be materially worse than CQ v0 on at least two horizons.

All other mixed, underpowered or inconclusive outcomes return `RESEARCH_FURTHER`.

A `RANKING_PROMOTION_CANDIDATE` verdict is evidence only. It does not alter production ordering. The single-date design is intentionally recorded as a limitation even if that verdict occurs.

## Runner

```text
python3 -m src.research.run_cq_v1_holdout_comparison_v1 \
  --forward-outcomes-jsonl <immutable-forward-outcomes.jsonl> \
  --forward-summary-json <immutable-forward-summary.json> \
  --cq-v1-scores-jsonl <immutable-cq-v1-scores.jsonl> \
  --cq-v1-score-summary-json <immutable-score-summary.json> \
  --output-dir <new-immutable-output-dir>
```

Outputs:

```text
holdout_report.json
summary.json
```

The output directory must be empty/new. Preflight or evaluation failures still emit `summary.json` with `terminal_state=FAILED` and never emit a promotion verdict.

## Safety

```text
research_only=1
market_only=1
db_writes=0
production_ranking_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
runtime_activation=0
```
