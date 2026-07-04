# Native SHORT Map Scope Seed Canary V1

## Purpose

`native_short_map_scope_seed_canary_v1` is a manual-only, market-only runner for
seeding explicit `native_short_map_scope_v1` rows after verifying the requested
Bitvavo EUR market is eligible in canonical `venue_market` + `asset`.

Initial intended canary:

```text
BTC
```

## Boundary

This runner does not call account, wallet, portfolio, selection, decision,
execution, broker, UI, scheduler, cron, systemd, materializer, or backfill layers.
It does not enumerate the Bitvavo universe; every symbol must be requested
explicitly.

It reads:

```text
venue_market
asset
native_short_map_scope_v1
```

It writes only (INSERT only; never UPDATE, DELETE, or overwrite):

```text
native_short_map_scope_v1
```

## Eligibility

A requested symbol is eligible when exactly one canonical `venue_market` row
exists that joins to the requested `asset` row and has:

```text
venue_market.venue='bitvavo'
venue_market.market='<SYMBOL>-EUR'
venue_market.quote_currency='EUR'
venue_market.is_market_data_enabled=1
venue_market.is_tradeable=1
asset.symbol='<SYMBOL>'
asset.is_enabled=1
```

`NULL`, missing, `0`, or non-integer flag values fail closed. Zero matching
rows fail with `VENUE_MARKET_NOT_FOUND`; more than one matching canonical row
fails with `AMBIGUOUS_VENUE_MARKET`. Candidate rows are always fetched with
`fetchall()` so duplicate canonical rows are never hidden.

## Existing Scope Semantics

All scope rows for the full six-part canonical key
`(venue, symbol, quote_currency, fib_trading_horizon, primary_interval,
supporting_interval)` are fetched:

- zero rows and eligible market: `planned` in dry-run, `seeded` after `--write`;
- exactly one identical `SUPPORTED` row with `NULL` reason fields: `skipped`
  (`SCOPE_ALREADY_SUPPORTED`), no write;
- exactly one `NOT_APPLICABLE` or otherwise different row: `failed`
  (`SCOPE_CONFLICT`), no write;
- more than one canonical row: `failed` (`AMBIGUOUS_SCOPE`), no write.

Existing rows are never normalized, updated, or overwritten.

## Result Statuses

Each per-symbol `RESULT` carries exactly one status:

```text
planned  dry-run only: the canonical SUPPORTED row would be inserted
seeded   write mode only: the canonical SUPPORTED row was inserted and committed
skipped  identical canonical SUPPORTED row already exists; nothing written
failed   ineligible, ambiguous, conflicting, or errored; nothing written
```

The final summary line reports deterministic counts:

```text
requested planned seeded skipped failed
```

The summary event is `FINISHED` when `failed=0`, otherwise `FAILED`.
Exit codes: `0` success, `1` any `failed` result, `2` usage error
(no symbols, or `--write` with more than one symbol).

## Dry-Run

Default mode writes nothing and never begins, commits, or rolls back a
transaction. Multiple explicit symbols are allowed in dry-run.

```bash
python -m src.market_data.run_native_short_map_scope_seed_canary_v1 \
  --symbols BTC \
  --output summary
```

## Explicit Write

Write mode requires `--write` and accepts exactly one explicit symbol.
Zero or multiple symbols are rejected with exit code `2` before any DB
connection is opened. The single accepted symbol runs in one transaction;
the scope read uses `FOR UPDATE`, and any insert failure rolls back fully.

```bash
python -m src.market_data.run_native_short_map_scope_seed_canary_v1 \
  --symbols BTC \
  --write \
  --output summary
```

For BTC, a successful `seeded` result writes exactly:

```text
venue=bitvavo
symbol=BTC
quote_currency=EUR
fib_trading_horizon=SHORT
primary_interval=4h
supporting_interval=1h
scope_support_state=SUPPORTED
scope_reason_code=NULL
scope_reason_detail=NULL
```

## Reason Codes

```text
VENUE_MARKET_NOT_FOUND   no canonical venue_market row for venue/market/quote/symbol
AMBIGUOUS_VENUE_MARKET   more than one canonical venue_market row
MARKET_DATA_NOT_ENABLED  venue_market.is_market_data_enabled is not 1
MARKET_NOT_TRADEABLE     venue_market.is_tradeable is not 1
ASSET_NOT_ENABLED        asset.is_enabled is not 1
AMBIGUOUS_SCOPE          more than one canonical scope row
SCOPE_CONFLICT           existing scope row differs from the exact canonical SUPPORTED row
SCOPE_ALREADY_SUPPORTED  identical canonical SUPPORTED row exists (status skipped)
```

Unexpected execution errors surface the exception class name as the reason code.

## Safety Markers

Expected runner output includes:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```
