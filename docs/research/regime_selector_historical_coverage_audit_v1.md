# Regime Selector Historical Coverage Audit V1

**Generated from:** `run_regime_selector_historical_coverage_audit_v1.py`
**Date:** 2026-05-14
**Venue:** bitvavo | **Interval:** 4h
**Boundary:** research-only · market-only · account-agnostic · read-only

---

## Purpose

Determine whether existing source tables contain sufficient historical data to
rerun `run_regime_selector_backtest_v1` (report_version=1.1) over a wider
time window, enabling multi-window hypothesis validation of the five candidates
in `docs/research/regime_selector_candidate_hypotheses_v1.md`.

The current v1.1 backtest covers only 2026-05-10 to 2026-05-14 (120 snapshots,
one bearish mini-window). Multi-window validation requires at least two
independent macro windows.

---

## Boundary

- Research-only
- Market-only
- Account-agnostic
- No account state, no balances, no positions
- No broker calls
- No order logic
- No paper/live distinction

---

## 1. Source table coverage summary

| Table | min_ts | max_ts | span_days | snapshots / dates | Blocker? |
|---|---|---|---|---|---|
| `selection_state` | 2026-03-20 | 2026-05-14 | 55 | 356 snaps / 33 dates | Partial¹ |
| `obs_market_candle` (bitvavo 4h) | 2021-01-01 | 2026-05-14 | 1,959 | 1,960 dates / 42 assets | **No** |
| `trade_setup_filter_observation` | 2026-04-26 | 2026-05-14 | 18 | 295 snaps / 14 dates | No² |
| `trade_setup_policy_preview_observation` | 2026-05-10 | 2026-05-14 | 4 | 123 snaps / 5 dates | No² |
| `paper_advice_observation` | 2026-05-13 | 2026-05-14 | 0 | 9 snaps / 2 dates | No² |

¹ Technically 1 day short of the 60-day nominal target. In practice: 356 snapshots available vs
120 currently loaded — **SUFFICIENT to run a wider backtest immediately** (see section 7).

² These tables are **optional enrichment** in the backtest runner. Their absence or sparsity does
not block running the backtest; affected observations will fall back to `SETUP=UNKNOWN`,
`POLICY=UNKNOWN`, `ADVICE=UNKNOWN` in the strategy signature. See section 4 for scope impact.

---

## 2. selection_state detail

**Coverage span:** 2026-03-20 to 2026-05-14 — 55 calendar days (with gaps)

**Snapshot density by calendar week:**

| week_start | week_end | snaps | assets |
|---|---|---|---|
| 2026-03-20 | 2026-03-22 | 3 | 39 |
| 2026-03-23 | 2026-03-29 | 7 | 39 |
| 2026-03-30 | 2026-04-01 | 17 | 39 |
| 2026-04-08 | 2026-04-09 | 6 | 39 |
| 2026-04-18 | 2026-04-19 | 14 | 40 |
| 2026-04-20 | 2026-04-26 | 12 | 40 |
| **2026-04-27** | **2026-05-01** | **139** | **41** |
| 2026-05-07 | 2026-05-10 | 39 | 42 |
| **2026-05-11** | **2026-05-14** | **119** | **42** |

**Coverage gaps:**

| from | to | gap_days |
|---|---|---|
| 2026-04-01 | 2026-04-08 | 6 |
| 2026-04-09 | 2026-04-18 | 8 |
| 2026-04-20 | 2026-04-23 | 2 |
| 2026-04-23 | 2026-04-26 | 2 |
| 2026-05-01 | 2026-05-07 | 5 |

**Density characterisation:**

- **Dense** (≥3 snaps/day): 20 of 33 dates — April 27 to May 1 and May 10 to May 14
  account for the bulk (258 snapshots)
- **Sparse** (1–2 snaps/day): 13 dates — March 20 to April 26 outside the dense clusters
  have only 1 snapshot per active day; each such day contributes ~40 observations
  per (selector_mode, horizon) combination after fan-out

**Total: 356 distinct snapshots** vs 120 currently loaded into the backtest table.
The additional 236 snapshots span 9 calendar weeks (with gaps) at a lower BTC price
range ($57–67K) than the May 10–14 window ($68–70K).

---

## 3. obs_market_candle — not a blocker

`obs_market_candle` (bitvavo, 4h) spans **2021-01-01 to 2026-05-14 — 5+ years**.
All 42 currently tracked assets have continuous 4h candle history.

The backtest performs binary-search candle lookups for current price, forward price
(4h/24h/72h), MFE, and MAE. This table is not a blocker for any window size within the
available `selection_state` range.

**72h forward coverage note:** The current max candle is 2026-05-14 12:00 UTC.
72h forward returns for snapshots taken after 2026-05-11 12:00 UTC require candles
that do not yet exist (2026-05-14 to 2026-05-17). This is expected and consistent with
the current v1.1 backtest behaviour — such observations will have `future_price=NULL`
and be excluded from 72h return statistics.

---

## 4. Optional strategy enrichment tables

The backtest runner resolves strategy signature fields from three optional tables.
If a table does not exist or has no row for a given snapshot, the corresponding
signature component falls back to `UNKNOWN`.

| Table | Available from | Impact on strategy signatures |
|---|---|---|
| `trade_setup_filter_observation` | 2026-04-26 | `SETUP=<real>` only from 2026-04-26+ |
| `trade_setup_policy_preview_observation` | 2026-05-10 | `POLICY=<real>` only from 2026-05-10+ |
| `paper_advice_observation` | 2026-05-13 | `ADVICE=<real>` only from 2026-05-13+ |

For all observations before 2026-04-26, the strategy signature will be:
```
SEL=<real>|SETUP=UNKNOWN|POLICY=UNKNOWN|ADVICE=UNKNOWN|APLUS=UNKNOWN
```

**Implications for hypothesis validation:**

- **H1–H4** (global/class regime hypotheses): Not affected by strategy signature
  enrichment. These hypotheses condition only on `global_regime` and
  `asset_class_regime`, which are computed from BTC/class candle returns regardless
  of strategy layer coverage.

- **H5** (`POLICY=INSUFFICIENT_SAMPLE` bucket): Only valid from 2026-04-26+ where
  `trade_setup_filter_observation` exists. Pre-April-26 observations will appear in the
  `SETUP=UNKNOWN` bucket, not in `POLICY=INSUFFICIENT_SAMPLE`. H5 validation is scoped
  to the April 26 — May 14 window (295 additional setup-filter snapshots).

---

## 5. BTC global regime character — coverage window

The available candle data classifies the following daily BTC regimes across the
selection_state window (2026-03-20 to 2026-05-14):

| Global regime | Calendar days observed |
|---|---|
| `GLOBAL_NEUTRAL` | 29 |
| `GLOBAL_RISK_ON` | 24 |
| `GLOBAL_BTC_MILD_DECLINE` | 22 |
| `GLOBAL_BTC_BREAKDOWN` | **0** |
| `GLOBAL_BTC_OVERHEATED` | 0 |
| `GLOBAL_ROTATION_WINDOW` | 0 |

**Key observations:**

1. All three main regimes (`NEUTRAL`, `RISK_ON`, `GBMD`) are present in meaningful
   quantities. This enables multi-window testing of H1–H4 across all three regime types.

2. **No `GLOBAL_BTC_BREAKDOWN` days** exist in the entire selection_state window.
   BTC remained in the $57–70K range throughout March–May 2026 with no 24h move
   exceeding −5%. H1's extreme-crash edge case (very negative BTC day preceding
   bounce) cannot be validated from this dataset alone.

3. **No `GLOBAL_BTC_OVERHEATED` days** (BTC 24h > +8%). The strongest risk-on moves
   reached +6% (March 5). H4 testing is limited to mild-to-moderate risk-on conditions.

4. The March 2026 data (BTC $57–65K) provides the most distinct macro contrast to
   the May 10–14 window (BTC $68–70K). Weekly grouping will isolate these periods.

---

## 6. Current regime_selector_backtest_observation_v1 state

| report_version | date range | snapshots | total_rows |
|---|---|---|---|
| 1.0 | 2026-05-10 to 2026-05-14 | 120 | 59,676 |
| 1.1 | 2026-05-10 to 2026-05-14 | 120 | 59,640 |

Both versions cover only the known May 10–14 bearish mini-window.
The wider backtest will add new rows via `ON DUPLICATE KEY UPDATE` for the
same report_version=1.1. Existing May 10–14 rows will be overwritten in-place
(same key); older-window rows will be inserted as new.

---

## 7. Verdict and recommended replay plan

### Verdict: SOURCE DATA SUFFICIENT — NO HISTORICAL BACKFILL REQUIRED

No new data needs to be written to any source table. The existing
`selection_state` and `obs_market_candle` tables are sufficient to run
`run_regime_selector_backtest_v1` over **all 356 available snapshots**, covering
9 calendar weeks from 2026-03-20 to 2026-05-14.

The 236 additional snapshots (beyond the 120 already processed) span multiple
BTC regimes at a different price level, providing the independent window contrast
that the multi-window validator needs.

### Recommended backtest command

```bash
python -m src.research.run_regime_selector_backtest_v1 \
  --venue bitvavo \
  --interval 4h \
  --from-ts 2026-03-20T00:00:00 \
  --limit-snapshots 356 \
  --horizons 4 24 72 \
  --min-group-n 8 \
  --write-db \
  --output table
```

**Parameter rationale:**
- `--from-ts 2026-03-20T00:00:00` — earliest available selection_state snapshot
- `--limit-snapshots 356` — all available snapshots
- `--min-group-n 8` — reduced from default 40 to retain sparse single-snapshot days
  in the aggregate tables; weekly aggregation in the validation script will enforce
  higher effective n
- `--write-db` — updates v1.1 rows in-place; adds new rows for pre-May-10 snapshots
- No `--to-ts` — default (now) picks up everything up to current date

### Then rerun multi-window validation

```bash
python -m src.research.run_regime_selector_multi_window_validation_v1 \
  --report-version 1.1 \
  --window-mode week \
  --min-n-ret 40 \
  --output table
```

`--window-mode week` groups by ISO calendar week. With 9 weeks available, the
validator will split per-week and classify each hypothesis across multiple
independent weekly windows.

---

## 8. Coverage limitations after replay

These limitations apply even after running the wider backtest. They do not block
the replay but must be documented in the validation report.

| Limitation | Affected hypotheses | Scope |
|---|---|---|
| No `GLOBAL_BTC_BREAKDOWN` days | H1 (extreme crash edge) | Cannot validate |
| No `GLOBAL_BTC_OVERHEATED` days | H4 (overbought context) | Cannot validate |
| Sparse pre-April-27 data (1 snap/day) | H1–H4 early weeks | Use weekly aggregation; single days may not meet min-n |
| Strategy enrichment only from 2026-04-26 | H5 | Validation scoped to April 26+ only |
| All data in the same macro cycle (no bear cycle) | H4 (risk-on in bear market) | BTC ranged $57–70K; no sustained bear available |
| 72h forward returns absent for most-recent snapshots | All | Expected — incomplete future candles |

---

## 9. What historical replay/backfill would provide

The following data, if it existed, would extend validation beyond the current limitations:

| Missing data | Would unblock |
|---|---|
| `selection_state` snapshots from mid-2025 through early 2026 (BTC $20–50K range) | H4 in a true bear market; GLOBAL_BTC_BREAKDOWN regime for H1 |
| `selection_state` during BTC +20% rally in 14 days | GLOBAL_BTC_OVERHEATED and GLOBAL_ROTATION_WINDOW regimes |
| `trade_setup_filter_observation` history before April 2026 | Full H5 signature enrichment across all windows |

These require replaying the strategy pipeline over historical market data — not just
widening the existing backtest query. This is a larger engineering task and is not
required to proceed with the immediate wider backtest over existing data.

---

## 10. Downstream gate

```
regime_selector_backtest_v1.1 findings           DONE
regime_selector_candidate_hypotheses_v1          DONE
regime_selector_multi_window_validation_v1       BLOCKED (single window)
regime_selector_historical_coverage_audit_v1     THIS DOCUMENT
    verdict: run wider backtest immediately using existing data

NEXT STEP:
  Run wider backtest (356 snapshots, 9 weeks, --from-ts 2026-03-20)
  → Re-run multi-window validation with --window-mode week
  → If ≥1 hypothesis achieves PROMISING_REPEATED: proceed to active_regime_observation design
  → If coverage still insufficient: document and wait for pipeline replay
```

---

## Safety

```
[SAFETY] broker_calls=0  broker_writes=0  order_submission=0  live_orders=0
[SCOPE]  research-only  market-only  account-agnostic  read-only-query
```
