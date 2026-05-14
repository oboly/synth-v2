# Active Regime Observation Design V1

**Status:** Design document — no migration, no runner, no routing implementation.
**Date:** 2026-05-14
**Validated input:** H1 only (`GLOBAL_BTC_MILD_DECLINE`)
**Boundary:** research-only · market-only · account-agnostic

---

## Purpose

Define a market-only observation layer that records current global and asset class
regime state in real time, for downstream research and future policy routing.

`active_regime_observation` is a **classification sink**, not a decision source.
It translates current market candle data into a labelled regime state and stores it.
Nothing downstream reads it as a permission. Nothing reads it as a trade instruction.

---

## Boundary

- **Market-only** — reads BTC and asset class candle data only
- **Account-agnostic** — no balances, no positions, no sleeves, no open orders
- **No paper/live distinction** — regime state is execution-mode-neutral
- **No broker calls** — reads from `obs_market_candle` only
- **No orders** — does not generate, modify, or cancel orders
- **No decision permissions** — does not produce `allowed` / `blocked` / `execution_intent`
- **No execution intent** — does not instruct `execution_planner` or `executor`
- **No selection score modification** — does not alter `selection_state` or `selection_score`

---

## Validated input — H1 only

### GLOBAL_BTC_MILD_DECLINE (H1)

From `regime_selector_multi_window_validation_v1`:

| Metric | Value |
|---|---|
| Condition | BTC 24h return ∈ [−5%, −1%) |
| 4h avg_ret% | +0.33 |
| 4h win_rate% | 57.5 |
| n_ret | 3,539 |
| Weekly pass rate | 6/7 (85.7%) |
| Stability | `PROMISING_REPEATED` |

**What H1 validates:**
- `GLOBAL_BTC_MILD_DECLINE` is a useful market-context label.
- When this regime is active, the 4h forward return distribution for selected altcoins
  is positive on average and wins more often than not.
- The signal reverses at 24h (avg −2.68%, 8.9% win) — the bounce does not carry.

**What H1 does not create:**
- H1 is not an entry rule.
- H1 is not a holding horizon instruction.
- H1 does not route any strategy.
- H1 does not override selection state, setup filter, or policy.
- H1 does not produce advice.

The `active_regime_observation` layer records when `GLOBAL_BTC_MILD_DECLINE` is active.
What happens downstream — if anything — is designed separately in the `policy_router` layer,
which is blocked until the observation layer is stable.

---

## Blocked candidates

The following hypotheses are explicitly not included in this design:

| Hypothesis | Status | Reason |
|---|---|---|
| H2 BTC_MILD_DECLINE_CLASS_STRESS_4H_BOUNCE | **REJECTED** | Weekly pass rate 1/3 (33%); fails in W16 and W18; signal is not repeatable as a standalone condition |
| H3 CLASS_LEADERSHIP_OVEREXTENSION_TRAP | **MIXED** | 2/3 weekly windows pass; n is low; W20 (n=15) reverses sign; needs more data |
| H4 BTC_RISK_ON_ALT_NO_LIFT_WARNING | **MIXED** | 4/7 windows pass; W14 and W19 show strongly positive GLOBAL_RISK_ON outcomes; the signal is context-dependent, not universal |
| H5 POLICY_INSUFFICIENT_SAMPLE_NEGATIVE_BUCKET | **MIXED/SPARSE** | Only 2 qualifying weekly windows; W19 contradicts; requires more policy-layer history |

H2–H5 class and policy regime fields **are included in the observation table schema**
as stored columns (because they are computationally cheap to record and will be needed
when those hypotheses are eventually revisited). They are not tagged as validated.

---

## Proposed observation table — `active_regime_observation_v1`

This schema is proposed for design review. **No migration is created in this document.**
Migration follows only after the schema is reviewed and the runner design is confirmed.

```sql
-- Proposed schema (not yet created)
-- active_regime_observation_v1

active_regime_observation_v1_id  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY
venue                            VARCHAR(32) NOT NULL
interval_code                    VARCHAR(16) NOT NULL       -- candle interval used for regime classification
asof_ts_utc                      DATETIME(6) NOT NULL       -- moment the classification was computed
source_candle_ts_utc             DATETIME(6) NOT NULL       -- close_ts_utc of the BTC candle driving global_regime

-- Global regime
global_regime                    VARCHAR(64) NOT NULL
global_regime_version            VARCHAR(16) NOT NULL       -- e.g. '1.1' — classifier version for audit
btc_return_24h_pct               DECIMAL(20,10)             -- raw BTC 24h return used for classification (NULL if candle missing)
btc_return_72h_pct               DECIMAL(20,10)             -- supplementary context

-- Asset class regime (one row per class per snapshot)
asset_class                      VARCHAR(32) NOT NULL
asset_class_regime               VARCHAR(64) NOT NULL
asset_class_regime_version       VARCHAR(16) NOT NULL
class_return_24h_pct             DECIMAL(20,10)
relative_class_vs_btc_24h_pct    DECIMAL(20,10)

-- Compound cross (pre-computed for downstream convenience)
global_class_regime              VARCHAR(128) NOT NULL      -- e.g. 'GLOBAL_BTC_MILD_DECLINE|CLASS_STRESS'

-- Hypothesis context (informational only — not a routing decision)
validated_hypothesis_tags_json   JSON                       -- e.g. ["H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT"]
validation_status                VARCHAR(32) NOT NULL       -- 'LIVE' | 'RESEARCH_ONLY'

-- Audit
source_ref_json                  LONGTEXT
created_ts_utc                   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
updated_ts_utc                   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)

-- Identity key: one row per (venue, interval, snapshot, asset_class)
UNIQUE KEY uq_active_regime_obs
  (venue, interval_code, asof_ts_utc, asset_class)
```

### Key schema decisions

**One row per (venue, interval_code, asof_ts_utc, asset_class)**
Each snapshot produces one row per asset class. Global regime fields (`global_regime`,
`btc_return_24h_pct`, etc.) are repeated on every row for that snapshot — this avoids
a join when querying any single asset class row and mirrors the design of
`regime_selector_backtest_observation_v1`.

**`global_regime_version` and `asset_class_regime_version`**
Track the classifier version (e.g. `'1.1'`) separately from the table schema version.
When the classification logic changes, old rows are not overwritten — the version field
distinguishes them. Reruns upsert via `ON DUPLICATE KEY UPDATE`.

**`validated_hypothesis_tags_json`**
A JSON array of context tags. Tags are informational only. They record which validated
hypotheses apply to this regime observation at this moment. They are not permissions,
not routing instructions, and not advice.

Example content when `global_regime = GLOBAL_BTC_MILD_DECLINE`:
```json
["H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT"]
```

Example content for any other regime:
```json
[]
```

**`validation_status`**
Set to `'RESEARCH_ONLY'` until the observation layer has been separately validated
end-to-end. When the policy_router design is confirmed and the observation layer is
smoke-tested, this field transitions to `'LIVE'` in a controlled update.

**`source_ref_json`**
Audit trail per row:
```json
{
  "scope": "research-only market-only account-agnostic",
  "broker_calls": 0,
  "broker_writes": 0,
  "order_submission": 0,
  "live_orders": 0,
  "classifier_version": "1.1",
  "source_table": "obs_market_candle",
  "venue": "bitvavo",
  "interval_code": "4h"
}
```

---

## Required classification semantics — v1.1

The classifier must apply these conditions in the exact order listed. Ordering matters
because several ranges overlap and a later rule would silently override a correct
earlier label if order is wrong.

### Global regime classification

Applied to BTC 24h return (`btc_return_24h_pct`).

```
Order  Label                      Condition
-----  -------------------------  ----------------------------------------------------
1      GLOBAL_UNKNOWN             btc_return_24h_pct IS NULL  (missing candle data only)
2      GLOBAL_BTC_BREAKDOWN       btc_return_24h_pct < -0.05
3      GLOBAL_BTC_MILD_DECLINE    btc_return_24h_pct >= -0.05  AND < -0.01
4      GLOBAL_NEUTRAL             btc_return_24h_pct >= -0.01  AND <= +0.01
5      GLOBAL_BTC_OVERHEATED      btc_return_24h_pct > +0.08
6      GLOBAL_ROTATION_WINDOW     btc_return_24h_pct < +0.04
                                  AND avg_alt_return_24h - btc_return_24h_pct > +0.04
7      GLOBAL_RISK_ON             btc_return_24h_pct > +0.01  (catch-all for positive BTC)
```

**Critical ordering notes:**
- Rule 1 is a null guard. Any downstream rule silently produces wrong output if BTC
  candle data is missing but the null check is omitted.
- Rules 2–4 are mutually exclusive by definition. They must be evaluated before
  OVERHEATED (rule 5), because `btc_return_24h_pct > +0.08` is a subset of
  `btc_return_24h_pct > +0.01` (RISK_ON). If OVERHEATED is checked after RISK_ON,
  OVERHEATED observations are silently classified as RISK_ON.
- ROTATION_WINDOW (rule 6) must be checked before RISK_ON (rule 7) for the same reason.
- GLOBAL_UNKNOWN must only mean missing/undetermined data. It must never represent
  a real but unlabelled market state. This was the root cause of the v1.0 classification
  bug (fixed in v1.1).

### Asset class regime classification

Applied to class 24h return relative to BTC 24h return.

```
Order  Label              Condition
-----  -----------------  ---------------------------------------------------
1      CLASS_UNKNOWN      class_return_24h_pct IS NULL
2      CLASS_RISK_OFF     relative_class_vs_btc < -0.05
3      CLASS_STRESS       relative_class_vs_btc < -0.02
4      CLASS_OVERHEATED   class_return_24h_pct > +0.10
5      CLASS_LEADERSHIP   relative_class_vs_btc > +0.04
6      CLASS_PULLBACK     btc_return_24h_pct > 0  AND class_return_24h_pct < 0
7      CLASS_LAGGARD      relative_class_vs_btc < -0.01
8      CLASS_NEUTRAL      (default — no other condition matched)
```

These are the same rules as in `run_regime_selector_backtest_v1.py`. The observation
layer must use an identical implementation to ensure backtested regimes match
live-observed regimes.

---

## H1 tagging specification

When `global_regime = 'GLOBAL_BTC_MILD_DECLINE'`:

```json
["H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT"]
```

**Tag semantics:**
- This tag records that the H1 hypothesis context is active.
- It does not mean "enter a trade".
- It does not mean "the next 4h candle will be positive".
- It does not modify any selection score, policy decision, or advice state.
- It is a research context marker that will be read by the future `policy_router`
  design, which is a separate document and a separate implementation step.

When `global_regime` is anything other than `GLOBAL_BTC_MILD_DECLINE`:

```json
[]
```

An empty array, not NULL. The column is always populated.

---

## Runner design sketch (not yet implemented)

The observation runner will:

1. Determine the current `asof_ts_utc` (now, or a specified snapshot time).
2. Query `obs_market_candle` for the BTC 4h candle at `[asof_ts_utc − 24h, asof_ts_utc]`.
3. Compute `btc_return_24h_pct` from the most recent two BTC candles.
4. Classify `global_regime` using the ordered rules above.
5. For each asset class in the asset universe:
   a. Query class candle returns for the same window.
   b. Compute `class_return_24h_pct` and `relative_class_vs_btc_24h_pct`.
   c. Classify `asset_class_regime`.
   d. Compose `global_class_regime`.
   e. Populate `validated_hypothesis_tags_json`.
6. Upsert one row per asset class into `active_regime_observation_v1`.
7. Print safety markers.

The runner must not:
- Call any broker or exchange API.
- Read `selection_state`, `decision_gate`, or any execution table.
- Modify `selection_state` or any score column.
- Write to any table other than `active_regime_observation_v1`.
- Produce routing decisions.

---

## What this observation layer enables

Once built and smoke-tested:

- The `policy_router` design can reference `active_regime_observation_v1` as its
  regime input, rather than recomputing regime from candles at runtime.
- Research scripts can join `active_regime_observation_v1` against
  `selection_state` to study how strategy states co-occur with regime states.
- Future hypotheses (H3, H4 if re-validated) can be tagged via
  `validated_hypothesis_tags_json` without schema changes.

---

## Downstream path

```
1. regime_selector_backtest_v1.1 findings             DONE
2. regime_selector_candidate_hypotheses_v1             DONE
3. regime_selector_multi_window_validation_v1          DONE — H1 PROMISING_REPEATED
4. regime_selector_historical_coverage_audit_v1        DONE
5. active_regime_observation design v1                 THIS DOCUMENT
   — design only; no migration, no runner, no routing

6. active_regime_observation migration + runner preview
   — schema review → migration → read-only smoke test
   — no broker calls; no order logic

7. active_regime_observation smoke + safety verification
   — verify regime labels match backtest output
   — verify H1 tag appears only on GLOBAL_BTC_MILD_DECLINE rows
   — verify validation_status = 'RESEARCH_ONLY'
   — verify zero broker calls

8. policy_router design
   — only after step 7 is complete and stable
   — maps (active_regime, strategy_state) → routing signal
   — pure read layer; no order placement

9. policy_router preview
   — read-only dry run; no writes to execution tables

10. selection/advice integration
    — only after policy_router is validated end-to-end
    — reviewed against decision_gate boundary before integration

11. decision_gate / execution
    — NOT STARTED; separate design; separate authorization
```

---

## Non-goals

This document does not define and this implementation must not include:

- Buy or sell signals of any kind.
- Routing decisions or policy permissions.
- Modifications to `selection_state`, `selection_score`, or `selection_bias`.
- Changes to `decision_gate`, `execution_planner`, or `executor`.
- Paper or live mode branching.
- Account filtering, sleeve logic, or balance checks.
- Any broker or exchange API call.
- Any execution intent or execution plan.

---

## Safety

```
[SAFETY] broker_calls=0  broker_writes=0  order_submission=0  live_orders=0
[SCOPE]  research-only  market-only  account-agnostic  design-document-only
```
