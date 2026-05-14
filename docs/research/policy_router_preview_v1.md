# Policy Router Preview V1

**Status:** Migration applied · Runner smoke-tested · DB write verified
**Date:** 2026-05-14
**Validated route:** `ROUTE_GBMD_4H_BOUNCE_CONTEXT` (H1 only)
**Boundary:** market-only · account-agnostic · no paper/live · no broker calls · no orders · no execution intent

---

## Purpose

`policy_router_preview_observation` is a market-only preview layer that maps each
enabled+tradeable asset to a research-only route candidate based on the current
active regime observation.

It reads `active_regime_observation` (and optionally `selection_state` as a source reference)
and writes one row per asset per snapshot.

The router does not decide account permission.
The router does not create execution intent.
The router does not place orders.
The router does not modify selection scores.

A `ROUTE_CANDIDATE` row means: "market context is consistent with the validated hypothesis
for this asset class." It is not a buy signal, not a hold instruction, and not an account
permission.

---

## Boundary

- **Market-only** — reads `active_regime_observation`, `asset`, and `selection_state` only
- **Account-agnostic** — no `account_id`, no balances, no positions, no exposure
- **No paper/live distinction** — route context is execution-mode-neutral
- **No broker calls** — reads only from the local DB
- **No orders** — does not generate, modify, or cancel orders
- **No execution intent** — does not instruct `execution_planner` or `executor`
- **No selection_engine changes** — does not alter `selection_state` or `selection_score`
- **No advice_engine changes** — does not write to `paper_advice_observation`
- **No decision_gate** — routing is observation only; permission remains in `decision_gate`

---

## Row grain

One row per: `(venue, interval_code, asof_ts_utc, asset_id, route_version)`

Each snapshot produces one row per enabled+tradeable asset (41 assets at 2026-05-14).

---

## Validated route — v1

Only one route code can become `ROUTE_CANDIDATE` in v1:

### `ROUTE_GBMD_4H_BOUNCE_CONTEXT`

**Condition:**
```
active_regime_observation.global_regime = GLOBAL_BTC_MILD_DECLINE
AND validated_hypothesis_tags_json contains H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT
```

**When active:**
- `route_status` = `ROUTE_CANDIDATE`
- `route_confidence` = `0.575000`
- `allowed_policy_family_json` = `["BOUNCE_RECLAIM_SHORT_WINDOW"]`
- `blocked_policy_family_json` = `["SWING_CONTINUATION", "LONG_HORIZON_HOLD", "BREAKOUT_FOLLOW_WITHOUT_CONFIRMATION"]`
- `route_reason_codes_json` = `["H1_PROMISING_REPEATED", "GLOBAL_BTC_MILD_DECLINE", "MARKET_ONLY_CONTEXT", "NOT_PERMISSION", "NOT_ORDER_INTENT"]`

**When not active (all other regimes):**
- `route_code` = `ROUTE_NO_MATCH`
- `route_status` = `ROUTE_NO_MATCH`
- `route_confidence` = `0.000000`
- `route_reason_codes_json` = `["NO_VALIDATED_ROUTE_MATCH", "MARKET_ONLY_CONTEXT", "NOT_PERMISSION", "NOT_ORDER_INTENT"]`

---

## Blocked routes — H2–H5

| Route code | Blocked reason |
|---|---|
| `ROUTE_GBMD_CLASS_STRESS_BOUNCE` | H2 rejected as standalone — weekly pass rate 1/3 |
| `ROUTE_CLASS_LEADERSHIP_TRAP` | H3 mixed — 2/3 windows, low n |
| `ROUTE_RISK_ON_ALT_NO_LIFT` | H4 mixed — 4/7 windows, context-dependent |
| `ROUTE_INSUFFICIENT_SAMPLE_BLOCK` | H5 mixed/sparse — only 2 qualifying windows |

These routes are not implemented. They will not appear in any row.

---

## Route status values

| Value | Meaning |
|---|---|
| `ROUTE_CANDIDATE` | H1 active; `BOUNCE_RECLAIM_SHORT_WINDOW` family conceptually eligible |
| `ROUTE_CONTEXT_ONLY` | Regime observed; no validated hypothesis matches — reserved for future use |
| `ROUTE_BLOCKED_UNVALIDATED` | Route code exists but not yet validated — reserved |
| `ROUTE_BLOCKED_REJECTED_HYPOTHESIS` | Explicitly rejected (H2–H5) — reserved |
| `ROUTE_LOW_SAMPLE` | Hypothesis mixed/sparse — reserved |
| `ROUTE_NO_MATCH` | No regime/hypothesis combination applies; current state |

`ROUTE_CANDIDATE` is not permission. `decision_gate` remains the authority on account permission.

---

## Table — `policy_router_preview_observation`

Row grain: **one row per (venue, interval_code, asof_ts_utc, asset_id, route_version)**

```
policy_router_preview_observation_id  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY

venue          VARCHAR(32)  NOT NULL
interval_code  VARCHAR(16)  NOT NULL
asof_ts_utc    DATETIME(6)  NOT NULL

asset_id    BIGINT UNSIGNED NOT NULL
symbol      VARCHAR(32)     NOT NULL
asset_class VARCHAR(32)     NOT NULL      -- regime asset class (BTC/ETH/L1_L2/DEFI/AI/INFRA/MEME/OTHER)

source_active_regime_observation_id  BIGINT UNSIGNED NULL
source_selection_state_ref_json      LONGTEXT NULL   -- selection snapshot ref, read-only
source_strategy_state_ref_json       LONGTEXT NULL   -- optional strategy ref

route_code              VARCHAR(96)   NOT NULL
route_version           VARCHAR(32)   NOT NULL
route_status            VARCHAR(64)   NOT NULL
route_confidence        DECIMAL(10,6) NULL
route_reason_codes_json LONGTEXT      NULL

global_regime                  VARCHAR(64)  NOT NULL
asset_class_regime             VARCHAR(64)  NOT NULL
global_class_regime            VARCHAR(128) NOT NULL
validated_hypothesis_tags_json LONGTEXT     NULL

allowed_policy_family_json  LONGTEXT NULL
blocked_policy_family_json  LONGTEXT NULL

source_ref_json  LONGTEXT NULL

created_ts_utc  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
updated_ts_utc  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)

UNIQUE KEY (venue, interval_code, asof_ts_utc, asset_id, route_version)
```

**Indexes:** asof/venue/interval, route_code, route_status, global_regime,
asset_class_regime, asset_class.

---

## Runner — `src/regime/run_policy_router_preview_v1.py`

```
python -m src.regime.run_policy_router_preview_v1 [OPTIONS]

Options:
  --venue       Exchange venue (default: bitvavo)
  --interval    Candle interval (default: 4h)
  --asof-ts     Observation timestamp ISO format (default: latest ARO snapshot)
  --write-db    Write rows to policy_router_preview_observation
  --output      table (default) | json
```

**Dry run (no write):**
```bash
python -m src.regime.run_policy_router_preview_v1 \
  --venue bitvavo --interval 4h --output table
```

**Write preview:**
```bash
python -m src.regime.run_policy_router_preview_v1 \
  --venue bitvavo --interval 4h --write-db --output table
```

---

## Smoke test — observed output (2026-05-14 18:09 UTC)

Current global regime: **GLOBAL_NEUTRAL** (BTC 24h +0.69%)
Active route: **ROUTE_NO_MATCH** for all assets (H1 only fires on `GLOBAL_BTC_MILD_DECLINE`)

| route_code | route_status | n |
|---|---|---|
| ROUTE_NO_MATCH | ROUTE_NO_MATCH | 41 |

Total rows written: **41** (one per enabled+tradeable asset).
Forbidden wording rows: **0**.
All `source_ref` safety fields: **0** or `not_allowed`/`false`.

---

## `source_ref_json` fields

Every row carries an audit object:

```json
{
  "scope": "market-only account-agnostic policy router preview",
  "broker_calls": 0,
  "broker_writes": 0,
  "order_submission": 0,
  "live_orders": 0,
  "decision_gate_changes": 0,
  "execution_planner_changes": 0,
  "executor_changes": 0,
  "selection_engine_changes": 0,
  "advice_engine_changes": 0,
  "paper_live_logic": "not_allowed",
  "account_state": "not_allowed",
  "route_is_permission": false,
  "route_is_order_intent": false
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
6.  active_regime_observation migration + runner        DONE  (merged 17477b4)
7.  policy_router_design_v1                             DONE  (merged d622fb4)
8.  policy_router_preview_v1 migration + runner         THIS DOCUMENT
    — migration applied
    — compile + dry run pass
    — write-db + DB verification pass
    — forbidden_word_rows = 0
    — safety fields correct
9.  validate router preview against forward outcomes     NEXT (blocked until step 8 stable)
    — join policy_router_preview_observation to forward returns
    — confirm ROUTE_CANDIDATE correlates with H1 forward-return profile
10. optional advice integration design                  BLOCKED
11. decision_gate remains separate and unchanged        NOT STARTED
12. execution remains separate and unchanged            NOT STARTED
```

---

## Non-goals

- No trading advice
- No buy/sell signals
- No order placement
- No account permission
- No order sizing
- No broker calls
- No live/paper routing logic
- No paper/live mode branching
- No decision_gate bypass
- No execution intent
- No selection_engine modification
- No advice_engine modification

---

## Safety

```
[SAFETY] broker_calls=0  broker_writes=0  order_submission=0  live_orders=0
         selection_engine_changes=0  advice_engine_changes=0
         decision_gate_changes=0  execution_planner_changes=0  executor_changes=0
         route_is_permission=false  route_is_order_intent=false
[SCOPE]  market-only  account-agnostic  no-decision-gate  no-execution-intent
```
