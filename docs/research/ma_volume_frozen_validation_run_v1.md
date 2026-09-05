# MA / Volume Frozen Historical Validation Run v1

Issue: #310

Status: research-only executable evidence lane

## Purpose

Close the remaining empirical gap in #310 without creating a second sampling or
future-label framework.

This run reuses two already-frozen immutable research artifacts only as
substrate:

```text
#661 temporal population
population_sha256=61bab264b2921b93a25a22ec0d12cbc031ad0ef234fa989b2ea43c894bc263b4
rows=19520
asofs=45
assets=445

#684 temporal forward outcomes
outcomes_sha256=2c1b3b9e17e6e06eec3831ac47b48bfd91944730cf9c6e75929979a795727500
rows=58560
horizons=1h,4h,24h
```

The CQ model family is not consumed as #310 truth. The frozen artifacts provide
only observation identity, asset/venue/as-of, chronological split, the frozen
baseline fields, and future outcome labels.

## Canonical flow

```text
immutable #661 observation identity + D/V/H split
+ immutable #684 future labels
+ canonical obs_market_candle 4h history <= observation as-of
-> #310 ma_volume_candidate_features_v1
-> frozen per-observation candidate rows
-> ma_volume_incremental_validation_v1
-> split/horizon-specific raw + baseline-controlled rank evidence
```

No sampling dates, split membership or forward labels are regenerated here.

## Frozen baseline

The preregistered baseline is:

```text
baseline_identity=frozen_cq_temporal_observation_composite_baseline_v1
selection_score
trade_quality_score
```

These values are copied verbatim from the frozen #661 observation population.
They are controls for incremental-information measurement, not a new production
ranking contract.

## Frozen candidate family

The feature contract is the already-reviewed #310 candidate seam:

```text
model_id=ma_volume_candidate_features
model_version=1.0
interval=4h
slope_bars=6

close_vs_sma50_pct
close_vs_sma150_pct
close_vs_sma200_pct
sma50_slope_pct_6b
sma150_slope_pct_6b
sma200_slope_pct_6b
bullish_ma_stack
volume_ratio_20
```

No threshold, color band, lifecycle class or feature selection is tuned by the
runner.

## PIT candle contract

For every frozen observation:

1. read only `obs_market_candle`;
2. use only `venue=bitvavo`, `interval_code=4h`;
3. use candle closes `<= observation as-of`;
4. query a bounded 240-bar retrieval window;
5. require the final 206 candle closes to form an exact contiguous 4h grid
   ending at the observation as-of;
6. reuse `ma_volume_candidate_features_v1`; do not recalculate MA/volume
   primitives in this runner.

The 206-bar requirement is the minimum history needed for SMA200 plus the frozen
6-bar SMA slope. The 240-bar query window is retrieval overlap only. It does not
change the feature lookback.

If exact/as-contiguous history is unavailable, candidate values remain null with
an explicit status. No earlier latest-row fallback, interpolation or imputation
is allowed.

`obs_market_candle` is keyed by asset/venue/interval rather than market pair.
The feature builder still requires a grouping label, so the runner derives a
deterministic internal grouping key from the frozen observation identity:
`asset:<asset_id>@<venue>`. It never reads current `venue_market` state. Later
pair listings, delistings or quote-market changes therefore cannot alter a
rerun of the same frozen population.

## Outcome contract

Every frozen population observation must have exactly one frozen outcome row for
each preregistered horizon:

```text
1h
4h
24h
```

Only `status=COMPLETE` exposes `forward_return_pct` to the validation metric.
Incomplete labels remain null and affect sample counts explicitly.

Outcome asset, venue, split and as-of identity must match the candidate
observation exactly.

## Validation

A full run evaluates the frozen candidate family unchanged on all three
chronological splits and all three frozen horizons.

For each candidate, horizon and split the existing validation harness reports:

- raw candidate/outcome sample count;
- baseline-complete partial sample count;
- raw Spearman;
- partial Spearman after controlling for the frozen baseline.

The full D/V/H evaluation is intentionally one preregistered execution after the
candidate family, baseline and horizons are frozen. Do not inspect one split and
then change feature definitions before opening the others.

Bounded smoke runs write candidate/validation artifacts but intentionally do not
call the split-complete evaluator.

## Immutable output and resume

Fresh output directories must not already exist.

The runner checkpoints after each as-of. `--resume` binds the exact invocation
and selected observation-ID hash. If an interruption leaves uncheckpointed
candidate rows, resume truncates them back to the checkpointed prefix before
continuing. A terminal `FINISHED` output is immutable and cannot be resumed;
`--resume` fails closed for it instead of trusting previously written artifacts.

Final artifacts:

```text
data/research/ma_volume_frozen_validation_v1_<timestamp>/
  candidate_observations.jsonl
  validation_rows_1h.jsonl
  validation_rows_4h.jsonl
  validation_rows_24h.jsonl
  validation_report_1h.json
  validation_report_4h.json
  validation_report_24h.json
  manifest.json
  checkpoint.json
```

Artifact SHA-256 values are persisted in the manifest.

## Required runtime sequence

Per `src/research/AGENTS.override.md`:

1. inspect `EXPLAIN`/indexes for the bounded 4h candle query;
2. one-as-of / one-asset smoke;
3. resume the same interrupted/bounded output;
4. several assets across all three frozen outcome horizons;
5. interrupt/resume smoke;
6. only then execute the full 45-as-of frozen population.

The broad run remains read-only against the database.

## Result disposition

After the immutable full-run artifacts are frozen, #310 must record an explicit
evidence disposition for each candidate family:

```text
RETAIN
REJECT
RESEARCH_FURTHER
```

No threshold or production promotion is implied by a positive correlation.
Any production use requires its own accepted contract.

## Safety

```text
research_only=1
market_only=1
db_writes=0
production_ranking_changes=0
selection_engine_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_activation=0
```
