# Native SHORT Map Ledger Materializer Canary v1

Manual canary for market-only population of:

- `native_short_map_v1`
- `native_short_map_generation_event_v1`
- `native_short_map_lifecycle_event_v1`

Safety markers:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

## Boundary

This canary reads supported native SHORT scopes and market candle-derived context only.

It does not read broker, wallet, account, selection, decision gate, execution planner, executor, UI, dashboard, scheduler, cron, or systemd state.

It does not perform historical backfill and does not depend on current-state CSV files.

## Entrypoint

```bash
python -m src.market_data.run_native_short_map_materializer_v1
```

Default mode is dry-run. Database writes require explicit `--write`.

Dry-run may inspect multiple symbols. Write mode is restricted to exactly one
parsed symbol and rejects zero or more than one symbol before opening any DB
connection or transaction.

Each accepted `--write` symbol materialization runs in its own transaction.

## Manual Dry-Run Command

```bash
python -m src.market_data.run_native_short_map_materializer_v1 --symbols BTC --output jsonl
```

Expected behavior:

- builds current market-only native SHORT fib context for `BTC`
- reads existing ledger state
- emits JSON lines with `attempted`, `published`, `skipped`, `failed`, IDs when existing, and reason codes
- performs no DB writes

## Explicit-Write Canary Command For One Symbol

```bash
python -m src.market_data.run_native_short_map_materializer_v1 --symbols BTC --write --output jsonl
```

Expected behavior:

- rejects `--write --symbols BTC,ETH` before any DB connection
- requires `BTC` to already exist as `SUPPORTED` in `native_short_map_scope_v1`
- resolves the scope by the full canonical key: `bitvavo` / symbol / `EUR` / `SHORT` / `4h` / `1h`
- zero matching canonical scope rows returns `SCOPE_NOT_FOUND_OR_NOT_SUPPORTED`
- more than one matching canonical scope row returns `AMBIGUOUS_SCOPE` and does not materialize
- writes at most one symbol attempt in one transaction
- publishes a new immutable map only when current context is available and structure hash is new
- writes `ATTEMPT_STARTED` plus `PUBLISHED` for a new map
- writes `ACTIVATED` for the new map
- writes `SUPERSEDED` for the previous active map only when a new map replaces it
- writes `ATTEMPT_STARTED` plus `REJECTED` when context is unavailable and the same rejection is not already the latest matching rejection

Repeated identical runs are idempotent:

- existing identical map: no new `native_short_map_v1` row
- existing identical map: no duplicate `PUBLISHED` generation event
- existing identical map: no duplicate lifecycle event
- existing same unavailable rejection: no duplicate generation attempt

Duplicate/unique conflicts are safe idempotent outcomes only when the already
visible ledger row matches the intended immutable map identity. Otherwise the
attempt fails closed and the runner rolls back the transaction.

## Read-Only Verification SQL

```sql
SELECT 'native_short_map_v1' AS table_name, COUNT(*) AS row_count
FROM native_short_map_v1
UNION ALL
SELECT 'native_short_map_generation_event_v1' AS table_name, COUNT(*) AS row_count
FROM native_short_map_generation_event_v1
UNION ALL
SELECT 'native_short_map_lifecycle_event_v1' AS table_name, COUNT(*) AS row_count
FROM native_short_map_lifecycle_event_v1;
```

```sql
SELECT
    map_id,
    venue,
    symbol,
    quote_currency,
    fib_trading_horizon,
    primary_interval,
    supporting_interval,
    structure_hash,
    published_generation_attempt_id,
    previous_map_id,
    map_cycle_id,
    market_snapshot_ts_utc,
    published_at_utc,
    anchor_low_ts_utc,
    anchor_low_price,
    anchor_high_ts_utc,
    anchor_high_price
FROM native_short_map_v1
WHERE venue = 'bitvavo'
  AND symbol = 'BTC'
  AND quote_currency = 'EUR'
  AND fib_trading_horizon = 'SHORT'
  AND primary_interval = '4h'
  AND supporting_interval = '1h'
ORDER BY map_id DESC
LIMIT 5;
```

```sql
SELECT
    generation_event_id,
    generation_attempt_id,
    event_type,
    event_ts_utc,
    reason_code,
    map_id,
    trigger_type,
    candidate_map_cycle_id,
    candidate_previous_map_id,
    latest_primary_close_ts_utc,
    latest_support_close_ts_utc
FROM native_short_map_generation_event_v1
WHERE venue = 'bitvavo'
  AND symbol = 'BTC'
  AND quote_currency = 'EUR'
  AND fib_trading_horizon = 'SHORT'
  AND primary_interval = '4h'
  AND supporting_interval = '1h'
ORDER BY generation_event_id DESC
LIMIT 10;
```

```sql
SELECT
    le.lifecycle_event_id,
    le.map_id,
    m.symbol,
    le.lifecycle_event_type,
    le.successor_map_id,
    le.event_ts_utc,
    le.reason_code,
    le.latest_primary_close_ts_utc,
    le.latest_support_close_ts_utc,
    le.observer_name,
    le.observer_version
FROM native_short_map_lifecycle_event_v1 le
JOIN native_short_map_v1 m
  ON m.map_id = le.map_id
WHERE m.venue = 'bitvavo'
  AND m.symbol = 'BTC'
  AND m.quote_currency = 'EUR'
  AND m.fib_trading_horizon = 'SHORT'
  AND m.primary_interval = '4h'
  AND m.supporting_interval = '1h'
ORDER BY le.lifecycle_event_id DESC
LIMIT 10;
```

```sql
SELECT
    symbol,
    lifecycle_state,
    lifecycle_state_source,
    active_map_id,
    latest_authoritative_event_type,
    latest_authoritative_reason_code,
    latest_terminal_lifecycle_event_type,
    latest_skip_reason_code
FROM native_short_map_current_lifecycle_v1
WHERE venue = 'bitvavo'
  AND symbol = 'BTC'
  AND quote_currency = 'EUR'
  AND fib_trading_horizon = 'SHORT'
  AND primary_interval = '4h'
  AND supporting_interval = '1h';
```

## Follow-Up Operational Gaps

- Scope seeding remains a separate explicit operation; this canary does not create `native_short_map_scope_v1` rows.
- Scheduling is not implemented; a future scheduling lane must define host ownership, lock policy, cadence, and duplicate-writer prevention.
- Alerting is not implemented; a future ops lane should alert on `failed > 0`, stale source candles, and open attempts.
- Backfill is not implemented; any historical replay must remain in research/backtest namespaces.
- Promotion criteria for more symbols are not implemented; expand only after one-symbol canary verification.
