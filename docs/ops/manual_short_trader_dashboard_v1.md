# Manual Short Trader Dashboard V1

## Purpose

`manual_short_trader_dashboard_v1` provides a read-only HTML snapshot of open
broker orders and balances, enriched with price-distance metrics and review
labels, grouped per symbol with BUY and SELL ladders displayed separately.

It does not:

- submit orders
- cancel orders
- write to any database
- make broker write calls
- create `decision_gate` permission
- create `execution_planner` intent
- enable `executor`

## Files

| File | Role |
|------|------|
| `src/reporting/manual_short_trader_dashboard_v1.py` | Pure computation and HTML/JSON rendering — no broker imports |
| `src/reporting/run_manual_short_trader_dashboard_v1.py` | Runner — only file that imports `BitvavoClient` and makes private read calls |

## Layer boundary

`manual_short_trader_dashboard_v1.py` (pure module):

- accepts raw broker dicts as plain Python dicts
- no `BitvavoClient` import
- no `src.common.db` import
- no `src.execution.*` imports beyond what normalizes the raw dicts
- safe to test without any broker credentials

`run_manual_short_trader_dashboard_v1.py` (runner):

- imports `BitvavoClient` for ticker price and optional private reads
- calls `get_open_orders()` and `get_balance()` only when `--live-broker` is
  passed
- never calls `place_order`, `cancel_order`, or any write path
- all broker private reads are still gated by the existing
  `SYNTH_BROKER_PRIVATE_READ_PERMISSION` env variable in `BitvavoClient`

## Labels

| Label | Condition |
|-------|-----------|
| `NEAR_SELL` | Sell order within 2 % above current price |
| `NEAR_BUY` | Buy order within 2 % below current price |
| `FILLED_REVIEW_NEEDED` | Partial fill detected (`0 < filled < amount`) |
| `MANUAL_ONLY` | Always present; marks that orders are placed manually |

## Usage

Offline mode (public ticker prices only, no orders):

```bash
python -m src.reporting.run_manual_short_trader_dashboard_v1 \
  --markets WLD-EUR ONDO-EUR \
  --output-html /tmp/short_trader_dashboard.html \
  --output summary
```

Live read-only mode (requires `SYNTH_BROKER_PRIVATE_READ_PERMISSION` env):

```bash
SYNTH_BROKER_PRIVATE_READ_PERMISSION=I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA \
python -m src.reporting.run_manual_short_trader_dashboard_v1 \
  --markets WLD-EUR ONDO-EUR \
  --live-broker \
  --output-html /tmp/short_trader_dashboard.html \
  --output-json /tmp/short_trader_snapshot.json \
  --fib-map-rows data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv \
  --output summary
```

## Fib map merge

When `--fib-map-rows` points to an existing `fibo_target_map_rows_v1.csv`, the
runner loads T1 / next-extension / reload targets and shows them as a compact
fib context row below each symbol's order tables.

## Safety markers

```
broker_writes=0
order_submission=0
db_writes=0
db_reads=0
executor=none
```
