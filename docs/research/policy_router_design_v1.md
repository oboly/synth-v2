# Policy Router Design V1

**Status:** Design-only. No implementation.
**Date:** 2026-05-14
**Depends on:** `active_regime_observation_preview_v1` (merged at `17477b4`)
**Boundary:** market-only · account-agnostic · no migration · no runner · no orders

---

## Purpose

Define a future pure-read routing layer that maps validated market regime context and strategy
state into a research-only route candidate.

The router does not decide account permission.
The router does not create execution intent.
The router does not place orders.
The router does not modify selection scores.

It is a classification layer that sits between market observation and the account-aware
decision_gate. It answers the question: "Given this regime context, which policy family is
conceptually eligible?" — not "Is this account allowed to trade?"

---

## Layer boundary

### Input allowed

| Source | Fields |
|---|---|
| `active_regime_observation` | `global_regime`, `asset_class_regime`, `global_class_regime`, `validated_hypothesis_tags_json`, `asof_ts_utc`, `venue`, `interval_code` |
| `selection_state` | `asset_id`, `symbol`, `asset_class`, `selection_score`, `selection_state_id`, `asof_ts_utc` |
| `trade_setup_filter_observation` | `setup_label`, `setup_status`, `asof_ts_utc` |
| `trade_setup_policy_preview_observation` | `policy_family`, `policy_label`, `asof_ts_utc` |
| `paper_advice_observation` | Optional enrichment only. Read reference, no routing authority. |
| Validated strategy/regime research labels | Static lookup constants only |

### Forbidden inputs

- `account_id`
- Balances
- Positions
- Portfolio exposure
- Paper/live mode
- Broker permissions
- Order sizing
- Order placement
- Execution intent
- Any account-state field

### Explicit layer distinction

```
selection_engine    → market-only candidate scoring
policy_router       → market-only policy/context routing candidate   ← THIS LAYER
decision_gate       → account-aware permission layer
execution_planner   → execution intent only
executor            → order handling
```

The policy_router sits between the market observation stack and the decision_gate.
It does not collapse into either neighbour.

---

## Current validated route candidate

Only one route candidate is allowed in design v1:

### `ROUTE_GBMD_4H_BOUNCE_CONTEXT`

**Condition:**
```
active_regime_observation.global_regime = GLOBAL_BTC_MILD_DECLINE
AND validated_hypothesis_tags_json contains H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT
```

**Meaning:**
- Market context supports possible short-window bounce behavior
- Does not mean buy
- Does not mean hold for 4h automatically
- Does not bypass setup filter
- Does not bypass decision_gate
- Does not create an execution plan
- Does not imply position size, account permission, or sleeve allocation

**Evidence basis:**
- H1 validated across 6/7 weekly windows (W13–W20, 2026-03-20 to 2026-05-14)
- Avg forward return (4h horizon): +0.29% | Win rate: 54.3% | n=1,435 qualifying observations
- Stability classification: `PROMISING_REPEATED`

---

## Blocked routes

The following route codes are explicitly prohibited in design v1 and must not be implemented
until further validation work is complete.

### `ROUTE_GBMD_CLASS_STRESS_BOUNCE`
**Reason:** H2 (`GBMD × CLASS_STRESS`) rejected as a standalone routing candidate.
Weekly pass rate 1/3 (33%). Committed to `REJECTED` in multi-window validation v1.

### `ROUTE_CLASS_LEADERSHIP_TRAP`
**Reason:** H3 (`CLASS_LEADERSHIP overextension`) mixed evidence. 2/3 windows, low n.
Cannot be relied upon as a repeating market structure signal.

### `ROUTE_RISK_ON_ALT_NO_LIFT`
**Reason:** H4 (`RISK_ON, alt underperforms`) is context-dependent. 4/7 windows.
The signal inverts in genuine BTC breakout weeks (e.g. W19 +1.25% / 83.3% win for alts).
Requires macro-condition qualifier not yet designed.

### `ROUTE_INSUFFICIENT_SAMPLE_BLOCK`
**Reason:** H5 (`POLICY_INSUFFICIENT_SAMPLE` negative bucket) is mixed/sparse with only
2 qualifying windows. May remain a policy-quality observation label only.

---

## Proposed future route output fields

No migration yet. These fields define the intended schema for a future
`policy_route_observation` table.

```
policy_route_observation_id        BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY

venue                              VARCHAR(32)  NOT NULL
interval_code                      VARCHAR(16)  NOT NULL
asof_ts_utc                        DATETIME(6)  NOT NULL
asset_id                           BIGINT UNSIGNED NOT NULL
symbol                             VARCHAR(32)  NOT NULL
asset_class                        VARCHAR(32)  NOT NULL

source_active_regime_observation_id  BIGINT UNSIGNED NOT NULL
source_selection_state_id            BIGINT UNSIGNED NULL   -- nullable if unavailable
source_strategy_state_ref_json       LONGTEXT NULL

route_code                         VARCHAR(64)  NOT NULL
route_version                      VARCHAR(32)  NOT NULL
route_status                       VARCHAR(64)  NOT NULL
route_confidence                   VARCHAR(32)  NULL       -- LOW / MODERATE / HIGH
route_reason_codes_json            LONGTEXT     NULL

global_regime                      VARCHAR(64)  NOT NULL
asset_class_regime                 VARCHAR(64)  NOT NULL
global_class_regime                VARCHAR(128) NOT NULL
validated_hypothesis_tags_json     LONGTEXT     NULL

allowed_policy_family_json         LONGTEXT     NULL
blocked_policy_family_json         LONGTEXT     NULL

source_ref_json                    LONGTEXT     NULL
created_ts_utc                     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
updated_ts_utc                     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                                                         ON UPDATE CURRENT_TIMESTAMP(6)
```

**Candidate UNIQUE KEY (future):**
`(venue, interval_code, asof_ts_utc, asset_id, route_code, route_version)`

---

## Route status values

| Value | Meaning |
|---|---|
| `ROUTE_CANDIDATE` | Validated hypothesis active; policy family conceptually eligible |
| `ROUTE_CONTEXT_ONLY` | Regime observed but no validated hypothesis matches this asset/class |
| `ROUTE_BLOCKED_UNVALIDATED` | Regime observed; route code exists but not yet validated |
| `ROUTE_BLOCKED_REJECTED_HYPOTHESIS` | Route code explicitly rejected (H2–H5 blocked) |
| `ROUTE_LOW_SAMPLE` | Hypothesis mixed or sparse; insufficient evidence to route |
| `ROUTE_NO_MATCH` | No regime/hypothesis combination applies |

**Important:** `ROUTE_CANDIDATE` is not permission. It means a market-only routing candidate
exists. Account permission is always resolved separately by decision_gate.

---

## Policy family semantics

Policy families are conceptual labels only. No implementation in this design version.

| Family | Meaning |
|---|---|
| `BOUNCE_RECLAIM_SHORT_WINDOW` | Short-horizon mean reversion candidate in mild-decline context |
| `SWING_CONTINUATION` | Trend-follow across multiple sessions |
| `BREAKOUT_FOLLOW` | Momentum entry following confirmed breakout |
| `MEAN_REVERSION` | Counter-trend entry against extended move |
| `DEFENSIVE_WAIT` | No new entry; hold or reduce only |
| `NO_NEW_ENTRY` | Regime context explicitly discourages new entries |

**For H1 / `ROUTE_GBMD_4H_BOUNCE_CONTEXT`:**

Allowed family candidate:
- `BOUNCE_RECLAIM_SHORT_WINDOW`

Explicitly blocked or inapplicable:
- `SWING_CONTINUATION` — H1 horizon is 4h, not multi-session trend
- `BREAKOUT_FOLLOW` — GBMD regime is the opposite of breakout context
- `LONG_HORIZON_HOLD` — not supported by H1 forward-return window

These are design-only labels. The decision_gate remains the authority on whether any
account is permitted to act on a route candidate.

---

## Required joins for future implementation

A future `run_policy_router_preview_v1.py` would join:

```
active_regime_observation
  ON venue, interval_code, asof_ts_utc (latest or explicit)

asset
  ON asset_id → asset_class

selection_state
  ON asset_id, venue, asof_ts_utc (fuzzy nearest or exact)

trade_setup_filter_observation
  ON asset_id, venue, asof_ts_utc (optional enrichment)

trade_setup_policy_preview_observation
  ON asset_id, venue, asof_ts_utc (optional enrichment)

paper_advice_observation
  ON asset_id, venue, asof_ts_utc (optional read reference only)
```

**No account joins.** No balance, position, or sleeve joins at any point in the router.

---

## Safety `source_ref_json` requirements

Any future implementation must include the following audit object in every written row:

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
  "paper_live_logic": "not_allowed",
  "account_state": "not_allowed"
}
```

And must emit the following safety line on every run:

```
[SAFETY] broker_calls=0  broker_writes=0  order_submission=0  live_orders=0
         decision_gate_changes=0  execution_planner_changes=0  executor_changes=0
[SCOPE]  market-only  account-agnostic  no-decision-gate  no-execution-intent
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
7.  policy_router_design_v1                             THIS DOCUMENT
8.  policy_router_preview_v1 migration + runner         NEXT
    — preview rows only
    — market-only, account-agnostic
    — no order placement
9.  validation of router preview against forward outcomes  BLOCKED
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
         decision_gate_changes=0  execution_planner_changes=0  executor_changes=0
[SCOPE]  market-only  account-agnostic  design-only  no-policy-router-impl
```
