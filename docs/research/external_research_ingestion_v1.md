# External Research Ingestion

Status: Permanent research/ETL data contract
Canonical location: `docs/research/external_research_ingestion_v1.md`
Scope: research-only
Runtime impact: none
Architecture boundary: this ingestion contract grants no authority to `selection_engine`, `decision_gate`, `execution_planner`, executor/agents, or broker behavior. It defines how external PRO/RV/Martee/A+ research notes are converted into structured, testable research inputs.

## Purpose

Convert external PRO/RV/Martee/A+ research into structured, testable research inputs.

External notes often contain:

- support zones
- shoulder lines
- retest zones
- reset zones
- target zones
- TP review zones
- invalidation zones
- timing windows
- short signals
- long signals
- macro stress scores

These must be extracted separately from narrative summaries so Synth can later validate them.

## Hard boundaries

- Do not change `selection_engine` behavior.
- Do not change `decision_gate`.
- Do not change `execution_planner`.
- Do not change `executor`.
- Do not enable broker writes.
- Do not create orders.
- Do not mark external research assets `BUY_READY`.
- Do not mark an asset tradeable without universe policy review.
- Keep all outputs research-only until validated.

## Core strategy idea: external_support_shoulder_reaction_strategy_v1

Martee/PRO zones are structural map levels, not direct trade commands.

Synth should wait for market behavior around those levels:

- support touch
- reaction
- close above/below
- volume confirmation
- higher-low confirmation
- relative strength
- BTC/macro not damaging

Allowed research outputs:

- NO_ACTION
- WAIT_FOR_SUPPORT_TOUCH
- SUPPORT_REACTION_CANDIDATE
- SHOULDER_BREAKOUT_CANDIDATE
- SHOULDER_RETEST_ENTRY_CANDIDATE
- TARGET_APPROACHING
- TP_REVIEW
- INVALIDATED

## Martee signal horizon model

Martee is a high-confidence external technical/oracle source, but signals have different horizons and precision.

### signal_kind

- SHORT_SIGNAL
- LONG_SIGNAL
- TARGET_ZONE
- RESET_ZONE
- SUPPORT_ZONE
- SHOULDER_LINE
- CONFIRMATION_TRIGGER
- INVALIDATION_ZONE
- TP_REVIEW_ZONE
- MTF_CONFIRMATION

### signal_horizon

- INTRADAY
- SHORT_TERM
- MEDIUM_TERM
- LONG_TERM
- MULTI_MONTH

### zone_precision

- NARROW
- MEDIUM
- WIDE

### source_confidence_prior

Default for Martee:

- VERY_HIGH

Important rule:

Broad long-term zones must not be scored as failed just because they are not hit quickly. Validation must respect `signal_horizon` and expected validation window.

## Extraction schema

Required fields:

- asset
- source_name
- source_date
- source_type
- level_role
- signal_kind
- signal_horizon
- zone_precision
- source_confidence_prior
- source_quote_currency
- source_level_single
- source_zone_low
- source_zone_high
- runtime_quote_currency
- runtime_level_single
- runtime_zone_low
- runtime_zone_high
- fx_pair
- fx_rate
- fx_rate_asof_ts
- fx_conversion_method
- reaction_required
- breakout_required
- retest_required
- confirmation_type
- target_usage
- synth_validation_status
- actionability
- notes

## level_role values

- SUPPORT_ZONE
- SHOULDER_LINE
- SHOULDER_ZONE
- RETEST_ZONE
- RESET_ZONE
- TARGET_ZONE
- TP_REVIEW_ZONE
- INVALIDATION_ZONE

## confirmation_type values

- TOUCH_REACTION
- CLOSE_ABOVE
- CLOSE_BELOW
- VOLUME_BREAK
- HIGHER_LOW
- MTF_CONFIRMATION

## target_usage values

- ENTRY_WATCH
- RETEST_WATCH
- TP_REVIEW
- REGIME_CONTEXT
- INVALIDATION_ONLY
- WAIT_FOR_REACTION

## Currency handling

Most external PRO/Martee/RV targets are quoted in USD.

Bitvavo/runtime prices are often EUR.

Rules:

- Never overwrite source USD levels.
- Store EUR conversion separately.
- Formula: EUR = USD / EURUSD.
- Historical validation should use FX rate at `source_date` or validation asof.
- Live validation should use latest available FX asof.
- If FX is unavailable, keep source USD only and mark conversion missing.

## Validation metrics

For every extracted level or zone:

- was_zone_reached
- first_touch_ts
- reaction_pct_after_touch
- max_drawdown_before_reaction
- direction_after_touch
- volume_confirmation
- relative_strength_confirmation
- invalidated_before_target
- time_to_target
- false_positive_notes

## Open research questions

- Do Martee support zones work better than targets?
- Do shoulder retests work better than breakout chases?
- Do short signals validate faster than long signals?
- Does weekly confirmation materially improve outcomes?
- Which asset classes respond best: crypto, commodities, indices, FX?

## Related documents

- `docs/architecture/external_research_overlay_contract_v1.md`
- `docs/research/external_elliott_wave_claim_validation_v1.md`
- `docs/research/external_forecast_event_registry_v1.md`
- `docs/archive/external_research_ingestion_historical_examples_v1.md`
