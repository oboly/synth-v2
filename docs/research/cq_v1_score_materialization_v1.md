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

`--features-jsonl` points to a completed Phase 2C `features.jsonl` artifact generated after the #612 CQ-v0 provenance amendment.

Every feature row must contain the contemporaneous Phase-1 `entry_quality_score` as `cq_v0`. This value is frozen in the PIT artifact before score materialization.

For each feature row, the runner reads the corresponding `research_entry_quality_shadow` row by `shadow_id` and verifies:

```text
asset_id
venue
asof_ts_utc
evidence_key
cq_model_version
current entry_quality_score == frozen feature cq_v0
```

The frozen feature `cq_v0`, not the mutable current DB value, is supplied to the Phase 2D1 scorer. A missing row, identity mismatch or changed CQ v0 fails the run. This prevents an upsert-backed shadow rewrite from silently changing a supposedly frozen candidate score.

Database reads are bounded by `--batch-size` (default 100). The runner does not scan candle/outcome tables.

## Output

A new run uses an empty evidence directory. It receives:

```text
cq_v1_scores.jsonl
summary.json
checkpoint.json
```

Each JSONL row contains the immutable shadow identity, frozen CQ v0, frozen model-family/hash identity and both candidate state/score/reason payloads.

The summary reports actual state counts and AVAILABLE rates. It never forces the pre-model 203/419 MRP coverage result; agreement or disagreement is evidence to inspect after the run.

## Interruption and resume

The repository research-runner contract requires clean interruption handling. After each complete score row the runner writes a checkpoint containing the processed count, last shadow id, feature-artifact path, batch size and frozen model/hash identity.

SIGINT/SIGTERM stops after the current complete row, writes:

```text
terminal_state=INTERRUPTED
```

and returns 130. `--resume` verifies checkpoint scope, reconciles any uncheckpointed JSONL tail and continues from the next feature row. A resumed run cannot switch feature input, batch size, model-family version or coverage-artifact hash.

## Missingness

The materializer does not repair missing support. If the frozen scorer returns `INSUFFICIENT_DATA` or `BLOCKED`, that state is written unchanged.

No imputation, weight renormalization, Sector Rotation substitution or per-asset MRP score substitution is performed.

## Outcome boundary

This slice is deliberately outcome-blind:

```text
forward_outcomes_read=0
```

After a full materialization artifact is accepted, the next #568 slice may pair these frozen scores with the separately preregistered 1h/4h/24h forward labels. The current source population is a single as-of cross-section, so any first paired result must be labeled bounded/cross-sectional rather than final chronological or multi-regime validation.

Because the prior Phase 2C artifact predates frozen `cq_v0` in `features.jsonl`, it must be regenerated through source exhaustion after this change. Its coverage summary should remain arithmetically unchanged; that must be verified rather than assumed.

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
