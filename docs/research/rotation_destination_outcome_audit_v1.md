# Rotation Destination Outcome Audit V1

## Purpose

Backtest whether dashboard rotation destinations have positive forward outcomes before changing destination tuning. The audit was added after the KITE case showed that market-only or low-evidence destinations can fail quickly.

## Runner

```bash
python -m src.research.run_rotation_destination_outcome_audit_v1 --help
```

Generated outputs are ignored by git under:

```text
data/research/rotation_destination_outcome_audit_v1/
```

If `--output-dir` is not supplied, each run writes into a unique timestamped run directory:

```text
data/research/rotation_destination_outcome_audit_v1/run_<YYYYMMDDTHHMMSSZ>/
```

If `--output-dir` is supplied, that path is used exactly.

Generated files per run:

```text
event_table_v1.csv
event_table_v1.jsonl
event_table_dedup_destination_v1.csv
event_table_dedup_destination_v1.jsonl
summary_by_confidence_v1.csv
summary_by_reason_v1.csv
summary_by_confidence_dedup_v1.csv
summary_by_reason_dedup_v1.csv
summary_by_curve_sanity_dedup_v1.csv
manifest_v1.json
report_v1.md
```

## Inputs

The runner is research-only and market-only by default. It reads:

- `paper_advice_observation` for historical source and destination advice snapshots.
- `obs_market_candle` for as-of closes, forward returns, and 24h adverse/favorable excursions.
- `asset` for enabled/tradeable market universe access through existing Market Breath helpers.
- `aplus_table1_report` and `aplus_table1_row` for point-in-time A+ freshness/context at or before each event as-of.

It reuses the dashboard destination helpers where possible:

- `market_candidate_quality_score`
- `rank_market_candidates`
- `target_state_for_advice`
- `risk_state_for_advice`
- `classify_fast_lifecycle`
- `classify_entry_zone_state`
- `classify_price_progress_state`
- `preview_next_zones`
- `classify_policy_block_display`
- `evaluate_rotation_destination_eligibility`
- `destination_confidence`

## Event Definition

For each sampled `paper_advice_observation.asof_ts_utc`, the runner ranks destination candidates using the same market-candidate score used by the rotation preview. It emits one event for every destination whose score is greater than the source symbol score. Clean destinations and excluded/low-confidence destinations are both retained so outcomes can be compared instead of filtered away.

The raw event table is source-weighted: the same destination can repeat for the same `asof_ts` when multiple held source symbols point to it.

Per event fields:

- `asof_ts`
- `source_symbol`
- `destination_symbol`
- `destination_score`
- `destination_eligible`
- `destination_confidence`
- `destination_exclusion_reasons`
- `aplus_state`
- `aplus_freshness`
- `curve_sanity_label`
- `source_rotation_state`
- `destination_policy_label`
- `return_1h`
- `return_4h`
- `return_24h`
- `return_72h`
- `max_adverse_excursion_24h`
- `max_favorable_excursion_24h`

Forward return horizons use the first candle close at or after the target horizon for the selected interval. For example, on `--interval 4h`, `return_1h` uses the next available 4h candle close because 1h candles are not being read.

If `--to-ts` includes recent snapshots without enough future candles for a horizon, that horizon is left blank for those events. Summaries aggregate only available numeric values per metric.

## Destination-Dedup View

The runner also writes a destination-dedup view to remove repeated `asof_ts + destination_symbol` rows from the summary layer.

Dedup key:

- `asof_ts`
- `destination_symbol`

Dedup row choice:

- highest `destination_score`
- deterministic tie-breaker: `source_symbol` ascending

This produces a destination-dedup perspective that is less sensitive to how many current source holdings happened to point at the same destination on the same snapshot.

## Comparison Buckets

`summary_by_confidence_v1.csv` groups outcomes by:

- `HIGH_CONFIDENCE_DESTINATION`
- `MEDIUM_CONFIDENCE_DESTINATION`
- `LOW_CONFIDENCE_DESTINATION`
- `MARKET_ONLY_DESTINATION`

`summary_by_reason_v1.csv` groups outcomes by confidence labels, curve labels, evidence labels, destination exclusion reasons, policy labels, and clean-vs-excluded buckets. Key labels include:

- `MISSING_APLUS_CONTEXT`
- `STALE_APLUS_CONTEXT`
- `APLUS_AVOID_OR_DISTORTED`
- `CURVE_NO_UP_SIGNAL`
- `CURVE_DOWN_PRESSURE`
- `CURVE_WEAK`
- `CLEAN_DESTINATION`
- `EXCLUDED_OR_LOW_CONFIDENCE_DESTINATION`

Destination-dedup summaries:

- `summary_by_confidence_dedup_v1.csv`
- `summary_by_reason_dedup_v1.csv`
- `summary_by_curve_sanity_dedup_v1.csv`

Use the raw summaries for source-weighted portfolio-pressure interpretation, and the dedup summaries for per-destination outcome interpretation.

`report_v1.md` shows raw row count vs destination-dedup row count, plus raw-by-confidence and dedup-by-confidence tables.

## Safety

The runner does not write to the database and does not call any broker, executor, execution planner, or decision gate path. Manifest safety markers are required:

```json
{
  "db_writes": 0,
  "broker_calls": 0,
  "broker_writes": 0,
  "order_submission": 0,
  "live_orders": 0
}
```

## Smoke Command

```bash
python -m src.research.run_rotation_destination_outcome_audit_v1 \
  --venue bitvavo \
  --interval 4h \
  --from-ts 2026-05-01T00:00:00Z \
  --to-ts 2026-05-31T23:59:59Z \
  --symbols KITE TAO HYPE NEAR RENDER SOL INJ \
  --max-events 200 \
  --write-files \
  --output table
```

This writes only research files by default. Use `--no-write-files` for stdout-only checks.

Without `--output-dir`, files are written under a unique `run_*` directory.

## Full Run Example

```bash
python -m src.research.run_rotation_destination_outcome_audit_v1 \
  --venue bitvavo \
  --interval 4h \
  --from-ts 2026-01-01T00:00:00Z \
  --to-ts 2026-05-31T23:59:59Z \
  --sample-step-hours 24 \
  --max-events 5000 \
  --output table
```

For an explicit location on a GamePC or other larger run host:

```bash
python -m src.research.run_rotation_destination_outcome_audit_v1 \
  --venue bitvavo \
  --interval 4h \
  --from-ts 2026-01-01T00:00:00Z \
  --to-ts 2026-05-31T23:59:59Z \
  --sample-step-hours 24 \
  --max-events 5000 \
  --output-dir data/research/rotation_destination_outcome_audit_v1/gamepc_full_20260531 \
  --output table
```
