# Short Swing Map Outcome Baseline V1

**Type:** Research-only baseline  
**Status:** P0-A implementation contract  
**Safety:** market-only, SELECT-only, no DB writes, no broker calls, no orders

## Purpose

Build a replay-safe baseline for native `SHORT` swing map outcomes.

V1 reconstructs the native map known at replay timestamp `T`, extracts target,
reload, and invalidation levels from native history payload only, then measures
forward `4h` candle outcomes.

## Source-Of-Truth Rule

Historical reconstruction uses append-only native lifecycle/history tables only:

- `native_short_map_v1`
- `native_short_map_generation_event_v1`
- `native_short_map_lifecycle_event_v1`

`native_short_map_scope_v1` is a current scope registry, not append-only
historical payload, and is not used for historical reconstruction.

Current-snapshot CSV artifacts are prohibited for historical reconstruction:

- no as-of-T map choice from current CSV
- no lifecycle reconstruction from current CSV
- no target/reload/invalidation levels from current CSV
- no rollover, map identity, or conclusions from current CSV
- no fallback to current CSV when native history is incomplete

If a current-snapshot CSV is ever compared, it must be labelled
`NON_HISTORICAL_DIAGNOSTIC` and must not feed baseline rows or summaries.
V1 does not perform that diagnostic.

## Native Table Inventory

`native_short_map_v1`

- Primary key: `map_id`
- Map-cycle lineage: `map_cycle_id`, `previous_map_id`, `previous_map_cycle_id`
- Effective timestamp: `published_at_utc`
- Market observation metadata: `market_snapshot_ts_utc`
- Recorded timestamp: `created_at_utc`
- Historical payload: anchors, `target_levels_json`, `invalidation_price`,
  `invalidation_rule`, `map_payload_json`

`native_short_map_generation_event_v1`

- Primary key: `generation_event_id`
- Map-cycle lineage: `generation_attempt_id`, `candidate_map_cycle_id`,
  `candidate_previous_map_id`, `map_id`
- Event timestamp: `event_ts_utc`
- Recorded timestamp: `created_at_utc`
- Historical role: append-only generation attempt ledger; `PUBLISHED` rows
  confirm map publication by attempt and `map_id`

`native_short_map_lifecycle_event_v1`

- Primary key: `lifecycle_event_id`
- Map-cycle lineage: `map_id`, `successor_map_id`
- Event timestamp: `event_ts_utc`
- Recorded timestamp: `created_at_utc`
- Historical role: append-only lifecycle ledger; terminal rows close a map

## Known By T

A native row is known by replay timestamp `T` only when both are true:

- its effective/event timestamp is `<= T`
- its recorded timestamp `created_at_utc` is `<= T`

For `native_short_map_v1`, the effective timestamp is `published_at_utc`.
For generation and lifecycle events, the effective timestamp is `event_ts_utc`.

Rows with an older effective timestamp but `created_at_utc > T` are post-T
revisions and are excluded. This is the explicit no-leakage rule for V1.

## Map Choice

For each `(symbol, T)` sample:

1. Keep only native map rows known by `T`.
2. Require a known `PUBLISHED` generation event for the map's
   `published_generation_attempt_id` and `map_id`.
3. Keep only lifecycle events known by `T`.
4. Treat maps with no lifecycle event, or latest lifecycle event `ACTIVATED`,
   as active.
5. Select the newest active map by `(published_at_utc, map_id)`.
6. If no active map exists, emit `DATA_UNAVAILABLE`.
7. If publication or required payload is incomplete, emit `HISTORY_INCOMPLETE`.

No current snapshot is used as a fallback.

## Replay Population

Default symbol discovery uses only append-only `PUBLISHED` generation rows
observable inside the requested replay window:

- `event_ts_utc >= start_ts_utc`
- `event_ts_utc <= end_ts_utc`
- `created_at_utc <= event_ts_utc`

Sample points use the same rule. A later-recorded ledger row with an effective
event timestamp inside the window must not create a historical `(symbol, T)`
sample. A symbol first introduced after the replay window must not enter the
default symbol universe or consume a default slot.

Explicit `--symbols` remains an explicit user-supplied scope, but samples still
come only from observable in-window `PUBLISHED` generation rows.

## Selected-Context Provenance

Every emitted baseline row includes the append-only ledger identities used to
justify the selected context:

- `published_generation_source_table`
- `published_generation_row_id`
- `published_generation_event_ts_utc`
- `published_generation_recorded_ts_utc`
- `published_generation_provenance_status`
- `published_generation_provenance_reason`
- `lifecycle_source_table`
- `lifecycle_row_id`
- `lifecycle_event_ts_utc`
- `lifecycle_recorded_ts_utc`
- `lifecycle_provenance_status`
- `lifecycle_provenance_reason`
- `map_id`
- `map_cycle_id`
- `selection_reason`

When no lifecycle row is required or known by `T`, lifecycle provenance columns
are still emitted with empty row/timestamp fields and:

```text
lifecycle_provenance_status=NO_LIFECYCLE_ROW_KNOWN_BY_T
lifecycle_provenance_reason=ACTIVE_BY_ABSENCE_OF_LIFECYCLE_EVENT_KNOWN_BY_T
```

## Outcome Rule

V1 uses forward `obs_market_candle` rows only for outcome measurement.

- Candles at or before `T` are not future outcome candles.
- The default forward window is 12 `4h` candles.
- Bullish maps hit targets when candle high reaches the next target.
- Bullish maps hit invalidation when candle low reaches invalidation.
- Bearish maps use the inverse high/low comparisons.
- If target and invalidation touch in the same candle, outcome is
  `AMBIGUOUS_SAME_CANDLE`.

## Output Layout

Runner:

```bash
python -m src.research.run_short_swing_map_outcome_baseline_v1 \
  --start-ts 2026-06-01T00:00:00Z \
  --end-ts 2026-07-01T00:00:00Z \
  --symbols WLD,NEAR \
  --write-files
```

Generated files:

```text
data/research/short_swing_map_outcome_baseline_v1/<run_id>/
  baseline_rows.csv
  baseline_rows.jsonl
  summary_by_status.csv
  provenance_manifest.json
```

Generated artifacts are research outputs and should not be committed unless
explicitly requested and reviewed.

## Safety Markers

The runner reports:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
db_writes=0
```

It does not import or call broker, account, UI, selection, decision gate,
execution planner, or executor modules.
