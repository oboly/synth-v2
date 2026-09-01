# CQ v1 daily temporal population v1

Issue: #661
Parent: #568
Canonical sampling contract: #646 / `config/research/cq_v1_temporal_sampling_v1.json`

## Purpose

Build the immutable point-in-time population for the already-frozen CQ v1 candidate family before any temporal forward outcomes are opened.

## Sampling authority

The builder does not own sampling dates. It loads the canonical temporal sampling contract and derives exactly the frozen daily UTC sequence and chronological split membership from that contract.

Unbounded execution therefore uses 45 as-of timestamps from 2026-07-18T00:00:00Z through 2026-08-31T00:00:00Z, partitioned by the frozen discovery / validation / holdout contract.

## PIT rules

For every asset/as-of observation:

- quality and signal inputs use the latest canonical source row with timestamp `<= asof_ts_utc` under exact asset, venue and interval identity;
- aggregate and per-asset MRP use canonical v1.0 ownership and timestamps at or before the observation as-of;
- MRP source timestamps and source ages are persisted explicitly;
- sector context is always `UNAVAILABLE_HISTORICAL_MEMBERSHIP` because historical membership provenance is unavailable; current membership must never be substituted;
- PPP remains unavailable unless a separate canonical historical PIT artifact supplies explicit provenance;
- missing evidence remains missing; no current/latest fallback, imputation or weight renormalization is allowed.

## Frozen model boundary

The builder must preserve exactly:

```text
model_family_version=1.0.0
coverage_artifact_sha256=f09a515535dd72c5422cbfea7ad449163132b298d1759f32701f0152c78aff2d
cq_v1_mrp_balanced_v1
cq_v1_mrp_anchor_v1
```

The temporal population builder may not retune weights, transforms, support rules or candidate membership.

## Reproducibility

Artifacts pin both the temporal sampling contract SHA-256 and selection-config SHA-256. Observation IDs are contiguous across emitted rows and remain collision-free when candidates are skipped. Checkpoint/resume validates immutable invocation and contract identity before appending.

Outputs are immutable research files only:

```text
data/research/cq_v1_temporal_population_v1_<timestamp>/
  observations.jsonl
  summary.json
  checkpoint.json
```

No reconstructed history is written into `research_entry_quality_shadow`.

## Execution discipline

Before the full 45-date population is produced:

1. exact-head CI and Codex review must pass;
2. historical lookup queries are inspected on gurkdb with EXPLAIN/index verification;
3. one-as-of / one-asset smoke is run from an isolated worktree;
4. resume/idempotency is exercised;
5. a bounded broader smoke is benchmarked;
6. only then is the complete population generated and its artifact hashes frozen.

Forward labels and outcome statistics are outside this slice and remain unopened until the population artifact is frozen.

## Safety

```text
research_only=1
market_only=1
account_awareness=0
outcomes_read=0
model_retuning=0
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
