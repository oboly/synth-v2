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

- the per-account dashboard render refreshes or reuses shared fib-map context
  before Profit Plan render
- the canonical account-scoped outputs are:
  - `/var/www/html/synth/accounts/<profile>/profit-plan.html`
  - `/var/www/html/synth/accounts/<profile>/profit-plan.json`
- browser links must use the public href
  `/synth/accounts/<profile>/open-orders-monitor.html`
  rather than a filesystem output path
- the legacy global `/synth/profit-plan.html` prototype is deprecated after
  account-scoped replacement verification

Identity model:

- `--account-profile` selects dashboard/output identity
- explicit profile access config resolves the account-scoped trading account
- the current DB still accepts a legacy stable trading-account ref through
  `trading_account.account_code`, but Profit Plan does not derive this from the
  profile name
- unmapped profiles fail closed with `PROFILE_HAS_NO_ACCOUNT_ACCESS`
- stale public prices fail closed as `STALE_CURRENT_PRICE`; Profit Plan hides
  percentage-distance and action-style output until public price refresh succeeds

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
| `src/reporting/run_manual_short_trader_profit_plan_v1.py` | Runner — account-scoped DB snapshot loader + shared fib context join |
| `src/market_data/native_short_fib_context_v1.py` | Canonical market-only native SHORT 4h/1h row contract |
| `src/market_data/run_native_short_fib_context_v1.py` | Deterministic native SHORT bridge builder / coverage runner |

## Map Lifecycle Rollover and MAP_COMPLETED Reporting

When the selected native SHORT candidate has `primary_4h_lifecycle_state=MAP_COMPLETED`:

- No active targets are shown (all sell levels have been historically reached or passed).
- The scenario shows `MAP_COMPLETED / WAIT_FOR_NEW_MAP` with reasons limited to the
  completion context — no active-target language is appended.
- `previous_target_levels` records the historically passed levels for audit.
- `rollover_state` and `current_map_status` on the native row surface whether a newer
  active map has already replaced it.

Candidate selection priority (highest to lowest):

1. Any active/developing state — not COMPLETED, not INVALIDATED.
2. MAP_COMPLETED — historical reference only, shown if no newer valid map exists.
3. INVALIDATED — never becomes active output context.

Within each tier, the newest `anchor_end_ts_utc` wins.

The reporting layer must never append active-scenario reasons to a MAP_COMPLETED card.
`_completed_map_override()` replaces (not appends to) the scenario reason tuple.

## View Toggle

The dashboard has a client-side toggle at the top:

| View | Shows |
|------|-------|
| **Relevant candidates** (default) | Symbols with TAKE_PROFIT_NEAR, REBUY_ZONE_NEAR, BUY_DIP, BREAKOUT_WATCH, REENTRY_WAIT, RANGE_BOUNCE, BREAKOUT_RETEST |
| **All candidates** | Every symbol with a loaded plan, including FAR_MOONBAG_ONLY, DO_NOT_TOUCH, NO_CLEAR_PLAN |

When **All candidates** is selected, a sticky client-side search field appears.
It filters instantly and case-insensitively across symbol, market, scenario,
primary state, action, horizon, and context statuses.

The selected view and search query are saved to profile-scoped `localStorage`
keys and restored on page reload so Joost/Hugo UI state does not bleed across
profiles.

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
| `fib_trading_horizon` | currently `SHORT` for the Profit Plan surface |
| `short_context_input_status` | raw source/input state such as `NATIVE_SHORT_CONTEXT_AVAILABLE`, `INSUFFICIENT_4H_HISTORY`, or `ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING` |
| `short_context_coverage_status` | explicit truth state such as `NATIVE_SHORT_CONTEXT_AVAILABLE`, `LEGACY_1D_CONTEXT_ONLY`, or `FIB_MAP_SYMBOL_MISSING` |
| `short_context_display_state` | human-facing SHORT-context warning state |
| `timeframe_label` | "15m scalp", "4h bounce", "1d swing" |
| `market` | Bitvavo market code shown on the card |
| `current_price` | Current public price snapshot |
| `existing_open_orders summary` | Read-only summary of open buys / sells already present |
| `target_exit_zone` | Fib extension targets |
| `active_target` | Next still-upcoming target used for distance-to-target and state alignment |
| `target_level_statuses` | Per-level lifecycle and order-coverage audit rows |
| `reload_reentry_zone` | Fib retrace levels used for manual reload planning |
| `invalidation_risk_zone` | Risk / invalidation level for the current setup |
| `distance_to_target_pct` | Signed percent distance from current price to the active upcoming target |
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
- `POST_EXTENSION_PULLBACK` → `Post-extension pullback`
- `MAP_RECOMPUTE_NEEDED` → `Map recompute needed`
- `DO_NOTHING` → `Do nothing`
- `NO_NATIVE_SHORT_FIB_CONTEXT` → `No native SHORT fib context`
- `MARKET_DATA_MISSING` → `Market data missing`
- `CONTEXT_INVALID_OR_STALE` → `Context invalid or stale`
- `INSUFFICIENT_DATA` → `Insufficient data`

Rules:

- These states are display-only. They are not order instructions.
- No order creation, cancellation, or modification happens here.
- Missing usable zone data no longer collapses automatically into generic
  `INSUFFICIENT_DATA` when a fresher truth state is known.
- Cards always link back to **Open Orders Monitor** when the linked HTML exists.
- `--monitor-html` is a filesystem output path only; `--monitor-href` is the
  public browser href used in rendered anchor tags.

## Target Lifecycle And Order Coverage

Profit Plan now treats each fib sell level as its own lifecycle item.

Per target level:

- market-only lifecycle is one of `UPCOMING`, `NEAR`, `REACHED`, `PASSED`, `COMPLETED`
- account-aware coverage is audited separately per level
- lifecycle uses market history since map activation where available, not current price alone
- lifecycle is monotonic: `REACHED`, `PASSED`, and `COMPLETED` never regress back to `NEAR` or `UPCOMING` because price pulled back
- when every mapped sell target is historically passed, Profit Plan switches to `scenario_type=MAP_COMPLETED`, sets `action_label=WAIT_FOR_NEW_MAP`, clears `active_target`, and removes old passed targets from `Active target / exit zone`
- passed levels never remain the `active_target`
- `distance_to_target_pct` always uses the next active upcoming target, never an already passed level
- a passed level with no fill evidence is shown as `PASSED_UNFILLED` with human wording `missed sell level`
- explicit fill evidence may show `REACHED_FILLED` or `COMPLETED`
- passed-level open orders are split between `MISSED_ORDER` and `OPEN_ORDER_AFTER_PASSED_LEVEL` when first-cross timing is available
- open sell orders are matched per individual level using bounded tolerance; broad sell-zone proximity does not count as coverage for every level

The full sell zone remains visible, but Profit Plan distinguishes:

- previous / reached levels
- the active next target
- later targets still ahead
- pullback / retest context after a passed target is shown separately and does not reactivate the old sell target

## Input Coverage Audit

`run_manual_short_trader_profit_plan_input_audit_v1.py` audits whether each market
has enough read-only inputs to show a useful Profit Plan card before cockpit wiring.

SHORT fib-context truth rule:

- canonical SHORT is `4h` primary with `1h` support
- Profit Plan now prefers the canonical market-only
  `data/research/native_short_fib_context_v1/native_short_fib_context_rows_v1.csv`
  bridge
- native SHORT is available only when the row status is
  `NATIVE_SHORT_CONTEXT_AVAILABLE`
- an existing `1d` fib-map row must never be reported as native SHORT context
- the `1d` fib-map remains reference-only fallback when native SHORT is absent

Zone-context input preference:

- first per symbol: manual CLI anchors via `--swing-anchors` and optional `--recent-lows`
- otherwise: canonical native SHORT rows from
  `data/research/native_short_fib_context_v1/native_short_fib_context_rows_v1.csv`
- final fallback: existing read-only
  `data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv`
- if the zone source is absent or the symbol is not present, Profit Plan fails closed and reports the exact reason

Open orders are enrichment only. A card can remain visible without open orders when
current price and zone context exist.

Open-order input preference:

- first: existing DB-backed `account_open_order_snapshot` read-only snapshot source
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

Zone-context input status values:

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

SHORT coverage status values:

- `NATIVE_SHORT_CONTEXT_AVAILABLE`
- `INSUFFICIENT_4H_HISTORY`
- `INSUFFICIENT_1H_HISTORY`
- `LEGACY_1D_CONTEXT_ONLY`
- `FIB_MAP_SYMBOL_MISSING`
- `FIB_MAP_SOURCE_MISSING`
- `MARKET_DATA_MISSING`
- `CONTEXT_INVALID_OR_STALE`

Expected examples:

- symbol with a valid native `4h` primary + `1h` support row →
  `NATIVE_SHORT_CONTEXT_AVAILABLE`
- a native `1h` row may be `ALIGNED_WITH_4H`, `RETEST_SUPPORTIVE`,
  `NEUTRAL_OR_NOT_CONFIRMING`, or `CONFLICT_WITH_4H`; only the last one implies
  a genuine contradiction
- `PLUME` with fresh price but no fib row → `FIB_MAP_SYMBOL_MISSING` /
  `NO_NATIVE_SHORT_FIB_CONTEXT`
- symbol with a native row but missing canonical support window →
  `INSUFFICIENT_1H_HISTORY` / `NO_NATIVE_SHORT_FIB_CONTEXT`
- symbol with a valid current `1d` fib-map row → `LEGACY_1D_CONTEXT_ONLY` /
  `NO_NATIVE_SHORT_FIB_CONTEXT`
- a `LEGACY_1D_CONTEXT_ONLY` card may still display ladder levels, completed-map
  history, and order-audit coverage for reference, but it must render as
  `scenario_type=LEGACY_CONTEXT_REFERENCE_ONLY` and `action_label=MANUAL_REVIEW`
  instead of native SHORT action semantics

## Acceptance Examples

### WLD-like (EXTENSION_RUNNER / TAKE_PROFIT_NEAR)

```
scenario_type = EXTENSION_RUNNER
action_label  = TAKE_PROFIT_NEAR
sell_zone     = [0.6500]  ← 1.618 extension
reasons       = ["Main target at 1.618 extension (0.6500).",
                 "Watch for round-number confluence near target — strong magnet.",
                 "Momentum supports continuation toward the target / sell zone at <price>."]
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
Account-scoped DB snapshot mode:

```bash
python -m src.reporting.run_manual_short_trader_profit_plan_v1 \
  --account-profile joost \
  --output-root /var/www/html/synth \
  --fib-map-rows data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv \
  --monitor-href /synth/accounts/joost/open-orders-monitor.html \
  --output summary
```

Shared fib-map prerequisite example:

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
  --account-profile joost \
  --output-root /var/www/html/synth \
  --fib-map-rows data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv \
  --swing-anchors WLD:0.30:0.38 FET:0.166:0.244 \
  --recent-lows FET:0.209 \
  --monitor-href /synth/accounts/joost/open-orders-monitor.html \
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
