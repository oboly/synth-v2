# Synth Documentation

This is the top-level documentation index for Synth v2.5.

Synth is a layered quantitative crypto trading and research system.

Before designing, implementing, or reviewing any lane, read:
docs/SYSTEM_FACTS.md

The current focus is:

- data correctness
- pipeline completeness
- research/backtest reliability
- paper-runtime safety
- later live execution readiness

Live trading permission is not granted.

---

## 1. Core Architecture

Canonical pipeline:

    obs
    → feat
    → measurement / event
    → signal
    → ranking
    → selection
    → decision
    → execution

Core rule:

- `selection_engine` is market-only and account-agnostic.
- `decision_gate` is account-aware permission and risk gating.
- `execution_planner` creates execution intent/plans.
- `executor` handles paper/live order lifecycle and state mutation.

No layer may bypass the next permission layer.

---

## 2. Main Documentation Files

General standards:

    docs/coding_standards.md

Database reference:

    docs/database/README.md

Architecture docs:

    docs/architecture/

Research docs:

    docs/research/

Core runtime docs:

    docs/core/

---

## 3. Database and Schema Rules

The database is the source of truth.

Permanent schema meaning belongs in:

    native table comments
    native column comments
    docs/database/README.md

Encoding standard:

    CHARSET = utf8mb4
    COLLATE = utf8mb4_unicode_ci

For broad schema/collation cleanup, preferred workflow when in-place migration is risky:

    DDL export
    normalize charset/collation/comments
    deploy clean schema
    reload/backfill data

This is a migration workflow choice, not a universal rule for every small schema edit.

---

## 4. Current Important Tables

Observation:

    obs_market_candle

Features:

    feat_candle

Market structure / measurement:

    structure_state
    feat_rejection_event
    feat_liquidity_event

Signals:

    signal_engine_state

Selection:

    selection_state

Asset profiles:

    asset
    asset_profile_snapshot
    vw_asset_profile_latest

Research/backtest:

    bt_selection_v2_replay
    bt_selection_v2_replay_eval_horizon_v2
    research_paper_candidate_signal
    research_oracle_*

Paper/runtime:

    decision_log
    execution_plan
    execution_event
    capital_reservation
    portfolio_position
    portfolio_sleeve
    runtime_state

---

## 5. Research / Backtest Boundary

Research and backtest tools may use future-aware returns or labels only in clearly separated namespaces:

    src/research/
    src/backtest/
    research_*
    bt_*
    docs/research/

Future-aware data must never leak into:

    live selection_engine path
    decision_gate
    execution_planner
    executor
    live inference

Oracle research is a microscope, not a steering wheel.

---

## 6. Asset Profile Layer

Static asset identity lives in:

    asset

Derived market behavior lives in:

    asset_profile_snapshot
    vw_asset_profile_latest

Meaning:

    liquidity_class = derived tradability tier
    beta_profile = derived market sensitivity / volatility behavior
    sector_group_code = empirical co-movement group

Backtests and replay must use point-in-time profile snapshots:

    asset_profile_snapshot.asof_ts_utc <= replay_asof_ts_utc

Do not use `vw_asset_profile_latest` for historical replay.

---

## 7. UI / Chart Framework

Current UI direction:

    Streamlit + Plotly debug UI

Purpose:

- inspect candles
- inspect features
- inspect signal states
- inspect selection states
- inspect asset profiles
- later inspect paper/backtest/oracle markers

UI rule:

    read-only only

Forbidden in UI:

    decision_state writes
    execution_plan writes
    order writes
    account/balance mutation
    trading control

Future UI direction:

    TradingView-style Lightweight Charts frontend
    Python/FastAPI read-only backend

---

## 8. Stateful Paper Runtime

The paper runtime can model:

    selection
    → decision
    → execution plan
    → capital reservation
    → paper fill / ack
    → portfolio position mutation
    → lifecycle invalidation / release
    → dashboard / runtime loop

This is a paper engine skeleton, not live execution.

---

## 9. Live Execution Status

Real Bitvavo execution is not active.

Still needed before live execution:

- Bitvavo REST/WebSocket execution adapter
- canonical exchange order layer
- live executor beside paper executor
- idempotent client order IDs
- fill reconciliation
- retry/rate-limit/error handling
- kill switch
- hard paper/live mode separation
- max notional / max active order controls

Live execution must be built as a separate live execution layer, not patched onto paper runtime.

---

## 10. Current Operational Priorities

Current priority order:

    1. Data correctness
    2. Pipeline completeness
    3. Schema/docs alignment
    4. Backtest/replay reliability
    5. Strategy tuning
    6. Runtime optimization
    7. Live execution

Do not optimize strategy on incomplete or misaligned data.

---

## 11. Infrastructure Notes

Current development environment:

    repo: ~/projects/synth-v2
    DB connection via .env
    UTC timestamps
    remote DB possible
    local MariaDB must not be assumed

Heavy backfills should preferably run on SSD-backed infrastructure.

SDHC/Odroid-style storage is acceptable for lightweight runtime, but not ideal for large historical rebuilds.

---

## 12. Final Rule

If a permanent rule, schema contract, or architectural boundary matters:

    document it
    add DB-native comments where relevant
    then update code

Do not rely on chat memory alone for permanent system behavior.
