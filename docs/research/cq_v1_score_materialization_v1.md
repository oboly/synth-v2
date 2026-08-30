# CQ v1 frozen score materialization v1

Issue: #612
Parent: #568
Status: research-only, outcome-blind materialization

## Purpose

Apply the already-frozen Phase 2D1 candidate family to immutable Phase 2C point-in-time feature observations and preserve the resulting CQ v1 candidate scores as a file artifact.

This stage does not inspect forward outcomes and does not select or tune a candidate.

## Frozen dependencies

```text
model family = cq_v1_model_candidate_v1 / 1.0.0
coverage artifact SHA-256 = f09a515535dd72c5422cbfea7ad449163132b298d1759f32701f0152c78aff2d
```

The scorer, transforms, weights and support policy come only from `src/research/cq_v1_model_candidate_v1.py`.

## Input

`--features-jsonl` points to a completed Phase 2C `features.jsonl` artifact.

For each feature row, the runner reads the corresponding `research_entry_quality_shadow` row by `shadow_id` and verifies the complete immutable identity:

```text
asset_id
venue
asof_ts_utc
evidence_key
cq_model_version
```

Only after the identity matches is `entry_quality_score` supplied as CQ v0 to the frozen scorer. A missing or mismatched research-shadow row fails the run.

Database reads are bounded by `--batch-size` (default 100). The runner does not scan candle/outcome tables.

## Output

`--output-dir` must be a new/empty evidence directory and receives:

```text
cq_v1_scores.jsonl
summary.json
```

Each JSONL row contains the immutable shadow identity, CQ v0, frozen model-family/hash identity and both candidate state/score/reason payloads.

The summary reports actual state counts and AVAILABLE rates. It never forces the pre-model 203/419 MRP coverage result; agreement or disagreement is evidence to inspect after the run.

## Missingness

The materializer does not repair missing support. If the frozen scorer returns `INSUFFICIENT_DATA` or `BLOCKED`, that state is written unchanged.

No imputation, weight renormalization, Sector Rotation substitution or per-asset MRP score substitution is performed.

## Outcome boundary

This slice is deliberately outcome-blind:

```text
forward_outcomes_read=0
```

After a full materialization artifact is accepted, the next #568 slice may pair these frozen scores with the separately preregistered 1h/4h/24h forward labels. The current source population is a single as-of cross-section, so any first paired result must be labeled bounded/cross-sectional rather than final chronological or multi-regime validation.

## Safety

```text
research_only=1
market_only=1
db_writes=0
forward_outcomes_read=0
production_ranking_changes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
```
