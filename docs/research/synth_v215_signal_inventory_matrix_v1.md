# Synth v2.15 Signal Inventory Matrix v1

## 1. Purpose

This document inventories the current Synth v2.15 market-only evidence surfaces before any new advice route is designed.

The goal is to separate:

- market observation
- deterministic feature measurement
- canonical live signals
- downstream market-only interpretation layers
- paper/readout layers
- research-only framework context

This is a design inventory, not a new execution path.

## 2. Runtime truth

Current runtime truth for live market signals:

- canonical live signal table: `signal_engine_state`
- legacy / non-runtime table: `signal_state`
- canonical 4h signal freshness is gated by eligible `feat_candle` snapshot coverage
- dashboard render is not signal ownership
- dashboard render must not define canonical market or signal freshness

Operational interpretation:

- `obs_market_candle` is the canonical market observation root.
- `feat_candle` is the deterministic market measurement layer.
- `signal_engine_state` is the live runtime signal layer consumed by active downstream market-only engines.
- `advice_state`, `ranking_state`, `selection_state`, `execution_zone_context`, and `trade_setup_filter_*` are downstream market-only interpretation/context layers, not account-aware permission.
- `paper_advice_observation` is paper/readout interpretation only.

4h freshness note:

- A new raw `4h` candle can exist before the next `feat_candle` snapshot is eligible.
- The active signal ETL chooses the latest eligible `feat_candle` snapshot, not simply the newest raw candle bucket.
- A one-step apparent lag can therefore be expected when the newest `4h` feature snapshot has not yet met coverage gating.

## 3. Signal inventory table

| signal_name | source module/table | current owner | layer | horizon | source_interval | account_aware | runtime_owned | freshness_requirement | current_status | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `obs_market_candle` | `obs_market_candle` / `src.etl.bitvavo.run_candles_etl` | `scripts/run_chain_4h.sh`, `scripts/odroid/run_market_candle_freshness_once.sh`, `scripts/odroid/run_paper_advice_lifecycle_refresh_once.sh` | market observation | MIXED | `15m/1h/4h/1d` | NO | YES | per interval freshness contract | ACTIVE | Root public market observation. Not itself a directional signal. |
| `feat_candle` | `feat_candle` / `src.features.run_feat_candle` | `scripts/run_chain_4h.sh` | features | MIXED | `4h` in active chain | NO | YES | latest eligible completed `4h` snapshot | ACTIVE | Deterministic measurements only. Upstream gate for canonical live signals. |
| `signal_engine_state` | `signal_engine_state` / `src.signal_engine.run_signal_state_etl` | `scripts/run_chain_4h.sh` | signals | MIXED | `1h/4h/1d`, canonical live gate currently `4h` | NO | YES | latest eligible `feat_candle` snapshot | ACTIVE | Canonical live signal table. Primitive families include `trend`, `volume`, `phase`, `compass`, `rotation`, `relative`, `setup`, `risk`, plus `expansion_delay_state`, `rotation_trigger_state`, and `signal_confidence`. |
| `signal_state` | legacy `signal_state` table | no active owner confirmed | legacy signals | UNKNOWN | stale | NO | LEGACY | none for live runtime | LEGACY | Must not be used as live runtime truth or freshness gate. |
| `advice_state` | `advice_state` / `src.advice.run_advice_engine` | `scripts/run_chain_4h.sh` | market-only interpretation | MID | `4h` | NO | YES | latest eligible completed `4h` cycle | ACTIVE | Reads `signal_engine_state`; still market-only; not permission, not sizing, not execution. |
| `ranking_state` | `ranking_state` / `src.ranking.run_ranking_engine` | `scripts/run_chain_4h.sh` | market-only ranking | MID | `4h` | NO | YES | latest eligible completed `4h` cycle | ACTIVE | Relative opportunity ordering from market-only context. |
| `asset_interval_quality` | `asset_interval_quality` / `src.measurement.run_asset_interval_quality_snapshot` | `scripts/run_chain_4h.sh` | quality/freshness evidence | MIXED | `1h/4h/1d` | NO | YES | interval freshness and coverage audit | ACTIVE | Not directional. Supplies trust/degraded/blocked quality context and gap diagnostics. |
| `selection_state` | `selection_state` / `src.selection.run_selection_engine_v2` | `scripts/run_chain_4h.sh` | market-only candidate selection | MIXED | combines `1d/4h/1h` | NO | YES | latest active 4h chain cycle | ACTIVE | Market-only candidate/ranking output. Must not read balances, positions, or orders. |
| `execution_zone_context` | `execution_zone_context` / `src.zone.run_zone_engine_v1` | `scripts/run_chain_4h.sh` | market context map | MID | `4h` | NO | YES | latest completed `4h` cycle | ACTIVE | Zone/fib map context. Useful for strategy interpretation later, but not account-aware permission. |
| `trade_setup_filter_observation` | `trade_setup_filter_observation` / `src.trade_setup_filter.run_trade_setup_filter_v1` | `scripts/run_chain_4h.sh` | market-only setup filter | MID | `4h` | NO | YES | latest active 4h chain cycle | ACTIVE | Explicitly market-only. Must not size, allocate, or create execution intent. |
| `trade_setup_policy_preview_observation` | `trade_setup_policy_preview_observation` / paper policy preview lane | `scripts/run_chain_4h.sh` | paper policy preview | MID | `4h` | NO | YES | latest active 4h chain cycle | ACTIVE | Downstream preview layer. Useful for review, not canonical primitive signal truth. |
| `paper_advice_observation` | `paper_advice_observation` / `src.advice.run_paper_advice_policy_v1` | `scripts/run_chain_4h.sh` | paper/readout interpretation | MID | `4h` | NO | YES | latest active 4h chain cycle | ACTIVE | Readout layer only. Must not be promoted as direct trade permission. |
| `intrabar_lifecycle_context_v1` | `src.reporting.intrabar_lifecycle_context_v1` | render/reporting readers only | display-only fast context | SHORT | `15m` with `4h` structural reference | NO | NO | fresh `15m` candles plus fresh price snapshot | ACTIVE | Useful fast price/zone reaction surface. Not canonical signal storage. |
| `market_breath_context_bridge_v1` | `src.reporting.market_breath_context_bridge_v1` | render/reporting readers only | read-only diagnostic bridge | LONG | `4h` | NO | NO | diagnostic freshness only | ACTIVE | Read-only bridge. Exposes Synth-native Market Breath diagnostics without changing runtime signal ownership. |
| `breath_fibo_framework_research` | `src/research/run_market_breath_*`, `src/research/run_fibo_*`, related `docs/research/fib_*` | research only | research framework context | LONG | mostly `4h/1d/1w` | NO | RESEARCH_ONLY | research-run specific | RESEARCH | Important future framework lane, but not current canonical runtime signal truth. |
| `aplus_normalized_external_context` | `aplus_table1_report`, `aplus_table1_row`, `docs/research/aplus_*` | external research normalization lanes | external research context | LONG | snapshot-based external context | NO | RESEARCH_ONLY | external snapshot freshness only | RESEARCH | May calibrate or validate later; must not replace Synth-native truth. |
| `martee_oracle_touch_semantics` | `docs/todo/martee_oracle_touch_semantics.md` | none; TODO only | external research semantics | LONG | daily/weekly/monthly semantic map | NO | RESEARCH_ONLY | none | RESEARCH | Research-only semantics. No active runtime ingestion identified. |
| `sparse_candle_gap_diagnostics` | `v_asset_interval_quality_v3` -> `asset_interval_quality` | `scripts/run_chain_4h.sh` | quality diagnostics | MIXED | `1h/4h/1d` | NO | YES | interval freshness and gap audit | ACTIVE | Gap events, missing candles, and coverage ratio are active diagnostics, not directional signals. |
| `shadow_heartbeat_research` | `src/research/run_shadow_heartbeat_outcome_validation_v1.py`, `docs/research/shadow_heartbeat_outcome_validation_v1.md` | research only | research validation | SHORT | `5m` heartbeat on `15m` market context | NO | RESEARCH_ONLY | research-run specific | RESEARCH | Measures live-like heartbeat states against forward outcomes. Not canonical runtime advice. |
| `position_lifecycle_research` | `src/research/run_position_lifecycle_*`, `docs/research/position_lifecycle_*` | research only | account-aware research review | MIXED | event-driven / position-driven | YES | RESEARCH_ONLY | research-run specific | RESEARCH | Not eligible as a signal input because it is position/account-aware. Keep out of canonical signal matrix. |

Notes on missing or not-yet-normalized items:

- No active runtime `market_trigger_engine` output table was identified in the current live chain.
- `failed_breakout` appears in TODO/archive/dashboard design material, not as a current canonical runtime table.
- `market_damage` currently appears as research/dashboard vocabulary, not as a normalized active runtime signal table.

## 4. Horizon-separated matrix

### SHORT

Current or near-current SHORT-horizon evidence surfaces:

- `intrabar_lifecycle_context_v1`
  - fast price-versus-zone reaction
  - `15m` lifecycle state
  - intrabar recompute hint
  - target touch context
- `obs_market_candle` `15m`
  - latest fast market structure and wick/close behavior
- `shadow_heartbeat_research`
  - research-only fast heartbeat validation
- `sparse_candle_gap_diagnostics`
  - freshness/gap caution for fast inputs

Current SHORT-horizon gaps:

- `failed_breakout` is not yet normalized as a canonical runtime table
- `market_damage` is not yet normalized as a canonical runtime table
- spike/take-profit context exists indirectly in downstream paper/readout surfaces, but not yet as a clean primitive runtime signal family

### MID

Current MID-horizon evidence surfaces:

- `signal_engine_state`
  - current canonical live signal truth
  - active `4h` runtime interpretation surface
  - contains `trend`, `volume`, `phase`, `compass`, `rotation`, `relative`, `setup`, `risk`
- `advice_state`
  - market-only interpretation of signal state
- `ranking_state`
  - relative ordering of opportunities
- `selection_state`
  - market-only candidate persistence across `1d/4h/1h`
- `execution_zone_context`
  - reclaim / continuation / support / target zone map
- `trade_setup_filter_observation`
  - setup-quality and readiness context
- `trade_setup_policy_preview_observation`
  - downstream preview logic for paper/readout lanes
- `paper_advice_observation`
  - paper/readout interpretation only
- `asset_interval_quality`
  - quality and freshness confidence for runtime inputs

MID-horizon emphasis:

- relative strength is active now through `relative_signal`, `relative_score`, and downstream ranking/selection inputs
- reclaim / continuation context exists now through `execution_zone_context`, `setup_signal`, and downstream setup filter lanes
- setup persistence exists now in ranking/selection outputs, but remains market-only and account-agnostic

### LONG

Current LONG-horizon context surfaces:

- `market_breath_context_bridge_v1`
  - read-only market-breath diagnostics for cockpit/paper-advice visibility
- `breath_fibo_framework_research`
  - Breath + Fibo framework lane
  - wave / map / anchor / zone research
- `aplus_normalized_external_context`
  - normalized external context
  - research/validation only
- `martee_oracle_touch_semantics`
  - external macro/touch semantics TODO only

LONG-horizon interpretation:

- LONG context is present mainly as research or diagnostic context, not yet as canonical runtime signal truth.
- wave degree, macro map, weekly/monthly context, and long-core hold/legacy-exit semantics are not yet normalized into a production signal contract.

## 5. Layer boundary notes

- Signals are market evidence only.
- Signals may support later strategy interpretation.
- Signals do not decide.
- Signals do not size.
- Signals do not read account balances, positions, cash, or live orders.
- Signals do not place, cancel, or replace orders.
- Signals must not include `account_balance`, `available_cash`, `position_size`, `live_order_id`, or broker order payloads.
- `decision_gate` remains the first account-aware permission layer.
- `execution_planner` remains the first execution-intent layer.
- `executor` remains the only order-handling layer.
- `paper_advice_observation` is still downstream readout, not decision permission.
- Dashboard render remains read-only visibility and is not canonical signal ownership.

## 6. Gaps and blockers before new advice route

- `signal_state` still exists as a stale legacy surface and should remain retired from live gating.
- `signal_engine_state` is canonical, but Batch 3 must consume explicit freshness and coverage-gating semantics.
- `advice_state`, `ranking_state`, `selection_state`, and `paper_advice_observation` are downstream market-only interpretation layers; they must not be mistaken for primitive signals.
- `execution_zone_context` is valuable market context, but any action-sounding language around it must not bypass strategy interpretation or account-aware permission.
- `failed_breakout` and `market_damage` are not yet normalized as canonical runtime signal tables.
- No active runtime `market_trigger_engine` output table was identified.
- Breath/Fibo context remains important but is still research/diagnostic rather than canonical runtime signal truth.
- A+ / Martee / Oracle context remains external research and must not become hidden runtime signal truth without validation.
- `intrabar_lifecycle_context_v1` and `market_breath_context_bridge_v1` are useful read-only surfaces, but they are not canonical signal ownership.
- `position_lifecycle_research` is account-aware and must stay outside the market-only signal matrix.

## 7. Recommended Batch 3

Recommended next Codex batch:

- design `docs/research/synth_v215_advice_route_contract_v1.md`
- Breath + Fibo framework first
- Synth signals confirm
- strategy interprets
- no implementation yet unless the contract is reviewed first

Suggested contract direction:

- `framework_context`
- `synth_confirmation_context`
- `strategy_interpretation`
- `proposal_contract`
- explicit forbidden account/order payload fields
- explicit promotion path from proposal to `decision_gate`
