# Regime Selector Backtest V1

## Purpose

`regime_selector_backtest_v1` measures whether selection_engine strategy behavior is better
explained by global market regime, asset class regime, a global × class cross, or strategy
signature properties derived from existing strategy outputs.

This is a **measurement tool only**. It does not select assets, route strategies, or produce
advice. It populates a research table that informs future regime selector design.

---

## Research-only boundary

This backtest is:
- **Market-only** — no account_id, no balances, no positions, no open orders, no execution plans.
- **Account-agnostic** — no sleeve logic, no broker calls, no live order submission.
- **Research-only** — writes only to `regime_selector_backtest_observation_v1`.

Every row in the output table carries `source_ref_json` with:

```json
{
  "scope": "research-only market-only account-agnostic",
  "broker_calls": 0,
  "broker_writes": 0,
  "order_submission": 0,
  "live_orders": 0
}
```

---

## Paper / live parity

Regime classification is **not paper or live specific**. The regime selector measures market
structure and strategy state — it has no knowledge of, and no dependency on, execution mode.

Paper/live mode belongs outside the strategy and regime layers:

```
regime selector (market-only measurement)
    ↓
policy_router design
    ↓
decision_gate  ← paper/live parity enforced here
    ↓
execution_planner
    ↓
executor
```

Do not add `risk_mode`, `PAPER_ONLY`, or any execution-mode flag to this layer.

---

## Strategy must not be manually horizon-selected

The regime selector's job is to **discover** which market regime properties predict which
strategy behavior, and at which horizon. Horizon is a backtest measurement parameter, not
a regime input.

Incorrect pattern (DO NOT DO):
```python
# Bad — manually assigning horizon based on regime
if regime == "GLOBAL_RISK_ON":
    horizon = 24
elif regime == "GLOBAL_BTC_BREAKDOWN":
    horizon = 4
```

Correct pattern: run the backtest across all horizons, let the data show which (regime, horizon)
combinations produce statistically meaningful separation, then design the downstream routing based
on those findings.

---

## Selector modes

The backtest stores one row per `(report, version, selector_mode, strategy_signature, asset, venue, interval, ts, horizon)`.
This allows all regime dimensions to coexist in the same table without overwriting.

| selector_mode       | Primary analysis dimension  |
|---------------------|-----------------------------|
| `GLOBAL`            | `global_regime`             |
| `ASSET_CLASS`       | `asset_class_regime`        |
| `GLOBAL_CLASS`      | `global_class_regime` (cross) |
| `STRATEGY_SIGNATURE`| `strategy_signature`        |
| `EXPERIMENTAL`      | custom / future use         |

All regime columns are stored on every row regardless of `selector_mode`, so any dimension
can be queried independently after the fact.

---

## Regime classifications

### Global regime (v1)

Based on BTC 24h return and average alt outperformance:

| Label                    | Condition                                              |
|--------------------------|--------------------------------------------------------|
| `GLOBAL_BTC_BREAKDOWN`   | BTC 24h < −5%                                         |
| `GLOBAL_BTC_OVERHEATED`  | BTC 24h > +8%                                         |
| `GLOBAL_ROTATION_WINDOW` | BTC < +4%, average alt outperformance > +4% above BTC |
| `GLOBAL_RISK_ON`         | BTC 24h > +1%                                         |
| `GLOBAL_NEUTRAL`         | BTC 24h ∈ [−1%, +1%]                                 |
| `GLOBAL_UNKNOWN`         | BTC candle data absent                                 |

### Asset class regime (v1)

Based on class 24h return relative to BTC 24h return:

| Label             | Condition                                              |
|-------------------|--------------------------------------------------------|
| `CLASS_RISK_OFF`  | Class vs BTC < −5%                                    |
| `CLASS_STRESS`    | Class vs BTC < −2%                                    |
| `CLASS_OVERHEATED`| Class 24h > +10%                                      |
| `CLASS_LEADERSHIP`| Class vs BTC > +4%                                    |
| `CLASS_PULLBACK`  | BTC positive, class 24h negative                      |
| `CLASS_LAGGARD`   | Class vs BTC < −1%                                    |
| `CLASS_NEUTRAL`   | Otherwise                                             |
| `CLASS_UNKNOWN`   | Class candle data absent                              |

### Asset classes

| Class     | Examples                                                  |
|-----------|-----------------------------------------------------------|
| `BTC`     | BTC                                                       |
| `ETH`     | ETH                                                       |
| `MEME`    | PEPE, DOGE, SHIB, FLOKI, BONK, WIF, MOG, BOME            |
| `DEFI`    | UNI, AAVE, RUNE, LDO, GMX, CRV, PENDLE, ENA              |
| `AI`      | FET, RNDR, WLD, TAO, VIRTUAL, AIXBT                       |
| `L1_L2`   | SOL, AVAX, ADA, ARB, OP, SUI, APT, TON, HYPE             |
| `INFRA`   | LINK, GRT, PYTH, XRP, VET, HBAR, BAND                    |
| `OTHER`   | Everything else                                           |

### Strategy signature

Combines five strategy layer fields into a single bucketing key:

```
{selection_state}|{setup_filter_state}|{policy_decision}|{advice_state}|{aplus_bucket}
```

When an optional table is absent, its component is `UNKNOWN`. The signature is always
non-null so the UNIQUE KEY constraint works correctly.

---

## Input tables

| Table | Required | Usage |
|-------|----------|-------|
| `selection_state` | Yes | Snapshot discovery, selection fields |
| `obs_market_candle` | Yes | Current price, forward price, BTC context, MFE/MAE |
| `trade_setup_filter_observation` | No | `setup_filter_state`, `setup_filter_reason` |
| `trade_setup_policy_preview_observation` | No | `policy_decision`, `setup_filter_state` |
| `paper_advice_observation` | No | `advice_state`, `advice_action`, `aplus_bucket`, `policy_decision` |

Optional tables are resolved via `information_schema`. If absent, the corresponding fields
are `NULL` and strategy signature tokens become `UNKNOWN`.

Column precedence for overlapping fields:
`paper_advice_observation` > `trade_setup_policy_preview_observation` > `trade_setup_filter_observation`

Candle column presence (`high_price`, `low_price`) is discovered at runtime via `SHOW COLUMNS`.
MFE/MAE are skipped if either column is absent.

---

## Output table

`regime_selector_backtest_observation_v1`

Key schema points:
- UNIQUE KEY: `(report_name, report_version, selector_mode, strategy_signature, asset_id, venue, interval_code, asof_ts_utc, horizon_hours)`
- `strategy_signature` is `NOT NULL` — the UNIQUE KEY requires it.
- Reruns with the same identity overwrite via `ON DUPLICATE KEY UPDATE`.
- Different `report_version` values coexist, enabling comparison across backtest configurations.

---

## CLI reference

```
python -m src.research.run_regime_selector_backtest_v1 [OPTIONS]

  --venue            Exchange venue (default: bitvavo)
  --interval         Candle interval for price lookups (default: 4h)
  --from-ts          Optional lower bound on asof_ts_utc (ISO format)
  --to-ts            Optional upper bound on asof_ts_utc (ISO format)
  --limit-snapshots  Max distinct snapshots to load (default: 180)
  --horizons         Forward return horizons in hours (default: 4 24 72)
  --min-group-n      Min observations per group in aggregate tables (default: 8)
  --limit-groups     Max rows per aggregate table (default: 12)
  --selector-modes   Which selector modes to write (default: all four)
  --write-db         Write to DB (omit for dry run)
  --output           Output format: table (default) or json
```

Smoke test:

```bash
python -m src.research.run_regime_selector_backtest_v1 \
  --venue bitvavo \
  --interval 4h \
  --limit-snapshots 120 \
  --horizons 4 24 72 \
  --min-group-n 6 \
  --write-db \
  --output table
```

---

## Downstream path

This backtest is the **first step** only. The correct downstream sequence is:

```
1. regime_selector_backtest_v1 (this tool)
   → identifies which regime dimensions produce meaningful outcome separation

2. regime selector candidates
   → human review of backtest findings; candidate regime rules proposed

3. active_regime_observation design
   → live regime classification table (reads market data only)
   → no decision_gate, no execution_planner, no executor changes

4. policy_router design
   → maps (active_regime, strategy_state) → routing decision
   → designed as a pure read layer on top of regime observation

5. optional selection / advice integration
   → only after regime selector and policy_router are validated
   → integration reviewed against decision_gate boundary
```

Do **not** skip steps. Do **not** add decision_gate, execution_planner, or executor changes
based on backtest findings alone.

---

## What this tool does not do

- Does not place orders (live or paper).
- Does not call any broker or exchange API.
- Does not bypass `decision_gate`.
- Does not modify `execution_planner`.
- Does not instruct `executor`.
- Does not implement paper/live parity logic.
- Does not manually select horizons for regime routing.
- Does not read account state, balances, sleeve configurations, or positions.
