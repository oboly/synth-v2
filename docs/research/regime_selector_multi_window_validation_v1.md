# Regime Selector Multi-Window Validation V1

**Generated:** 2026-05-14
**Script:** `run_regime_selector_multi_window_validation_v1.py`
**Table:** `regime_selector_backtest_observation_v1`
**report_version:** 1.1
**window_mode:** week
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
| min_ts | 2026-03-21 00:00:00 |
| max_ts | 2026-05-14 17:12:25.954282 |
| span_days | 54 |
| distinct_dates | 32 |
| distinct_snapshots | 356 |
| total_rows | 163248 |
| selector_modes | 4 |
| global_regimes | 4 |
| class_regimes | 8 |
| distinct_sigs | 52 |

**Horizon forward-return coverage:**

| horizon_h | n_ret | n_missing |
|---|---|---|
| 4h | 52404 | 2012 |
| 24h | 47544 | 6872 |
| 72h | 36940 | 17476 |

**Day distribution:**

| date | snapshots | rows |
|---|---|---|
| 2026-03-21 | 1 | 468 |
| 2026-03-22 | 1 | 468 |
| 2026-03-23 | 1 | 468 |
| 2026-03-24 | 1 | 468 |
| 2026-03-25 | 1 | 468 |
| 2026-03-26 | 1 | 468 |
| 2026-03-27 | 1 | 468 |
| 2026-03-28 | 1 | 468 |
| 2026-03-29 | 1 | 468 |
| 2026-03-30 | 8 | 1236 |
| 2026-03-31 | 4 | 456 |
| 2026-04-01 | 5 | 2304 |
| 2026-04-08 | 5 | 972 |
| 2026-04-09 | 1 | 468 |
| 2026-04-18 | 1 | 480 |
| 2026-04-19 | 13 | 3060 |
| 2026-04-20 | 3 | 1440 |
| 2026-04-23 | 6 | 1224 |
| 2026-04-26 | 3 | 1440 |
| 2026-04-27 | 32 | 15360 |
| 2026-04-28 | 31 | 14880 |
| 2026-04-29 | 30 | 14400 |
| 2026-04-30 | 25 | 12000 |
| 2026-05-01 | 21 | 10332 |
| 2026-05-07 | 4 | 1968 |
| 2026-05-08 | 2 | 984 |
| 2026-05-09 | 3 | 1464 |
| 2026-05-10 | 30 | 14964 |
| 2026-05-11 | 31 | 15624 |
| 2026-05-12 | 33 | 16428 |
| 2026-05-13 | 34 | 16728 |
| 2026-05-14 | 22 | 10824 |

**Global regime distribution (GLOBAL selector mode):**

| global_regime | n |
|---|---|
| GLOBAL_NEUTRAL | 23586 |
| GLOBAL_BTC_MILD_DECLINE | 11847 |
| GLOBAL_RISK_ON | 5373 |
| GLOBAL_ROTATION_WINDOW | 6 |

---

## Validation method

Window mode: **week**. The dataset is split by calendar week and each hypothesis is evaluated independently per window.

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

**Top-level validation status: `MULTI_WINDOW_DATA_PRESENT`**

### H1 — BTC_MILD_DECLINE_4H_BOUNCE

**Horizon:** 4h | **Stability:** `PROMISING_REPEATED`

**Overall aggregate:**

| n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% |
|---|---|---|---|---|
| 3539 | +0.33 | +57.5 | +1.84 | -1.13 |

**Per-week breakdown (min_n_ret≥10):**

| window | n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% | pass |
|---|---|---|---|---|---|---|
| 2026-W12 | 39 | +0.51 | +79.5 | +3.05 | -1.40 | PASS |
| 2026-W13 | 117 | +0.11 | +51.3 | +1.19 | -1.16 | PASS |
| 2026-W14 | — | — | — | — | — | — |
| 2026-W15 | — | — | — | — | — | — |
| 2026-W16 | 40 | -1.20 | +15.0 | +1.87 | -2.07 | FAIL |
| 2026-W17 | 140 | +0.88 | +77.9 | +2.14 | -1.18 | PASS |
| 2026-W18 | 1560 | +0.26 | +57.6 | +1.47 | -0.94 | PASS |
| 2026-W19 | 205 | +1.07 | +73.2 | +2.85 | -1.38 | PASS |
| 2026-W20 | 1435 | +0.29 | +54.3 | +2.10 | -1.27 | PASS |

### H2 — BTC_MILD_DECLINE_CLASS_STRESS_4H_BOUNCE

**Horizon:** 4h | **Stability:** `REJECTED`

**Overall aggregate:**

| n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% |
|---|---|---|---|---|
| 529 | +0.65 | +62.0 | +2.17 | -1.14 |

**Per-week breakdown (min_n_ret≥10):**

| window | n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% | pass |
|---|---|---|---|---|---|---|
| 2026-W12 | — | — | — | — | — | — |
| 2026-W13 | — | — | — | — | — | — |
| 2026-W14 | — | — | — | — | — | — |
| 2026-W15 | — | — | — | — | — | — |
| 2026-W16 | 20 | -1.23 | +15.0 | +2.02 | -2.24 | FAIL |
| 2026-W17 | — | — | — | — | — | — |
| 2026-W18 | 54 | +0.23 | +42.6 | +2.44 | -1.21 | FAIL |
| 2026-W19 | — | — | — | — | — | — |
| 2026-W20 | 440 | +0.79 | +66.4 | +2.12 | -1.07 | PASS |

### H3 — CLASS_LEADERSHIP_OVEREXTENSION_TRAP

**Horizon:** 4h | **Stability:** `MIXED`

**Overall aggregate:**

| n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% |
|---|---|---|---|---|
| 251 | -2.45 | +24.3 | +2.00 | -4.45 |

**Per-week breakdown (min_n_ret≥10):**

| window | n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% | pass |
|---|---|---|---|---|---|---|
| 2026-W12 | — | — | — | — | — | — |
| 2026-W13 | — | — | — | — | — | — |
| 2026-W14 | — | — | — | — | — | — |
| 2026-W15 | — | — | — | — | — | — |
| 2026-W16 | — | — | — | — | — | — |
| 2026-W17 | — | — | — | — | — | — |
| 2026-W18 | 30 | -6.43 | 0.0 | +2.29 | -7.28 | PASS |
| 2026-W19 | 195 | -2.17 | +23.6 | +1.82 | -4.00 | PASS |
| 2026-W20 | 15 | +0.14 | +66.7 | +3.56 | -5.85 | FAIL |

### H4 — BTC_RISK_ON_ALT_NO_LIFT_WARNING

**Horizon:** 4h | **Stability:** `MIXED`

**Overall aggregate:**

| n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% |
|---|---|---|---|---|
| 1791 | -1.12 | +31.4 | +2.07 | -2.60 |

**Per-week breakdown (min_n_ret≥10):**

| window | n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% | pass |
|---|---|---|---|---|---|---|
| 2026-W12 | — | — | — | — | — | — |
| 2026-W13 | 78 | -0.66 | +23.1 | +0.97 | -1.45 | PASS |
| 2026-W14 | 226 | +0.16 | +51.3 | +1.39 | -1.42 | FAIL |
| 2026-W15 | 80 | -1.64 | +5.0 | +1.44 | -2.53 | PASS |
| 2026-W16 | — | — | — | — | — | — |
| 2026-W17 | 141 | +0.05 | +50.4 | +2.51 | -1.50 | FAIL |
| 2026-W18 | 846 | -2.06 | +19.4 | +2.01 | -2.96 | PASS |
| 2026-W19 | 210 | +1.25 | +83.3 | +3.67 | -2.75 | FAIL |
| 2026-W20 | 210 | -1.82 | +7.1 | +1.83 | -3.48 | PASS |

### H5 — POLICY_INSUFFICIENT_SAMPLE_NEGATIVE_BUCKET

**Horizon:** 24h | **Stability:** `MIXED`

**Overall aggregate:**

| n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% |
|---|---|---|---|---|
| 274 | -2.87 | +18.6 | +3.27 | -4.88 |

**Per-week breakdown (min_n_ret≥10):**

| window | n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% | pass |
|---|---|---|---|---|---|---|
| 2026-W12 | — | — | — | — | — | — |
| 2026-W13 | — | — | — | — | — | — |
| 2026-W14 | — | — | — | — | — | — |
| 2026-W15 | — | — | — | — | — | — |
| 2026-W16 | — | — | — | — | — | — |
| 2026-W17 | — | — | — | — | — | — |
| 2026-W18 | — | — | — | — | — | — |
| 2026-W19 | 44 | -0.26 | +61.4 | +8.53 | -4.65 | FAIL |
| 2026-W20 | 230 | -3.37 | +10.4 | +2.26 | -4.93 | PASS |

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
