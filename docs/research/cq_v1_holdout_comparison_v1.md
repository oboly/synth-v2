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

Before any aggregate outcome evaluation, a separate `cq_v1_holdout_input_manifest_v1` must freeze SHA-256 digests for all four immutable input files. The evaluator verifies those file digests before parsing/evaluating them. The manifest is therefore the phase boundary between artifact generation and holdout inspection; it must be preserved as immutable research evidence before the evaluator is run.

The score summary must report `FINISHED`, the same sample count/last identity, model-family version and pinned coverage artifact. The forward summary must report 1257 rows and 419 observations. The JSONL population must contain every score identity exactly once and exactly one row for each required horizon. A truncated, modified, or substituted artifact cannot receive a promotion verdict.

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

Only the two numeric parameters consumed by the evaluator remain configurable in the frozen protocol:

```text
minimum_candidate_sample = 100
material_spearman_delta = 0.02
```

The verdict semantics themselves are code-frozen and regression-tested:

- `RANKING_PROMOTION_CANDIDATE`: sufficient identical-sample observations on all three horizons, material Spearman improvement versus both CQ v0 and `selection_score` on every horizon, and non-negative top-bucket mean forward return on every horizon.
- `CQ_V1_SHADOW_ACCEPTED`: sufficient sample on all horizons and positive Spearman improvement versus CQ v0 on at least two of three horizons.
- `REJECT`: both frozen candidates materially worse than CQ v0 on at least two horizons.
- all other mixed, underpowered or inconclusive outcomes: `RESEARCH_FURTHER`.

A `RANKING_PROMOTION_CANDIDATE` verdict is evidence only. It does not alter production ordering. The single-date design is intentionally recorded as a limitation even if that verdict occurs.

## Runner

```text
python3 -m src.research.run_cq_v1_holdout_comparison_v1 \
  --frozen-manifest-json <frozen-input-manifest.json> \
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

The output directory must be empty/new. A non-empty output directory is never modified. Other preflight/evaluation failures on a new output directory emit `summary.json` with `terminal_state=FAILED` and never emit a promotion verdict.

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
