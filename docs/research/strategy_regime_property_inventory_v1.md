# Strategy Regime Property Inventory v1

Generated: 2026-05-14T09:21:11Z

Git HEAD: ec5d721 (HEAD -> research/strategy-regime-property-inventory-v1, origin/main, origin/fix/paper-advice-odroid-publisher-permissions-v1, origin/HEAD, main, fix/paper-advice-odroid-publisher-permissions-v1) Fix Odroid paper advice dashboard publisher verification

## Status

Research-only inventory. This document extracts candidate regime properties from existing Synth strategies, policies, research backtests and measurement layers.

It does not create orders, execution intent, account permission, live/paper routing, or broker calls.

## Core design decision

Regime should be inferred from historically validated strategy behaviour, not manually selected by horizon.

Correct flow:

    existing strategies and backtests
      -> extract implicit market conditions
      -> validate forward outcomes by condition
      -> define regime signatures
      -> regime selector
      -> policy router

Incorrect flow:

    horizon = regime
    paper/live = regime
    account permission = regime

## Non-regime fields

The following must not become regime inputs:

- execution_mode
- PAPER versus LIVE
- account_id
- sleeve balances or available equity
- max notional
- broker write permission
- order state
- executor state

These belong to runtime, decision_gate, execution_planner or executor. Regime selector must remain market-only and account-agnostic.

## Inventory

### selection_engine_v2

- Layer: selection_engine
- Current role: Market-only ranking and candidate selection. Account-agnostic. Produces selection_state, selection_bias, score, rank, quality and allowed sleeve context.
- Source paths:
- src/selection/selection_engine_v2.py
- src/selection/run_selection_engine_v2.py
- configs/selection_engine_v2.yaml

Candidate regime properties:

- selection_state
- selection_bias
- selection_score
- priority_rank
- quality_status_1d
- quality_status_4h
- quality_status_1h
- timing_refinement_score
- regime_label_4h if present
- allowed_sleeves as market suitability context, not account permission

Candidate good regime:

- ranked early rotation candidate
- trusted multi-timeframe quality
- constructive pullback/reclaim context
- defensive but improving setup

Candidate bad regime:

- quality degraded or blocked
- rank decay
- neutral/avoid state despite narrative strength
- conflicting higher-timeframe structure

Validation status: Partial. Selection output exists and can be joined to forward returns, but regime extraction is not yet formalized.

Missing validation:

- Forward return by selection_state x class x BTC context
- Rank decay and false-positive analysis
- Quality penalty contribution by regime

Architecture boundary: May inform regime selector and policy router after validation. Must not become account-aware and must not place orders.

Next action: Use as primary source for market-only strategy fingerprints.

### trade_setup_filter_v1

- Layer: research_policy_filter
- Current role: Filters current selection candidates using rank, market context and setup suitability before policy preview.
- Source paths:
- src/trade_setup_filter/run_trade_setup_filter_v1.py

Candidate regime properties:

- btc_prior_24h
- selection_state
- priority_rank
- selection_score
- setup_filter_state
- setup_filter_reason
- target_horizon as observed outcome hint, not regime definition

Candidate good regime:

- early rotation pullback/reclaim setup
- BTC weak-but-not-breaking context
- WATCHLIST rank sweet spot
- candidate weak set where pullback mean reversion can work

Candidate bad regime:

- rank outside sweet spot
- selection_state not eligible
- BTC breakdown
- late chase after move

Validation status: Medium. It already produces observations. Needs full regime/class slicing.

Missing validation:

- Backtest pass/fail by BTC prior return buckets
- Backtest pass/fail by asset class
- Forward return by setup_filter_reason
- MAE/MFE versus entry/TP/invalidation zones

Architecture boundary: Research/preview filter only. Should not encode live/paper mode. Should not own account permission.

Next action: Extract setup_filter_reason as strategy fingerprint input.

### trade_setup_filter_policy_preview_v1

- Layer: research_policy_preview
- Current role: Preview layer that blocks/allows current 24h policy candidates based on historical sample evidence.
- Source paths:
- src/research/run_trade_setup_filter_policy_preview_v1.py

Candidate regime properties:

- policy_decision
- suggested_horizon
- allowed_now
- sample sufficiency
- current_target_horizon

Candidate good regime:

- sufficient historical sample for current setup class
- current candidate belongs to validated historical bucket

Candidate bad regime:

- BLOCK_FOR_24H
- INSUFFICIENT_SAMPLE
- policy sample mismatch

Validation status: Early but useful. It correctly behaves as evidence preview, not execution permission.

Missing validation:

- Replace horizon-as-manual-regime with regime selector output
- Backtest policy decisions by global regime and class regime
- Store sample size and confidence bands explicitly

Architecture boundary: Must remain research preview until promoted. Do not mix with decision_gate or executor.

Next action: Convert horizon-specific preview into regime-aware policy evidence.

### paper_advice_policy_v1

- Layer: paper_navigation
- Current role: Read-only navigation aggregation. Combines selection, setup filter, policy preview, A+ bucket and execution zones into advice_state/action.
- Source paths:
- src/advice/paper_advice_policy_v1.py
- src/advice/run_paper_advice_policy_v1.py
- docs/core/paper_advice_policy_v1.md

Candidate regime properties:

- advice_state
- advice_action
- aplus_bucket
- setup_filter_state
- policy_decision
- leg_direction
- entry_zone
- tp_zone
- invalidation_price
- confidence_score
- risk_label

Candidate good regime:

- WATCH_CORE with setup confirmation
- CORE_CONTEXT plus reclaim
- WATCH where caution is explicit and zones are valid

Candidate bad regime:

- NO_NEW_BUY
- AVOID
- BLOCK_24H
- WAIT without setup confirmation

Validation status: Operational as static dashboard input. Not yet a validated strategy.

Missing validation:

- Advice_state forward return analysis
- Advice_action transition analysis over time
- Entry/TP/invalidation hit-rate validation
- Separation of regime property from dashboard presentation

Architecture boundary: Must stay market-only and account-agnostic. PAPER/LIVE mode is not a regime property. It belongs to runtime/deployment and later execution permission.

Next action: Use as dashboard-facing interpretation layer, not as source of execution truth.

### paper_advice_static_dashboard_v1

- Layer: reporting
- Current role: Static read-only dashboard publisher. Shows latest paper_advice_observation snapshot.
- Source paths:
- src/reporting/run_paper_advice_static_dashboard_v1.py
- docs/core/paper_advice_static_dashboard_v1.md
- scripts/publish_paper_advice_dashboard_to_odroid.sh

Candidate regime properties:

- None. Reporting layer only.

Candidate good regime:

- Not applicable

Candidate bad regime:

- Not applicable

Validation status: Working deployment/reporting utility.

Missing validation:

- No strategy validation belongs here

Architecture boundary: No strategy logic, no regime selection, no execution. Dashboard is display only.

Next action: Keep as observer. Do not add strategy shortcuts here.

### breath_curve_research_policy_backtest_v1

- Layer: research_backtest
- Current role: Research execution simulation for Breath Curve checkpoints and outcomes.
- Source paths:
- docs/research/breath_curve_research_policy_backtest_v1.md

Candidate regime properties:

- anchor_ts
- checkpoint
- offset_match
- full alignment score
- 0.618 recognition
- 0.786 recognition
- 1.000 pulse outcome
- 1.272 extension outcome

Candidate good regime:

- phase-locked symbol behaviour
- clean 0.618 or 0.786 recognition
- positive extension behaviour with stable offset

Candidate bad regime:

- half-phase drift
- offset instability
- late overshoot without early recognition
- regime-shift flagged asset

Validation status: Research-only. Useful for phase/regime hypotheses, not selection modifiers yet.

Missing validation:

- Non-overlap validation by symbol
- Regime bucket comparison
- Random anchor baseline
- Class-specific phase stability

Architecture boundary: Must stay market-only research. No selection_engine modifier until validated.

Next action: Feed regime selector as optional phase-context candidate only after stronger validation.

### breath_curve_regime_gated_policy_preview_v1

- Layer: research_policy_preview
- Current role: Preview for gating Breath Curve policy by regime diagnostics.
- Source paths:
- src/research/run_breath_curve_regime_gated_policy_preview_v1.py
- docs/research/breath_curve_regime_gated_policy_preview_v1.md

Candidate regime properties:

- regime gate pass/fail
- phase cohort
- symbol-specific alignment
- offset stability

Candidate good regime:

- stable phase cohort
- offset match aligns with positive forward outcome

Candidate bad regime:

- offset edge cases
- drift after checkpoint
- speculative/unstable phase behaviour

Validation status: Early research lane.

Missing validation:

- Compare against strategy-independent global regime
- Compare asset-class regime versus symbol-specific regime
- Quantify whether gate adds edge beyond selection_engine_v2

Architecture boundary: Research-only. No decision or execution side effects.

Next action: Use as one candidate feature family for regime selector backtest.

### A+ canonical Table 1 regime gate validation

- Layer: external_research_context
- Current role: External narrative/field context normalized into buckets such as APLUS_CANONICAL_CORE, APLUS_CAUTION and APLUS_AVOID.
- Source paths:
- src/research/run_aplus_table1_regime_gate_validation_v1.py
- docs/research/aplus_table1_regime_gate_validation_v1.md
- data/aplus_raw/2026-05-13_1915_table1_canonical_breathline.txt

Candidate regime properties:

- phase
- coherence
- field
- geometry
- structural_role
- expansion_quality
- anchor_strength
- strategic_bias
- aplus_bucket

Candidate good regime:

- canonical core with clean geometry and strong anchor
- anchor context with market setup confirmation

Candidate bad regime:

- APLUS_AVOID
- low coherence
- distorted geometry
- exhaustion/collapse phase

Validation status: External research context. Needs market validation before any strategic weight.

Missing validation:

- Forward returns by aplus_bucket
- A+ bucket interaction with selection_state
- A+ bucket interaction with asset class
- Failure analysis for canonical core assets in AVOID market setups

Architecture boundary: External narrative may label context. It must not bypass validated market signals.

Next action: Treat as exogenous regime prior, not direct trade advice.

### swing_pullback_recovery_v5 / paper candidate preview

- Layer: research_backtest_staging
- Current role: Research staging contract for market-only paper candidates derived from historical backtest filters.
- Source paths:
- src/research/paper_candidate_contract_v1.py
- docs/research/paper_candidate_contract_v1.md

Candidate regime properties:

- btc_prior_24h window
- rotation_bucket
- classification_code
- selection_state
- priority_rank
- sleeve_fit_code
- simulated_horizon_hours
- simulated_net_return

Candidate good regime:

- ROTATION_EARLY
- PULLBACK_WATCH
- WATCHLIST rank 1-10
- BTC prior 24h weak but controlled

Candidate bad regime:

- BTC breakdown
- late rotation
- rank outside accepted band
- negative simulated net return clusters

Validation status: Promising. This is likely one of the cleanest sources for regime signature extraction.

Missing validation:

- Rebuild replay by class and regime
- Evaluate 4h/24h/72h forward returns
- Check whether the edge is global, class-specific or symbol-specific

Architecture boundary: Contract is research-only and explicitly forbids account/order/execution fields.

Next action: Use as first seed strategy for regime selector backtest.

### execution_zone_context / zone_engine_v1

- Layer: measurement
- Current role: Market measurement of entry/target/invalidation zones. Despite the name, it is context, not execution.
- Source paths:
- src/zone/run_zone_engine_v1.py

Candidate regime properties:

- leg_direction
- entry_zone_low/high/type
- tp_zone_low/high/type
- invalidation_price
- zone_confidence_score
- zone_alignment_score

Candidate good regime:

- valid zones with strong confidence
- entry zone near current market
- asymmetric TP/invalidation structure

Candidate bad regime:

- inverted or stale zones
- low alignment
- target below entry for long context unless leg_direction is DOWN

Validation status: Operational measurement. Needs hit-rate validation.

Missing validation:

- Entry touch rate
- TP hit rate
- Invalidation hit rate
- MAE/MFE by selection/advice/regime

Architecture boundary: Measurement only. It must not decide entries by itself.

Next action: Join zone outcomes to strategy-regime backtest.

### decision_gate / execution_planner / executor

- Layer: excluded_from_regime_definition
- Current role: Account-aware permission, execution intent and order handling layers.
- Source paths:
- src/decision_gate
- src/execution_planner
- src/executor
- src/execution

Candidate regime properties:

- None. These are not regime sources.

Candidate good regime:

- Not applicable

Candidate bad regime:

- Not applicable

Validation status: Explicit exclusion.

Missing validation:

- No regime validation belongs here

Architecture boundary: Do not use account_id, sleeve balances, live/paper mode, notional, broker permission or order state as regime inputs.

Next action: Keep clean separation. Regime selector must sit upstream as market-only context.

## Discovered regime-relevant files

| File | Pattern hits |
|---|---:|
| `/home/gurk/projects/synth-v2/src/selection/selection_engine_v2.py` | quality=32, rank_score=44, selection_state=40 |
| `/home/gurk/projects/synth-v2/src/research/run_swing_pullback_strategy_sim_v1.py` | btc_context=6, classification=20, execution_boundary=3, rank_score=27, rotation_context=20, selection_state=28 |
| `/home/gurk/projects/synth-v2/src/research/run_swing_pullback_v5_paper_candidate_preview_v1.py` | aplus_context=3, btc_context=12, classification=18, execution_boundary=1, rank_score=36, rotation_context=18, selection_state=11 |
| `/home/gurk/projects/synth-v2/src/research/run_trade_setup_filter_policy_preview_v1.py` | btc_context=11, policy_decision=37, rank_score=28, selection_state=11 |
| `/home/gurk/projects/synth-v2/src/research/run_strategy_regime_property_inventory_v1.py` | aplus_context=6, breath_curve=7, btc_context=3, classification=5, execution_boundary=17, policy_decision=6, quality=3, rank_score=7, rotation_context=3, selection_state=13, zone_context=7 |
| `/home/gurk/projects/synth-v2/src/research/run_parking_rotation_strategy_sim_v1.py` | btc_context=16, classification=9, rank_score=35, rotation_context=11, selection_state=6 |
| `/home/gurk/projects/synth-v2/docs/research/swing_pullback_strategy_sim_v1.md` | aplus_context=2, btc_context=3, classification=8, execution_boundary=21, quality=1, rank_score=15, rotation_context=8, selection_state=14 |
| `/home/gurk/projects/synth-v2/src/synth_sleeves/agents.py` | aplus_context=1, rank_score=22, selection_state=45 |
| `/home/gurk/projects/synth-v2/src/research/run_replay_policy_eval_v1.py` | btc_context=15, classification=8, rank_score=16, rotation_context=12, selection_state=15 |
| `/home/gurk/projects/synth-v2/docs/core/execution_runtime_canonical_map_v1.md` | aplus_context=12, execution_boundary=50 |
| `/home/gurk/projects/synth-v2/src/selection/run_selection_engine.py` | classification=10, rank_score=14, rotation_context=1, selection_state=36 |
| `/home/gurk/projects/synth-v2/src/research/run_replay_policy_grid_v1.py` | btc_context=7, classification=17, rank_score=14, rotation_context=17, selection_state=6 |
| `/home/gurk/projects/synth-v2/src/research/run_paper_candidate_stage_writer_v1.py` | btc_context=9, classification=11, execution_boundary=1, rank_score=19, rotation_context=10, selection_state=9 |
| `/home/gurk/projects/synth-v2/src/selection/run_selection_engine_v2.py` | quality=12, rank_score=12, selection_state=31 |
| `/home/gurk/projects/synth-v2/src/advice/run_paper_advice_policy_v1.py` | aplus_context=9, execution_boundary=7, policy_decision=9, rank_score=13, selection_state=7, zone_context=10 |
| `/home/gurk/projects/synth-v2/src/ranking/run_ranking_engine.py` | classification=23, rank_score=1, rotation_context=30 |
| `/home/gurk/projects/synth-v2/src/zone/engine_v1.py` | breath_curve=6, zone_context=46 |
| `/home/gurk/projects/synth-v2/src/research/run_paper_candidate_decision_gate_preview_v1.py` | btc_context=4, classification=7, execution_boundary=7, rank_score=19, rotation_context=7, selection_state=8 |
| `/home/gurk/projects/synth-v2/src/research/run_strategy_battle_arena_v2.py` | aplus_context=1, btc_context=10, classification=7, execution_boundary=1, rank_score=19, rotation_context=7, selection_state=6 |
| `/home/gurk/projects/synth-v2/docs/research/breath_curve_phase_calibration_findings_20260513.md` | breath_curve=46, execution_boundary=3 |
| `/home/gurk/projects/synth-v2/src/research/run_trade_setup_filter_backfill_v1.py` | btc_context=8, rank_score=19, selection_state=14 |
| `/home/gurk/projects/synth-v2/src/research/run_arena_v2_paper_candidate_stage_bridge_v1.py` | btc_context=7, classification=6, execution_boundary=1, rank_score=15, rotation_context=6, selection_state=6 |
| `/home/gurk/projects/synth-v2/docs/core/selection_engine_v2.md` | quality=17, rank_score=4, selection_state=18 |
| `/home/gurk/projects/synth-v2/src/backtest/run_backtest_selection_eval_v1.py` | aplus_context=2, rank_score=16, selection_state=17 |
| `/home/gurk/projects/synth-v2/src/advice/paper_advice_policy_v1.py` | aplus_context=12, classification=1, policy_decision=7, rank_score=1, selection_state=14 |
| `/home/gurk/projects/synth-v2/src/selection/selection_overlay_engine.py` | rank_score=6, rotation_context=1, selection_state=27 |
| `/home/gurk/projects/synth-v2/src/research/run_named_replay_policy_v1.py` | btc_context=3, classification=11, rank_score=4, rotation_context=13, selection_state=3 |
| `/home/gurk/projects/synth-v2/src/reporting/run_live_advice_report_extended.py` | classification=1, rank_score=12, selection_state=21 |
| `/home/gurk/projects/synth-v2/src/reporting/run_extended_trade_report.py` | classification=2, rank_score=9, rotation_context=2, selection_state=21 |
| `/home/gurk/projects/synth-v2/src/research/run_selection_v2_replay_backfill.py` | quality=6, rank_score=12, selection_state=15 |
| `/home/gurk/projects/synth-v2/src/signal_engine/signal_engine.py` | rotation_context=31 |
| `/home/gurk/projects/synth-v2/src/research/run_trade_setup_filter_outcome_report_v1.py` | btc_context=8, rank_score=16, selection_state=7 |
| `/home/gurk/projects/synth-v2/src/reporting/run_paper_advice_static_dashboard_v1.py` | aplus_context=2, execution_boundary=7, policy_decision=5, rank_score=5, selection_state=5, zone_context=7 |
| `/home/gurk/projects/synth-v2/docs/research/breath_curve_random_anchor_baseline_findings_20260512.md` | breath_curve=27, execution_boundary=3 |
| `/home/gurk/projects/synth-v2/src/execution_planner/run_execution_planner_v1.py` | execution_boundary=6, selection_state=23 |
| `/home/gurk/projects/synth-v2/docs/research/breath_curve_partial_to_full_backtest_v1_findings.md` | aplus_context=2, breath_curve=23, classification=1, execution_boundary=3 |
| `/home/gurk/projects/synth-v2/src/research/run_strategy_scoring_board_v1.py` | breath_curve=14, execution_boundary=10, rank_score=4 |
| `/home/gurk/projects/synth-v2/src/research/run_selection_context_filter_eval_v1.py` | btc_context=13, rank_score=8, selection_state=7 |
| `/home/gurk/projects/synth-v2/src/research/run_aplus_table1_regime_gate_validation_v1.py` | aplus_context=20, execution_boundary=7, selection_state=1 |
| `/home/gurk/projects/synth-v2/src/backtest/run_advice_backtest_v2.py` | rank_score=14, selection_state=14 |
| `/home/gurk/projects/synth-v2/docs/research/aplus_breathline_harmonic_snapshot_20260513_0358.md` | aplus_context=3, breath_curve=22, execution_boundary=3 |
| `/home/gurk/projects/synth-v2/src/backtest/run_advice_backtest_v3.py` | rank_score=14, selection_state=13 |
| `/home/gurk/projects/synth-v2/src/backtest/run_advice_backtest_v1.py` | rank_score=14, selection_state=13 |
| `/home/gurk/projects/synth-v2/docs/research/parking_rotation_strategy_sim_v1.md` | btc_context=2, classification=3, execution_boundary=5, rank_score=4, rotation_context=6, selection_state=5 |
| `/home/gurk/projects/synth-v2/docs/research/breath_curve_policy_baseline_findings_20260512.md` | breath_curve=22, execution_boundary=3 |
| `/home/gurk/projects/synth-v2/docs/research/breath_curve_calibrated_policy_findings_20260513.md` | breath_curve=21, execution_boundary=4 |
| `/home/gurk/projects/synth-v2/docs/research/breath_curve_random_anchor_wider_window_findings_20260513.md` | breath_curve=20, execution_boundary=3 |
| `/home/gurk/projects/synth-v2/src/engine/write_signal_engine_state.py` | rotation_context=22 |
| `/home/gurk/projects/synth-v2/docs/research/strategy_scoring_board_findings_20260513.md` | breath_curve=12, execution_boundary=9, quality=1 |
| `/home/gurk/projects/synth-v2/docs/research/breath_curve_codex_reflection_20260513.md` | breath_curve=17, classification=1, execution_boundary=3, selection_state=1 |
| `/home/gurk/projects/synth-v2/docs/research/aplus_harmonic_snapshot_validation_findings_20260513.md` | breath_curve=19, execution_boundary=3 |
| `/home/gurk/projects/synth-v2/src/trade_setup_filter/engine_v1.py` | btc_context=7, rank_score=8, selection_state=5 |
| `/home/gurk/projects/synth-v2/src/selection/run_selection_backfill.py` | classification=1, rank_score=6, rotation_context=1, selection_state=12 |
| `/home/gurk/projects/synth-v2/src/research/run_aplus_harmonic_snapshot_validation_v1.py` | aplus_context=9, breath_curve=7, execution_boundary=4 |
| `/home/gurk/projects/synth-v2/src/orchestration/run_paper_cycle_v1.py` | execution_boundary=10, rank_score=4, selection_state=6 |
| `/home/gurk/projects/synth-v2/src/decision/run_decision_engine.py` | rank_score=9, selection_state=11 |
| `/home/gurk/projects/synth-v2/src/trade_setup_filter/repository.py` | btc_context=3, rank_score=9, selection_state=7 |
| `/home/gurk/projects/synth-v2/src/research/run_replay_policy_eval_horizon_v2.py` | btc_context=2, classification=4, execution_boundary=1, rank_score=4, rotation_context=4, selection_state=4 |
| `/home/gurk/projects/synth-v2/src/research/run_aplus_harmonic_transition_validation_v1.py` | breath_curve=15, execution_boundary=4 |
| `/home/gurk/projects/synth-v2/src/advice/run_advice_engine.py` | rank_score=6, rotation_context=12, selection_state=1 |
| `/home/gurk/projects/synth-v2/docs/research/strategy_candidate_registry_v1.md` | aplus_context=1, btc_context=2, execution_boundary=13, quality=3 |
| `/home/gurk/projects/synth-v2/src/orchestration/run_live_paper_cycle_v1.py` | execution_boundary=11, selection_state=7 |
| `/home/gurk/projects/synth-v2/src/ranking/run_ranking_backfill.py` | classification=6, rank_score=2, rotation_context=9 |
| `/home/gurk/projects/synth-v2/docs/research/swing_pullback_v5_paper_candidate_preview_v1.md` | aplus_context=1, btc_context=1, classification=3, execution_boundary=4, rank_score=3, rotation_context=3, selection_state=2 |
| `/home/gurk/projects/synth-v2/docs/research/selection_context_filter_v1.md` | btc_context=5, execution_boundary=5, rank_score=3, selection_state=4 |
| `/home/gurk/projects/synth-v2/docs/research/breath_curve_random_anchor_baseline_findings_20260513.md` | breath_curve=14, execution_boundary=3 |
| `/home/gurk/projects/synth-v2/docs/research/breath_curve_non_overlap_validation_findings_20260513.md` | breath_curve=10, execution_boundary=6, quality=1 |
| `/home/gurk/projects/synth-v2/src/trade_setup_filter/observation_repository.py` | btc_context=4, rank_score=8, selection_state=4 |
| `/home/gurk/projects/synth-v2/src/research/run_paper_candidate_execution_planner_preview_v1.py` | execution_boundary=10, rank_score=4, selection_state=2 |
| `/home/gurk/projects/synth-v2/src/orchestration/run_live_paper_loop_v1.py` | execution_boundary=11, selection_state=5 |
| `/home/gurk/projects/synth-v2/docs/research/breath_curve_partial_to_full_backtest_v1.md` | aplus_context=1, breath_curve=11, classification=1, execution_boundary=3 |
| `/home/gurk/projects/synth-v2/docs/core/decision_gate_v1.md` | btc_context=1, execution_boundary=5, rank_score=2, selection_state=8 |
| `/home/gurk/projects/synth-v2/src/zone/repository.py` | zone_context=15 |
| `/home/gurk/projects/synth-v2/src/research/run_paper_candidate_exposure_preview_v1.py` | execution_boundary=1, rank_score=14 |
| `/home/gurk/projects/synth-v2/src/research/run_paper_candidate_contract_intake_smoke_v1.py` | btc_context=2, classification=2, execution_boundary=2, rank_score=5, rotation_context=2, selection_state=2 |
| `/home/gurk/projects/synth-v2/src/research/run_breath_curve_random_anchor_baseline_v2.py` | breath_curve=8, execution_boundary=7 |
| `/home/gurk/projects/synth-v2/src/research/run_breath_curve_phase_band_report_v1.py` | breath_curve=11, execution_boundary=4 |
| `/home/gurk/projects/synth-v2/docs/core/current_implementation_order.md` | execution_boundary=8, selection_state=7 |
| `/home/gurk/projects/synth-v2/src/research/run_paper_candidate_pnl_preview_v1.py` | execution_boundary=1, rank_score=13 |
| `/home/gurk/projects/synth-v2/src/reporting/run_paper_dashboard_v1.py` | rank_score=7, selection_state=7 |

## Proposed next backtest

Name: regime_selector_backtest_v1

Compare these selector designs:

- Global regime only
- Asset-class regime only
- Symbol-specific regime only
- Global regime x asset class
- Strategy-specific regime signature

Outcome metrics:

- forward return over 4h, 24h, 72h
- max adverse excursion
- max favourable excursion
- entry zone touch rate
- TP zone hit rate
- invalidation hit rate
- rank decay
- state transition quality

## Architecture target

    market observations/features
      -> regime_selector
      -> active_regime_observation
      -> policy_router
      -> active_strategy_profile
      -> selection/advice modifiers after validation

No decision_gate, execution_planner or executor changes are implied by this inventory.
