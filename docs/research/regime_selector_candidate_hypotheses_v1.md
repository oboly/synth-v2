# Regime Selector Candidate Hypotheses V1

**Source findings:** `docs/research/regime_selector_backtest_v1_1_findings_summary.md`
**Source data:** `regime_selector_backtest_observation_v1` — `report_version=1.1`
**Venue:** bitvavo | **Interval:** 4h | **Observation window:** 2026-05-10 to 2026-05-14 (4-day bearish)

---

## Boundary

- Research-only
- Market-only
- Account-agnostic
- No account state, no balances, no positions
- No broker calls
- No order logic
- No paper/live distinction
- No routing implementation yet

---

## Source findings

- `docs/research/regime_selector_backtest_v1_1_findings_summary.md`
- `report_version=1.1` in `regime_selector_backtest_observation_v1`

The v1.1 findings establish the empirical basis for these hypotheses. Hypotheses do not
extend or modify those findings — they translate them into testable propositions with
explicit validation requirements and rejection criteria.

---

## Candidate hypotheses

---

### Candidate 1 — BTC_MILD_DECLINE_4H_BOUNCE

**Condition**
- `global_regime = GLOBAL_BTC_MILD_DECLINE`
  - BTC 24h return ∈ [−5%, −1%)

**Expected behavior**
- Short-term 4h bounce profile; positive average return and majority win rate at 4h.
- Not a directional or swing hold signal.

**Evidence (v1.1, report_version=1.1)**

| horizon | n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% |
|---|---|---|---|---|---|
| 4h | 1,435 | +0.29 | 54.3 | 2.10 | −1.27 |
| 24h | 451 | −2.68 | 8.9 | 3.80 | −3.95 |

**Failure / reversal**
- By 24h the signal fully inverts: `GLOBAL_BTC_MILD_DECLINE` is the worst global regime
  at the 24h horizon (−2.68% avg, 8.9% win).
- 4h bounce does not carry forward.

**Interpretation**
- Mild BTC selling pressure (not crash, not neutral) may create a temporary supply/demand
  imbalance that resolves in altcoin favourable price action within 4h, then gives way to
  continued selling pressure.
- Possible mechanism: oversold reaction to BTC mild drawdown, resolved quickly.
- This is not a confirmed mechanism — it is a testable hypothesis.

**Single-window caveat**
- The entire evidence base comes from a 4-day bearish window in May 2026.
- `GLOBAL_BTC_MILD_DECLINE` may not even appear in a sustained bull market — the regime
  itself may be sparse or absent across market cycles.

**Readiness**
- Candidate only. Requires multi-window validation before any downstream use.

---

### Candidate 2 — BTC_MILD_DECLINE_CLASS_STRESS_4H_BOUNCE

**Condition**
- `global_regime = GLOBAL_BTC_MILD_DECLINE`
- `asset_class_regime = CLASS_STRESS`
  - Class 24h return vs BTC 24h return < −2%

**Expected behavior**
- Strongest observed short-term bounce cross in the v1.1 dataset.
- Stressed asset classes under mild BTC decline may see the sharpest mean-reversion bounce
  at 4h due to compounded selling pressure correcting in the short window.

**Evidence (v1.1, 4h)**

| cross | n_ret | avg_ret% | win_rate% | avg_mae% |
|---|---|---|---|---|
| GLOBAL_BTC_MILD_DECLINE\|CLASS_STRESS | 440 | +0.79 | 66.4 | −1.07 |
| GLOBAL_BTC_MILD_DECLINE\|CLASS_NEUTRAL | 618 | +0.28 | 51.8 | −1.25 |
| GLOBAL_BTC_MILD_DECLINE\|CLASS_LAGGARD | 342 | −0.31 | 41.5 | −1.62 |

**Failure / reversal**
- At 24h the CLASS_STRESS cross inverts to −3.57% avg / 5.0% win — the worst 24h cross
  in the dataset.
- The bounce is short-lived and followed by continued deterioration.

**Interpretation**
- CLASS_STRESS (class underperforming BTC by > 2%) under mild BTC decline appears to
  produce the sharpest 4h bounce, but the 24h profile indicates this is a mean-reversion
  snap, not the start of outperformance.
- CLASS_LAGGARD (underperforming BTC by 1–2%) does not bounce at 4h — the threshold
  matters; mild class stress is not equivalent to severe class stress.

**Readiness**
- Promising. n=440 at 4h is sufficient for directional signal.
- Must be validated across bull, sideways, and post-spike windows before use.

---

### Candidate 3 — CLASS_LEADERSHIP_OVEREXTENSION_TRAP

**Condition**
- `asset_class_regime = CLASS_LEADERSHIP`
  - Class 24h return vs BTC 24h return > +4%
- Especially when `global_regime = GLOBAL_NEUTRAL`

**Expected behavior**
- Overextended class after recent outperformance produces adverse 4h outcomes.
- Not a buy/add context; candidate negative filter.

**Evidence (v1.1, 4h)**

| cross | n_ret | avg_ret% | win_rate% | avg_mae% |
|---|---|---|---|---|
| GLOBAL_NEUTRAL\|CLASS_LEADERSHIP | 75 | −2.81 | 13.3 | −5.21 |

**For comparison — worst observed 4h cross.**

**Interpretation**
- CLASS_LEADERSHIP after recent outperformance (class outpacing BTC by > 4% in 24h) in
  a flat global regime may indicate late entry or exhaustion, not continued momentum.
- High class return relative to BTC can reflect a brief rotation spike rather than
  sustained relative strength.
- The −5.21% average MAE at 4h is the deepest in the dataset — entries here face
  significant intrabar drawdown even if they recover.

**Current n caveat**
- n=75 is too low for a standalone quantitative signal.
- Direction is consistent with the theoretical interpretation, but the magnitude and
  specific cross combination need higher-n confirmation.

**Readiness**
- Candidate negative filter only. Directional signal only at current n.
- Do not use as a primary routing rule until validated across more windows and n ≥ 200.

---

### Candidate 4 — BTC_RISK_ON_ALT_NO_LIFT_WARNING

**Condition**
- `global_regime = GLOBAL_RISK_ON`
  - BTC 24h return > +1%
- Especially when asset class is not actively participating (CLASS_NEUTRAL or CLASS_LAGGARD)

**Expected behavior**
- BTC rising does not automatically produce positive altcoin selection outcomes at 4h.
- Naive risk-on assumption — that BTC up means altcoin positions should outperform — is
  not supported in this observation window.

**Evidence (v1.1, 4h)**

| regime | n_ret | avg_ret% | win_rate% | avg_mae% |
|---|---|---|---|---|
| GLOBAL_RISK_ON | 210 | −1.82 | 7.1 | −3.48 |
| GLOBAL_RISK_ON\|CLASS_NEUTRAL | 205 | −1.82 | 7.3 | −3.51 |

**Interpretation**
- In the observed window (bearish macro), GLOBAL_RISK_ON had the lowest 4h win rate of
  any global regime (7.1%). This may reflect brief BTC recovery rallies that did not
  rotate into altcoins.
- The CLASS_NEUTRAL cross contains essentially all GLOBAL_RISK_ON observations, suggesting
  that during these brief BTC bounces, asset classes remained flat/underperforming.
- The −3.48% average MAE at 4h indicates that even the maximum intrabar gain was followed
  by reversal within the candle window.

**Single-window caveat**
- This entire observation window is bearish. GLOBAL_RISK_ON had only 210 observations —
  representing short-lived BTC bounces within a downtrend, not sustained bull regime.
- In a genuine bull cycle, GLOBAL_RISK_ON may produce very different outcomes.
- This hypothesis is directional only until validated across bull-cycle windows.

**Readiness**
- Candidate warning signal. Directional observation, not a routing rule.
- Needs bull/sideways cycle validation urgently before any interpretation is generalized.

---

### Candidate 5 — POLICY_INSUFFICIENT_SAMPLE_NEGATIVE_BUCKET

**Condition**
- `strategy_signature` contains `POLICY=INSUFFICIENT_SAMPLE`
  - i.e. `setup_filter_state=PASS` and `policy_decision=INSUFFICIENT_SAMPLE`

**Expected behavior**
- Strategies in this signature bucket show a weaker forward profile at 24h.

**Evidence (v1.1, 24h)**

| signature | n_ret | avg_ret% | win_rate% |
|---|---|---|---|
| SEL=WATCHLIST\|SETUP=PASS\|POLICY=INSUFFICIENT_SAMPLE\|ADVICE=UNKNOWN\|APLUS=UNKNOWN | 233 | −3.42 | 10.3 |

**For comparison at 24h:**

| signature | n_ret | avg_ret% | win_rate% |
|---|---|---|---|
| SEL=WATCHLIST\|SETUP=FAIL\|POLICY=UNKNOWN\|ADVICE=UNKNOWN\|APLUS=UNKNOWN | 1,740 | −1.77 | 19.1 |
| SEL=WATCHLIST\|SETUP=PASS\|POLICY=WATCH_ONLY\|ADVICE=UNKNOWN\|APLUS=UNKNOWN | 68 | −1.43 | 30.9 |

**Interpretation**
- `POLICY=INSUFFICIENT_SAMPLE` appears as a weaker outcome bucket than `WATCH_ONLY`
  and even `SETUP=FAIL` at 24h.
- This is directionally consistent: a strategy that passed setup filtering but has
  insufficient policy sample depth may represent a lower-confidence state.
- The comparison with `AVOID|SETUP=FAIL` (−3.40% / 2.9% win) and
  `AVOID|SETUP=UNKNOWN` (−1.36% / 25.0% win) suggests `SETUP=FAIL` carries
  additional negative information beyond the selection state alone — a separate
  but related observation.

**Secondary observation — WATCH_ONLY vs ALLOW_24H**
- `POLICY=WATCH_ONLY`: 24h avg −1.43%, win_rate 30.9% (n=68)
- `POLICY=BLOCK_FOR_24H`: 24h avg −2.52%, win_rate 12.7% (n=79)
- Permissive policy decisions did not add positive expected value at 24h.
- Note: n is low for both. Direction only.

**Readiness**
- Keep as policy-quality observation.
- Do not route from this observation yet.
- Validate the `INSUFFICIENT_SAMPLE` bucket across more windows and assess whether it
  remains consistently below `WATCH_ONLY` at multiple horizons.

---

## Validation requirements before downstream use

For any candidate to progress from hypothesis to routing candidate, it must satisfy all
of the following:

**Window coverage**
- Validated across multiple non-overlapping market windows.
- Windows must include: bull, bear, sideways, and post-spike (BTC ±15% in 7 days) regimes.
- The current evidence (2026-05-10 to 2026-05-14) is a 4-day bearish window only.

**Sample adequacy**
- n_ret ≥ 200 per horizon per candidate, post multi-window aggregation.
- Candidates with n < 100 in this window require proportionally more windows before
  promotion.

**Signal stability**
- Stable sign of avg_ret across all validation windows (not just majority).
- Win rate separation from the all-horizon baseline (39.4% at 4h) must hold across windows.
- Sign reversal in more than one validation window is sufficient grounds for rejection.

**MFE/MAE ratio**
- MFE:MAE ratio ≥ 1.5 at the intended action horizon.
- If avg_ret is positive but avg_MFE/avg_MAE < 1.0, treat as a trap, not a signal.

**Horizon specificity**
- If the candidate has a sign reversal across horizons (e.g. positive at 4h, negative at
  24h), this must be documented explicitly and the candidate scoped to one horizon only.
- Do not promote a candidate that shows a strong 4h signal without documenting and
  acknowledging the 24h reversal.

**Robustness checks**
- Results must hold excluding BTC and ETH from the asset set.
- Results must hold excluding assets with < 30-day listing age or daily volume < threshold.
- Results must not be driven by a single asset class.

**Candle completeness**
- No candidate may be promoted if its evidence relies on observations where 72h forward
  candles do not yet exist (i.e. recent snapshots with incomplete forward windows).

---

## Rejection criteria

Reject or downgrade a candidate to REJECTED or INCONCLUSIVE if any of the following hold:

| Rejection condition | Notes |
|---|---|
| Effect disappears outside the current 4-day bearish window | The window is not representative of all market conditions |
| Effect is driven by one asset class | Robustness check failure |
| Evidence relies on incomplete recent candles | Forward return bias |
| avg_ret positive but MFE/MAE < 1.0 | Trap, not signal |
| High win_rate but tiny avg_ret and large MAE | Win rate is misleading |
| n_ret < 100 after multi-window aggregation | Insufficient statistical basis |
| Effect contradicts across 4h/24h/72h without a clear mechanism | Unexplained instability |
| Sign of avg_ret flips in more than one validation window | Not a stable signal |

Downgrade (not reject) if:
- Effect is real but only in specific asset class subsets — scope the hypothesis narrower.
- Effect is real but n is marginal — keep as directional observation, not routing candidate.

---

## Current status table

| Candidate | Code | 4h Evidence | 24h Evidence | n_ret (4h) | Readiness |
|---|---|---|---|---|---|
| BTC_MILD_DECLINE_4H_BOUNCE | H1 | +0.29%, 54.3% win | −2.68%, 8.9% win | 1,435 | Multi-window validation needed |
| BTC_MILD_DECLINE_CLASS_STRESS_4H_BOUNCE | H2 | +0.79%, 66.4% win | inverted, −3.57% | 440 | Multi-window validation needed |
| CLASS_LEADERSHIP_OVEREXTENSION_TRAP | H3 | −2.81%, 13.3% win | not isolated | 75 | Low n — directional only |
| BTC_RISK_ON_ALT_NO_LIFT_WARNING | H4 | −1.82%, 7.1% win | — | 210 | Bull cycle validation needed |
| POLICY_INSUFFICIENT_SAMPLE_NEGATIVE_BUCKET | H5 | — | −3.42%, 10.3% win | (24h n=233) | Policy-quality observation only |

---

## Downstream path

```
1. Candidate hypotheses v1  ← THIS DOCUMENT
   → translate findings into testable propositions with rejection criteria

2. Multi-window validation report
   → run backtest across bull, bear, sideways, post-spike windows
   → validate or reject each candidate

3. Candidate promotion / rejection list
   → explicit PROMOTED / REJECTED / INCONCLUSIVE per hypothesis
   → define final scope for any promoted candidates (horizon, class filter, etc.)

4. active_regime_observation design
   → live regime classification table (reads market data only)
   → only after step 3 produces at least one PROMOTED candidate
   → no decision_gate, no execution_planner, no executor

5. policy_router preview
   → maps (active_regime, strategy_state) → routing signal
   → only after active_regime_observation is designed and validated
   → pure read layer; no order placement

6. selection/advice integration
   → only after policy_router is validated end-to-end
   → reviewed against decision_gate boundary before integration

7. decision_gate / execution remains untouched
   → until separately designed and explicitly authorized
```

Do not skip steps. Do not build steps 4–7 based on single-window findings alone.

---

## Explicit non-goals

This document and any associated code:

- Do not produce live or paper trade signals.
- Do not produce order, advice, or execution instructions.
- Do not modify `selection_engine`.
- Do not modify `decision_gate`.
- Do not modify `execution_planner`.
- Do not modify `executor`.
- Do not distinguish paper from live.
- Do not call any broker or exchange API.
- Do not write to any table except an explicit research output table.

---

## Safety

```
[SAFETY] broker_calls=0  broker_writes=0  order_submission=0  live_orders=0
[SCOPE]  research-only  market-only  account-agnostic  hypothesis-document-only
```
