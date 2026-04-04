
# Project Tree — Current Structure

```text
synth-v2/
├── LICENSE
├── Makefile
├── README.md
├── chat.py
├── chat_cli.py
├── compose.yaml
├── configs/
│   ├── compute/
│   │   ├── config.example.yaml
│   │   └── config.yaml
│   ├── enums_reference.md
│   ├── etl_bitvavo_candles.yaml
│   └── strategy_ma_layers.yaml
├── data/
│   ├── aplus_parsed/
│   ├── aplus_prompt_out/
│   ├── aplus_raw/
│   └── aplus_rejected/
├── docs/
│   ├── README.md
│   ├── architecture_overview.md
│   ├── architecture_symbolic_pipeline.md
│   ├── asset_flag_policy.md
│   ├── breathline_compass.md
│   ├── breathline_mapping_spec.md
│   ├── dashboard_design.md
│   ├── database/
│   │   ├── GENERATE_SCHEMA_SNAPSHOT.md
│   │   ├── README.md
│   │   ├── schema_explanation.md
│   │   └── schema_snapshot.sql
│   ├── examples/
│   │   └── example_strategy_pipeline.py
│   ├── legacy/
│   │   ├── README_breathlie_dashboard_data_upsert.sql
│   │   └── README_breathline_dashboard.md
│   ├── module_architecture.md
│   ├── module_registry.md
│   ├── repo_structure_policy.md
│   ├── sector_module_design.md
│   ├── start_new_chat_context.md
│   ├── strategy_modules.md
│   ├── structure_zone_wave_foundation.md
│   ├── system_diagram.md
│   ├── todo/
│   │   ├── breathline_alignment.md
│   │   └── pre-impuls_activation_state.txt
│   ├── token_selection.txt
│   └── watchlist_design.md
├── logs/
├── notes/
│   ├── chat_distilled_notes.md
│   ├── compute_requirements_legacy.txt
│   └── future_extensions.md
├── scripts/
│   ├── __init__.py
│   ├── aplus_parse_codex.py
│   ├── aplus_store_raw.py
│   ├── aplus_upsert_compass.py
│   ├── prediction_create_from_aplus.py
│   ├── process_aplus_codex.py
│   ├── split_bundle.sh
│   ├── start_synth.sh
│   ├── write_aplus_prompt.py
│   └── write_bundle.sh
├── src/
│   ├── __init__.py
│   ├── advice/
│   │   └── run_advice_engine.py
│   ├── aplus/
│   │   ├── factor_extractor.py
│   │   ├── models.py
│   │   ├── parser.py
│   │   └── repository.py
│   ├── backtest/
│   │   ├── backtest_runner.py
│   │   └── backtest_worker.py
│   ├── collectors/
│   ├── common/
│   │   ├── db.py
│   │   ├── enums.py
│   │   └── utc.py
│   ├── dashboard/
│   ├── decision/
│   │   └── run_decision_engine.py
│   ├── engine/
│   │   ├── dataset_cache.py
│   │   ├── job_queue.py
│   │   ├── run_signal_engine.py
│   │   ├── submit_job.py
│   │   └── write_signal_engine_state.py
│   ├── etl/
│   │   ├── bitvavo/
│   │   │   ├── etl_bitvavo_candles.py
│   │   │   ├── etl_bitvavo_ticker24h.py
│   │   │   └── run_candles_etl.py
│   │   └── coingecko/
│   │       ├── etl_coingecko_assets.py
│   │       └── etl_coingecko_global.py
│   ├── execution/
│   │   └── run_execution_intent.py
│   ├── features/
│   │   ├── candle_feat_builder.py
│   │   ├── candle_loader.py
│   │   ├── etl_candle_feat.py
│   │   ├── indicators.py
│   │   └── run_feat_candle.py
│   ├── guards/
│   ├── interpreters/
│   │   └── regime_filter.py
│   ├── live/
│   │   └── run_live_cycle.py
│   ├── logging/
│   │   └── logging_setup.py
│   ├── main.py
│   ├── migrations/
│   │   ├── 0001_init.sql
│   │   ├── 0002_latest_views.sql
│   │   ├── 0004_portfolio_execution_stub.sql
│   │   └── 0005_portfolio_execution_views.sql
│   ├── portfolio/
│   │   └── run_portfolio_state.py
│   ├── prediction/
│   │   ├── models.py
│   │   ├── repository.py
│   │   └── scoring.py
│   ├── risk/
│   │   └── run_risk_engine.py
│   ├── selection/
│   │   └── run_selection_engine.py
│   ├── signal_engine/
│   │   ├── etl_signal_state.py
│   │   ├── expansion_rotation.py
│   │   ├── run_signal_state_etl.py
│   │   └── signal_engine.py
│   └── strategies/
│       └── ema_trend_strategy.py
├── tests/
│   └── db_test.py
└── venv/
