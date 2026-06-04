# Manual Short Trader Profit Plan Dashboard V1

Legacy/internal name: `manual_short_trader_profit_plan_v1`

User-facing page title: **Profit Plan**

## Purpose

`manual_short_trader_profit_plan_v1` renders the user-facing **Profit Plan**:
a non-technical, scenario-based HTML dashboard for manual short trading review.
It shows *what to watch next* per symbol, not a raw order dump.

The existing **Open Orders Monitor** (`manual_short_trader_dashboard_v1`) remains
the technical audit view. Profit Plan links back to Open Orders Monitor.

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
| `buy_zone` | Fib retrace levels where to place buy orders |
| `sell_zone` | Fib extension targets |
| `invalidation_level` | Level where the scenario is invalid |
| `reasons` | Up to 3 plain-language explanations |
| `order_summary` | Matching active orders + missing suggested orders |

All cards carry: `MANUAL_ONLY — read-only snapshot, no automatic placement`

## Future Profit Plan Cards Backlog

Future Profit Plan cards should explicitly surface:

- Position / market
- Current price
- Existing open orders
- Target/exit zones
- Reload/re-entry zones
- Invalidated / risk zone
- “Do nothing” state
- “Take profit already waiting” state
- “Price ran away” state
- “Reload zone approaching” state
- “Order too far / stale” state
- Link back to Open Orders Monitor
- Safety note: manual-only, no order creation/cancellation

These additions stay display-only. They do not create, cancel, or modify orders.

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
  --swing-anchors WLD:0.30:0.38 FET:0.166:0.244 \
  --recent-lows FET:0.209 \
  --output-html /tmp/profit_plan_v1.html \
  --output summary
```

Live read-only mode (requires `SYNTH_BROKER_PRIVATE_READ_PERMISSION`):

```bash
SYNTH_BROKER_PRIVATE_READ_PERMISSION=I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA \
python -m src.reporting.run_manual_short_trader_profit_plan_v1 \
  --markets WLD-EUR ONDO-EUR FET-EUR \
  --swing-anchors WLD:0.30:0.38 FET:0.166:0.244 \
  --recent-lows FET:0.209 \
  --live-broker \
  --output-html /tmp/profit_plan_v1.html \
  --output-json /tmp/profit_plan_snapshot.json \
  --monitor-html /tmp/manual_short_trader_dashboard_v1.html \
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
