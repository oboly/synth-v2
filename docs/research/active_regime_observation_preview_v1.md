# Active Regime Observation Preview V1

**Status:** Migration applied · Runner smoke-tested · DB write verified
**Date:** 2026-05-14
**Validated hypothesis:** H1 only (`GLOBAL_BTC_MILD_DECLINE`)
**Boundary:** market-only · account-agnostic · no paper/live · no broker calls · no orders

---

## Purpose

`active_regime_observation` is a market-only observation layer that records the current
global and asset-class regime state at each run time. It is the live counterpart to the
research-only `regime_selector_backtest_observation_v1` table.

It classifies regime state from candle data only and stores one row per asset class per
snapshot. Nothing it writes is a routing decision, a policy permission, or an order signal.

---

## Boundary

- **Market-only** — reads `obs_market_candle` and `asset` metadata only
- **Account-agnostic** — no balances, positions, sleeves, orders
- **No paper/live distinction** — regime state is execution-mode-neutral
- **No broker calls** — reads only from the local DB
- **No orders** — does not generate, modify, or cancel orders
- **No decision permissions** — does not produce allowed/blocked/execution_intent
- **No execution intent** — does not instruct execution_planner or executor
- **No selection score modification** — does not alter selection_state or selection_score
- **No policy_router** — routing is the next separate step, not yet designed

---

## Validated input — H1 only

Only one hypothesis is tagged in `validated_hypothesis_tags_json`:

| Hypothesis | Condition | Tag |
|---|---|---|
| H1 BTC_MILD_DECLINE_4H_BOUNCE | `global_regime = GLOBAL_BTC_MILD_DECLINE` | `H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT` |

The tag is **context only**. It records that the H1 regime context is active.
It is not an entry rule, not a holding horizon, and not a routing instruction.

When `global_regime` is anything other than `GLOBAL_BTC_MILD_DECLINE`, the tag array
is empty (`[]`). The column is never NULL.

---

## Blocked candidates

H2–H5 are explicitly not tagged as validated. They may be revisited in a future version.

| Hypothesis | Status |
|---|---|
| H2 BTC_MILD_DECLINE_CLASS_STRESS_4H_BOUNCE | REJECTED — weekly pass rate 1/3 |
| H3 CLASS_LEADERSHIP_OVEREXTENSION_TRAP | MIXED — 2/3 windows, low n |
| H4 BTC_RISK_ON_ALT_NO_LIFT_WARNING | MIXED — 4/7 windows, context-dependent |
| H5 POLICY_INSUFFICIENT_SAMPLE_NEGATIVE_BUCKET | MIXED/SPARSE — only 2 qualifying windows |

Class regime fields for all classes are still stored in every row, so future validation
of H2–H5 does not require a schema change.

---

## Table — `active_regime_observation`

Row grain: **one row per (venue, interval_code, asof_ts_utc, asset_class, regime versions)**

```
active_regime_observation_id  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY

venue          VARCHAR(32)  NOT NULL
interval_code  VARCHAR(16)  NOT NULL
asof_ts_utc    DATETIME(6)  NOT NULL
source_candle_ts_utc  DATETIME(6)  NULL    -- close_ts_utc of BTC candle driving global_regime

asset_class   VARCHAR(32)  NOT NULL
asset_count   INT UNSIGNED NULL

global_regime          VARCHAR(64)  NOT NULL
global_regime_version  VARCHAR(32)  NOT NULL
btc_return_24h_pct     DECIMAL(20,10) NULL
btc_return_72h_pct     DECIMAL(20,10) NULL
avg_alt_return_24h_pct DECIMAL(20,10) NULL

asset_class_regime          VARCHAR(64)  NOT NULL
asset_class_regime_version  VARCHAR(32)  NOT NULL
class_return_24h_pct           DECIMAL(20,10) NULL
relative_class_vs_btc_24h_pct  DECIMAL(20,10) NULL

global_class_regime  VARCHAR(128) NOT NULL   -- e.g. 'GLOBAL_BTC_MILD_DECLINE|CLASS_STRESS'

validated_hypothesis_tags_json  LONGTEXT NULL   -- e.g. ["H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT"]
validation_status               VARCHAR(64)  NOT NULL

source_ref_json  LONGTEXT NULL

created_ts_utc  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
updated_ts_utc  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)

UNIQUE KEY (venue, interval_code, asof_ts_utc, asset_class,
            global_regime_version, asset_class_regime_version)
```

**Indexes:** asof_ts_utc/venue/interval, global_regime, asset_class_regime,
global_class_regime, validation_status.

---

## Runner — `src/regime/run_active_regime_observation_v1.py`

```
python -m src.regime.run_active_regime_observation_v1 [OPTIONS]

Options:
  --venue           Exchange venue (default: bitvavo)
  --interval        Candle interval (default: 4h)
  --asof-ts         Observation timestamp ISO format (default: now UTC)
  --lookback-hours  Candle window before asof_ts (default: 96)
  --write-db        Write rows to active_regime_observation
  --output          table (default) | json
```

**Dry run (no write):**
```bash
python -m src.regime.run_active_regime_observation_v1 \
  --venue bitvavo --interval 4h --output table
```

**Write latest observation:**
```bash
python -m src.regime.run_active_regime_observation_v1 \
  --venue bitvavo --interval 4h --write-db --output table
```

---

## Classification semantics — v1.1

Rules are applied in the exact order listed. Ordering is required to avoid overlap bugs.

### Global regime

| Order | Label | Condition |
|---|---|---|
| 1 | `GLOBAL_UNKNOWN` | `btc_return_24h_pct IS NULL` (missing data only) |
| 2 | `GLOBAL_BTC_BREAKDOWN` | `btc_24h < −0.05` |
| 3 | `GLOBAL_BTC_MILD_DECLINE` | `−0.05 ≤ btc_24h < −0.01` |
| 4 | `GLOBAL_NEUTRAL` | `−0.01 ≤ btc_24h ≤ +0.01` |
| 5 | `GLOBAL_BTC_OVERHEATED` | `btc_24h > +0.08` (must precede RISK_ON) |
| 6 | `GLOBAL_ROTATION_WINDOW` | `btc_24h < +0.04` AND `avg_alt − btc_24h > +0.04` (must precede RISK_ON) |
| 7 | `GLOBAL_RISK_ON` | `btc_24h > +0.01` (catch-all for positive BTC) |

`GLOBAL_UNKNOWN` must only mean missing BTC candle data. It must never represent a real
but unlabelled market state (the root cause of the v1.0 classification bug, fixed in v1.1).

### Asset class regime

| Order | Label | Condition |
|---|---|---|
| 1 | `CLASS_UNKNOWN` | class return is NULL |
| 2 | `CLASS_RISK_OFF` | relative vs BTC < −5% |
| 3 | `CLASS_STRESS` | relative vs BTC < −2% |
| 4 | `CLASS_OVERHEATED` | class 24h return > +10% |
| 5 | `CLASS_LEADERSHIP` | relative vs BTC > +4% |
| 6 | `CLASS_PULLBACK` | BTC positive AND class 24h negative |
| 7 | `CLASS_LAGGARD` | relative vs BTC < −1% |
| 8 | `CLASS_NEUTRAL` | default |

---

## Smoke test — observed output (2026-05-14 18:09 UTC)

Current global regime: **GLOBAL_NEUTRAL** (BTC 24h return +0.69%)
H1 tag: **not active** (H1 tags only on GLOBAL_BTC_MILD_DECLINE)

| asset_class | n | global_regime | class_regime | cross | btc_24h% | class_24h% |
|---|---|---|---|---|---|---|
| AI | 4 | GLOBAL_NEUTRAL | CLASS_NEUTRAL | GLOBAL_NEUTRAL\|CLASS_NEUTRAL | +0.69 | +0.10 |
| BTC | 1 | GLOBAL_NEUTRAL | CLASS_NEUTRAL | GLOBAL_NEUTRAL\|CLASS_NEUTRAL | +0.69 | +0.69 |
| DEFI | 3 | GLOBAL_NEUTRAL | CLASS_PULLBACK | GLOBAL_NEUTRAL\|CLASS_PULLBACK | +0.69 | −0.21 |
| ETH | 1 | GLOBAL_NEUTRAL | CLASS_NEUTRAL | GLOBAL_NEUTRAL\|CLASS_NEUTRAL | +0.69 | +0.92 |
| INFRA | 7 | GLOBAL_NEUTRAL | CLASS_NEUTRAL | GLOBAL_NEUTRAL\|CLASS_NEUTRAL | +0.69 | +1.94 |
| L1_L2 | 10 | GLOBAL_NEUTRAL | CLASS_PULLBACK | GLOBAL_NEUTRAL\|CLASS_PULLBACK | +0.69 | −0.40 |
| MEME | 3 | GLOBAL_NEUTRAL | CLASS_PULLBACK | GLOBAL_NEUTRAL\|CLASS_PULLBACK | +0.69 | −0.91 |
| OTHER | 13 | GLOBAL_NEUTRAL | CLASS_NEUTRAL | GLOBAL_NEUTRAL\|CLASS_NEUTRAL | +0.69 | +0.68 |

All 8 rows written. All source_ref safety fields zero or `not_implemented`.

---

## `validation_status` values

| Value | Meaning |
|---|---|
| `H1_CONTEXT_VALIDATED` | global_regime = GLOBAL_BTC_MILD_DECLINE; H1 tag active |
| `OBSERVED_UNVALIDATED_CONTEXT` | All other regimes; no validated hypothesis active |

---

## `source_ref_json` fields

Every row carries an audit object:

```json
{
  "scope": "market-only account-agnostic active regime observation",
  "broker_calls": 0,
  "broker_writes": 0,
  "order_submission": 0,
  "live_orders": 0,
  "policy_router": "not_implemented",
  "selection_engine_changes": 0,
  "decision_gate_changes": 0,
  "execution_planner_changes": 0,
  "executor_changes": 0,
  "validated_hypotheses": ["H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT"]
}
```

---

## Downstream path

```
1.  regime_selector_backtest_v1.1 findings              DONE
2.  regime_selector_candidate_hypotheses_v1             DONE
3.  regime_selector_multi_window_validation_v1          DONE  (H1 PROMISING_REPEATED)
4.  regime_selector_historical_coverage_audit_v1        DONE
5.  active_regime_observation design v1                 DONE
6.  active_regime_observation migration + runner        THIS DOCUMENT
    — migration applied
    — compile + dry run pass
    — write-db + DB verification pass
    — safety fields all zero
7.  policy_router design                                NEXT (blocked until step 6 stable)
    — maps (active_regime, strategy_state) → routing signal
    — pure read layer; no order placement
8.  policy_router preview                               BLOCKED
9.  selection/advice integration                        BLOCKED
10. decision_gate / execution                           NOT STARTED
```

---

## Non-goals

- No buy or sell signals
- No routing decisions or policy permissions
- No modification of selection_state, selection_score, or selection_bias
- No changes to decision_gate, execution_planner, or executor
- No paper or live mode branching
- No account filtering or balance checks
- No broker or exchange API calls
- No execution intent or execution plan

---

## Safety

```
[SAFETY] broker_calls=0  broker_writes=0  order_submission=0  live_orders=0
         selection_engine_changes=0  decision_gate_changes=0
         execution_planner_changes=0  executor_changes=0
[SCOPE]  market-only  account-agnostic  no-policy-router  observation-only
```
