Status: Archived historical record
Active ownership: none
Current work: see canonical documentation / GitHub Issues
Archived by: docs/TODO cleanup Batch 4A

Canonical research owner: `docs/research/historical_breath_regime_context_backbone_v1.md`
P0 builder implementation: `src/research/run_historical_breath_regime_context_builder_v1.py`
Note: this file's own `Status: active` / `PARTIAL_CONTEXT_EXISTS` framing below is stale as of archiving; retained verbatim for historical record.

---

# TODO — Historical Breath Regime Context Backbone

## Status

- `active`
- decision: `PARTIAL_CONTEXT_EXISTS`

## Sources

- `docs/research/historical_breath_regime_context_backbone_v1.md`
- `src/reporting/market_breath_context_bridge_v1.py`
- `src/research/run_market_breath_analysis_v1.py`
- `src/research/run_market_breath_outcome_validation_v1.py`
- `src/research/run_market_breath_v1_1_calibration_audit.py`
- `src/research/run_regime_selector_backtest_v1.py`
- `src/regime/run_active_regime_observation_v1.py`
- `src/research/run_breath_curve_symbol_regime_validation_v1.py`
- `src/research/run_breath_curve_regime_gated_policy_preview_v1.py`
- `src/research/run_aplus_table1_regime_gate_validation_v1.py`

## Current state / facts

- Historical per-symbol breath-like rows already exist in `data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl`.
- Historical regime rows already exist in `regime_selector_backtest_observation_v1`.
- `active_regime_observation` is not a historical backbone; it is a thin current runtime snapshot.
- `market_breath_context_bridge_v1` is display-only and computes current context on demand.
- A+ history exists, but only as partial symbol-scoped snapshots and research views.
- Fibo context is still fragmented across `fibo_target_map_v1`, `execution_zone_context`, and dashboard merge logic.
- No single canonical row exists today with `symbol + asof_ts_utc + breath/regime/fibo/aplus` context in one place.

## Open tasks by priority

### P0

- Implement `historical_breath_regime_context_builder_v1` as a research-only file-output runner.
- Normalize the canonical row contract:
  `symbol, venue, interval, asof_ts_utc, breath_phase, breath_alignment, market_regime, btc_context, symbol_regime, fibo_context, aplus_context_state, martee_context_state, relative_strength_bucket, momentum_bucket, quality_state, confidence_bucket, source_refs, research_only`
- Define exact derivation precedence when multiple partial sources exist for the same symbol/timestamp.

### P1

- Reuse existing historical regime labels from `regime_selector_backtest_observation_v1` where safe.
- Reuse or derive historical breath labels from market-breath output rows using replay-safe as-of logic.
- Add replay-safe fibo context derivation using file outputs first, not runtime tables.
- Canonicalize A+ state mapping from current historical views into stable enum labels.

### P2

- Add strict vs default join modes for later backtests.
- Add context freshness and staleness audit summaries.
- Add row-level quality labels for missing/partial source coverage.
- Keep `MARKET_ONLY_CONTEXT + touch=TRUE + fakeout=FALSE` parked as research-only until symbol/time concentration is materially reduced.
  Current conclusion: not robust enough for strategy/advice promotion because `XLM` and the `2026-05-25` 3-day bucket dominate return contribution.

### P3

- Consider an optional later DB write path only after the file-output builder is reviewed and accepted.
- Consider Martee normalization only if a durable symbol/timestamp source is introduced.

## Blockers / dependencies

- Need canonical builder implementation before `symbol_reaction_profile_by_context_v1`.
- Need replay-safe fibo context mapping design before claiming a usable `fibo_context`.
- Need explicit enum mapping from existing market-breath / regime-selector / A+ lane labels into canonical context labels.

## Boundary

- research-only
- market-only
- account-agnostic
- no broker calls
- no broker writes
- no order submission
- no executor changes
- no decision_gate changes
- no execution_planner changes
- no selection_engine promotion
- no runtime advice routing

## Non-goals

- No live trading enablement
- No DB writes in the first builder batch
- No public dashboard actioning
- No using external narrative labels as executable signals
- No direct strategy recommendations from context labels alone
- No downstream runtime use of the current touch/fakeout shape lead while robustness remains `NOT_ROBUST`
