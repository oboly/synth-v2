# State‑Driven Runtime Orchestration Audit – Issue #331

## 1. Scope & Purpose

This document audits the existing *freshness* and *recompute* mechanisms that drive the market‑only runtime orchestration in Synth v2. The goal is to inventory current implementations, classify ownership, triggers, inputs/outputs, lock usage and consumers, identify duplicate or missing state transitions, and propose candidates for a future **state‑driven dispatcher** (see `docs/todo/state_driven_runtime_orchestration_v1.md`).

## 2. Mechanism Inventory

| Mechanism | File / Module | Layer | Primary Owner | Trigger(s) | Input(s) | Output(s) | Locks / Transactions |
|-----------|---------------|-------|---------------|------------|----------|-----------|----------------------|
| `public_candle_freshness` | `src/etl/bitvavo/run_candles_etl.py` (and related ETL) | market_data / ETL | ETL pipeline | New candle arrival (timer‑driven) | Raw candle rows | `market_price_snapshot_v1` rows, freshness flag | DB write transaction (no explicit lock) |
| Fast recompute lifecycle worklist | `src/reporting/run_fast_recompute_lifecycle_v1.py` | reporting / dashboard | Reporting runner | Scheduler / manual run (`--output-html`) | Latest `paper_advice_observation`, market prices, label registry | HTML table / JSON rows of `RecomputeLifecycleRow` | Read‑only DB queries (no lock) |
| Fast lifecycle classification | `src/reporting/fast_lifecycle_recompute_v1.py` | reporting | Same as above | Called by worklist builder | Row data (price, zones, leg) | `RecomputeLifecycleRow.lifecycle_state`, `recompute_needed` | Pure function – no DB |
| Native SHORT scope‑status materializer | `src/market_data/native_short_scope_status_materializer_v1.py` | market_data | Native SHORT materializer lane | Run invoked by scheduler (`run_native_short_scope_status_materializer`) | Scope key, cadence config, candles, map geometry | `native_short_scope_status_v1` rows, `native_short_scope_observation_v1` rows, optional map lifecycle events | MariaDB transaction per scope (INSERT/UPDATE), uses `RUNNER_NAME` lock via DB row‑level atomicity |
| Scope support events & cadence config fetchers | Same module (helper functions) | market_data | Same as above | Materializer run start | DB reads | Fact objects for projection engine | Read‑only |

## 3. Ownership & Data Flow

1. **ETL → Market Price Snapshot** – `run_candles_etl` writes fresh price snapshots; downstream readers treat these as market‑only observations.
2. **Paper Advice → Recompute Worklist** – `run_fast_recompute_lifecycle_v1` reads the latest `paper_advice_observation` (market‑only) and market prices to compute which advice maps need refresh. It produces a *read‑only* worklist for UI consumption – **no DB writes**.
3. **Native SHORT Materializer** – Reads cadence configs, scope‑support events, and candle data; writes **scope status** (`native_short_scope_status_v1`) and **observations** (`native_short_scope_observation_v1`). This is the only component that mutates runtime state based on freshness.
4. **Map Materializer** – `materialize_scope_symbol` (in `native_short_map_materializer_v1`) is reused by the status materializer to rebuild map geometry before status projection; it writes `native_short_map_materializer_v1` tables but does not emit lifecycle events unless a new map is published.

## 4. Locks / Transactions

- The **materializer** uses a single DB transaction per scope when inserting observation and updating the run record. The `INSERT … ON DUPLICATE KEY UPDATE` on `native_short_scope_status_v1` provides deterministic up‑sert semantics without explicit advisory locks.
- The **recompute worklist** and **fast lifecycle** are pure read‑only and therefore lock‑free.
- The **ETL** writes are performed in batch with default autocommit; no explicit row‑level locking beyond DB engine guarantees.

## 5. Consumers

- **Dashboards** (`run_fast_recompute_lifecycle_v1`, `run_paper_advice_static_dashboard_v1`) consume the recompute worklist for human inspection.
- **Execution Planner** does **not** read any of the above – it solely relies on `decision_gate` output.
- **Native SHORT execution** (future lane) will eventually consume `native_short_scope_status_v1` to decide whether a map refresh is required.

## 6. Duplicates / Missing Transitions

| Issue | Description | Impact |
|-------|-------------|--------|
| Duplicate freshness detection | Both `public_candle_freshness` (ETL) and `native_short_scope_status_materializer_v1` evaluate candle freshness for the same symbol/interval, leading to redundant DB writes. | Inefficient I/O, possible race where ETL updates snapshot after materializer has already evaluated stale data. |
| Missing timer‑to‑state bridge | The recompute worklist (`run_fast_recompute_lifecycle_v1`) is only exposed to UI; there is **no downstream component** that consumes its output to trigger a state change (e.g., schedule a refresh). | Manual intervention required; prevents automation of refresh cycles. |
| No explicit state transition event for *stale‑map* | `native_short_scope_status_materializer_v1` projects `observation_freshness_state` but does **not** emit a dedicated lifecycle event when a map becomes stale, relying on UI to interpret the flag. | Hard to build a deterministic dispatcher that reacts to stale‑map signals. |
| Lack of centralized freshness flag | Freshness is represented in multiple places: `market_price_snapshot`, `paper_advice_observation`, `native_short_scope_status_v1`. No single source‑of‑truth for “is this symbol ready for refresh?”. | Increases cognitive load for orchestrator design. |

## 7. Candidates for State‑Driven Dispatcher

1. **Scope‑Status Projection as Source‑of‑Truth** – Promote `native_short_scope_status_v1.observation_freshness_state` (and `source_freshness_state`) to the canonical freshness flag. All downstream components (dashboards, future execution lanes) would read this single table.
2. **Event Table for Refresh Triggers** – Introduce a lightweight `native_short_refresh_trigger_v1` table populated by the materializer when `observation_freshness_state` becomes `STALE` or `OVERDUE`. The dispatcher subscribes to this table (polling or logical replication) and schedules the appropriate refresh runner.
3. **Consolidate ETL Freshness** – Remove the separate `public_candle_freshness` module; let the materializer compute freshness directly from the `market_price_snapshot` rows it already reads.
4. **Remove UI‑Only Worklist** – Deprecate `run_fast_recompute_lifecycle_v1` as a public API; replace it with a *service* that emits refresh‑trigger events based on scope‑status changes.
5. **Lock‑Free Up‑sert Guarantees** – Keep the current `INSERT … ON DUPLICATE KEY UPDATE` pattern for status rows; the dispatcher can rely on the unique `(venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval)` key to deduplicate work.

## 8. Recommended Design Sketch (high‑level)

```
Market Observation (price snapshot) ──► Native SHORT Scope‑Status Materializer
                                          │
                                          ▼
                         native_short_scope_status_v1 (freshness flag)
                                          │
                                          ▼
                        State‑Driven Dispatcher (watch table)
                                          │
                                          ▼
                    Refresh Runner (re‑runs map materializer / advice)
```

The dispatcher reads only the status table, emits a row in `native_short_refresh_trigger_v1` when `observation_freshness_state` transitions to `STALE` or `OVERDUE`. The refresh runner then executes the map materializer and updates the status projection again – forming a closed, deterministic loop.

## 9. Next Steps (non‑code)

- Create a **design issue** to add `native_short_refresh_trigger_v1` and update the materializer to write to it.
- Update `docs/todo/state_driven_runtime_orchestration_v1.md` with the new source‑of‑truth description.
- Draft a **dispatcher service spec** (could be a small Python service using `psycopg2` polling) – out of scope for the current audit.

---
*All safety markers confirmed: `broker_private_calls=0 broker_writes=0 order_submission=0 executor=none decision_gate=none`.*
