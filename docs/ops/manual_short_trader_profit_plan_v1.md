# Manual Short Trader Profit Plan Dashboard V1

Legacy/internal name: `manual_short_trader_profit_plan_v1`

User-facing page title: **Profit Plan**

## Purpose

`manual_short_trader_profit_plan_v1` renders the user-facing **Profit Plan**:
a non-technical, scenario-based HTML dashboard for manual short trading review.
It shows *what to watch next* per symbol, not a raw order dump.

The existing **Open Orders Monitor** (`manual_short_trader_dashboard_v1`) remains
the technical audit view. Profit Plan links back to Open Orders Monitor.

Cockpit integration:

- the read-only cockpit render refreshes `fibo_target_map_v1` before Profit Plan
  render
- the cockpit publishes Profit Plan at `/var/www/html/synth/profit-plan.html`
- the cockpit may also publish `/var/www/html/synth/profit-plan.json` for the
  read-only snapshot payload
- browser links must use the public href `/synth/open-orders-monitor.html`
  rather than the filesystem output path

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
| `src/reporting/manual_short_trader_profit_plan_v1.py` | Pure computation and HTML/JSON rendering — no broker/DB imports |
| `src/reporting/run_manual_short_trader_profit_plan_v1.py` | Runner — imports BitvavoClient, htf_fib_extension_confluence_v1, htf_fib_reentry_ladder_v1 |

## View Toggle

The dashboard has a client-side toggle at the top:

| View | Shows |
|------|-------|
| **Relevant candidates** (default) | Symbols with TAKE_PROFIT_NEAR, REBUY_ZONE_NEAR, BUY_DIP, BREAKOUT_WATCH, REENTRY_WAIT, RANGE_BOUNCE, BREAKOUT_RETEST |
| **All candidates** | Every symbol with a loaded plan, including FAR_MOONBAG_ONLY, DO_NOT_TOUCH, NO_CLEAR_PLAN |

The selected view is saved to `localStorage` and restored on page reload.

## Separation

- Open Orders Monitor = audit/read-only open-order visibility
- Profit Plan = human-readable scenario planning
- Neither page submits or cancels orders
- Any future mutation/action requires an explicit authenticated UI layer and must not bypass `decision_gate`, `execution_planner`, or `executor`

## Per-Symbol Card

Each card shows:

| Field | Values |
|-------|--------|
| `scenario_type` | EXTENSION_RUNNER, REENTRY_WAIT, RANGE_BOUNCE, BREAKOUT_RETEST, NO_CLEAR_PLAN |
| `action_label` | TAKE_PROFIT_NEAR, REBUY_ZONE_NEAR, BUY_DIP, BREAKOUT_WATCH, WAIT, FAR_MOONBAG_ONLY, DO_NOT_TOUCH |
| `timeframe_label` | "15m scalp", "4h bounce", "1d swing" |
| `market` | Bitvavo market code shown on the card |
| `current_price` | Current public price snapshot |
| `existing_open_orders summary` | Read-only summary of open buys / sells already present |
| `target_exit_zone` | Fib extension targets |
| `reload_reentry_zone` | Fib retrace levels used for manual reload planning |
| `invalidation_risk_zone` | Risk / invalidation level for the current setup |
| `distance_to_target_pct` | Signed percent distance from current price to nearest target |
| `distance_to_reload_pct` | Signed percent distance from current price to nearest reload zone |
| `distance_to_invalidation_pct` | Signed percent distance from current price to invalidation / risk zone |
| `primary_state` | Main display-only manual planning state |
| `secondary_state` | Optional second display-only state when another condition also matters |
| `suggested_manual_attention_label` | Clear user-facing label derived from `primary_state` |
| `reasons` | Up to 3 plain-language explanations |
| `order_summary` | Matching active orders + missing suggested orders |

All cards carry: `MANUAL_ONLY — read-only snapshot, no automatic placement`

## Manual Planning States

Profit Plan v1.1 adds deterministic display-only states:

- `TAKE_PROFIT_WAITING` → `Take profit already waiting`
- `RELOAD_ZONE_APPROACHING` → `Reload zone approaching`
- `PRICE_RAN_AWAY` → `Price ran away`
- `INVALIDATION_NEAR` → `Invalidation / risk zone near`
- `ORDER_TOO_FAR_OR_STALE` → `Order too far or stale`
- `DO_NOTHING` → `Do nothing`
- `INSUFFICIENT_DATA` → `Insufficient data`

Rules:

- These states are display-only. They are not order instructions.
- No order creation, cancellation, or modification happens here.
- Missing usable zone data resolves to `INSUFFICIENT_DATA`.
- Cards always link back to **Open Orders Monitor** when the linked HTML exists.
- `--monitor-html` is a filesystem output path only; `--monitor-href` is the
  public browser href used in rendered anchor tags.

## Input Coverage Audit

`run_manual_short_trader_profit_plan_input_audit_v1.py` audits whether each market
has enough read-only inputs to show a useful Profit Plan card before cockpit wiring.

Zone-context input preference:

- first per symbol: manual CLI anchors via `--swing-anchors` and optional `--recent-lows`
- otherwise: existing read-only `data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv`
- if the zone source is absent or the symbol is not present, Profit Plan fails closed and reports the exact reason

Open orders are enrichment only. A card can remain visible without open orders when
current price and zone context exist.

Open-order input preference:

- first: existing DB-backed `account_open_order_snapshot` read-only snapshot source
- fallback: existing private broker read path only when the runner is explicitly started with `--live-broker`
- no broker write path is introduced

Per market it reports:

- `has_current_price`
- `has_existing_open_orders`
- `open_order_count`
- `zone_context_input_status`
- `has_target_exit_zone`
- `has_reload_reentry_zone`
- `has_invalidation_zone`
- `has_fib_extension_context`
- `has_reentry_ladder_context`
- `has_stale_order_metadata`
- `primary_missing_reason`
- `all_missing_reasons`
- `would_render_state`
- `filtered_by_profit_plan`

Common missing reasons:

- `MISSING_CURRENT_PRICE`
- `MISSING_ZONE_CONTEXT`
- `ZONE_SOURCE_MISSING`
- `ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING`
- `OPEN_ORDER_SOURCE_MISSING`
- `NO_STALE_ORDER_METADATA`
- `READY_FOR_PROFIT_PLAN`

Zone-context status values:

- `HAS_ZONE_CONTEXT`
- `MISSING_ZONE_CONTEXT`
- `ZONE_SOURCE_MISSING`
- `ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING`
- `MANUAL_ZONE_CONTEXT_USED`

Open-order status values:

- `HAS_OPEN_ORDERS`
- `NO_OPEN_ORDERS`
- `OPEN_ORDER_SOURCE_MISSING`

This audit is read-only only. It reuses the same input sources as the Profit Plan
runner where possible and does not change Profit Plan behavior by itself.

## Acceptance Examples

### WLD-like (EXTENSION_RUNNER / TAKE_PROFIT_NEAR)

```
scenario_type = EXTENSION_RUNNER
action_label  = TAKE_PROFIT_NEAR
sell_zone     = [0.6500]  ← 1.618 extension
reasons       = ["Main target at 1.618 extension (0.6500).",
                 "Watch for round-number confluence near target — strong magnet.",
                 "Momentum suggests continuation — hold sells until target."]
```

Requires: `--swing-anchors WLD:0.30:0.38`

### FET-like (REENTRY_WAIT / REBUY_ZONE_NEAR with missed main rebuy)

```
scenario_type = REENTRY_WAIT
action_label  = REBUY_ZONE_NEAR
buy_zone      = [0.2142, 0.2050]  ← r382 and r500
reasons       = ["Last dip missed the main re-buy by 1.95% — tighten the ladder.",
                 "First-touch level (0.2142) would have caught the dip.",
                 "Main re-buy is at 0.2050 — set a limit order there."]
```

Requires: `--swing-anchors FET:0.166:0.244 --recent-lows FET:0.209`

### ONDO-like (RANGE_BOUNCE / BUY_DIP with DEEP_RETRACE profile)

```
scenario_type = RANGE_BOUNCE
action_label  = BUY_DIP
buy_zone      = [0.800, 0.730]  ← r618 and r786
```

## Usage

Offline mode (no broker orders, public prices only):

```bash
python -m src.reporting.run_manual_short_trader_profit_plan_v1 \
  --markets WLD-EUR ONDO-EUR FET-EUR \
  --fib-map-rows data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv \
  --monitor-href /synth/open-orders-monitor.html \
  --output-html /tmp/profit_plan_v1.html \
  --output summary
```

Cockpit render prerequisite for the default WLD/ONDO page:

```bash
python -m src.research.run_fibo_target_map_v1 \
  --symbols WLD,ONDO \
  --write-files \
  --output summary \
  --output-dir data/research/fibo_target_map_v1
```

Manual anchors remain supported and override missing source context for the named symbol:

```bash
python -m src.reporting.run_manual_short_trader_profit_plan_v1 \
  --markets WLD-EUR ONDO-EUR FET-EUR \
  --fib-map-rows data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv \
  --swing-anchors WLD:0.30:0.38 FET:0.166:0.244 \
  --recent-lows FET:0.209 \
  --monitor-href /synth/open-orders-monitor.html \
  --output-html /tmp/profit_plan_v1.html \
  --output summary
```

Live read-only mode (requires `SYNTH_BROKER_PRIVATE_READ_PERMISSION`):

```bash
SYNTH_BROKER_PRIVATE_READ_PERMISSION=I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA \
python -m src.reporting.run_manual_short_trader_profit_plan_v1 \
  --markets WLD-EUR ONDO-EUR FET-EUR \
  --fib-map-rows data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv \
  --live-broker \
  --output-html /tmp/profit_plan_v1.html \
  --output-json /tmp/profit_plan_snapshot.json \
  --monitor-html /tmp/manual_short_trader_dashboard_v1.html \
  --monitor-href /synth/open-orders-monitor.html \
  --output summary
```

## Safety markers

```
broker_writes=0
order_submission=0
db_writes=0
db_reads=0
executor=none
```
