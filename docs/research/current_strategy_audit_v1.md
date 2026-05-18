# Current Strategy Audit V1

Date: 2026-05-18

Scope: read-only architecture and backtest readiness review. This document does
not change runtime behavior, does not enable paper/live trading, and does not
modify decision, execution, broker, order, timer, or DB schema paths.

## Summary

Synth currently has an active market-only 4h runtime chain that produces
selection, setup-filter, policy-preview, paper-advice, zone, and runtime
snapshot observations. The chain is suitable for forward-return validation, but
only if historical replay outputs are kept in `synth_bt` or another explicit
research/backtest namespace.

The current active strategy surface is best described as a paper-navigation
stack, not an executable strategy:

- `selection_engine_v2` ranks market-only assets and writes `selection_state`.
- `trade_setup_filter_v1` narrows the latest selection snapshot with market
  setup context and writes `trade_setup_filter_observation`.
- `trade_setup_filter_policy_preview_v1` adds observation-only symbol/horizon
  policy labels.
- `paper_advice_policy_v1` interprets the latest market/setup/policy/zone/A+
  context and writes `paper_advice_observation`.
- Rotation preview is account-aware dashboard review logic. It must not be
  treated as an allocation or order strategy.

## A. Active Runtime Chain

### selection_state

Current producer:

- `scripts/run_chain_4h.sh`
- `python -m src.selection.run_selection_engine_v2 --venue bitvavo --write-db`
- Core logic: `src/selection/selection_engine_v2.py`

Inputs:

- `asset`
- latest `asset_interval_quality`
- latest `signal_engine_state` for `1d`, `4h`, and `1h`
- `configs/selection_engine_v2.yaml`

Output:

- `selection_state`

Interpretation:

`selection_engine_v2` is market-only and account-agnostic. It scores 4h context,
1d structure, 1h timing refinement, quality penalties, relative rank, and state
thresholds into `AVOID`, `NEUTRAL`, `WATCHLIST`, `PREPARE`, and `BUY_READY`.
It also emits priority rank, allowed sleeve labels, and summary text. It does
not read balances, positions, orders, execution plans, or account state.

### trade_setup_filter_observation

Current producer:

- `scripts/run_chain_4h.sh`
- `python -m src.trade_setup_filter.run_trade_setup_filter_v1 --venue bitvavo --limit 40 --asset-suitability-mode candidate_weak_set --write-db --output table`
- Core logic: `src/trade_setup_filter/engine_v1.py`
- Latest-candidate read path: `src/trade_setup_filter/repository.py`
- Write path: `src/trade_setup_filter/observation_repository.py`

Inputs:

- latest `selection_state`
- `asset`
- BTC 1h `obs_market_candle` context for the latest global 1h context timestamp

Output:

- `trade_setup_filter_observation`

Interpretation:

The filter is market/setup context only. In the current runtime invocation it
requires `WATCHLIST`, rank in the configured range, bounded BTC 24h prior, and
excludes the `candidate_weak_set`. It emits `PASS` or `FAIL` plus a reason such
as `MARKET_DAMAGE_CAUTION`, `MARKET_DAMAGE_RISK`,
`BTC_PRIOR_OVERHEAT_ZONE`, `RANK_OUTSIDE_SETUP_ELIGIBLE_RANGE`, or
`ASSET_SUITABILITY_WEAK_SET_CANDIDATE`.

### paper_advice_observation

Current producer:

- `scripts/run_chain_4h.sh`
- `python -m src.advice.run_paper_advice_policy_v1 --venue bitvavo --interval 4h --write-db --output table`
- Core logic: `src/advice/paper_advice_policy_v1.py`

Inputs:

- latest `selection_state`
- latest matching `trade_setup_filter_observation`
- latest `trade_setup_policy_preview_observation`
- latest `execution_zone_context` through `vw_paper_advice_execution_zone_context_v1`
- latest normalized A+ Table 1 DB snapshot from `aplus_table1_report` and
  `aplus_table1_row`

Output:

- `paper_advice_observation`

Interpretation:

`paper_advice_policy_v1` is paper interpretation only. It converts market/setup,
policy-preview, zone, and A+ context into labels such as `PAPER_READY`,
`WATCH_CORE`, `WATCH`, `NO_NEW_BUY`, `BLOCK_24H`, `CORE_CONTEXT`, and `WAIT`.
It prints explicit safety markers:

```text
broker_calls=0 broker_writes=0 order_submission=0 live_orders=0
decision_gate=none execution_planner=none executor=none
```

### strategy_runtime_snapshot

Current producer:

- `scripts/run_chain_4h.sh`
- `python -m src.strategy_runtime.run_strategy_runtime_snapshot --interval 4h --chain-name run_chain_4h --notes ...`
- Component inventory logic: `src/strategy_runtime/runtime_snapshot_writer.py`

Inputs:

- CLI metadata: venue, interval, chain name, notes
- current git commit
- hard-coded market-chain component specs in `default_market_chain_components`

Outputs:

- `strategy_runtime_snapshot`
- `strategy_runtime_component`

Interpretation:

This is a runtime provenance ledger, not a strategy. It records the market-only
component set and explicitly writes disabled flags for live trading, decision
gate, and execution.

### Rotation Preview / Cockpit Outputs

Current producers:

- Rotation preview model: `src/research/run_position_rotation_preview_v1.py`
- Static dashboard: `src/reporting/run_position_rotation_static_dashboard_v1.py`
- Odroid orchestration: `scripts/odroid/run_mvp_readonly_pipeline_once.sh`
- Cockpit output docs: `docs/ops/synth_mvp_readonly_cockpit_v1.md`

Inputs:

- latest `account_position_snapshot`
- `trading_account`
- latest `paper_advice_observation`
- latest `market_price_snapshot` for display price and distance columns

Outputs:

- `/var/www/html/synth/rotation-preview.html`
- `/var/www/html/synth/index.html`

Interpretation:

The rotation preview is account-aware review/dashboard logic. It reads positions
and paper advice to classify existing holdings into `HOLD`, `HOLD_REVIEW`,
`REDUCE_CANDIDATE`, `EXIT_CANDIDATE`, or stale-source variants. It also ranks
better candidates heuristically from paper-advice context. It is not a
selection strategy, not a decision gate, and not order logic.

## B. Strategy / Component Inventory

| component | file/module | layer | market-only or account-aware | input tables | output tables | horizon | current status | backtest readiness | leakage risk notes |
|---|---|---|---|---|---|---|---|---|---|
| Selection Engine v2 | `src/selection/selection_engine_v2.py`, `src/selection/run_selection_engine_v2.py` | selection | market-only / account-agnostic | `asset`, `asset_interval_quality`, `signal_engine_state` | `selection_state` | 1d/4h/1h context, runtime chain on 4h | active | needs replay source | Ready for historical replay if candidates are rebuilt point-in-time from historical signals and written to `synth_bt`, not backfilled into operational `selection_state`. |
| Selection Engine v1 | `src/selection/run_selection_engine.py` | selection | market-only / account-agnostic | legacy signal/ranking context | `selection_state` | mixed legacy | deprecated | not a strategy | Legacy producer shares table name; avoid mixing v1/v2 engine names in backtests. |
| Selection Overlay Engine | `src/selection/selection_overlay_engine.py`, `src/selection/run_selection_overlay_engine.py` | overlay | market-only | `selection_state` | `selection_enriched_overlays` | latest snapshot | research/dashboard-only | needs labels | Current overlay is derived from selection fields; avoid treating overlay labels as independent alpha without point-in-time validation. |
| Trade Setup Filter v1 | `src/trade_setup_filter/engine_v1.py`, `src/trade_setup_filter/run_trade_setup_filter_v1.py` | setup filter | market/setup only | latest `selection_state`, BTC `obs_market_candle`, `asset` | `trade_setup_filter_observation` | 24h target horizon | active | needs replay source | Must replay from historical `selection_state` plus point-in-time BTC candles; do not backfill operational table for research. |
| Trade Setup Policy Preview v1 | `src/research/run_trade_setup_filter_policy_preview_v1.py` | policy preview | market-only / observation-only | `trade_setup_filter_observation` | `trade_setup_policy_preview_observation` | 24h / long-horizon labels | paper | needs labels | Current symbol allow/block sets are derived from prior outcome analysis; use only as labels to validate, not as proof of current edge. |
| Paper Advice Policy v1 | `src/advice/paper_advice_policy_v1.py`, `src/advice/run_paper_advice_policy_v1.py` | paper advice | market-only / account-agnostic | `selection_state`, `trade_setup_filter_observation`, `trade_setup_policy_preview_observation`, `vw_paper_advice_execution_zone_context_v1`, `aplus_table1_report`, `aplus_table1_row` | `paper_advice_observation` | 4h snapshot with 24h/paper context | paper | needs replay source | Snapshot-only until all inputs have historical point-in-time replay; latest A+ DB context is a leakage risk if joined to old market snapshots. |
| A+ Table 1 DB Context | `src/research/load_aplus_reports_to_db_v1.py`, `src/advice/run_paper_advice_policy_v1.py` | context enrichment | market-only context | raw A+ reports, `aplus_table1_report`, `aplus_table1_row` | paper-advice fields | snapshot context | paper/research | needs labels | Latest A+ context must not be applied to historical market windows unless A+ snapshots are timestamped and replayed point-in-time. |
| Execution Zone Context | `src/zone/run_zone_engine_v1.py`, view `vw_paper_advice_execution_zone_context_v1` | market zone context | market-only | market candles / zone context tables | `execution_zone_context` and view | 4h zone context | active paper context | needs replay source | Operational latest zones are not safe for historical testing unless zones are recomputed point-in-time. |
| Market Price Snapshot v1 | `src/market_data/run_market_price_snapshot_v1.py`, `src/market_data/market_price_snapshot_v1.py` | market data | public market-only | Bitvavo public `/ticker/price` | `market_price_snapshot` | latest display price | active/dashboard support | not a strategy | Latest prices are display-only; never use them as historical entry/exit prices. |
| Strategy Runtime Snapshot | `src/strategy_runtime/run_strategy_runtime_snapshot.py`, `src/strategy_runtime/runtime_snapshot_writer.py` | runtime provenance | market-only metadata | git metadata and component specs | `strategy_runtime_snapshot`, `strategy_runtime_component` | run snapshot | active | not a strategy | Useful for provenance, not outcome validation. |
| Paper Advice Static Dashboard | `src/reporting/run_paper_advice_static_dashboard_v1.py` | reporting | market-only/static output | `paper_advice_observation`, candle lifecycle context | static HTML | dashboard refresh | dashboard-only | not a strategy | Lifecycle display must not be confused with refreshed advice or execution permission. |
| Rotation Preview | `src/research/run_position_rotation_preview_v1.py`, `src/reporting/run_position_rotation_static_dashboard_v1.py` | account-aware review dashboard | account-aware | `account_position_snapshot`, `trading_account`, `paper_advice_observation`, `market_price_snapshot` | static HTML only | latest review | dashboard-only | not a strategy | Reads current holdings; retrospective tests are account-review studies, not selection alpha tests. |
| Selection v2 Replay Backfill | `src/research/run_selection_v2_replay_backfill.py` | research replay | market-only | historical `signal_engine_state`, candles, config | `synth_bt.bt_selection_v2_replay` | historical 1h/4h/1d context | research | ready with caveats | Uses trusted quality assumptions in replay; document that difference from runtime quality snapshots. |
| Trade Setup Filter Backfill | `src/research/run_trade_setup_filter_backfill_v1.py` | research replay | market-only | historical `selection_state`, BTC candles | `synth_bt.bt_trade_setup_filter_observation` | 24h target | research | needs replay source | Good namespace separation; verify source selection snapshots are true replay rows, not operational backfills. |
| Trade Setup Outcome Report | `src/research/run_trade_setup_filter_outcome_report_v1.py` | outcome measurement | market-only | `trade_setup_filter_observation`, `obs_market_candle` | optional CSV if requested | configurable forward hours | research | ready for latest-observation audit | Reads operational observations; okay for recent audit but not clean historical backtest if observations were overwritten or backfilled. |
| Replay Policy Eval v1/v2 | `src/research/run_replay_policy_eval_v1.py`, `src/research/run_replay_policy_eval_horizon_v2.py` | research/backtest eval | market-only | `synth_bt.bt_selection_v2_replay`, `ranking_state`, `obs_market_candle` | `synth_bt.bt_selection_v2_replay_eval_*` | 4h/24h and horizons | research | ready with caveats | Contains future returns by design; keep fields inside `synth_bt`/research only. |
| Swing Pullback Sim | `src/research/run_swing_pullback_strategy_sim_v1.py` | research strategy simulation | market-only | replay/eval/ranking context | research outputs | 72h/168h variants | research | needs labels / broader replay | Prior docs say not paper-ready globally; avoid promotion without expanded replay and regime/symbol validation. |
| Parking Rotation Sim | `src/research/run_parking_rotation_strategy_sim_v1.py` | research strategy simulation | market-only | replay/eval/ranking context | research outputs | 24h variants | research | needs broader replay | Existing docs note short replay window and repaired sleeve context; not runtime-eligible. |
| Breath Curve Research | `src/research/backtest_breath_curve_*`, `src/research/run_breath_curve_*` | research/backtest | market-only research | breath curve datasets / candles / A+ context depending runner | research outputs / `synth_bt` research tables | research-specific | research | separate lane | Keep separate from current active runtime until validated and promoted through explicit candidate contract. |
| Paper Candidate Stage | `src/research/run_paper_candidate_stage_writer_v1.py` and related paper-candidate tools | research/paper staging | market-only staging, decision previews separate | paper candidate contract inputs | staging/research tables | candidate-specific | research/paper staging | needs labels | Must not bypass decision gate; staged candidates are not active strategy permission. |

## C. Current Policy Interpretation

### selection_engine_v2

`selection_engine_v2` is the active market-only ranking layer. It consumes latest
quality and signal snapshots, applies quality penalties, combines 4h context
scores with pullback, expansion, confidence, and relative strength, applies 1h
timing refinement, and emits a state/rank/sleeve summary.

Current policy meaning:

- `BUY_READY`: market-only high-readiness label. It is not account permission.
- `PREPARE`: constructive market state that may be near readiness.
- `WATCHLIST`: market structure worth monitoring, but not full permission.
- `NEUTRAL`: no strong setup.
- `AVOID`: blocked or weak setup.

### trade_setup_filter_v1

`trade_setup_filter_v1` is an additional setup/context gate over the latest
selection snapshot. It is not account-aware. It currently focuses on WATCHLIST
rank ranges, BTC 24h market context, overheat/risk bands, and a candidate weak
set.

`PASS` means the latest candidate passed this market/setup screen. It does not
mean buy, size, reserve, or execute.

### paper_advice_policy_v1

`paper_advice_policy_v1` is a paper interpretation layer. It combines selection,
setup filter, policy-preview labels, A+ context, and zone context. It maps those
inputs to paper labels and reason codes for review and dashboarding.

It is not a decision gate. It explicitly prints `decision_gate=none`,
`execution_planner=none`, and `executor=none`.

### Market Damage Caution / Risk

Market damage is currently expressed through BTC 24h prior in
`trade_setup_filter_v1`:

- below the hard minimum: `MARKET_DAMAGE_RISK`
- below the softer minimum: `MARKET_DAMAGE_CAUTION`
- above the maximum: `BTC_PRIOR_OVERHEAT_ZONE`

These are market-context filters, not account rules. They can be backtested as
labels against forward returns if the BTC context is resolved point-in-time.

### A+ Table 1 DB Context Usage

Runtime paper advice now defaults to `db://latest` for normalized A+ Table 1
context. `aplus_table1_report` and `aplus_table1_row` are used as paper-advice
enrichment only. Raw A+ files remain legacy fallback/archive material.

Backtesting A+ context requires timestamped A+ snapshots. Applying the latest A+
snapshot to historical selection/filter rows would leak future context.

### Zone Invalidation / Recompute-Needed

Zone context contributes target, entry/reaction, invalidation, and
recompute-needed labels to paper advice and rotation review. These labels should
be preserved during replay because they explain whether a setup was still inside
its known zone contract or needed a fresh zone computation.

For backtests, `ZONE_RECOMPUTE_NEEDED` and invalidation-related labels are
classification features, not license to repair history with newer zones. A
historical replay may recompute zones only from candles and context available at
that replay timestamp. The operational `execution_zone_context` table must not
be historically backfilled or rewritten to create a synthetic past timeline; use
a separate `synth_bt` replay table or explicit `data/research/...` artifact
instead.

### Rotation Preview

Rotation preview is an account-aware readout over current positions and latest
paper advice. It has useful review labels and distance columns, but it is not a
strategy selector. It should be evaluated, at most, as a retrospective account
review aid after a separate paper/account state replay exists.

## D. Backtest Readiness

### Can Be Backtested Now

These are closest to ready:

- Buy-and-hold baselines from `obs_market_candle` for same windows and same
  symbols.
- `selection_engine_v2` label forward returns if using
  `src/research/run_selection_v2_replay_backfill.py` into
  `synth_bt.bt_selection_v2_replay`.
- `trade_setup_filter_v1` labels if replayed into
  `synth_bt.bt_trade_setup_filter_observation` or evaluated from point-in-time
  replay rows.
- Existing replay policy eval tables under `synth_bt` for research-only
  selection/filter policy grids.
- Recent operational observation audits with
  `run_trade_setup_filter_outcome_report_v1`, as long as the result is framed
  as an operational-observation audit, not a clean historical backtest.

### Need Historical Replay Tables

These need point-in-time replay before clean historical testing:

- `paper_advice_policy_v1`, because it joins selection, setup filter,
  policy-preview, execution-zone, and A+ context.
- `trade_setup_filter_policy_preview_v1`, because its labels were derived from
  previous outcome analysis and should be validated as fixed labels over a
  held-out replay window.
- `execution_zone_context`, because latest operational zones cannot be applied
  backward. Historical zone context must be recomputed point-in-time into a
  research/backtest namespace; operational `execution_zone_context` must not be
  historically backfilled.
- A+ Table 1 context, because historical A+ report timestamps must be aligned to
  each replay timestamp.

### Snapshot-Only / Not Safe For Historical Testing

Not safe as historical strategies without further replay design:

- latest `market_price_snapshot` rows; these are current display prices only.
- static dashboard HTML outputs; they are render artifacts, not strategy state.
- `strategy_runtime_snapshot`; this is provenance metadata.
- rotation preview latest rows; they combine account holdings with current paper
  advice and current market price display.

### Future Leakage Risks

Primary leakage risks:

- Joining latest A+ Table 1 DB context onto old selection/filter snapshots.
- Using latest execution zones for historical entries/targets/invalidation.
- Recomputing invalidation or `ZONE_RECOMPUTE_NEEDED` labels with candles that
  were not available at the replay timestamp.
- Backfilling operational `selection_state`, `trade_setup_filter_observation`,
  or `paper_advice_observation` with historical rows and then treating the table
  as a clean runtime timeline.
- Historically backfilling operational `execution_zone_context`; that would mix
  runtime latest-zone semantics with research replay semantics.
- Letting future-return columns escape from `synth_bt`/research into runtime,
  decision, execution, dashboard, or paper-advice operational tables.
- Using current account positions to evaluate historical strategy selection.

### Avoiding Operational Table Backfill Contamination

Rules:

- Keep historical replay outputs under `synth_bt` or explicit
  `data/research/...` outputs.
- Preserve operational tables as latest/runtime observations unless a migration
  explicitly changes the contract.
- Use engine names, versions, config hashes, replay timestamps, and source
  snapshot timestamps in backtest tables.
- Do not write forward returns to operational tables.
- Do not backfill operational `execution_zone_context`; create replay-specific
  zone rows in `synth_bt` or `data/research/...`.
- Do not let dashboards read future-return fields.
- When comparing to operational observations, label the result as
  "operational observation audit", not clean historical backtest.

## E. Proposed Backtest Sequence

Minimal safe order:

1. Same-window buy-and-hold baseline using `obs_market_candle` only.
2. `selection_state` forward return validation from replayed
   `selection_engine_v2` rows.
3. `trade_setup_filter_v1` pass/fail forward return validation from
   point-in-time replay rows.
4. `paper_advice_policy_v1` label forward return validation after A+ and zone
   replay sources are point-in-time safe.
5. Rotation preview retrospective review only, account-aware and not selection
   strategy.
6. Breath Curve research remains separate until validated and explicitly
   promoted through the strategy candidate contract.

## F. Explicit Architecture Boundaries

- `selection_engine` = market-only / account-agnostic.
- `trade_setup_filter` = market/setup context only.
- `paper_advice_policy` = paper interpretation only.
- `decision_gate` = account-aware permissions.
- `execution_planner` = intent only after permission.
- `executor` = order handling.
- `rotation preview` = account-aware review dashboard, not order logic.

No research, reporting, dashboard, or preview code may create orders, reserve
capital, bypass decision gate, or enable execution paths.

## G. Next Implementation Candidates

Recommended next branches:

1. `research/buy-hold-baseline-v1`
   - Build a read-only same-window baseline report from `obs_market_candle`.
   - Output only docs and optional `data/research/...` artifacts.
   - No operational table writes.

2. `research/selection-state-forward-return-v1`
   - Use `synth_bt.bt_selection_v2_replay` or create a clean replay if missing.
   - Validate `selection_state`, rank buckets, and score buckets against forward
     returns.
   - Keep future returns inside `synth_bt`/research namespace.

3. `research/trade-setup-filter-forward-return-v1`
   - Replay or read point-in-time `trade_setup_filter_v1` decisions in
     `synth_bt`.
   - Compare PASS/FAIL/reason buckets against 4h/24h/72h returns.
   - Do not use operational latest observations as the main backtest source.

Recommended TODO placement:

- Keep strategy-candidate follow-up coordination in
  `docs/todo/strategy_candidates.md`.
- If broader backtest orchestration grows beyond these three branches, add a
  dedicated `docs/todo/backtests.md` in a separate documentation-only patch.

## Sanity Commands Used For This Audit

Read-only inspection commands used:

```bash
rg --files src/selection src/trade_setup_filter src/advice src/research src/strategy_runtime src/reporting docs/research docs/ops docs/todo
rg -n "selection_state|trade_setup_filter_observation|paper_advice_observation|strategy_runtime_snapshot|rotation preview|market_damage|A\\+|aplus" src docs
```

No broker calls were made. No DB writes were made. No runtime behavior changed.
