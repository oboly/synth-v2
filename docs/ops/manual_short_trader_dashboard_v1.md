# Manual Short Trader Dashboard V1

Legacy/internal name: `manual_short_trader_dashboard_v1`

User-facing page title: **Open Orders Monitor**

## Purpose

`manual_short_trader_dashboard_v1` provides the read-only HTML behind the user-facing
**Open Orders Monitor**. It shows open broker orders and balances, enriched with
price-distance metrics and review labels, grouped per symbol with BUY and SELL
ladders displayed separately.

Open Orders Monitor is the technical audit view. It is not the scenario/planning page.

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
| `src/reporting/run_manual_short_trader_dashboard_v1.py` | Runner — account-scoped DB snapshot loader + HTML/JSON writer |

## Layer boundary

Open Orders Monitor:

- is audit/read-only open-order visibility
- does not submit or cancel orders
- does not bypass `decision_gate`, `execution_planner`, or `executor`
- remains separate from the Profit Plan scenario page

Any future mutation/action must live in an explicit authenticated UI layer and
must not bypass decision or execution boundaries.

`manual_short_trader_dashboard_v1.py` (pure module):

- accepts raw broker dicts as plain Python dicts
- no `BitvavoClient` import
- no `src.common.db` import
- no `src.execution.*` imports beyond what normalizes the raw dicts
- safe to test without any broker credentials

`run_manual_short_trader_dashboard_v1.py` (runner):

- requires explicit `--account-profile`
- resolves dashboard identity through explicit profile access config in
  `src/reporting/account_dashboard_profile_access_v1.py`
- resolves exactly one `trading_account_id`
- reads only `trading_account_balance_snapshot`, `account_open_order_snapshot`,
  `account_asset`, and shared market-price/fib-map context
- fails closed on unmapped profile access or ambiguous account resolution
- never calls a broker client, `place_order`, `cancel_order`, or any write path

Current configured profile access:

- `joost` → `bitvavo` → legacy stable trading-account ref `bitvavo_joost_read`

Unmapped profiles, including `hugo`, fail closed with:

- `PROFILE_HAS_NO_ACCOUNT_ACCESS`

## Labels

| Label | Condition |
|-------|-----------|
| `NEAR_SELL` | Sell order within 2 % above current price |
| `NEAR_BUY` | Buy order within 2 % below current price |
| `FILLED_REVIEW_NEEDED` | Partial fill detected (`0 < filled < amount`) |
| `MANUAL_ONLY` | Always present; marks that orders are placed manually |

## Usage

Account-scoped render:

```bash
python -m src.reporting.run_manual_short_trader_dashboard_v1 \
  --account-profile joost \
  --output-root /var/www/html/synth \
  --output summary
```

Canonical per-account outputs:

- `/var/www/html/synth/accounts/<profile>/open-orders-monitor.html`
- `/var/www/html/synth/accounts/<profile>/open-orders-monitor.json`
- Profit Plan links back via `/synth/accounts/<profile>/open-orders-monitor.html`

## Fib map merge

When `--fib-map-rows` points to an existing `fibo_target_map_rows_v1.csv`, the
runner loads T1 / next-extension / reload targets and shows them as a compact
fib context row below each symbol's order tables.

## Safety markers

```
broker_writes=0
order_submission=0
db_writes=0
db_reads=1
executor=none
```
