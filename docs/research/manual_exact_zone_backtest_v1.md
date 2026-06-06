# manual_exact_zone_backtest_v1

**Layer:** research/backtest only  
**Status:** active — first test (NEAR/EUR, 15m, 14d)

---

## Purpose

Backtest a manually-specified exact entry/exit zone against historical 15m candles.
Measures whether a predicted price level was hit, how long it took, and compares against
a buy-and-hold baseline over the same window.

---

## Execution semantics

| Rule | Detail |
|---|---|
| Entry trigger | First candle (strictly after prediction_ts) with `low <= buy_level` |
| Entry price | `buy_level` (exact fill assumed) |
| Exit trigger | First candle **strictly after** entry candle with `high >= sell_target` |
| Exit price | `sell_target` if hit; final candle close price otherwise |
| Same-candle rule | Entry and exit may not occur on the same candle |
| Fees / slippage | None |
| Partial fills | None |
| Ladder | None |

---

## First test: NEAR/EUR

| Parameter | Value |
|---|---|
| symbol | NEAR |
| quote | EUR |
| venue | bitvavo |
| interval | 15m |
| horizon | 14 days |
| buy_level | 2.00 EUR |
| sell_target | 2.12 EUR |
| starting_capital | 100 EUR |
| prediction_ts | 2026-05-21T00:00:00Z |
| prediction_timestamp_status | ASSUMED |

**Prediction timestamp note:** No exact saved observation for NEAR with support 2.00,
support zone 1.90–1.95, breakout 2.12–2.15, next watch 2.25–2.35 was found in the
repo or DB. The timestamp `2026-05-21T00:00:00Z` is assumed. If the exact observation
is located later, re-run with `--prediction-ts` set to the canonical timestamp and
remove the ASSUMED marker.

---

## Metrics calculated

| Field | Description |
|---|---|
| `entry_hit` | True if buy_level touched after prediction_ts |
| `entry_ts` | Timestamp of entry candle |
| `entry_price` | buy_level (exact) |
| `target_hit` | True if sell_target touched strictly after entry candle |
| `target_ts` | Timestamp of exit candle |
| `exit_price` | sell_target if hit; final close otherwise |
| `gross_return_pct` | `(exit_price - entry_price) / entry_price * 100` |
| `pnl_eur` | `starting_capital * gross_return_pct / 100` |
| `time_to_target_hours` | Hours from entry_ts to target_ts (null if not hit) |
| `maximum_adverse_excursion_pct` | Worst (lowest low − entry_price) / entry_price * 100 over trade window |
| `maximum_favorable_excursion_pct` | Best (highest high − entry_price) / entry_price * 100 over trade window |
| `final_value_eur` | `starting_capital + pnl_eur` |
| `buy_and_hold_return_from_entry_to_end` | `(final_window_close - entry_price) / entry_price * 100` |
| `improvement_vs_buy_and_hold` | `gross_return_pct - buy_and_hold_return_from_entry_to_end` |

---

## Context annotation

Context fields are **annotation only** — they do not filter or gate the backtest.

| Field | Source |
|---|---|
| `market_regime` | `market_regime_snapshot` near prediction_ts |
| `symbol_regime` | `paper_advice_observation` or `selection_state` near prediction_ts |
| `breath_phase` | `paper_advice_observation` near prediction_ts |
| `breath_alignment` | `paper_advice_observation` near prediction_ts |
| `context_quality_tier` | `paper_advice_observation` or `selection_state` near prediction_ts |

All fields default to `UNKNOWN` if the DB row is absent.

---

## Reference levels (chart only)

`1.90`, `1.95`, `2.15`, `2.25`, `2.35`

These are the support zone and next-watch levels from the original prediction.
They are not used in any trade logic.

---

## Reserve-policy variants

Four variants run automatically over the same candle window and capital.
The reserve policy is resolved from `src/account/long_reserve_policy_v1.py`.

| Variant | reserve% | sell strategy | tp_scope | live-valid? |
|---|---|---|---|---|
| A_FULL_EXIT_BENCHMARK | 0% | 100% at 2.12 | CHILD_SHORT_SWING | No — benchmark only |
| B_MAX_50_FIRST_TARGET | 50% | 50% at 2.12, 50% held to close | CHILD_SHORT_SWING | Yes |
| C_20_15_15_RUNNER | 50% | 20% at 2.12 / 15% at 2.25 / 15% at 2.35 / 50% held | CHILD_SHORT_SWING | Yes |
| D_PARENT_TF_FULL_EXIT_BENCHMARK | 50% | 100% at 2.12 (parent TF exit) | PARENT_TF_FULL | Only if parent TF target confirmed |

Variant D marks `parent_tf_target_status=UNKNOWN` when no parent TF confirmation is available.
It is never marked live-valid under UNKNOWN status.

### NEAR result (2026-05-21, 14-day window)

```
variant                          final_eur  gross%  realized  unrealized  sold%  reserve%  vs B&H%
C_20_15_15_RUNNER                   116.38   16.38      5.70       10.68     50        50    -4.98
B_MAX_50_FIRST_TARGET               113.68   13.68      3.00       10.68     50        50    -7.68
A_FULL_EXIT_BENCHMARK [BM]          106.00    6.00      6.00        0.00    100         0   -15.37
D_PARENT_TF_FULL_EXIT_BENCHMARK     106.00    6.00      6.00        0.00    100        50   -15.37
```

B&H return over window: +21.37% (final close ~2.43 EUR). All variants underperform raw B&H —
the runner strategy captures less upside than holding the full position.
C captures most of the available upside by staging exits at 2.25 and 2.35.

## Continuation-gate variants (v1 extension)

Five continuation-aware variants run over the same candle window.
Context is fetched from the DB at T1 touch timestamp (point-in-time — no future leakage).

### Gate states

| State | Meaning |
|---|---|
| `CONTINUATION_SUPPORTED` | All: positive regime + positive breath + positive alignment + close above target |
| `CONTINUATION_WEAK` | Partial positive context — not all conditions met |
| `REGIME_CONFLICT` | market_regime or symbol_regime in negative set |
| `BREATH_CONFLICT` | breath_phase or breath_alignment in negative set |
| `CONTEXT_UNKNOWN` | All four fields are UNKNOWN — gate cannot fire |
| `NOT_LIVE_VALID` | parent_tf_target_status=UNKNOWN for PARENT_CONTEXT type |

### Variant behavior by type

| Variant ID | Type | Gate effect |
|---|---|---|
| C1_BASELINE_20_15_15_RUNNER | BASELINE | No gate; baseline C sell 20/15/15 |
| C2_BREATH_HOLD_FIRST_TARGET | BREATH_HOLD | Reduce T1 sell by 50% if CONTINUATION_SUPPORTED; else baseline |
| C3_REGIME_TARGET_SHIFT | REGIME_SHIFT | Shift ladder to 2.25/2.35/2.43 if CONTINUATION_SUPPORTED; else baseline |
| C4_BREATH_TRAILING_RUNNER | TRAILING_RUNNER | Stop further tranches if REGIME_CONFLICT or BREATH_CONFLICT; else hold runner |
| C5_PARENT_CONTEXT_RUNNER | PARENT_CONTEXT | live_valid=False when parent_tf_target_status=UNKNOWN |

### NEAR result (2026-05-21, 14d, context=FOUND — signal_engine_state 2026-05-23 16:00)

```
variant                          final_eur  gross%  live   gate_state         gate_applied
C1_BASELINE_20_15_15_RUNNER         116.38   16.38  True   CONTINUATION_WEAK  False (BASELINE_NO_GATE)
C2_BREATH_HOLD_FIRST_TARGET         116.38   16.38  True   CONTINUATION_WEAK  True
C3_REGIME_TARGET_SHIFT              116.38   16.38  True   CONTINUATION_WEAK  True
C4_BREATH_TRAILING_RUNNER           116.38   16.38  True   CONTINUATION_WEAK  True
C5_PARENT_CONTEXT_RUNNER            116.38   16.38  False  NOT_LIVE_VALID     True
```

Context found: `signal_engine_state+selection_state+paper_advice_observation` at 2026-05-23 16:00 (~150 min before T1 touch).
- `breath_phase=EXPANSION` (PHASE_EXPANSION_COHERENT), `breath_alignment=SUPPORTIVE` (COMPASS_EXPANSION_SUPPORT)
- `market_regime=TRENDING_UP` (TREND_UP_STRONG proxy), `symbol_regime=RANGE` (regime_label_4h)
- Gate = CONTINUATION_WEAK: positive breath and regime, but T1 touch candle close_vs_target=-1.72% (closed below 2.12)

C2-C4 fall back to baseline because CONTINUATION_SUPPORTED requires close above target.
C5 is NOT_LIVE_VALID (parent_tf_target_status=UNKNOWN).

**Sample size: n=1. Do not overfit. Gate fires with real context; CONTINUATION_SUPPORTED
would require the T1 touch candle to close above target.**

### Emitted fields per continuation variant

`breath_phase_at_target`, `breath_alignment_at_target`, `market_regime_at_target`,
`symbol_regime_at_target`, `context_quality_tier_at_target`, `continuation_gate_state`,
`continuation_gate_reason`, `sell_reduction_reason`, `target_shift_reason`,
`runner_hold_reason`, `live_valid`, `overshoot_pct_at_t1`, `close_vs_target_pct_at_t1`,
`context_lookup_status`, `context_source`, `context_ts_utc`, `context_age_minutes`,
`max_context_age_minutes`, `context_freshness_status`, `gate_applied`,
`fallback_policy`, `fallback_reason`

## Outputs

```
data/research/manual_exact_zone_backtest_v1/near_exact_first_test/
  summary_v1.json                        # Single-target backtest result and context
  event_rows_v1.jsonl                    # Per-candle event log
  chart_v1.png                           # 15m price chart with entry/exit/reference lines
  variant_summary_v1.json                # 4 reserve-policy variant results (A/B/C/D)
  variant_rows_v1.jsonl                  # One row per reserve-policy variant
  chart_variants_v1.png                  # Price chart with all target levels
  continuation_variant_summary_v1.json   # 5 continuation-gate variant results
  continuation_variant_rows_v1.jsonl     # One row per continuation variant
  continuation_gate_breakdown_v1.csv              # Gate state + reason per continuation variant
  breath_regime_breakdown_v1.csv                  # Context at T1 decision point per variant
  continuation_context_lookup_audit_v1.csv        # Per-variant context lookup audit
  continuation_context_lookup_summary_v1.json     # Aggregate context/gate counts
  continuation_gate_applied_breakdown_v1.csv      # gate_applied=True variants only
```

---

## Safety markers

```
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

---

## Run command

```bash
# Full run (single-target + 4 reserve variants + 5 continuation variants)
python -m src.research.run_manual_exact_zone_backtest_v1

# Skip reserve variants
python -m src.research.run_manual_exact_zone_backtest_v1 --no-variants

# Skip continuation variants
python -m src.research.run_manual_exact_zone_backtest_v1 --no-continuation

# Skip chart
python -m src.research.run_manual_exact_zone_backtest_v1 --no-chart
```

---

## Planned extensions (not in v1)

- Ladder entry (multiple buy levels)
- TP threshold sweep: 1%, 2%, 3%, 5%, 8%
- Results grouped by market_regime and breath_phase across multiple windows
- Walk-forward over multiple prediction windows
- Continuation gate re-evaluation at T2 and T3 decision points (currently only T1)
