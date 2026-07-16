# Native SHORT Fib Context Snapshot Contract V1

## Status and purpose

This contract defines the persisted, market-only native SHORT rows snapshot
consumed by a later read-only Profit Plan owner. It replaces no database
authority and does not authorize reporting to produce market truth.

The producer is:

```text
src.market_data.native_short_fib_context_snapshot_v1
src.market_data.run_native_short_fib_context_snapshot_v1
```

It is account-agnostic and reads only persisted public-market authorities. It
does not import reporting, account, selection, decision, planning, execution,
broker, or research packages.

## Canonical owner and path

The only scheduled owner is the existing 4h market chain. Publication runs
exactly once immediately after:

```text
scripts/run_native_short_scope_status_chain_once.sh
```

That predecessor completes map evaluation, scope-status projection, and
map-level status projection. A snapshot failure exits the existing 4h chain
non-zero through `run_step`; the producer never falls back to an older snapshot.
No service, timer, cron entry, or second scheduler is introduced.

Default runtime directory:

```text
/var/www/html/synth/_runtime/native_short_context_snapshot_v1/
```

Direct override:

```text
SYNTH_NATIVE_SHORT_CONTEXT_SNAPSHOT_DIR
--output-dir
```

## Field-by-field source authority

The full canonical scope key applies to every lookup:

```text
venue / symbol / quote_currency / SHORT / 4h / 1h
```

| Snapshot field(s) | Canonical persisted source | Projection rule |
|---|---|---|
| `symbol`, `venue`, `quote_currency`, `fib_trading_horizon`, `primary_interval`, `supporting_interval`, `scope_id`, `scope_support_state` | `native_short_map_scope_v1` | Current inventory only; `NOT_APPLICABLE` produces an explicit `UNAVAILABLE` row. |
| `scope_status_id`, `scope_status_code`, `scope_status_reason_code`, `source_freshness_state`, `observation_freshness_state`, `actionability_state` | `native_short_scope_status_v1` | Forwarded verbatim; the producer does not repeat precedence logic. |
| `native_map_id`, `map_cycle_id`, `primary_4h_lifecycle_state` | `native_short_scope_status_v1.current_map_id`, `current_map_cycle_id`, `map_lifecycle_state` | The projection is the sole current-map selector and lifecycle authority. |
| `latest_primary_close_ts_utc`, `latest_support_close_ts_utc` | `native_short_scope_status_v1.primary_latest_candle_ts_utc`, `supporting_latest_candle_ts_utc` | Absolute persisted timestamps; absence fails closed as `MISSING`. |
| `projection_as_of_utc`, `projection_rebuilt_at_utc`, `latest_observation_id`, `latest_run_id`, `latest_observed_at_utc` | `native_short_scope_status_v1` | Forwarded provenance. `projection_as_of_utc` is the semantic freshness clock. |
| `latest_generation_event_id`, `latest_lifecycle_event_id` | `native_short_scope_status_v1` | Forwarded exact selected IDs. |
| `latest_generation_event_ts_utc` | `native_short_map_generation_event_v1`, by the exact projection ID | Provenance only; never used to select a map or infer freshness. |
| `latest_lifecycle_event_ts_utc` | `native_short_map_lifecycle_event_v1`, by the exact projection ID and selected map | Provenance only; lifecycle state remains projection-owned. |
| `anchor_start_ts_utc`, `anchor_low_price` | selected `native_short_map_v1.anchor_low_ts_utc`, `anchor_low_price` | Verbatim immutable geometry. |
| `anchor_end_ts_utc`, `anchor_high_price` | selected `native_short_map_v1.anchor_high_ts_utc`, `anchor_high_price` | Verbatim immutable geometry. |
| `breakout_gate_price`, `ext_1_272_price`, `ext_1_618_price`, `ext_2_000_price` | selected `native_short_map_v1.fib_ratios_json` named keys | Strict named extraction; no price ordering and no Fib calculation. |
| `reload_r382_price`, `reload_r500_price`, `reload_r618_price`, `reload_r786_price` | selected `native_short_map_v1.fib_ratios_json` named keys | Strict named extraction; no reentry calculation. |
| `invalidation_price` | selected `native_short_map_v1.invalidation_price` | Verbatim immutable geometry. |
| `map_published_at_utc`, `map_structure_hash`, `previous_map_cycle_id` | selected `native_short_map_v1` | Verbatim immutable provenance. |
| `source_primary_ref`, `source_support_ref`, `source_primary_candle_count`, `source_support_candle_count` | selected `native_short_map_v1` | Geometry-source provenance at immutable map publication. |
| `active_target_levels_json` | `native_short_map_level_status_v1` rows for the projection-selected map | Exact named roles whose persisted state is `ACTIVE`. |
| `previous_target_levels_json` | `native_short_map_level_status_v1` rows for the projection-selected map | Exact named roles whose persisted state is `REACHED`, `PASSED`, or `COMPLETED`. `HISTORICAL` is not reinterpreted. |
| `level_status_ids_json`, `level_status_as_of_utc` | `native_short_map_level_status_v1` | IDs are sorted by closed role order; every row as-of must equal projection as-of. |
| `context_freshness_status` | adapter over persisted scope/source/observation status plus authority completeness | Closed family `FRESH`, `STALE`, `MISSING`, `UNAVAILABLE`; producer run time is never an input. |
| `context_status` | compatibility adapter over `context_freshness_status`, projection lifecycle, and completeness | `NATIVE_SHORT_CONTEXT_AVAILABLE` only for complete `FRESH` active/completed authority; otherwise existing fail-closed bridge statuses. |
| `source_name`, `source_version` | snapshot contract | Producer identity, not market freshness. |
| `field_availability_json` | snapshot validation | Explicit status for compatibility fields and projected fields; never presentation inference. |

### Explicitly unavailable current semantics

No accepted persisted current authority exists for these legacy bridge fields:

```text
latest_primary_close_price
supporting_1h_state
max_primary_high_since_anchor
min_primary_low_since_anchor
current_map_status
previous_map_lifecycle_state
rollover_state
```

They are emitted as empty/`UNAVAILABLE` compatibility values and recorded as
`UNAVAILABLE` in `field_availability_json`. In particular, the producer does
not read immutable `map_payload_json` as if its publication-time supporting or
lifecycle interpretation were current.

`previous_map_cycle_id` is available directly from immutable map provenance.
The lifecycle of that previous map is not joined or reconstructed.

## Validation and fail-closed behavior

A row can expose `NATIVE_SHORT_CONTEXT_AVAILABLE` only when all of the
following hold:

- scope is `SUPPORTED` and its current projection exists;
- primary and supporting persisted source timestamps are absolute and present;
- the projection selects one map ID and cycle;
- the exact selected immutable map exists and its cycle matches;
- every required named geometry field is finite and positive;
- exact generation and lifecycle provenance IDs resolve;
- exactly one row exists for each closed V1 SELL role;
- each level row matches map ID, cycle, projection as-of, and immutable named
  geometry price;
- persisted source and observation states are current;
- projection lifecycle is `MAP_ACTIVE` or `MAP_COMPLETED`.

Missing authorities remain visible as a `MISSING` or `UNAVAILABLE` row. Stale
persisted authority remains `STALE`. The producer never fills a missing source
timestamp with `datetime.now()`, database `NOW()`, publication time, an
immutable map timestamp, a CSV, or a research artifact.

## Snapshot identity and canonical serialization

Rows are uniquely sorted by symbol and serialized as canonical JSON with sorted
keys and compact separators. Every source ID and source timestamp that can
change the semantic snapshot is part of the canonical rows payload.

Rebuild-only surrogate/operational fields (`scope_status_id`,
`level_status_ids_json`, `projection_rebuilt_at_utc`) remain present for audit
but are excluded from semantic identity. Rebuilding an otherwise identical
projection therefore does not create a new snapshot merely because rebuildable
row IDs or operational rebuild time changed.

```text
content_digest = SHA-256(canonical row schema + canonical rows)
snapshot_id    = nsctx-v1-<first 24 hex chars of content_digest>
```

Operational `generated_ts_utc`, `publication_ts_utc`, paths, and publication
result do not affect semantic identity. Identical persisted inputs therefore
produce `UNCHANGED` and no new semantic snapshot directory. A changed authority
ID, timestamp, geometry, lifecycle, level state, or freshness state changes the
identity.

## Envelope and freshness summary

The manifest and bundle envelope contain:

```text
schema_version
row_schema_version
snapshot_id
content_digest
generated_ts_utc
publication_ts_utc
source_as_of_timestamps
row_count
counts {supported, fresh, stale, missing, unavailable}
overall_freshness_state
producer {name, version}
safety markers
```

`generated_ts_utc` and `publication_ts_utc` are absolute operational metadata.
They never make a source fresh. Overall freshness uses fail-closed precedence:

```text
MISSING > UNAVAILABLE > STALE > FRESH
```

## Atomic publication protocol

The stable file is only the commit pointer:

```text
manifest_v1.json
```

It references immutable files under:

```text
snapshots/<snapshot_id>/native_short_fib_context_rows_v1.csv
snapshots/<snapshot_id>/snapshot_bundle_v1.json
```

Publication is:

1. build and validate all rows in memory;
2. serialize rows and bundle in memory;
3. write each immutable file through a temp file in the same directory;
4. flush and fsync the file;
5. `os.replace` it;
6. fsync its directory and the immutable snapshot parent;
7. validate digests and paths;
8. write, flush, fsync, and atomically replace `manifest_v1.json` last;
9. fsync the manifest parent directory.

A failure before step 8 can leave an unreferenced immutable file, but cannot
damage or partially advance the last valid snapshot. A reader must resolve the
CSV through `manifest_v1.json`; it must not scan `snapshots/` for the newest
directory.

## CLI

Default execution is read-only/dry-run:

```bash
python -m src.market_data.run_native_short_fib_context_snapshot_v1 --output jsonl
```

Explicit publication:

```bash
python -m src.market_data.run_native_short_fib_context_snapshot_v1 \
  --publish \
  --output summary
```

Exit `0` means `DRY_RUN`, `PUBLISHED`, or validated `UNCHANGED`; exit `1`
means load, contract, or publication failure; argument errors use argparse exit
`2`; interruption exits `130`.

## PR B dependency

PR B may consume only `manifest_v1.json`, validate its schema/digests, and pass
the referenced immutable `native_short_fib_context_rows_v1.csv` to the existing
native SHORT CSV parser. It must not rebuild native context, select a map, join
candles for geometry/lifecycle, or treat the unavailable legacy fields as
authority.

## Safety markers

```text
broker_private_calls=0
broker_calls=0
broker_writes=0
order_submission=0
live_orders=0
account_awareness=0
decision_gate=none
execution_planner=none
executor=none
reporting_writes_market_truth=false
new_scheduler=false
```
