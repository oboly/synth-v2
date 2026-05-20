# TODO — Strategy Candidates

## Status

Open design questions. No implementation yet.

## Source

```text
docs/research/strategy_candidate_horizon_buckets_v1.md
```

## Core rule

```text
Asset != strategy.
```

Correct selection unit:

```text
candidate = (
    asset,
    strategy_family,
    horizon_bucket,
    setup_context,
    validation_state,
)
```

## P2 — Horizon bucket design review

Status: open.

Tasks:

- Decide whether selection_engine should rank per horizon bucket independently.
- Specify how same-asset candidates conflict or reinforce each other.
- Specify how decision_gate resolves exposure when multiple active candidates target the same asset.
- Define graduation rules from `BREATH_CURVE_RESEARCH` to runtime-eligible candidate buckets only after validation.
- Preserve the rule: asset is not a strategy.

## P1 — Current strategy audit follow-up

Status: open.

Source:

```text
docs/research/current_strategy_audit_v1.md
```

Tasks:

- Start with same-window buy-and-hold baselines before evaluating strategy labels.
- Validate `selection_state` forward returns from replay tables, not operational table backfills.
- Validate `trade_setup_filter_v1` PASS/FAIL/reason buckets only from point-in-time replay rows.
- Keep `paper_advice_policy_v1` validation blocked until A+ Table 1 and zone context can be replayed point-in-time.
- Treat rotation preview as account-aware retrospective review only, not a selection strategy.

Boundary:

```text
Backtest outputs stay in synth_bt or data/research.
No forward-return fields in runtime tables.
No decision_gate, execution_planner, executor, broker, or order changes.
```

## Boundary

```text
selection_engine may rank market-only candidates.
decision_gate resolves account-aware exposure/conflicts/sizing/permission.
execution_planner/executor do not contain candidate logic.
```

No direct buy/sell/order logic belongs here.

## P2 — Swing pullback 168h research lead

Status: research lead / not paper-ready.

Source:

```text
docs/research/strategy_candidate_registry_v1.md
```

Context:

The 72h/168h swing pullback variants produced strong per-symbol returns but failed global promotion due to:

```text
MIN_WINRATE_NOT_MET
MIN_POSITIVE_MONTH_RATIO_NOT_MET
WORST_MONTH_AVG_LOSS_EXCEEDED
```

Likely missing components:

- exit algorithm
- regime filter
- symbol-specific promotion layer
- parent-state logic review

Tasks:

- Keep the 168h branch as a research lead, not a live or paper candidate.
- Revisit only through explicit validation of exit logic, regime filtering, and symbol-specific promotion rules.
- Do not stage arena-v2 candidates through the older `swing_pullback_recovery_v5` contract.

## P3 — Legacy Synth v1 regime/strategy prior review

Status: parked research prior.

Source:

```text
docs/legacy_synth_v1_regime_strategy_priors.md
```

Tasks:

- Define a v2 `regime_selector` contract.
- Define a v2 `strategy_selector` contract.
- Build a research export with `asset_id`, `symbol`, `interval_code`, `asof_ts_utc`, `regime_code`, `candidate_strategy_family`, and `source_prior`.
- Validate old priors on current v2 feature/signal data.
- Only then consider selection_engine integration.

Boundary:

```text
Legacy priors are microscope data, not steering input.
Do not implement direct old Synth v1 strategy routing in live code.
No selection/advice/decision/execution changes without a separate reviewed task.
```


####################################
# External Research Ingestion TODO #
####################################

## Goal

Extract structured zones, targets, thresholds, timing windows, and asset labels from external PRO/RV/Martee/A+/membership notes.

This is research-only input. It must not create buy/sell signals, selection_engine modifiers, decision_gate permissions, execution_planner behavior, or order logic.

## Priority

High.

## Why

External notes contain concrete levels and timing windows that should be machine-readable for later validation.

Examples:
- BTC reclaim / resistance / B-wave thresholds
- altcoin fib targets
- Martee Oracle follow-up zones
- PRO buy zones / sell zones / shoulder lines
- RV chart trajectory targets
- commodity macro zones
- regulatory/event timing windows

## Proposed outputs

### Docs

- docs/research/external_pro_narrative_registry.md
- docs/research/external_research_zone_extraction_v1.md
- docs/research/external_algorithmic_zone_forecast_v1.md
- docs/research/external_asset_targets_registry_v1.md

### Data

- data/research/external_pro_registry/
- data/research/external_asset_targets/
- data/research/external_oracle_zones/
- data/research/external_watch_windows/

## Proposed structured fields

asset:
  Symbol or macro asset, e.g. BTC, LINK, HYPE, ENJ, DXY, gold, crude.

source_name:
  FFGRV, Martee, A+, Crypto Masterminds, RV session, etc.

source_date:
  Session or publication date.

source_type:
  PRO_NOTE / RV_NOTE / ORACLE_ZONE / TECHNICAL_ANALYSIS / MACRO_NOTE.

level_type:
  BUY_ZONE / SUPPORT / RESISTANCE / BREAKOUT_TRIGGER / INVALIDATION /
  TARGET / EXIT_ZONE / SHOULDER_LINE / FIB_TARGET / WATCH_LEVEL /
  MACRO_THRESHOLD / TIME_WINDOW.

zone_low:
  Decimal where applicable.

zone_high:
  Decimal where applicable.

level_single:
  Decimal where applicable.

quote_currency:
  USD / EUR / INDEX_POINTS / PERCENT / UNKNOWN.

time_window_start:
  Optional.

time_window_end:
  Optional.

horizon:
  SHORT_TERM / MEDIUM_TERM / LONG_TERM / MULTI_YEAR / EVENT_WINDOW.

confidence_source:
  HIGH / MEDIUM / LOW according to source confidence.

synth_validation_status:
  UNVALIDATED / PUBLIC_ANCHORED / HIT_REACTED / HIT_FAILED / EXPIRED.

actionability:
  WATCH_ONLY.

notes:
  Short source-specific note.

architecture_boundary:
  Research-only. No runtime trading logic.

## Validation metrics

For every extracted zone/target:

- was_zone_reached
- first_touch_ts
- max_reaction_after_touch
- direction_after_touch
- volume_confirmation
- relative_strength_confirmation
- invalidated_before_target
- time_to_target
- false_positive_notes

## Implementation phases

### Phase 1 — Manual extraction

Extract all zones/targets from current external PRO bundle into markdown and/or JSONL.

### Phase 2 — Schema proposal

Create a simple JSONL contract for external targets.

### Phase 3 — Loader preview

Build read-only parser/loader that validates the JSONL shape.
No DB writes in v1 unless explicitly approved.

### Phase 4 — DB staging table

Optional later:
external_research_target_observation

DB writes only after schema review.

### Phase 5 — Validation report

Compare historical/current price movement against extracted zones.

## Hard boundaries

- Do not add to selection_engine.
- Do not add to decision_gate.
- Do not add to execution_planner.
- Do not add to executor.
- Do not create orders.
- No broker writes.
- No live trading.
