# Symbol Re-entry Profile Backtest V1

## Purpose

`symbol_reentry_profile_backtest_v1` scans historical candle data to classify
how each symbol typically retraces after an impulse up-move. It answers:
*how deep does price pull back before bouncing, and does it respect fib levels?*

It does not:

- submit orders
- cancel orders
- write to any database
- make broker calls
- create `decision_gate` permission
- create `execution_planner` intent
- enable `executor`
- reference account state, balances, or positions

## Files

| File | Role |
|------|------|
| `src/research/htf_fib_reentry_ladder_v1.py` | Pure fib retrace ladder — no DB, no broker |
| `src/research/run_symbol_reentry_profile_backtest_v1.py` | DB-backed backtest runner |

## Layer boundary

`htf_fib_reentry_ladder_v1.py` (pure module):

- no DB imports
- no broker imports
- accepts `HtfReentryInput` with caller-provided swing anchors
- safe to use in any context without credentials

`run_symbol_reentry_profile_backtest_v1.py` (runner):

- reads `obs_market_candle` from DB (read-only)
- no `BitvavoClient` import
- no broker write calls
- all private account data excluded

## Retrace Level Ladder

Formula: `retrace_price = swing_high - (swing_high - swing_low) * fib_level`

| Label | Fib Level | Role |
|-------|-----------|------|
| `retrace_0_382` | 0.382 | FIRST_TOUCH |
| `retrace_0_500` | 0.500 | MAIN_REBUY |
| `retrace_0_618` | 0.618 | DEEP_REBUY |
| `retrace_0_786` | 0.786 | PANIC_RESET |

## FET fixture verification

Input: `swing_low=0.166, swing_high=0.244, recent_low=0.209`

| Level | Price | Touched |
|-------|-------|---------|
| retrace_0_382 | ≈0.2142 | ✓ (recent_low=0.209 ≤ 0.2142) |
| retrace_0_500 | 0.2050 | ✗ (0.209 > 0.205) |
| retrace_0_618 | ≈0.1958 | ✗ |
| retrace_0_786 | ≈0.1827 | ✗ |

`missed_main_rebuy_by_pct ≈ 1.95%`

## Profile Fields

| Field | Description |
|-------|-------------|
| `sample_size` | Number of impulse swings analysed |
| `preferred_retrace_level` | Level with highest touch count |
| `touch_count_*` | How often each level was touched per swing |
| `avg_bounce_after_*` | Average close-above-deepest-low after touching each level |
| `missed_by_pct_main` | Average % above r500 when r500 was not touched |
| `wickiness_score` | Fraction of swings where r382 touched but r500 not (wick-only) |
| `fib_respect_score` | Fraction of swings where deepest retrace ≤ r500 or NO_TOUCH |
| `volatility_score` | `min(avg_impulse_pct / 100, 1)` |
| `classification` | Symbol behaviour label |

## Classifications

| Label | Condition |
|-------|-----------|
| `INSUFFICIENT_SAMPLE` | `sample_size < min_sample` |
| `DEEP_RETRACE` | `preferred` in (r618, r786) |
| `CLEAN_FIB_RESPECT` | `fib_respect_score ≥ 0.6` AND `preferred` in (r382, r500) |
| `WICK_HEAVY` | `wickiness_score ≥ 0.5` |
| `BREAKOUT_RETEST` | `preferred == r382` |
| `INCOHERENT` | none of the above |

## Deepest Retrace Labels

`deepest_retrace_label` per event:

- `retrace_0_382` / `retrace_0_500` / `retrace_0_618` / `retrace_0_786` — deepest fib level touched
- `FULL_RETRACE` — deepest low ≤ swing low (full round-trip)
- `NO_TOUCH` — price did not reach r382 in the lookforward window

## Outputs

Written to `data/research/symbol_reentry_profile_backtest_v1/` when `--write-files` is passed:

| File | Content |
|------|---------|
| `profile_summary_v1.csv` | One row per symbol — classification and scores |
| `profile_events_v1.jsonl` | One JSON line per impulse+retrace event |
| `manifest_v1.json` | Run metadata and safety markers |

## Usage

Offline profile scan (no DB writes):

```bash
python -m src.research.run_symbol_reentry_profile_backtest_v1 \
  --symbols WLD,FET,ONDO \
  --interval 1d \
  --lookback-candles 500 \
  --output summary
```

Write files to disk:

```bash
python -m src.research.run_symbol_reentry_profile_backtest_v1 \
  --symbols WLD,FET,ONDO \
  --interval 1d \
  --lookback-candles 500 \
  --min-impulse-pct 15 \
  --lookforward-bars 60 \
  --write-files \
  --output summary
```

All symbols (default: all enabled assets in DB):

```bash
python -m src.research.run_symbol_reentry_profile_backtest_v1 \
  --interval 1d \
  --write-files \
  --output summary
```

## Safety markers

```
broker_writes=0
order_submission=0
broker_calls=0
db_writes=0
db_reads=candle_read_only
executor=none
research_only=true
```
