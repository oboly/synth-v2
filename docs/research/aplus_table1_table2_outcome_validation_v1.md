# A+ Table 1 / Table 2 Outcome Validation V1

## Purpose
Measure whether the normalized A+ Table 1 (Breathline Vector Snapshot) and Table 2 (Harmonic Phase Overlay) symbolic labels correlate with forward market outcomes at fixed horizons. Measurement only — no runtime integration.

## Research-only boundary
- Research-only.
- Market-only.
- Account-agnostic.
- No trading advice.
- No buy/sell signal.
- No account permission.
- No execution intent.
- No order.
- No DB writes.
- No broker/API calls.
- No paper/live branching.
- Does not modify `selection_engine`, `advice_engine`, `decision_gate`, `execution_planner`, `executor`.
- Does not touch `run_chain_4h.sh`, policy_router files, or `paper_advice_policy_v1`.

## Source files
- Joined A+ snapshot (input):
  `data/research/aplus_table1_table2_normalized_v1/table1_table2_joined_20260515_1244.jsonl`
- Snapshot timestamp: `prediction_ts_utc = 2026-05-15T12:44:48Z`
- Snapshot rows: 41 tokens
- Normalization status: `VALID` (from `aplus_table1_table2_normalized_v1`)

## Method
For every `(token, prediction_ts_utc)` row in the joined dataset, the validator:

1. Resolves `token` to `asset_id` via the `asset` table (`asset.symbol = token`).
2. Reads the latest `obs_market_candle` row where `close_ts_utc <= prediction_ts_utc` for that asset at the requested venue+interval. This is the `base_ts_utc` / `base_price` (close).
3. For each requested forward horizon `H` (hours), reads the first `obs_market_candle` row where `close_ts_utc >= base_ts_utc + H hours`. This is the `future_ts_utc` / `future_price` (close).
4. Computes `forward_return_pct = ((future_price / base_price) - 1) * 100`.
5. Computes MFE/MAE over `(base_ts_utc, future_ts_utc]` using the candle `high_price` / `low_price` extremes, both expressed as `% of base_price`.

Row grain: one row per `(token, horizon)`. Expected total: `41 tokens × 3 horizons = 123 rows`.

Validation status per row:
- `VALID` — base + future candles found and `forward_return_pct` computed.
- `NO_ASSET` — token not present in `asset` table.
- `NO_BASE_CANDLE` — no candle at or before `prediction_ts_utc`.
- `NO_BASE_PRICE` — base candle present but price unusable.
- `NO_FUTURE_CANDLE` — no candle at or after `base_ts_utc + H hours` (typically: snapshot too fresh; horizon hasn't elapsed yet).
- `NO_FUTURE_PRICE` — future candle present but price unusable.

## Horizons
Defaults: `4h`, `24h`, `72h`. Override with `--horizons 4 24 72`.

## Label aggregations
Single-field groupings (per horizon):
- `table1_phase`
- `table1_coherence`
- `table1_field`
- `table1_structural_role`
- `table1_strategic_bias`
- `table2_harmonic_phase`
- `table2_offset_band`
- `table2_quality`
- `table2_extension_risk`

Cross groupings (per horizon):
- `table1_coherence × table2_quality`
- `table1_strategic_bias × table2_extension_risk`
- `table1_phase × table2_harmonic_phase`

Per-group metrics:
- `n` — rows in group
- `n_with_return` — rows with non-null `forward_return_pct`
- `avg_return_pct`
- `median_return_pct`
- `win_rate_pct` (= 100 × positive returns / `n_with_return`)
- `avg_mfe_pct`
- `avg_mae_pct`

Best/worst extraction: groups with `n_with_return >= 2` are ranked by `avg_return_pct`. Output includes top-positive and weakest groups per horizon.

## Results (snapshot 2026-05-15T12:44:48Z)
- Input tokens: 41
- Outcome rows produced: 123 (41 tokens × 3 horizons)
- Tokens missing from `asset` table: 0
- Base candles resolved for all 41 tokens (`base_ts_utc = 2026-05-15T12:00:00`, 4h interval)
- Forward coverage (snapshot is fresh):
  - `4h`: 0 valid / 41 total — all `NO_FUTURE_CANDLE` (snapshot ~45min before the next 4h candle close)
  - `24h`: 0 valid / 41 total — all `NO_FUTURE_CANDLE`
  - `72h`: 0 valid / 41 total — all `NO_FUTURE_CANDLE`

No `avg_return_pct` / `win_rate_pct` aggregations are available yet because no forward candles have closed since `prediction_ts_utc`. The run is deterministic and re-runnable: as new `obs_market_candle` rows accumulate, re-running this script will populate forward returns for the 4h horizon first, then 24h and 72h.

Strongest / weakest label groups: not yet computable. They will appear in `best_worst.horizon_<H>h.top_positive_groups` and `weakest_groups` once `n_with_return >= 2` per group.

## Single-snapshot limitation
This validation is built on **one** A+ snapshot. The result is explicitly tagged with:
- `sample_limitation = LOW_SAMPLE_SINGLE_SNAPSHOT`
- `runtime_promotion_allowed = false`

Even once forward candles are available, **no label or group may be promoted to a runtime feature from this single snapshot**. The intent is to identify candidate groups for multi-snapshot validation, not to derive policy.

## Downstream path
1. Raw A+ snapshot
2. Normalized labels (`aplus_table1_table2_normalized_v1`)
3. Outcome validation (this lane — measurement only)
4. Multi-snapshot validation (future research lane; required before any feature consideration)
5. Optional candidate feature design (only after multi-snapshot validation)
6. No direct selection / advice / decision / execution use at any step

Any future use must:
- enter through its own preview table
- be evaluated across multiple snapshots and market regimes
- never bypass `decision_gate`
- never produce order intent
- never imply account permission

## Outputs
Output dir: `data/research/aplus_table1_table2_outcome_validation_v1/`
- `label_outcomes_20260515_1244.jsonl` — one JSON line per `(token, horizon)` outcome row.
- `validation_summary_20260515_1244.json` — coverage, aggregations, best/worst groups, safety markers.

## Safety markers
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
- `paper_live_logic = not_allowed`
- `account_state = not_allowed`
- `research_only = true`
- `market_only = true`
- `account_agnostic = true`

## Script
`src/research/run_aplus_table1_table2_outcome_validation_v1.py`

CLI:
- `--joined-path` (default: snapshot joined JSONL for 2026-05-15 12:44)
- `--venue` (default `bitvavo`)
- `--interval` (default `4h`)
- `--horizons H [H ...]` (default `4 24 72`)
- `--output-dir` (default `data/research/aplus_table1_table2_outcome_validation_v1`)
- `--output {table,json}` (default `table`)
- `--write-files` (writes the two output files when set)
