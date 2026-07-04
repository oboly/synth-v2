# Market Signal Snapshot Inventory Contract v1

## Purpose

P0-B Market Signal Snapshot Inventory is a market-only, research-only,
read-only inventory of canonical signal/context primitives that already exist
in Synth v2. It makes per-symbol, per-timeframe source state explicit,
including provenance, coverage, and freshness.

The inventory is non-predictive. It does not establish trading edge, predictive
value, strategy promotion, recommendation, order intent, trade direction,
capital allocation, or account permission.

## Non-Goals

This layer must not:

- create strategy logic, selection logic, ranking, confidence, score, or action
  labels;
- read balances, positions, orders, wallets, account settings, broker state, or
  API secrets;
- call `selection_engine`, `decision_gate`, `execution_planner`, executor,
  agent, broker, account, or dashboard-policy loaders;
- write operational runtime truth;
- submit orders, create live/paper execution intent, or enable live trading;
- treat Breathline, A+, narratives, or external notes as strategy authority.

## Runner

Module:

```bash
python -m src.research.build_market_signal_snapshot_inventory_v1 \
  --symbols BTC,ETH,SOL \
  --venue bitvavo \
  --as-of-ts-utc 2026-06-05T12:00:00Z \
  --native-short-context-rows data/research/native_short_fib_context_v1/native_short_fib_context_rows_v1.csv
```

Required inputs:

- `--symbols`: comma-separated explicit symbols. Symbols are never inferred from
  an account, wallet, profile, or dashboard scope.
- `--venue`: explicit venue.
- `--as-of-ts-utc`: UTC as-of timestamp. If omitted, the CLI uses current UTC.
- `--native-short-context-rows`: canonical native SHORT context rows CSV source.
- `--output-dir`: optional output root override. The runner always creates the
  deterministic `run_id` subdirectory under this root.

Default output root:

```text
data/research/market_signal_snapshot_inventory_v1/<run_id>/
```

Generated files are research artifacts and are not intended for git.

## Source Inventory

The v1 registry is limited to verified canonical sources:

- native SHORT map context status from
  `src.market_data.native_short_fib_context_v1`;
- native SHORT 4h lifecycle state from `NativeShortContextRow`;
- native SHORT 1h support/alignment state from `NativeShortContextRow`;
- native SHORT freshness and map lineage fields from `NativeShortContextRow`;
- 4h local MA/ATR context from
  `src.market_context.local_ma_atr_context_v1`;
- 4h impulse-health state from
  `src.market_context.impulse_health_state_v1`;
- derived 4h extension-context state from
  `src.market_context.market_context_builder_v1`;
- 4h and 1h `obs_market_candle` availability/freshness.

Known exclusions in v1:

- RSI;
- volume or participation signals;
- rotation signals;
- support/resistance or breakout families not already present in the native
  SHORT context row;
- BTC-relative signals;
- Breathline and A+ rows.

The extension context builder contains display hints in its source module. This
inventory records only the existing extension state and input states; it excludes
profit-plan bias and action-sounding display labels from snapshot rows.

## `signal_registry.json`

Array of registry entries. Every entry contains:

- `signal_id`: stable unique signal identifier.
- `signal_family`: canonical source family.
- `technical_meaning`: human explanation of what the source measures.
- `source_module`: module or table that owns the source.
- `source_function_or_artifact`: function, field, artifact, or read path.
- `timeframe`: source timeframe such as `4h`, `1h`, or `4h+1h`.
- `raw_value_type`: JSON type shape of `raw_value`.
- `normalized_state_semantics`: how `normalized_state` is interpreted.
- `freshness_source`: timestamp source used for freshness summaries.
- `coverage_semantics`: how coverage is classified.
- `available_in_v1_runner`: boolean availability in this runner.

## `signal_snapshot_rows.jsonl`

One JSON object per symbol/signal/timeframe. Required fields:

- `symbol`
- `as_of_ts_utc`
- `timeframe`
- `signal_id`
- `signal_family`
- `raw_value`
- `normalized_state`
- `source_module`
- `source_record_id`
- `source_lineage`
- `freshness_ts_utc`
- `coverage_status`
- `availability_status`
- `error_status`

Missing, stale, partial, invalid, and unavailable states remain explicit.
Fallback values are never substituted as if they were canonical.

Native SHORT missing-data behavior:

- if the native SHORT source file is missing, each requested symbol still emits
  native rows with `coverage_status=SOURCE_MISSING` and
  `availability_status=DATA_UNAVAILABLE`;
- if the source file exists but a symbol row is missing, that symbol still emits
  native rows with explicit unavailable state;
- native lineage is preserved when present: `map_cycle_id`, current map status,
  previous map cycle/state, rollover state, selection reason, source references,
  source name/version, 4h lifecycle, and 1h support state.

Candle behavior:

- candle reads are bounded to `close_ts_utc <= as_of_ts_utc`;
- future candles returned by a fake or unexpected source are defensively filtered
  before snapshot construction;
- no row count is presented as independent sample size.

## Coverage Semantics

Coverage statuses:

- `AVAILABLE`: source value is present and not stale/partial.
- `PARTIAL`: source exists but canonical state is incomplete, insufficient, or
  low confidence.
- `STALE`: canonical state or latest source timestamp is stale.
- `SOURCE_MISSING`: required source row or bounded candle source is missing.
- `DATA_UNAVAILABLE`: source exists but cannot provide the value.

Availability statuses:

- `AVAILABLE`
- `DATA_UNAVAILABLE`

## `coverage_summary.csv`

One row per signal/timeframe:

- `signal_id`
- `timeframe`
- `eligible_symbols`
- `available_symbols`
- `partial_symbols`
- `stale_symbols`
- `unavailable_symbols`
- `error_symbols`

Counts are state coverage counts only. They are not statistical sample sizes.

## `freshness_summary.csv`

One row per signal/timeframe:

- `signal_id`
- `timeframe`
- `freshest_timestamp`
- `oldest_available_timestamp`
- `stale_count`
- `missing_timestamp_count`

## `manifest.json`

Manifest fields:

- `schema_version`
- `runner_name`
- `runner_version`
- `generated_at_ts_utc`
- `as_of_ts_utc`
- `run_id`
- `venue`
- `explicit_symbols`
- `source_artifact_paths`
- `source_module_versions`
- `row_counts`
- `artifact_filenames`
- `artifact_sha256`
- `manifest_hash_note`
- `safety_statement`

`run_id` is deterministic from schema version, venue, explicit symbols,
as-of timestamp, native SHORT source path, and candle lookback. By default,
`generated_at_ts_utc` is tied to the as-of timestamp for reproducible artifacts;
test callers may inject the same timestamp explicitly.

`manifest.json` receives a deterministic SHA-256 over the canonical manifest
payload before `artifact_sha256.manifest.json` is embedded. This avoids
self-referential file-byte hash instability while keeping a reproducible
manifest hash preimage.

## Reproducibility

For identical fixture inputs, as-of timestamp, symbols, venue, source path,
candle lookback, and output root override, the generated artifact bytes are
deterministic.

The runner writes only to its output directory. Unit tests use fake native rows
and fake candles instead of a live database.

## Architecture Boundaries

Correct data flow for this runner:

```text
canonical source row / bounded candle observation
-> market-context source builder where already canonical
-> inventory row
-> research artifact
```

Forbidden flows:

```text
inventory -> selection
inventory -> decision_gate
inventory -> execution_planner
inventory -> executor/order
inventory -> broker
inventory -> account mutation
dashboard/reporting -> source policy
external narrative -> signal authority
```

Safety markers for runner output:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```
