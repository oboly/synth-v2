# Market Breath Analysis V1

## Purpose
Market Breath Analysis V1 starts a Synth-native breath workflow derived only from market data already in Synth. It measures whether each enabled and tradeable asset is compressing, expanding, extending, resetting, or transitioning based on recent OHLCV behavior.

This lane is research-only. It is not trading advice, buy/sell advice, account permission, execution planning, or order handling.

## Decoupling From A+ Symbolic Reports
A+ Breathline reports remain external symbolic research labels. They are not used as inputs here.

Market Breath V1 deliberately replaces new A+ report expansion with a market-derived workflow:
- no A+ raw files
- no A+ normalized labels
- no external PRO files
- no symbolic labels
- no paired Table1/Table2 inputs

The only inputs are Synth market data tables.

## Boundary
- Research-only.
- Market-only.
- Account-agnostic.
- No DB writes.
- No broker/API calls.
- No trading advice or buy/sell advice.
- No `selection_engine`, `advice_engine`, `decision_gate`, `execution_planner`, or `executor` changes.
- No order logic.
- No paper/live branching.
- Does not touch `run_chain_4h.sh`, policy router files, or `paper_advice_policy_v1`.

## Input Data
Default CLI inputs:
- `venue = bitvavo`
- `interval_code = 4h`
- `lookback_candles = 120`

Database reads:
- `asset`: `asset_id`, `symbol`, `is_enabled`, `is_tradeable`
- `obs_market_candle`: `open_price`, `high_price`, `low_price`, `close_price`, `close_ts_utc`

The runner processes one latest observation per enabled and tradeable asset. If `--asof-ts` is omitted, it uses the latest `obs_market_candle.close_ts_utc` for the selected venue and interval. No future candles are read.

## Formulae And Thresholds
All scores are deterministic V1 proxies. No ML is used.

Returns:
- `return_1`, `return_3`, `return_6`, `return_12` are percent close-to-close returns over 1, 3, 6, and 12 candles.

Range:
- `range_pct = (high_price - low_price) / close_price * 100` for the latest candle.

ATR proxy:
- `atr_pct_proxy` is the average true-range percent over the latest 14 candles.
- True range uses max of high-low, high-previous-close, and low-previous-close.

Compression:
- High when latest `range_pct` and `atr_pct_proxy` are below their own recent medians.
- Formula: `0.55 * low_range_score + 0.45 * low_atr_score`.

Expansion:
- High when latest range, recent absolute return, and ATR proxy exceed their own baselines.
- Formula: `0.45 * high_range_score + 0.35 * high_return_score + 0.20 * high_atr_score`.

Momentum:
- Signed score from `return_3`, `return_6`, and `return_12` with a consistency bonus.
- Positive when returns are consistently positive; negative when consistently negative.

Reversal pressure:
- High when the asset was extended but `return_1` or `return_3` turns negative, especially with an expanding range.

Relative strength:
- Signed score from asset `return_6` and `return_12` minus BTC `return_6` and `return_12`.

BTC alignment:
- Positive when asset and BTC directions align.
- Negative when they diverge.

Breadth alignment:
- Computed after all assets are scored.
- Positive when an asset's `return_6` direction aligns with the market-wide positive/negative ratio.

## Phase Definitions
`HOLD_COMPRESSION`:
Compression is high, expansion is low, and absolute momentum is low.

`INHALE_ACCUMULATION`:
Compression is medium/high, momentum is slightly positive, and relative strength is positive.

`EXHALE_EXPANSION`:
Expansion is high, momentum is positive, and relative strength is positive.

`OVERBREATH_EXTENSION`:
Expansion and momentum are very high while reversal pressure is rising.

`COLLAPSE_RESET`:
Momentum is negative with high reversal pressure.

`NEUTRAL_TRANSITION`:
Fallback when no stronger phase condition is met.

`INSUFFICIENT_DATA`:
Fewer than 24 candles are available for the asset.

## State Definitions
`EARLY`:
Reserved for future finer-grained detection.

`FORMING`:
A phase condition is present but not strongly confirmed.

`CONFIRMED`:
The phase condition is stronger by V1 thresholds.

`LATE`:
Used for extension behavior.

`RESET`:
Used for collapse/reset behavior.

`UNKNOWN`:
Fallback for neutral or insufficient classifications.

## Output Files
Written only when `--write-files` is passed:
- `data/research/market_breath_analysis_v1/market_breath_observations_v1.jsonl`
- `data/research/market_breath_analysis_v1/market_breath_summary_v1.json`

Each observation row contains:
- `venue`, `interval_code`, `asset_id`, `symbol`, `asof_ts_utc`
- `lookback_candles`, `close_price`
- `return_1`, `return_3`, `return_6`, `return_12`
- `atr_pct_proxy`, `range_pct`
- `compression_score`, `expansion_score`, `momentum_score`, `reversal_pressure_score`
- `relative_strength_score`, `btc_alignment_score`, `breadth_alignment_score`
- `market_breath_phase`, `market_breath_state`, `market_breath_score`, `market_breath_confidence`
- `invalid_reason`

## CLI
```bash
python -m src.research.run_market_breath_analysis_v1 \
  --venue bitvavo \
  --interval 4h \
  --lookback-candles 120 \
  --output table
```

Options:
- `--venue` default `bitvavo`
- `--interval` default `4h`
- `--lookback-candles` default `120`
- `--asof-ts` optional UTC timestamp
- `--output-dir` default `data/research/market_breath_analysis_v1`
- `--write-files`
- `--output table/json` default `table`

## Limitations
- V1 is a deterministic proxy, not a validated feature.
- No outcome labels are used in phase building.
- No future candles are used.
- Thresholds are deliberately simple and may need calibration.
- Sparse candle histories can produce `INSUFFICIENT_DATA`.
- No runtime promotion is allowed in V1.
- No feature-candidate promotion is allowed in V1.

## Downstream Path
1. `market_breath_analysis`
2. `market_breath_outcome_validation`
3. `strategy_candidate_horizon_buckets`
4. Optional selection-engine modifier only after repeated validation
5. `decision_gate` unchanged
6. `execution_planner` unchanged
7. `executor` unchanged

Market Breath must never bypass account-aware permission or execution layers.

## Safety Markers
- `broker_calls = 0`
- `broker_writes = 0`
- `order_submission = 0`
- `live_orders = 0`
- `db_writes = 0`
- `selection_engine_changes = 0`
- `advice_engine_changes = 0`
- `decision_gate_changes = 0`
- `execution_planner_changes = 0`
- `executor_changes = 0`
