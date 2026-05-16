# Asset Layer Eligibility Audit V1

## Purpose

APT and SXT should be able to participate in market-data ingestion and research
without becoming tradeable, advice-eligible, decision-eligible, or
execution-eligible.

This audit maps current `asset` flag usage before changing runtime behavior.

## Current Asset Flags

Current documented flags:

- `is_enabled`
- `is_tradeable`
- `is_portfolio`

The current implementation uses `is_enabled` as a broad system participation
flag, not only as a data-ingestion flag. That makes it unsafe to set APT/SXT to
`is_enabled=1` only to collect candles.

## Code Path Map

| Layer / path | File | Current asset filter | Effect |
|---|---|---|---|
| Bitvavo candle ETL | `src/etl/bitvavo/run_candles_etl.py` | `WHERE is_enabled = 1` | Normal candle ingestion only loads enabled assets. |
| Candle features | `src/features/etl_candle_feat.py` | `WHERE is_enabled = 1` | Feature rows are generated for all enabled assets. |
| Signal backfill | `src/signal_engine/run_signal_backfill.py` | `a.is_enabled = 1` | Signal snapshots are built from enabled assets. |
| Signal state ETL | `src/signal_engine/run_signal_state_etl.py` | `a.is_enabled = 1` | Latest feature snapshots and signal rows are filtered to enabled assets. |
| Signal engine | `src/engine/run_signal_engine.py` | `a.is_enabled = 1` | Signal engine reads latest feature rows for enabled assets. |
| Selection engine | `src/selection/run_selection_engine_v2.py` | `a.is_enabled = 1 AND a.is_tradeable = 1` | Selection candidates require both enabled and tradeable. |
| Advice engine | `src/advice/run_advice_engine.py` | `a.is_enabled = 1` | Advice engine counts and reads signal rows for enabled assets. It consumes signal snapshots that can be produced for enabled assets. |
| Paper advice policy | `src/advice/run_paper_advice_policy_v1.py` | Reads `selection_state`; no direct `is_enabled` filter in the main query | Paper advice follows selection output. If an asset enters selection, it can flow here. |
| Policy router preview | `src/regime/run_policy_router_preview_v1.py` | `is_enabled = 1 AND is_tradeable = 1` | Router preview asset universe is tradeable enabled assets. |
| Trade setup filter backfill | `src/research/run_trade_setup_filter_backfill_v1.py` | Reads `selection_state`; no direct asset eligibility gate in the observed query | It follows selection snapshots, so selection eligibility is upstream. |
| Market breath analysis | `src/research/run_market_breath_analysis_v1.py` | `is_enabled = 1 AND is_tradeable = 1` | Current research scaffold is tradeable-universe only. |
| Sparse candle diagnostics | `src/research/run_sparse_candle_diagnostics_v1.py` | `is_enabled = 1` | Diagnostics default to enabled assets. |
| Fib bull run sell-zone overview | `src/research/run_fib_bull_run_sell_zone_overview_v1.py` | `a.is_enabled = 1` | Research output defaults to enabled assets. |
| Asset profile snapshots | `src/asset_profile/repository.py` | `a.is_enabled = 1` | Derived profile snapshots use enabled assets. |
| Structure state measurement | `src/measurement/run_structure_state_engine.py` | `a.is_enabled = 1` | Structure measurements read enabled feature rows. |
| Fib observation / zone backfills | `src/zone/run_fib_observation_backfill_v1.py`, `src/zone/run_execution_zone_context_backfill_v1.py` | `is_enabled = 1 AND is_tradeable = 1` | Zone-oriented backfills use tradeable enabled assets. |
| Decision / execution | `src/decision`, `src/execution` | No asset flag broadening found in this audit | These layers should remain separate and unchanged. |

## Direct Answers

1. `asset.is_enabled` is used by normal candle ETL, candle feature ETL, signal
   engines, asset profile snapshots, measurement runners, multiple research
   diagnostics, selection, advice snapshot selection, and some zone/reporting
   backfills.

2. `asset.is_tradeable` is used by the selection engine, market breath analysis,
   policy/router preview, and zone-oriented backfills to restrict candidate
   universes to tradeable assets.

3. `asset.is_portfolio` appears mostly as metadata/documentation in the audited
   paths. It is not the main gate for ingestion, selection, advice, or execution
   in the reviewed code.

4. Yes. Normal Bitvavo candle ETL uses `WHERE is_enabled = 1`.

5. Yes for many core paths. Candle feature runners, signal runners,
   `selection_engine`, and `advice_engine` use `is_enabled=1` directly. Trade
   setup and paper advice mostly consume upstream `selection_state`, so their
   effective universe is controlled by selection output rather than an
   independent research-only flag.

6. Not safely with the current flag model. Setting APT/SXT to `is_enabled=1`
   would make them eligible for normal ETL plus downstream feature, signal,
   research, and possibly advice-adjacent flows. `is_tradeable=0` blocks the
   current selection engine, but the broad `is_enabled` usage is still too much
   runtime participation for a data-ingestion-only intent.

## Recommendation

Use Path A before promoting APT/SXT into normal candle ingestion.

### Path A - Preferred

Introduce explicit layer-specific eligibility metadata, then migrate code paths
to use the narrowest relevant flag:

- Candle ETL: `is_data_ingestion_enabled = 1`
- Research/feature diagnostics: `is_research_enabled = 1`
- Selection/advice candidate generation: `is_tradeable = 1` plus a future
  explicit selection eligibility flag if needed
- Portfolio-specific reports: `is_portfolio = 1`
- Decision and execution: unchanged account-aware gates

Under this model APT/SXT could be:

- `is_data_ingestion_enabled = 1`
- `is_research_enabled = 1`
- `is_enabled = 0` until deprecated or redefined
- `is_tradeable = 0`
- `is_portfolio = 0`

That would allow normal candle ingestion and research coverage without making
APT/SXT selection/advice/execution candidates.

Path A should be implemented as a separate migration plus small, explicit code
changes per layer. It should include smoke tests proving APT/SXT candles ingest
while selection/advice outputs exclude them.

### Path B - Temporary Bridge

Until Path A exists, keep `run_research_candidate_candles_etl_v1.py` as a
temporary bridge only. It explicitly selects requested symbols, uses public
market-data endpoints, and writes only `obs_market_candle` when `--write-db` is
passed.

TODO: Replace the bridge with layer-specific asset eligibility flags and normal
ETL participation once Path A is implemented and validated.

## Boundary

No runtime behavior should change from this audit alone.

Do not set APT/SXT to `is_tradeable=1`.
Do not change decision gate, execution planner, executor, broker/order logic, or
paper/live branching as part of asset data-ingestion eligibility.
