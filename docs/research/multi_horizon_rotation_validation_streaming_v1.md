# Multi-Horizon Rotation Validation Streaming v1

Issue: #593

## Purpose

Evaluate the frozen #593 discovery/validation contract on large canonical JSONL artifacts without materializing the full artifact in memory.

This implementation does **not** change the frozen metrics, baselines, split semantics, candidate family, or holdout policy defined by `multi_horizon_rotation_validation_v1.md`.

## Why this runner exists

The first real discovery artifact contains 3,636,288 rows and is about 2.3 GiB. The original reference runner loads all rows plus a global identity set into Python memory before evaluation. That reference implementation remains useful for small fixtures but is not the production research execution path for multi-million-row artifacts.

## Bounded-memory contract

The streaming runner consumes canonical dataset-builder JSONL in nondecreasing `asof_ts` order and retains only:

- sufficient statistics for pair/partial correlations;
- per `venue + asset_id + candidate_id` temporal state;
- turn indexes required for the frozen lead/lag pairing rule;
- regime aggregates;
- one as-of cohort for exact cross-horizon pairing.

It does not retain all `ValidationRow` objects or all row identities.

Canonical ordering is part of this execution path. An as-of reversal fails closed. Duplicate identities inside an as-of cohort fail closed.

## Semantic equivalence

`tests/test_multi_horizon_rotation_validation_streaming_v1.py` compares the complete streaming summary against the frozen in-memory evaluator on the same synthetic canonical rows, including:

- coverage;
- correlation versus B0/B1;
- forward IC;
- partial correlation versus B0/B1;
- persistence/sign flips/chop;
- cross-horizon correlation;
- Holm-Bonferroni family;
- lead/lag versus B1;
- B0 regime stability.

Tiny floating-point differences from online sufficient-statistic accumulation are accepted only within strict numerical tolerance; metric definitions are unchanged.

## Runner

```text
python -m src.research.run_multi_horizon_rotation_validation_streaming_v1 \
  --input-jsonl <phase_rows.jsonl> \
  --split-manifest <split_manifest_v1.json> \
  --phase discovery|validation \
  --output-json <evaluation.json>
```

There is deliberately no `final_holdout` CLI option.

## Safety

```text
research_only=1
market_only=1
database_reads=0
database_writes=0
account_awareness=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
final_holdout_access=DENY
```
