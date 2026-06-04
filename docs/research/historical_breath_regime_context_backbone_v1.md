# Historical Breath Regime Context Backbone V1

## Purpose

Define whether Synth v2 already has a canonical historical Breath/Regime context source that can be joined onto later lifecycle and replay events, and if not, define the canonical builder path before implementing `symbol_reaction_profile_by_context_v1`.

This document is research-only. It does not authorize strategy promotion, selection changes, decision changes, execution changes, broker calls, or DB writes.

## Decision

`PARTIAL_CONTEXT_EXISTS`

Synth already has multiple historical context ingredients, but they are split across:

- market-breath research files
- regime-selector research tables
- current-only active regime snapshot rows
- A+ historical archives/views
- breath-curve and regime-gated research artifacts
- current/display-oriented reporting bridges

There is no single canonical historical row source today with:

`symbol + venue + interval + asof_ts_utc + breath_phase + breath_alignment + market_regime + btc_context + symbol_regime + fibo_context + aplus_context_state`

## Current Findings

### Source inventory

| source | type | historical | symbol_scoped | timestamp_field | interval_field | breath_fields | regime_fields | joinable_to_events | status | notes |
|---|---|---|---|---|---|---|---|---|---|---|
| `signal_engine_state` | `DB_TABLE` | `YES` | `YES` | `signal_ts_utc` | implicit signal timeframe | `phase_signal`, `phase_score` | none | `PARTIAL` | `USEFUL_INPUT` | Very deep history: ~1.6M rows, 2021-01-01 through 2026-06-03. Good historical spine candidate, but labels are signal-engine specific, not canonical breath/regime buckets. |
| `selection_state` | `DB_TABLE` | `YES` | `YES` | `asof_ts_utc` | mixed via `advice_ts_1h_utc` / `advice_ts_4h_utc` | none | `regime_label_1h`, `regime_label_4h` | `PARTIAL` | `USEFUL_INPUT` | Historical market snapshots exist across 53 days. Regime labels are present, but row purpose is selection snapshotting, not canonical context storage. |
| `trade_setup_filter_observation` | `DB_TABLE` | `YES` | `YES` | `context_ts_utc`, `asof_ts_utc` | implicit | none | none | `PARTIAL` | `USEFUL_INPUT` | Historical, event-adjacent context timestamps exist. Good join helper, but not a canonical breath/regime table. |
| `execution_zone_context` | `DB_TABLE` | `PARTIAL` | `YES` | `asof_ts_utc` | `source_timeframes` | none | none | `PARTIAL` | `USEFUL_INPUT` | Only one distinct recent day in DB audit. Useful for fib/zone context, but history is too thin to serve as the main backbone. |
| `active_regime_observation` | `DB_TABLE` | `NO` | `NO` | `asof_ts_utc`, `source_candle_ts_utc` | implicit 4h in runner | none | `global_regime`, `asset_class_regime`, `global_class_regime` | `NO` for deep backtests | `CURRENT_SNAPSHOT` | Only 8 rows on one day. Asset-class scoped, not symbol-scoped. Useful for current runtime preview, not historical replay joins. |
| `regime_selector_backtest_observation_v1` | `DB_TABLE` | `YES` | `YES` | `asof_ts_utc` | `interval_code`, `horizon_hours` | none | `global_regime`, `asset_class_regime`, `global_class_regime` | `PARTIAL` | `RESEARCH_ONLY` | Strongest existing historical regime source: ~222k rows across 32 distinct days. But it is a backtest observation table, not a canonical context row store, and its primary purpose is measuring outcomes rather than publishing reusable context rows. |
| `market_breath_analysis_v1` output | `RESEARCH_FILE` | `NO` | `YES` | `asof_ts_utc` | `interval_code` | `market_breath_phase`, `market_breath_state`, `market_breath_confidence`, `momentum_score`, `relative_strength_score` | none | `NO` | `RESEARCH_ONLY` | `data/research/market_breath_analysis_v1/market_breath_observations_v1.jsonl` has only latest-style observations, 41 rows. Good schema reference, not historical backbone. |
| `market_breath_v1_1_calibration_audit` output | `RESEARCH_FILE` | `YES` | `PARTIAL` | `asof_ts_utc` | `interval_code` | phase percentages, top phase symbols, avg momentum/relative strength | none | `PARTIAL` | `RESEARCH_ONLY` | `phase_distribution_by_asof_v1.jsonl` has 60 historical as-of rows, but mostly market-wide aggregates plus top-symbol lists, not full per-symbol rows. |
| `market_breath_outcome_validation_v1` output | `RESEARCH_FILE` | `YES` | `YES` | `asof_ts_utc` | `interval_code` | `market_breath_phase`, `market_breath_state`, `market_breath_confidence`, `momentum_score`, `relative_strength_score` | none | `YES` | `USEFUL_INPUT` | Best existing historical per-symbol breath-like file: 2,460 rows. Replay-safe enough for research joins, but stored as outcome-validation artifacts rather than a canonical reusable context table. |
| `market_breath_regime_stability_validation_v1` output | `RESEARCH_FILE` | `YES` | `NO` | `window_start_ts`, `window_end_ts` | `interval_code` | phase outcome summaries | regime dependency summaries | `NO` | `RESEARCH_ONLY` | Window-level analysis only. Useful for validating phase stability, not event joins. |
| `market_breath_context_bridge_v1` | `REPORTING_BRIDGE` | `NO` | `YES` | latest resolved `asof_ts_utc` | `interval_code` | derives `market_breath_context_state` from live/current observations | none | `NO` | `DISPLAY_ONLY` | Reads current market breath observations plus latest A+ rows and maps display context. It does not read a canonical stored historical backbone and does not persist one. |
| `vw_aplus_research_dataset` / `vw_aplus_research_with_returns` | `DB_VIEW` | `YES` | `YES` | `asof_ts_utc`, `aplus_prediction_ts_utc` | none | A+ class/final-class | none | `PARTIAL` | `USEFUL_INPUT` | Historical enough for symbol-scoped A+ context, but only 8 distinct days. Joinable as optional A+ state, not enough to anchor the whole context model. |
| `aplus_table1_row` + `aplus_table1_report` | `DB_TABLE` | `YES` | `YES` via token | `prediction_ts_utc` on report | none | `phase` | none | `PARTIAL` | `USEFUL_INPUT` | Historical A+ snapshots exist, but normalization is split across report and row tables and still needs canonical context-state mapping. |
| `breathline_token_snapshot` / `breathline_token_consistency` | `DB_TABLE` | `YES` | `YES` | `prediction_ts_utc` | none | breathline momentum/class corrections | none | `PARTIAL` | `LEGACY` | Historical symbol-scoped rows exist across 8 days, but they belong to legacy breathline/A+ lanes rather than current market-breath canonicalization. |
| `breath_curve_symbol_regime_validation_v1/*_enriched_rows.csv` | `RESEARCH_FILE` | `YES` | `YES` | `as_of_ts_utc`, `anchor_ts_utc` | `interval_code` | `phase_drift_bucket` | `btc_eth_context_bucket` | `PARTIAL` | `RESEARCH_ONLY` | Historical symbol-scoped research rows exist, but labels are lane-specific and centered on breath-curve policy validation, not canonical market context. |
| `breath_curve_regime_gated_policy_preview_v1/*_policy_rows.csv` | `RESEARCH_FILE` | `YES` | `YES` | `as_of_ts_utc`, `anchor_ts_utc` | `interval_code` | `phase_drift_bucket` | `btc_eth_context_bucket`, `regime_class` | `PARTIAL` | `RESEARCH_ONLY` | Rich research inputs for later bucket design, but still policy-preview artifacts rather than a general context row source. |
| `aplus_table1_regime_gate_validation_v1/*_enriched_rows.csv` | `RESEARCH_FILE` | `YES` | `YES` | `as_of_ts_utc`, `anchor_ts_utc` | `interval_code` | `aplus_phase`, `phase_drift_bucket` | `btc_eth_context_bucket`, `regime_class` | `PARTIAL` | `RESEARCH_ONLY` | Strong A+ plus regime enrichment rows exist historically, but only inside a regime-gated validation lane. |
| `research_breath_curve_policy_result` | `DB_TABLE` | `PARTIAL` | `YES` | `anchor_date` | none | none | none | `NO` | `RESEARCH_ONLY` | Symbol + anchor-date policy result table exists, but it is not a generic context backbone. |
| `sector_regime` | `DB_TABLE` | `UNKNOWN` | `NO` | `ts_utc` | `timeframe` | none | `regime_label` | `NO` | `UNKNOWN` | Empty in current DB audit. |

### Key answers

#### 1. Do we already have historical breath/regime rows per timestamp?

Partially.

- Historical per-symbol breath-like rows exist in `data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl`.
- Historical regime rows exist in `regime_selector_backtest_observation_v1`.
- Historical selection/regime labels exist in `selection_state`.
- Historical A+ snapshots exist in A+ tables/views and breathline archives.

But there is no single canonical historical context row store that unifies these into one replay-safe join target.

#### 2. Are they per-market, per-symbol, or only current/live snapshots?

Mixed.

- `active_regime_observation` is current-ish and asset-class scoped, not symbol-scoped.
- `market_breath_context_bridge_v1` is current/display-oriented.
- `market_breath_outcome_validation_v1` is per-symbol and historical.
- `regime_selector_backtest_observation_v1` is per-symbol and historical.
- `market_breath_v1_1_calibration_audit` is historical but largely market-wide aggregate.
- breath-curve and A+ regime-gated files are symbol-scoped but lane-specific.

#### 3. Are A+ / Martee / Breath / Fibo labels normalized enough to join onto lifecycle/backtest events?

Only partially.

- A+ is the most normalized external lane today: `aplus_*` tables, `vw_aplus_research_dataset`, and `vw_aplus_research_with_returns` are joinable by symbol and prediction timestamp.
- Market Breath V1 files expose stable labels like `market_breath_phase` and numeric scores.
- Regime selector files expose stable labels like `global_regime`, `asset_class_regime`, and `global_class_regime`.
- Breath-curve artifacts expose reusable buckets like `btc_eth_context_bucket` and `phase_drift_bucket`, but those are lane-specific and not yet canonical cross-research enums.
- `martee_context_state` does not appear as a normalized first-class stored field in the audited sources.
- Fibo context is still fragmented across `execution_zone_context`, `fibo_target_map_v1` files, and dashboard merges; no canonical historical `fibo_context` label exists yet.

#### 4. Is there a canonical table or only research output files?

No single canonical table exists.

Closest candidates today:

- `regime_selector_backtest_observation_v1` for historical regime labels
- `data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl` for historical per-symbol breath labels
- A+ research views for optional A+ state

But these are still separate research products, not a single backbone.

#### 5. What exact runner should build the context if missing?

Proposed canonical builder:

`historical_breath_regime_context_builder_v1`

Future runner path:

- `src/research/run_historical_breath_regime_context_builder_v1.py`
- `docs/research/historical_breath_regime_context_builder_v1.md`
- `tests/test_historical_breath_regime_context_builder_v1.py`

## Bridge and runner interpretation

### `market_breath_context_bridge_v1`

This module is display/readout oriented.

- It imports `build_base_observation()` and `add_breadth_and_scores()` from `run_market_breath_analysis_v1`.
- It computes current market-breath rows from candles on demand.
- It joins only the latest valid A+ legacy snapshot from `aplus_table1_report` + `aplus_table1_row`.
- It prints table/json output and declares `db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0`.

Conclusion:

- It does **not** read a canonical stored historical context backbone.
- It does **not** persist a historical context backbone.
- It should be treated as `DISPLAY_ONLY`.

### `run_regime_selector_*`

The regime-selector family splits cleanly into:

- `run_regime_selector_backtest_v1.py`
  Writes historical research observations to `regime_selector_backtest_observation_v1`.
- `run_regime_selector_historical_coverage_audit_v1.py`
  Read-only audit of source coverage.
- `run_regime_selector_multi_window_validation_v1.py`
  Read-only validation over existing backtest observations.
- `run_regime_selector_candidate_hypotheses_v1.py`
  Read-only evidence printer.
- `run_regime_selector_v1_1_findings_report.py`
  Read-only findings report.

Conclusion:

- Only `run_regime_selector_backtest_v1.py` persists historical rows.
- Those rows are reusable as historical regime inputs, but they are backtest observations, not a generalized context backbone.

## Proposed canonical context row

Future canonical row contract:

```text
symbol
venue
interval
asof_ts_utc
source_event_ts_utc
breath_phase
breath_alignment
market_regime
btc_context
symbol_regime
fibo_context
aplus_context_state
martee_context_state
relative_strength_bucket
momentum_bucket
quality_state
confidence_bucket
source_refs
research_only=true
```

Suggested enum targets:

### `breath_phase`

- `EXPANSION`
- `CONTRACTION`
- `RELOAD`
- `IGNITION`
- `POST_SPIKE`
- `UNKNOWN`

### `breath_alignment`

- `ALIGNED`
- `EARLY`
- `LATE`
- `INCOHERENT`
- `UNKNOWN`

### `market_regime`

- `RISK_ON`
- `RISK_OFF`
- `ALT_STRENGTH`
- `BTC_DAMAGE`
- `MIXED`
- `UNKNOWN`

### `btc_context`

- `BTC_OK`
- `BTC_DAMAGE_CAUTION`
- `BTC_DAMAGE_HARD`
- `UNKNOWN`

### `symbol_regime`

- `REL_STRENGTH`
- `LAGGARD`
- `HIGH_BETA`
- `LOW_BETA`
- `UNKNOWN`

### `fibo_context`

- `NEAR_SUPPORT`
- `MID_RANGE`
- `NEAR_TARGET`
- `EXTENSION`
- `UNKNOWN`

## Proposed builder

### Name

`historical_breath_regime_context_builder_v1`

### Initial source priority

1. Base timestamp spine:
   `signal_engine_state` or `selection_state`, depending on target interval and replay lane
2. Historical breath bucket:
   derive from market-breath formulas or reuse `market_breath_outcome_validation_v1` rows when aligned to the same interval
3. Historical regime bucket:
   derive or reuse from `regime_selector_backtest_observation_v1`
4. BTC context:
   map from BTC return / regime labels at the same or earlier `asof_ts_utc`
5. Symbol regime:
   derive from relative strength / class leadership / laggard buckets
6. Fibo context:
   derive from `fibo_target_map_v1` rows and/or replay-safe zone context
7. A+ context:
   join from `vw_aplus_research_dataset` or canonicalized A+ snapshots
8. Martee context:
   leave `UNKNOWN` until a normalized source exists

### Initial output mode

Files only first:

`data/research/historical_breath_regime_context_builder_v1/`

No DB writes in the first batch.

## Join contract for later backtests

Default join contract:

- join by `symbol`
- join by exact `interval` when available, otherwise explicitly documented compatible interval
- choose nearest `asof_ts_utc <= event_ts_utc`
- enforce a max staleness threshold per interval
- if no row matches within threshold, emit `UNKNOWN` buckets
- default mode must **not** drop the event solely because context is missing
- strict mode may optionally drop missing-context events

Suggested initial staleness thresholds:

- `15m` events -> max context staleness `<= 8h`
- `1h` events -> max context staleness `<= 24h`
- `4h` events -> max context staleness `<= 48h`
- `1d` events -> max context staleness `<= 7d`

## Safety boundary

```text
research_only=true
broker_calls=0
broker_writes=0
order_submission=0
executor=none
decision_gate=none
execution_planner=none
selection_engine_promotion=0
```

This backbone is a research labeling layer only. It must not become trade permission, strategy promotion, or execution intent.

## Recommended next batch

Implement:

`historical_breath_regime_context_builder_v1`

Scope for that batch:

- research-only
- market-only
- account-agnostic
- file outputs only
- no DB writes initially
- no selection/decision/execution integration

Output target:

`data/research/historical_breath_regime_context_builder_v1/`

That builder should become the canonical dependency before `symbol_reaction_profile_by_context_v1`.

## Source references

- `src/reporting/market_breath_context_bridge_v1.py`
- `src/research/run_market_breath_analysis_v1.py`
- `src/research/run_market_breath_outcome_validation_v1.py`
- `src/research/run_market_breath_v1_1_calibration_audit.py`
- `src/research/run_market_breath_regime_stability_validation_v1.py`
- `src/research/run_regime_selector_backtest_v1.py`
- `src/research/run_regime_selector_historical_coverage_audit_v1.py`
- `src/research/run_regime_selector_multi_window_validation_v1.py`
- `src/regime/run_active_regime_observation_v1.py`
- `src/research/run_breath_curve_symbol_regime_validation_v1.py`
- `src/research/run_breath_curve_regime_gated_policy_preview_v1.py`
- `src/research/run_aplus_table1_regime_gate_validation_v1.py`
- `data/research/market_breath_analysis_v1/market_breath_observations_v1.jsonl`
- `data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl`
- `data/research/market_breath_v1_1_calibration_audit/phase_distribution_by_asof_v1.jsonl`
- `data/research/breath_curve_symbol_regime_validation_v1/`
- `data/research/breath_curve_regime_gated_policy_preview_v1/`
- `data/research/aplus_table1_regime_gate_validation_v1/`
