# Native SHORT Map Ledger Health Report V1

## Purpose

`native_short_map_ledger_health_report_v1` is a manual, read-only reporting
runner that inspects the current state of the native SHORT map ledger for
explicitly requested symbols and reports scope, lifecycle, map identity,
generation-chain integrity, and source-candle freshness as explicit
machine-readable fields.

Initial operational target is BTC only. The CLI accepts any explicit symbol
for future read-only inspection but never enumerates a universe.

## Ownership

Owned as a market-only, account-agnostic **reporting/ops observability
lane** under `src/reporting/`:

- `src/reporting/native_short_map_ledger_health_report_v1.py` (core logic)
- `src/reporting/run_native_short_map_ledger_health_report_v1.py` (CLI runner)

It is intentionally not under `src/market_data/`: that namespace owns
market-data acquisition/context (candle ETL, the map materializer, the
scope seeder), not report construction or operational ledger-health
presentation. This report is a read-only, presentation-only sibling to the
native SHORT map ledger canaries that live under `src/market_data/`:

- `native_short_map_materializer_v1.py` / `run_native_short_map_materializer_v1.py`
- `run_native_short_map_scope_seed_canary_v1.py`

It does not depend on, call, or import any of the above. The only
cross-package dependency it takes is
`src.market_data.native_short_map_lifecycle_v1` — the shared, DB-free
lifecycle contract module (dataclasses, enums, and the pure
`project_current_native_short_map_lifecycle` projection function). That
module performs no DB access and is not a market-data producer/acquisition
module, so depending on it does not pull any ledger writer into this
reporting lane. Direct canonical-candle comparison (`obs_market_candle`) is
a raw, local, read-only SQL query in this module — not an imported
dependency on any market-data acquisition code.

## Boundary

This runner never creates, materializes, rebuilds, repairs, or promotes
maps. It never mutates the scope table, the lifecycle table, or the
generation-event table.

It reads only:

```text
native_short_map_scope_v1
native_short_map_v1
native_short_map_generation_event_v1
native_short_map_lifecycle_event_v1
obs_market_candle (latest closed primary/supporting candle timestamp only)
```

It never issues `INSERT`, `UPDATE`, `DELETE`, or DDL, and every connection is
explicitly rolled back and closed after each symbol's report is built.

## Non-Goals

This report does not:

- create, materialize, rebuild, repair, or promote a native SHORT map;
- seed, update, or normalize `native_short_map_scope_v1`;
- invoke the materializer, scope seeder, or any lifecycle-mutation path;
- touch account, wallet, portfolio, broker, or private exchange state;
- touch `selection_engine`, `decision_gate`, `execution_planner`, or
  `executor`;
- import or depend on Breathline, A+, phase, lattice, recovery, prediction,
  or research modules;
- enumerate a symbol universe — every symbol must be requested explicitly;
- infer a buy/sell/hold/reentry/risk instruction, or make any market
  prediction.

## CLI Examples

Default JSONL output for BTC:

```bash
python -m src.reporting.run_native_short_map_ledger_health_report_v1 \
  --symbols BTC
```

Concise summary output, multiple explicit symbols:

```bash
python -m src.reporting.run_native_short_map_ledger_health_report_v1 \
  --symbols BTC,ETH \
  --output summary
```

`--symbols` is comma-separated, deduplicated, and sorted alphabetically
before processing, so output ordering is deterministic regardless of input
order.

## Result Contract

Exactly one `STARTED` event, one `RESULT` event per requested symbol (in
sorted-symbol order), then exactly one `FINISHED` (or `FAILED` if any
symbol's report generation raised) event.

`STARTED` includes the canonical scope defaults (`venue`, `quote_currency`,
`fib_trading_horizon`, `primary_interval`, `supporting_interval`), the
requested symbol list, and the standard safety markers plus `db_writes=0`.

Each `RESULT` carries `status` (`reported` or `failed`) plus every field
described below. `status=failed` means report generation itself raised
(for example, a DB connectivity error); it does not mean the ledger is
unhealthy — ledger health is `overall_health_status`.

`FINISHED`/`FAILED` reports deterministic counts: `requested`, `healthy`,
`not_applicable`, `needs_review`, `failed`, `elapsed_seconds`.

Exit codes: `0` all reports generated successfully, `1` any `status=failed`
report, `2` usage error (no symbols).

## Canonical Scope Key

Every symbol is evaluated against exactly one canonical scope key:

```text
bitvavo / <SYMBOL> / EUR / SHORT / 4h / 1h
```

### Scope Section

- `scope_row_count`: number of `native_short_map_scope_v1` rows found for
  the canonical key.
- `scope_status`: one of `MISSING`, `SUPPORTED`, `NOT_APPLICABLE`,
  `AMBIGUOUS` (more than one row, identical `scope_support_state`), or
  `CONFLICTING` (more than one row, differing `scope_support_state`).
- `scope_status_detail`: human-readable detail behind `scope_status`.
- `scope_support_state`, `scope_reason_code`, `scope_reason_detail`: raw
  stored values, populated only when exactly one scope row exists.

## Lifecycle Semantics

`lifecycle_state` and `lifecycle_state_source` are produced by calling the
canonical projection function
`native_short_map_lifecycle_v1.project_current_native_short_map_lifecycle`
directly — the same pure function the DB view
`native_short_map_current_lifecycle_v1` mirrors. This only runs when
`scope_status` resolves to exactly one row (`SUPPORTED` or
`NOT_APPLICABLE`); otherwise `lifecycle_evaluated=false` and
`lifecycle_state="NOT_EVALUATED"` with `lifecycle_state_source` naming the
unresolved scope status.

## Map Identity, Active-Map Resolution, and Structure

- `map_count`: total `native_short_map_v1` rows for the canonical key,
  independent of scope-row validity.
- `active_map_resolution_status`: `NO_ACTIVE_MAP`, `SINGLE_ACTIVE_MAP`, or
  `AMBIGUOUS_ACTIVE_MAP_CANDIDATES`. This is computed independently from raw
  map + lifecycle-event rows (a map is an "active candidate" when it has no
  lifecycle event, or its latest lifecycle event is `ACTIVATED`), so more
  than one simultaneous candidate is reported explicitly instead of being
  silently resolved by a tie-break. `active_map_candidate_ids` lists every
  candidate in deterministic order.
- `active_map_id` is the resolved candidate (the latest by
  `published_at_utc`, then `map_id`, matching the canonical view's
  tie-break) even when ambiguous; `active_map_resolution_status` is the
  authoritative signal for whether that resolution should be trusted.
- Structure/identity fields (`active_map_structure_hash`,
  `active_map_published_generation_attempt_id`, `active_map_cycle_id`,
  `active_map_previous_map_id`, `active_map_previous_map_cycle_id`,
  `active_map_published_at_utc`, `active_map_market_snapshot_ts_utc`,
  anchor low/high timestamps and prices, `active_map_invalidation_price`,
  `active_map_invalidation_rule`, `active_map_target_levels_json`) are
  reported verbatim from the stored ledger row with no trading
  interpretation. `active_map_target_levels_json` is the raw stored JSON
  payload, not parsed or evaluated.

## Generation-Chain Integrity Semantics

`generation_chain_integrity_status` is derived only from the active map's
own `published_generation_attempt_id` and never assumes a chain is valid
merely because a map row exists:

```text
NO_ACTIVE_MAP               no resolved active map candidate to validate
ATTEMPT_STARTED_MISSING     no ATTEMPT_STARTED event for the attempt
PUBLISHED_EVENT_MISSING     no PUBLISHED event for the attempt
PUBLISHED_MAP_ID_MISMATCH   a PUBLISHED event exists but its map_id
                             does not match the active map
OK                          ATTEMPT_STARTED and PUBLISHED are both present
                             and PUBLISHED.map_id matches the active map
```

`generation_chain_integrity_reason` is a plain-text explanation of the
status above.

## Source Freshness Semantics

Freshness compares each active map's stored source candle timestamp against
the latest available closed candle timestamp for the same
venue/symbol/interval, using the identical `obs_market_candle` join-on-
`asset` query shape already used by the materializer's candle fetch. There
is no `is_closed` column — closedness is an ingest-side guarantee, and
"latest" is simply the maximum stored `close_ts_utc`.

Per-field state (`primary_source_freshness_state`,
`supporting_source_freshness_state`) and the combined
`source_freshness_state` (the least-fresh of the two, in the precedence
order `MISSING > UNAVAILABLE > AHEAD_OR_INCONSISTENT > STALE > CURRENT`):

```text
NO_ACTIVE_MAP           no active map to compare (skipped)
MISSING                 the map's stored source timestamp is absent
UNAVAILABLE             no comparable latest candle exists at all
CURRENT                 stored timestamp equals the latest available timestamp
STALE                   stored timestamp is older than the latest available timestamp
AHEAD_OR_INCONSISTENT   stored timestamp is newer than the latest available timestamp
```

This is a point-in-time comparison only. There is no wall-clock age
threshold and no time-based heuristic anywhere in this calculation.

## Overall Health

`overall_health_status` is one of `HEALTHY`, `NOT_APPLICABLE`, or
`NEEDS_REVIEW`, derived only from the observations above:

- `NOT_APPLICABLE`: `scope_status=NOT_APPLICABLE` and no maps exist under
  that scope (if maps do exist, that is itself flagged as
  `MAPS_EXIST_UNDER_NOT_APPLICABLE_SCOPE` and escalates to `NEEDS_REVIEW`).
- `HEALTHY`: `scope_status=SUPPORTED`, `lifecycle_state=MAP_ACTIVE`, a single
  unambiguous active-map candidate, `generation_chain_integrity_status=OK`,
  and `source_freshness_state=CURRENT`.
- `NEEDS_REVIEW`: anything else. `overall_health_reason_codes` lists every
  contributing reason (for example `SCOPE_AMBIGUOUS`,
  `LIFECYCLE_STATE_MAP_REBUILD_REQUIRED`,
  `GENERATION_CHAIN_PUBLISHED_EVENT_MISSING`,
  `SOURCE_FRESHNESS_STALE`, `AMBIGUOUS_ACTIVE_MAP_CANDIDATES`).

`overall_health_status` and its reason codes are ledger-state observations
only. They carry no buy/sell/hold/reentry/risk instruction and no market
prediction.

## Operational Interpretation Boundary

This report describes what is stored in the ledger and how it compares to
the latest available candle context. It does not evaluate, validate, or
recommend a trading action, and it does not claim that a `HEALTHY` map is a
good trade or that a `NEEDS_REVIEW` map is a bad one. Reviewers must apply
their own judgment; this tool only removes the need to hand-inspect raw
ledger rows.

**This report does not create or change ledger state.** It opens read-only
connections, always rolls back, and never calls the materializer, the scope
seeder, or any lifecycle-mutation code path.

## Safety Markers

Expected runner `STARTED` output includes:

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
