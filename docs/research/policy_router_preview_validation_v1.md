# Policy Router Preview Validation V1

**Status:** ROUTE_VALIDATED_FOR_PREVIEW
**Date:** 2026-05-14
**Source:** `regime_selector_backtest_observation_v1` report_version=1.1
**Boundary:** research-only · market-only · account-agnostic · read-only · no DB writes

---

## Purpose

Validate whether the `policy_router_preview_v1` route predicate
(`ROUTE_GBMD_4H_BOUNCE_CONTEXT`) matches the H1 forward-return profile in
historical backtest data.

The live `policy_router_preview_observation` table cannot serve as the sole
validation source — the current regime is `GLOBAL_NEUTRAL`, so there are zero
`ROUTE_CANDIDATE` rows in the latest snapshot. Historical validation uses the
widened v1.1 backtest (356 snapshots, 2026-03-21 00:00:00 → 2026-05-14 17:12:25.954282,
42 assets) as the outcome ground truth.

---

## Boundary

- **Research-only** — no writes, no scheduler integration
- **Market-only** — reads `regime_selector_backtest_observation_v1` only
- **Account-agnostic** — no account_id, no balances, no positions
- **No selection_engine changes**
- **No advice_engine changes**
- **No decision_gate changes**
- **No execution_planner changes**
- **No executor changes**

---

## Why the latest preview table alone is insufficient

`policy_router_preview_observation` is written by the live runner at each snapshot.
At the time of this validation (2026-05-14), the current global regime is
`GLOBAL_NEUTRAL` (BTC 24h +0.69%). `ROUTE_GBMD_4H_BOUNCE_CONTEXT` only fires on
`GLOBAL_BTC_MILD_DECLINE`. Therefore the latest snapshot has 41 rows, all
`ROUTE_NO_MATCH` — there are **zero `ROUTE_CANDIDATE` rows** to validate against.

The backtest table contains 356 snapshots across multiple market
regimes including 100 GBMD snapshots, making it the correct source.

---

## Historical validation source

| Field | Value |
|---|---|
| Table | `regime_selector_backtest_observation_v1` |
| report_version | 1.1 |
| selector_mode | `GLOBAL` |
| Snapshots | 356 |
| Date range | 2026-03-21 00:00:00 → 2026-05-14 17:12:25.954282 |
| Assets | 42 |
| Horizons | 4h, 24h, 72h |
| Total rows | 163248 |

---

## Route predicate

```
ROUTE_GBMD_4H_BOUNCE_CONTEXT  if:
  selector_mode = GLOBAL
  AND global_regime = GLOBAL_BTC_MILD_DECLINE
```

H2 (`GBMD × CLASS_STRESS`) is not included — it was rejected as a standalone route.
No strategy_signature filtering. No account data.

---

## Regime distribution (GLOBAL mode, 4h)

| global_regime | snapshots | n_rows |
|---|---|---|
| GLOBAL_NEUTRAL | 203 | 7862 |
| GLOBAL_BTC_MILD_DECLINE | 100 | 3949 |
| GLOBAL_RISK_ON | 51 | 1791 |
| GLOBAL_ROTATION_WINDOW | 2 | 2 |


---

## Route candidate vs no-match by horizon

| horizon | route | n_ret | avg_ret | win_rate | avg_mfe | avg_mae |
|---|---|---|---|---|---|---|
| 4h | ROUTE_GBMD_4H_BOUNCE_CONTEXT | 3539 | +0.328 | 57.5% | +1.845 | -1.131 |
| 4h | ROUTE_NO_MATCH | 9562 | -0.368 | 43.5% | — | — |
| 24h | ROUTE_GBMD_4H_BOUNCE_CONTEXT | 2555 | -0.211 | 46.3% | +3.010 | -2.318 |
| 24h | ROUTE_NO_MATCH | 9331 | -0.887 | 33.8% | — | — |
| 72h | ROUTE_GBMD_4H_BOUNCE_CONTEXT | 2104 | +0.102 | 47.1% | +4.537 | -3.330 |
| 72h | ROUTE_NO_MATCH | 7131 | -0.907 | 39.4% | — | — |

**24h label:** `SHORT_WINDOW_ONLY_CONFIRMED`
— The 4h bounce is the primary signal window. Negative 24h avg confirms this is
a short-window-only context, not a multi-session hold signal.

---

## All global regimes at 4h (GLOBAL mode)

| global_regime | n_ret | avg_ret | win_rate | avg_mfe | avg_mae |
|---|---|---|---|---|---|
| GLOBAL_BTC_MILD_DECLINE | 3539 | +0.328 | 57.5% | +1.845 | -1.131 |
| GLOBAL_NEUTRAL | 7769 | -0.196 | 46.4% | +2.046 | -1.854 |
| GLOBAL_RISK_ON | 1791 | -1.116 | 31.4% | +2.073 | -2.604 |
| GLOBAL_ROTATION_WINDOW | 2 | -1.450 | 0.0% | +1.526 | -1.541 |


`GLOBAL_BTC_MILD_DECLINE` is the only regime with positive avg_ret and win_rate > 50%
at the 4h horizon. The route predicate cleanly isolates the best-performing regime.

---

## Weekly stability — ROUTE_GBMD_4H_BOUNCE_CONTEXT at 4h

min_weekly_n_ret = 40

| week_start | n_ret | avg_ret_4h | win_rate_4h | verdict |
|---|---|---|---|---|
| 2026-03-16 | 39 | +0.511 | 79.5% | LOW_SAMPLE |
| 2026-03-23 | 117 | +0.112 | 51.3% | PASS |
| 2026-03-30 | 3 | +1.150 | 100.0% | LOW_SAMPLE |
| 2026-04-13 | 40 | -1.195 | 15.0% | FAIL |
| 2026-04-20 | 140 | +0.881 | 77.9% | PASS |
| 2026-04-27 | 1560 | +0.263 | 57.6% | PASS |
| 2026-05-04 | 205 | +1.067 | 73.2% | PASS |
| 2026-05-11 | 1435 | +0.294 | 54.3% | PASS |

| Metric | Value |
|---|---|
| Qualifying weeks (n≥40) | 6 |
| Passing weeks | 5 |
| Pass rate | 83.3% |

**W2026-04-13** is the single failing week — BTC was recovering from the April low,
briefly suppressing the mild-decline bounce pattern.

---

## Validation criteria and result

| Criterion | Threshold | Result | Status |
|---|---|---|---|
| n_ret 4h | ≥ 300 | 3539 | PASS |
| avg_ret 4h | > 0 | +0.328 | PASS |
| win_rate 4h | > 50% | 57.5% | PASS |
| avg_ret better than no-match | route > no-match | +0.328 vs -0.368 | PASS |
| win_rate better than no-match | route > no-match | 57.5% vs 43.5% | PASS |
| Qualifying weeks | ≥ 2 | 6 | PASS |
| Weekly pass rate | ≥ 60% | 83.3% | PASS |
| 24h avg_ret | no requirement | -0.211 | SHORT_WINDOW_ONLY_CONFIRMED |

---

## Validation decision

**`ROUTE_VALIDATED_FOR_PREVIEW`**

`ROUTE_CANDIDATE` is not permission and not order intent.
`decision_gate` remains the authority on account permission.
`execution` remains separate and unchanged.

---

## Downstream gate

```
If ROUTE_VALIDATED_FOR_PREVIEW:
  ✓ policy_router_preview_v1 may remain as the active preview route
  → next step may be advice integration design only
  → decision_gate still unchanged
  → execution unchanged

If ROUTE_MIXED / ROUTE_REJECTED / ROUTE_LOW_SAMPLE:
  ✗ route stays preview-only
  ✗ blocked from advice integration design
```

---

## Safety

```
[SAFETY] broker_calls=0  broker_writes=0  order_submission=0  live_orders=0
         selection_engine_changes=0  advice_engine_changes=0
         decision_gate_changes=0  execution_planner_changes=0  executor_changes=0
         route_is_permission=false  route_is_order_intent=false
[SCOPE]  research-only  market-only  account-agnostic  read-only  no-db-writes
```
