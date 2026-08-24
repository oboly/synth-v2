# Bitvavo Venue Execution Constraint Sync V1

## Purpose

`bitvavo_venue_execution_constraint_sync_v1` is the canonical refresh writer
for the `venue_execution_constraint` table: tick size, quantity step size,
min base quantity, min quote notional, supported order types, and supported
time-in-force for every active Bitvavo market quoted in a given currency
(EUR by default).

It closes the writer gap identified in #509: the table's reader/contract
side (`src/market_rules/venue_execution_constraints_v1.py`, fail-closed
MISSING/STALE/FRESH resolution) and Bitvavo-specific transform
(`src/market_rules/bitvavo_venue_adapter_v1.py`, pure function, already
implemented and tested) existed with no owned process to actually populate
the table on an ongoing basis — every row had been static since the one-time
seed migration on 2026-07-25 (`db/migrations/20260725_manual_execution_ladder_p0_safety_v1.sql`).

Public-API-only runner. No authentication required, no broker write calls.

It does not:

- read or use account balances, positions, or holdings to decide which
  markets to sync
- call any private/authenticated Bitvavo endpoint
- submit, cancel, or modify orders
- write to `decision_gate`, `execution_planner`, or `executor` state
- change the existing freshness threshold
  (`DEFAULT_MAX_METADATA_AGE_SECONDS`, 7 days) consumed by
  `resolve_venue_execution_constraints`
- invent a default value for a market with missing/malformed source fields

## Truth model

`venue_execution_constraint` is the sole source of execution-metadata truth
for `decision_gate`/`execution_planner`/automatic-BUY and -exit runtime
consumers (`src/entry_policy/automatic_buy_runtime_repository_v1.py`,
`src/exit_policy/automatic_exit_runtime_repository_v1.py`). This runner is
the only process that writes that table. It performs a full DB-first upsert
each run — the DB row for a market is always the last value this runner
observed from Bitvavo's public API for that market at
`metadata_synced_ts_utc`; it does not merge with or fall back to any
hardcoded per-asset table.

A market with no row, or a row older than the reader's freshness threshold,
correctly resolves `MISSING`/`STALE` and blocks the automatic-BUY/exit path —
this runner does not change that contract, only keeps the table current so
fresh resolution is reachable.

## Files

| File | Role |
|------|------|
| `src/market/run_bitvavo_venue_execution_constraint_sync_v1.py` | Runner — public API fetch + DB upsert |
| `src/market_rules/bitvavo_venue_adapter_v1.py` | Pure Bitvavo row -> `VenueExecutionConstraints` transform (pre-existing, unchanged) |
| `src/market_rules/venue_execution_constraints_v1.py` | Contract, DB read, fail-closed resolver (pre-existing, unchanged) |
| `src/execution/bitvavo_client.py` (`BitvavoClient.for_public`) | Public HTTP client used for `/v2/markets` (pre-existing, unchanged) |

## What it upserts

Only `venue_execution_constraint`, keyed on the table's existing
`UNIQUE KEY uq_venue_execution_constraint_market (venue, market)`:

- **INSERT** a market seen for the first time
- **UPDATE** an existing market whose metadata changed
- **no-op** (rowcount 0) an existing market whose metadata is byte-identical
  to what Bitvavo currently reports — reruns against unchanged source state
  never touch `updated_ts_utc` or create duplicate rows

A market present in the requested quote-currency universe but rejected by
the transform (missing a required field, or `status != "trading"`) is
reported as skipped and is **not written** — its existing row (or absence)
is left exactly as-is, so it continues to fail closed at the resolver.

## Scope: all active markets for the quote currency, not account holdings

`--quote-filter` (default `EUR`) selects the market universe directly from
Bitvavo's public response (`quote` field) — never from what any account
currently holds or trades. This keeps the table market-only and
account-agnostic, and means a market becomes resolvable as soon as it starts
trading on Bitvavo, before any account is configured to trade it.

## Usage

Dry-run (no DB writes, public API only):

```bash
python -m src.market.run_bitvavo_venue_execution_constraint_sync_v1 \
  --venue bitvavo --quote-filter EUR --output summary
```

Write mode:

```bash
python -m src.market.run_bitvavo_venue_execution_constraint_sync_v1 \
  --venue bitvavo --quote-filter EUR --write-db --output summary
```

Expected summary output:

```
STARTED runner=bitvavo_venue_execution_constraint_sync_v1 mode=write venue=bitvavo quote_filter=EUR
runner=bitvavo_venue_execution_constraint_sync_v1 version=0.1
venue=bitvavo
eur_market_count=430
resolved_count=430
skipped_count=0
inserted=422
updated=0
unchanged=8
broker_private_calls=0
broker_writes=0
order_submission=0
decision_gate=none
execution_planner=none
executor=none
FINISHED runner=bitvavo_venue_execution_constraint_sync_v1 elapsed_s=1.4
```

## Owner and cadence

**Owner: `gurkdb` (DB host).** This is the single documented production
owner for `venue_execution_constraint` writes; no other process or host may
write this table.

**Cadence: manual/on-demand for now.** No systemd timer/service is installed
by this change. #509 delivers the writer and a controlled one-shot run for
#456 Stage B acceptance only; timer activation is a separate, explicitly
reviewed follow-up. Bitvavo market metadata (tick size, step size, minimums)
changes infrequently — a daily cadence is expected to be sufficient once a
timer is introduced, matching the existing 7-day
`DEFAULT_MAX_METADATA_AGE_SECONDS` freshness margin with comfortable
headroom — but no timer is enabled as part of this change.

## Safety markers

```
broker_private_calls=0
broker_writes=0
order_submission=0
decision_gate=none
execution_planner=none
executor=none
db_writes=venue_execution_constraint_upsert_only
```
