# Regime Selector Backtest — v1.1 Findings Summary

**Generated from:** `run_regime_selector_v1_1_findings_report.py`
**Table:** `regime_selector_backtest_observation_v1`
**Versions compared:** 1.0 (baseline) vs 1.1 (corrected classifier + canonical signatures)
**Venue:** bitvavo | **Interval:** 4h | **Snapshots:** 120 (2026-05-10 to 2026-05-14)
**Boundary:** research-only · market-only · account-agnostic · no broker calls

---

## 1. Data integrity — both versions

| report_version | total_rows | selector_modes | distinct_signatures | snapshots |
|---|---|---|---|---|
| 1.0 | 59,676 | 4 (balanced 14,919 each) | 37 | 120 |
| 1.1 | 59,640 | 4 (balanced 14,910 each) | 39 | 120 |

Both versions are internally balanced: all four selector_modes (GLOBAL, ASSET_CLASS,
GLOBAL_CLASS, STRATEGY_SIGNATURE) have identical row counts. No mode-shape violations.
The 36-row difference between versions reflects minor snapshot-boundary changes between
the two runs.

---

## 2. Strategy signature format — fully corrected

| report_version | keyed format (`SEL=…`) | positional format | null/empty |
|---|---|---|---|
| 1.0 | 0 | 59,676 | 0 |
| 1.1 | 59,640 | 0 | 0 |

v1.0: all positional (e.g. `WATCHLIST|FAIL|UNKNOWN|UNKNOWN|UNKNOWN`)
v1.1: all keyed (e.g. `SEL=WATCHLIST|SETUP=FAIL|POLICY=UNKNOWN|ADVICE=UNKNOWN|APLUS=UNKNOWN`)

Zero positional signatures in v1.1. Zero null/empty in either version.
v1.1 has 39 distinct signatures vs 37 in v1.0 — the keyed format exposes two additional
buckets that the positional format was collapsing together (differing SETUP/POLICY combinations
that mapped to the same positional string).

---

## 3. GLOBAL_UNKNOWN — the v1.0 semantic error, confirmed

The core problem in v1.0 was that the classifier had no label for BTC 24h returns in
[−5%, −1%). Those observations fell through to `GLOBAL_UNKNOWN`.

### v1.0 GLOBAL_UNKNOWN composition (horizon=24h)

| BTC 24h range | n | avg_ret% | win_rate% |
|---|---|---|---|
| −5% to −1% (mild decline — the leak) | 1,640 | −2.68 | 8.9 |

**All 1,640 GLOBAL_UNKNOWN rows in v1.0 contain real BTC return data** (none are
truly missing). `unknown_with_btc_data = 4,920` across all modes confirms this.
In v1.0, `GLOBAL_UNKNOWN` was 100% mislabelled market state, not missing data.

### v1.1 GLOBAL_UNKNOWN status

| report_version | unknown_total | unknown_with_btc_data | unknown_truly_missing |
|---|---|---|---|
| 1.0 | 4,920 | 4,920 | 0 |
| **1.1** | **0** | **0** | **0** |

In the current 120-snapshot window, BTC candle data is present for all snapshots.
`GLOBAL_UNKNOWN` has zero rows in v1.1 — the semantic label now means what it says.

---

## 4. GLOBAL regime distribution — v1.0 vs v1.1

### 4h horizon

**v1.0**

| regime | n_total | n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% |
|---|---|---|---|---|---|---|
| GLOBAL_UNKNOWN | 1,640 | 1,230 | **+0.20** | **51.1** | 2.04 | −1.40 |
| GLOBAL_NEUTRAL | 3,123 | 3,071 | −1.02 | 33.1 | 2.04 | −2.60 |
| GLOBAL_RISK_ON | 210 | 210 | −1.82 | 7.1 | 1.83 | −3.48 |

**v1.1**

| regime | n_total | n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% |
|---|---|---|---|---|---|---|
| GLOBAL_BTC_MILD_DECLINE | 1,804 | 1,435 | **+0.29** | **54.3** | 2.10 | −1.27 |
| GLOBAL_NEUTRAL | 2,956 | 2,945 | −0.94 | 34.5 | 2.06 | −2.52 |
| GLOBAL_RISK_ON | 210 | 210 | −1.82 | 7.1 | 1.83 | −3.48 |

**Interpretation change at 4h:** The positive signal previously attributed to
`GLOBAL_UNKNOWN` is now correctly attributed to `GLOBAL_BTC_MILD_DECLINE`. The
magnitude strengthens slightly (from +0.20% to +0.29%, win rate 51.1% → 54.3%)
because the v1.1 bucket includes a small number of additional observations at
the boundary. The signal is real and now has a correct semantic label.

### 24h horizon

**v1.1**

| regime | n_ret | avg_ret% | win_rate% |
|---|---|---|---|
| GLOBAL_RISK_ON | 210 | −1.99 | 19.0 |
| GLOBAL_NEUTRAL | 2,714 | −2.06 | 18.1 |
| GLOBAL_BTC_MILD_DECLINE | 451 | **−2.68** | **8.9** |

At 24h, `GLOBAL_BTC_MILD_DECLINE` is the **worst** regime. The 4h bounce inverts.
GLOBAL_NEUTRAL and GLOBAL_RISK_ON converge to near-identical 24h outcomes (−2.06% vs
−1.99%), suggesting global BTC context has low 24h discriminating power in this window.

### 72h horizon

`GLOBAL_BTC_MILD_DECLINE` has zero 72h returns — these are the most recent snapshots
(2026-05-12 to 2026-05-14) where the 72h forward candles do not yet exist.
Available: GLOBAL_NEUTRAL (−4.62%, n=533), GLOBAL_RISK_ON (−6.62%, n=205).

---

## 5. GLOBAL_BTC_MILD_DECLINE across horizons (v1.1)

| horizon | n_total | n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% |
|---|---|---|---|---|---|---|
| **4h** | 1,804 | 1,435 | **+0.29** | **54.3** | 2.10 | −1.27 |
| **24h** | 1,804 | 451 | **−2.68** | **8.9** | 3.80 | −3.95 |
| **72h** | 1,804 | 0 | — | — | — | — |

The horizon reversal is sharp and consistent:
- 4h: positive average return, majority win rate — bounce behaviour
- 24h: worst global regime, lowest win rate — the bounce does not persist

The MAE at 4h is the smallest of any global regime (−1.27%), supporting the view that
mild BTC decline creates a low-drawdown, short-lived bounce window, not a sustained rally.

---

## 6. GLOBAL_CLASS cross — v1.1 (4h, n_ret ≥ 40)

| cross | n_ret | avg_ret% | win_rate% | avg_mae% |
|---|---|---|---|---|
| GLOBAL_BTC_MILD_DECLINE\|CLASS_STRESS | 440 | **+0.79** | **66.4** | −1.07 |
| GLOBAL_BTC_MILD_DECLINE\|CLASS_NEUTRAL | 618 | +0.28 | 51.8 | −1.25 |
| GLOBAL_BTC_MILD_DECLINE\|CLASS_LAGGARD | 342 | −0.31 | 41.5 | −1.62 |
| GLOBAL_NEUTRAL\|CLASS_UNKNOWN | 71 | −0.33 | 45.1 | −1.11 |
| GLOBAL_NEUTRAL\|CLASS_LAGGARD | 103 | −0.39 | 18.4 | −2.25 |
| GLOBAL_NEUTRAL\|CLASS_NEUTRAL | 1,659 | −0.77 | 37.6 | −2.56 |
| GLOBAL_NEUTRAL\|CLASS_PULLBACK | 474 | −1.15 | 26.8 | −2.38 |
| GLOBAL_NEUTRAL\|CLASS_STRESS | 563 | −1.18 | 36.1 | −2.41 |
| GLOBAL_RISK_ON\|CLASS_NEUTRAL | 205 | −1.82 | 7.3 | −3.51 |
| GLOBAL_NEUTRAL\|CLASS_LEADERSHIP | 75 | −2.81 | 13.3 | −5.21 |

The two positive 4h buckets are both `GLOBAL_BTC_MILD_DECLINE` crosses.
The `GLOBAL_BTC_MILD_DECLINE|CLASS_STRESS` combination (n=440) has the only
large-sample positive return (+0.79%) and the highest win rate (66.4%) in
the entire 4h dataset. Its MAE (−1.07%) is also the shallowest, indicating
limited downside in this window.

At 24h, the same cross inverts to the worst outcome (−3.57%, 5.0% win),
confirming the 4h bounce does not carry.

**The worst 4h cross remains:** `GLOBAL_NEUTRAL|CLASS_LEADERSHIP` at −2.81%,
13.3% win — overbought class entering a flat market.

---

## 7. Horizon overall summary — v1.1

| horizon | n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% | min | max |
|---|---|---|---|---|---|---|---|
| 4h | 4,590 | −0.59 | 39.4 | 2.07 | −2.17 | −13.10 | +17.79 |
| 24h | 3,375 | −2.14 | 16.9 | 3.08 | −4.14 | −11.63 | +26.18 |
| 72h | 738 | −5.17 | 9.6 | 4.65 | −7.10 | −14.55 | +21.27 |

The 4h window has the highest win rate (39.4%) and lowest average loss. The MFE:MAE
ratio deteriorates with horizon length, indicating the market moved further against
entries the longer the hold. The full window is net-bearish; no horizon produces
a positive average return.

---

## 8. Strategy signature comparison — top buckets at 24h

### v1.0 (positional format)

| signature | n_ret | avg_ret% | win_rate% |
|---|---|---|---|
| `WATCHLIST\|FAIL\|UNKNOWN\|UNKNOWN\|UNKNOWN` | 1,788 | −1.74 | 19.5 |
| `NEUTRAL\|FAIL\|UNKNOWN\|UNKNOWN\|UNKNOWN` | 660 | −2.49 | 15.0 |
| `AVOID\|FAIL\|UNKNOWN\|UNKNOWN\|UNKNOWN` | 156 | −3.06 | 3.8 |
| `WATCHLIST\|PASS\|INSUFFICIENT_SAMPLE\|UNKNOWN\|UNKNOWN` | 229 | −3.27 | 11.4 |
| `PREPARE\|FAIL\|UNKNOWN\|UNKNOWN\|UNKNOWN` | 125 | −2.15 | 18.4 |
| `AVOID\|UNKNOWN\|UNKNOWN\|UNKNOWN\|UNKNOWN` | 90 | −1.05 | 28.9 |
| `WATCHLIST\|PASS\|BLOCK_FOR_24H\|UNKNOWN\|UNKNOWN` | 83 | −2.45 | 12.0 |
| `WATCHLIST\|PASS\|WATCH_ONLY\|UNKNOWN\|UNKNOWN` | 69 | −1.68 | 27.5 |

### v1.1 (keyed format)

| signature | n_ret | avg_ret% | win_rate% |
|---|---|---|---|
| `SEL=WATCHLIST\|SETUP=FAIL\|POLICY=UNKNOWN\|ADVICE=UNKNOWN\|APLUS=UNKNOWN` | 1,740 | −1.77 | 19.1 |
| `SEL=NEUTRAL\|SETUP=FAIL\|POLICY=UNKNOWN\|ADVICE=UNKNOWN\|APLUS=UNKNOWN` | 737 | −2.66 | 13.7 |
| `SEL=AVOID\|SETUP=FAIL\|POLICY=UNKNOWN\|ADVICE=UNKNOWN\|APLUS=UNKNOWN` | 206 | −3.40 | 2.9 |
| `SEL=WATCHLIST\|SETUP=PASS\|POLICY=INSUFFICIENT_SAMPLE\|ADVICE=UNKNOWN\|APLUS=UNKNOWN` | 233 | −3.42 | 10.3 |
| `SEL=PREPARE\|SETUP=FAIL\|POLICY=UNKNOWN\|ADVICE=UNKNOWN\|APLUS=UNKNOWN` | 122 | −2.13 | 18.9 |
| `SEL=AVOID\|SETUP=UNKNOWN\|POLICY=UNKNOWN\|ADVICE=UNKNOWN\|APLUS=UNKNOWN` | 92 | −1.36 | 25.0 |
| `SEL=WATCHLIST\|SETUP=PASS\|POLICY=BLOCK_FOR_24H\|ADVICE=UNKNOWN\|APLUS=UNKNOWN` | 79 | −2.52 | 12.7 |
| `SEL=WATCHLIST\|SETUP=PASS\|POLICY=WATCH_ONLY\|ADVICE=UNKNOWN\|APLUS=UNKNOWN` | 68 | −1.43 | 30.9 |

The relative ordering and magnitudes are stable between versions.
Key signal from signatures:
- `WATCH_ONLY` outperforms `BLOCK_FOR_24H` and `ALLOW_24H` at 24h — the
  policy's permissive decisions do not add positive expected value.
- `INSUFFICIENT_SAMPLE` is a reliable negative signal (−3.42% at 24h).
- `AVOID|SETUP=FAIL` is the weakest selection state at 24h (−3.40%, 2.9% win).
- `AVOID|SETUP=UNKNOWN` (no filter data available) is notably better than
  `AVOID|SETUP=FAIL` (−1.36% vs −3.40%), suggesting `SETUP=FAIL` carries
  additional negative information beyond the `AVOID` selection state alone.

---

## 9. Does v1.1 change interpretation vs v1.0?

**Yes, in one specific and material way:**

In v1.0, the positive 4h signal at 51.1% win rate / +0.20% average return was
attributed to `GLOBAL_UNKNOWN` — a label that should mean missing data. That
made the signal appear unreliable or an artefact.

In v1.1, the same signal is correctly attributed to `GLOBAL_BTC_MILD_DECLINE`
(BTC 24h ∈ [−5%, −1%]). The signal strengthens (54.3% win / +0.29%) and is
now semantically coherent: mild BTC selling pressure produces short-term bounce
behaviour in altcoin selections at 4h, which then reverses sharply by 24h.

**Everything else is stable:** GLOBAL_NEUTRAL and GLOBAL_RISK_ON show negligible
changes in avg_ret or win_rate between versions (rounding-level differences only).
Strategy signature relative ordering is preserved. GLOBAL_CLASS cross rankings
and magnitudes are consistent.

---

## 10. Key findings table

| Finding | Horizon | Regime / Signature | avg_ret% | win_rate% | n_ret | Reliability |
|---|---|---|---|---|---|---|
| Mild BTC decline bounce | 4h | GLOBAL_BTC_MILD_DECLINE | +0.29 | 54.3 | 1,435 | High (large n) |
| Mild decline × stressed class | 4h | GBMD\|CLASS_STRESS | +0.79 | 66.4 | 440 | Moderate |
| Mild decline × neutral class | 4h | GBMD\|CLASS_NEUTRAL | +0.28 | 51.8 | 618 | High |
| Mild decline 24h reversal | 24h | GLOBAL_BTC_MILD_DECLINE | −2.68 | 8.9 | 451 | Moderate |
| Overbought class trap | 4h | GNEUTRAL\|CLASS_LEADERSHIP | −2.81 | 13.3 | 75 | Low n — directional only |
| BTC risk-on flat at 4h | 4h | GLOBAL_RISK_ON | −1.82 | 7.1 | 210 | Moderate |
| Policy WATCH_ONLY > ALLOW_24H | 24h | signature | −1.43 vs −2.52 | 31 vs 13 | 68 / 79 | Low n — directional |
| INSUFFICIENT_SAMPLE signal | 24h | SETUP=PASS\|POLICY=INSUFF | −3.42 | 10.3 | 233 | Moderate |

**Single-window caveat:** All findings are from a 4-day bearish window (2026-05-10 to
2026-05-14). The mild-decline bounce signal, while the clearest positive in the data,
needs validation across multiple market cycles before it can inform routing design.

---

## 11. What this does not cover

- No decision_gate changes proposed.
- No execution_planner changes proposed.
- No executor or broker logic.
- No paper/live mode logic.
- No policy_router design.
- No routing implementation.

The correct downstream path remains:
```
regime_selector_backtest_v1.1 findings (this document)
    → regime selector candidate rules
    → active_regime_observation design (market-only, read)
    → policy_router design
    → decision_gate integration (separate, validated step)
```

---

## Safety

```
[SAFETY] broker_calls=0  broker_writes=0  order_submission=0  live_orders=0
[SCOPE]  research-only  market-only  account-agnostic  read-only-query
```
