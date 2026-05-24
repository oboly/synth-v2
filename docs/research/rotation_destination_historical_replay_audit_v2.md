# Rotation Destination Historical Replay Audit V2

## Purpose

`rotation_destination_historical_replay_audit_v2` reconstructs destination candidates per historical sample timestamp from market-only point-in-time state, then measures forward outcomes.

This is deliberately different from V1:

- V1 audits existing snapshot outputs.
- V2 replays candidate construction historically and does **not** use paper advice snapshots as candidate source.

## Scope And Boundaries

- Research-only.
- Market-only.
- Account-agnostic.
- No broker calls, broker writes, or order submission.
- No account/portfolio/balance/open-order table usage.
- No decision gate, execution planner, or executor behavior changes.

Leakage boundaries:

- Replay input state is bounded at or before each `sample_ts_utc`.
- Future candles are used only for outcome measurement.
- `paper_advice_observation` is not used as candidate source.
- If a source is unsafe/ambiguous for historical replay, it should be excluded and documented.

## Runner

```bash
python -m src.research.run_rotation_destination_historical_replay_audit_v2 --help
```

Default output root:

```text
data/research/rotation_destination_historical_replay_audit_v2/
```

Each run writes to:

```text
data/research/rotation_destination_historical_replay_audit_v2/run_<YYYYMMDDTHHMMSSZ>/
```

Use `--output-root` to override the root; run subdirectories remain `run_<UTC_RUN_ID>/`.

Generated output directories under this root are ignored by git.

## CLI

- `--venue`
- `--interval`
- `--start-ts`
- `--end-ts`
- `--sample-every-n`
- `--max-samples`
  - `0` means unlimited
- `--top-n-destinations`
- `--horizons-hours`
  - accepts either spaced values like `4 8 12 24 48`
  - or comma-separated input like `4,8,12,24,48`
- `--write-files` / `--no-write-files`
- `--output-root`

## Replay Flow

For each historical sample timestamp:

1. Build market-only observations with as-of filtering at `sample_ts_utc`.
2. Reconstruct weak-source to strong-destination candidate rows deterministically.
3. Assign confidence, curve sanity, setup/policy preview states.
4. Measure forward outcomes at configured horizons.
5. Emit raw events.
6. Dedup by `sample_ts_utc + destination_symbol` with:
   - highest `destination_score`
   - tie-breaker `source_symbol` ascending
7. Emit summaries and leakage guard report.

## Confidence Terminology Note

`market_breath_confidence` in the underlying observation rows means coverage or measurement availability only.

It is:

- not trend probability
- not phase stability
- not forward-return confidence

To make this less ambiguous in v2 outputs, the event tables also expose:

- `measurement_coverage_score`

The existing `confidence_bucket` labels remain unchanged for backward compatibility, even though names such as `HIGH_CONFIDENCE_DESTINATION` should not be read as predictive certainty.

## Output Files

- `manifest_v2.json`
- `event_table_raw_historical_replay_v2.csv`
- `event_table_raw_historical_replay_v2.jsonl`
- `event_table_dedup_destination_historical_replay_v2.csv`
- `event_table_dedup_destination_historical_replay_v2.jsonl`
- `summary_by_confidence_historical_replay_v2.csv`
- `summary_by_confidence_included_only_v2.csv`
- `summary_by_confidence_excluded_only_v2.csv`
- `summary_by_reason_historical_replay_v2.csv`
- `summary_by_destination_symbol_historical_replay_v2.csv`
- `summary_by_symbol_and_confidence_v2.csv`
- `summary_by_curve_sanity_historical_replay_v2.csv`
- `summary_by_symbol_and_curve_sanity_v2.csv`
- `summary_by_market_regime_historical_replay_v2.csv`
- `summary_by_rank_bucket_historical_replay_v2.csv`
- `leakage_guard_report_v2.json`

Event-table additive alias field:

- `measurement_coverage_score`

## Manifest And Leakage Guard

`manifest_v2.json` and `leakage_guard_report_v2.json` include:

- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `account_tables_used=false`
- `paper_advice_snapshots_used=false`
- `max_input_ts_gt_sample_ts_rows=0` (required pass condition)

`manifest_v2.json` also includes terminology alias metadata so downstream readers can distinguish:

- coverage or measurement availability
- bucket naming kept for backward compatibility

## Smoke Examples

Comma-separated horizons with unlimited samples:

```bash
python -m src.research.run_rotation_destination_historical_replay_audit_v2 \
  --venue bitvavo \
  --interval 4h \
  --start-ts 2026-05-01T00:00:00Z \
  --end-ts 2026-05-31T23:59:59Z \
  --sample-every-n 6 \
  --max-samples 0 \
  --top-n-destinations 10 \
  --horizons-hours 4,8,12,24,48 \
  --write-files \
  --output table
```

Spaced horizons:

```bash
python -m src.research.run_rotation_destination_historical_replay_audit_v2 \
  --venue bitvavo \
  --interval 4h \
  --start-ts 2026-05-01T00:00:00Z \
  --end-ts 2026-05-31T23:59:59Z \
  --sample-every-n 6 \
  --max-samples 5 \
  --top-n-destinations 10 \
  --horizons-hours 4 8 12 24 48 \
  --write-files \
  --output table
```
