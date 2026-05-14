# Regime Selector Multi-Window Validation V1

**Generated:** 2026-05-14
**Script:** `run_regime_selector_multi_window_validation_v1.py`
**Table:** `regime_selector_backtest_observation_v1`
**report_version:** 1.1
**window_mode:** day
**min_n_ret:** 40

---

## Boundary

- Research-only
- Market-only
- Account-agnostic
- No account state, no balances, no positions
- No broker calls
- No order logic
- No paper/live distinction
- No routing implementation

---

## Source candidates

- `docs/research/regime_selector_candidate_hypotheses_v1.md`
- `docs/research/regime_selector_backtest_v1_1_findings_summary.md`

---

## Coverage audit

| Field | Value |
|---|---|
| min_ts | 2026-05-10 22:15:36.422933 |
| max_ts | 2026-05-14 14:15:24.928362 |
| span_days | 3 |
| distinct_dates | 5 |
| distinct_snapshots | 120 |
| total_rows | 59640 |
| selector_modes | 4 |
| global_regimes | 3 |
| class_regimes | 6 |
| distinct_sigs | 39 |

**Horizon forward-return coverage:**

| horizon_h | n_ret | n_missing |
|---|---|---|
| 4h | 18360 | 1520 |
| 24h | 13500 | 6380 |
| 72h | 2952 | 16928 |

**Day distribution:**

| date | snapshots | rows |
|---|---|---|
| 2026-05-10 | 3 | 1512 |
| 2026-05-11 | 31 | 15624 |
| 2026-05-12 | 33 | 16428 |
| 2026-05-13 | 34 | 16728 |
| 2026-05-14 | 19 | 9348 |

**Global regime distribution (GLOBAL selector mode):**

| global_regime | n |
|---|---|
| GLOBAL_NEUTRAL | 8868 |
| GLOBAL_BTC_MILD_DECLINE | 5412 |
| GLOBAL_RISK_ON | 630 |

---

## Validation method

Window mode: **day**. The dataset is split by calendar day and each hypothesis is evaluated independently per window.

Minimum n_ret per window: **40** (per-window threshold is min_n_ret // 4 = 10 to allow day-level splits).

Multi-window threshold: the dataset must span at least **14 calendar days** across distinct macro regime characters (bull, bear, sideways) before any hypothesis can be promoted.

---

## Hypothesis pass/fail criteria

| Hypothesis | Primary horizon | Pass condition |
|---|---|---|
| H1 BTC_MILD_DECLINE_4H_BOUNCE | 4h | avg_ret > 0 AND win_rate > 50% |
| H2 BTC_MILD_DECLINE_CLASS_STRESS_4H_BOUNCE | 4h | avg_ret > 0 AND win_rate > 55% |
| H3 CLASS_LEADERSHIP_OVEREXTENSION_TRAP | 4h | avg_ret < 0 AND win_rate < 40% |
| H4 BTC_RISK_ON_ALT_NO_LIFT_WARNING | 4h | avg_ret < 0 AND win_rate < 30% |
| H5 POLICY_INSUFFICIENT_SAMPLE_NEGATIVE_BUCKET | 24h | avg_ret < 0 AND win_rate < 30% |

Stability classifications:

| Status | Meaning |
|---|---|
| `VALIDATION_BLOCKED_INSUFFICIENT_COVERAGE` | Data does not span multiple independent windows |
| `PROMISING_REPEATED` | Passes in ≥ 80% of windows (multi-window only) |
| `PROMISING_SINGLE_WINDOW_ONLY` | Passes within the available window but no multi-window evidence |
| `MIXED` | Passes in 50–80% of windows |
| `REJECTED` | Passes in < 50% of windows |
| `LOW_SAMPLE` | Insufficient n_ret to evaluate |

---

## Results

**Top-level validation status: `VALIDATION_BLOCKED_INSUFFICIENT_COVERAGE`**

> **IMPORTANT:** The DB contains only a single 4-day bearish window
> (2026-05-10 to 2026-05-14, 120 snapshots). Day-level splits within
> this window are shown for internal consistency inspection only.
> They are **not** independent market windows. All hypotheses remain
> **unvalidated** at the multi-window level.

### H1 — BTC_MILD_DECLINE_4H_BOUNCE

**Horizon:** 4h | **Stability:** `PROMISING_SINGLE_WINDOW_ONLY`

**Overall aggregate:**

| n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% |
|---|---|---|---|---|
| 1435 | +0.29 | +54.3 | +2.10 | -1.27 |

**Per-day breakdown (min_n_ret≥10):**

| window | n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% | pass |
|---|---|---|---|---|---|---|
| 2026-05-10 | — | — | — | — | — | — |
| 2026-05-11 | — | — | — | — | — | — |
| 2026-05-12 | 246 | +1.44 | +90.2 | +1.91 | -1.90 | PASS |
| 2026-05-13 | 779 | -0.04 | +43.9 | +2.34 | -1.19 | FAIL |
| 2026-05-14 | 410 | +0.24 | +52.4 | +1.78 | -1.04 | PASS |

### H2 — BTC_MILD_DECLINE_CLASS_STRESS_4H_BOUNCE

**Horizon:** 4h | **Stability:** `PROMISING_SINGLE_WINDOW_ONLY`

**Overall aggregate:**

| n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% |
|---|---|---|---|---|
| 440 | +0.79 | +66.4 | +2.12 | -1.07 |

**Per-day breakdown (min_n_ret≥10):**

| window | n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% | pass |
|---|---|---|---|---|---|---|
| 2026-05-10 | — | — | — | — | — | — |
| 2026-05-11 | — | — | — | — | — | — |
| 2026-05-12 | 120 | +1.23 | +85.0 | +1.71 | -1.88 | PASS |
| 2026-05-13 | 140 | +0.67 | +57.1 | +2.22 | -0.80 | PASS |
| 2026-05-14 | 180 | +0.60 | +61.1 | +2.32 | -0.73 | PASS |

### H3 — CLASS_LEADERSHIP_OVEREXTENSION_TRAP

**Horizon:** 4h | **Stability:** `PROMISING_SINGLE_WINDOW_ONLY`

**Overall aggregate:**

| n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% |
|---|---|---|---|---|
| 75 | -2.81 | +13.3 | +1.80 | -5.21 |

**Per-day breakdown (min_n_ret≥10):**

| window | n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% | pass |
|---|---|---|---|---|---|---|
| 2026-05-10 | 60 | -3.54 | 0.0 | +1.36 | -5.05 | PASS |
| 2026-05-11 | 15 | +0.14 | +66.7 | +3.56 | -5.85 | FAIL |
| 2026-05-12 | — | — | — | — | — | — |
| 2026-05-13 | — | — | — | — | — | — |
| 2026-05-14 | — | — | — | — | — | — |

### H4 — BTC_RISK_ON_ALT_NO_LIFT_WARNING

**Horizon:** 4h | **Stability:** `PROMISING_SINGLE_WINDOW_ONLY`

**Overall aggregate:**

| n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% |
|---|---|---|---|---|
| 210 | -1.82 | +7.1 | +1.83 | -3.48 |

**Per-day breakdown (min_n_ret≥10):**

| window | n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% | pass |
|---|---|---|---|---|---|---|
| 2026-05-10 | — | — | — | — | — | — |
| 2026-05-11 | 210 | -1.82 | +7.1 | +1.83 | -3.48 | PASS |
| 2026-05-12 | — | — | — | — | — | — |
| 2026-05-13 | — | — | — | — | — | — |
| 2026-05-14 | — | — | — | — | — | — |

### H5 — POLICY_INSUFFICIENT_SAMPLE_NEGATIVE_BUCKET

**Horizon:** 24h | **Stability:** `PROMISING_SINGLE_WINDOW_ONLY`

**Overall aggregate:**

| n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% |
|---|---|---|---|---|
| 233 | -3.42 | +10.3 | +2.32 | -4.98 |

**Per-day breakdown (min_n_ret≥10):**

| window | n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% | pass |
|---|---|---|---|---|---|---|
| 2026-05-10 | — | — | — | — | — | — |
| 2026-05-11 | 89 | -3.33 | +19.1 | +2.51 | -4.69 | PASS |
| 2026-05-12 | 98 | -2.96 | +7.1 | +2.25 | -4.89 | PASS |
| 2026-05-13 | 43 | -4.39 | 0.0 | +1.75 | -5.50 | PASS |
| 2026-05-14 | — | — | — | — | — | — |

---

## Insufficient coverage handling

When only the May 2026 mini-window is present, this script:

- Reports `VALIDATION_BLOCKED_INSUFFICIENT_COVERAGE` as the top-level status.
- Still produces day-level evidence tables for internal consistency inspection.
- Does not promote any hypothesis to routing-ready status.
- States explicitly: **Candidate hypotheses remain unvalidated.**

---

## Required next data / replay steps

To unblock multi-window validation:

1. Run `run_regime_selector_backtest_v1.py` with a much wider `--from-ts` / `--to-ts`:
   - Target: 60–90 days of history
   - `--limit-snapshots 2160` (90 days × 6 snapshots/day at 4h)
   - Ensure candle history covers the full window in `obs_market_candle`

2. Required window characters for full validation:
   - Sustained BTC bull run (+20% over 30 days) — to test H4
   - Rotation window (BTC flat, alts outperforming) — to test H2 and H3
   - Post-spike crash (BTC -30% in 7 days) — to test H1 edge case
   - Sideways ranging (BTC ±5% over 30 days) — baseline neutrality

3. After replay, re-run:
   ```
   python -m src.research.run_regime_selector_multi_window_validation_v1 \
     --report-version 1.1 \
     --window-mode week \
     --min-n-ret 40
   ```

4. Do NOT design `active_regime_observation` until at least one hypothesis
   achieves `PROMISING_REPEATED` status across ≥ 2 independent macro windows.

---

## Downstream gate

```
1. regime_selector_backtest_v1.1 findings  ← DONE
2. regime_selector_candidate_hypotheses_v1  ← DONE
3. regime_selector_multi_window_validation_v1  ← THIS DOCUMENT
   status: VALIDATION_BLOCKED_INSUFFICIENT_COVERAGE
   gate: DO NOT PROCEED to step 4 until at least one hypothesis
         achieves PROMISING_REPEATED across independent market windows
4. active_regime_observation design  ← BLOCKED
5. policy_router preview  ← BLOCKED
6. selection/advice integration  ← BLOCKED
7. decision_gate / execution  ← NOT STARTED (separate design)
```

---

## Safety

```
[SAFETY] broker_calls=0  broker_writes=0  order_submission=0  live_orders=0
[SCOPE]  research-only  market-only  account-agnostic  read-only-query
```
