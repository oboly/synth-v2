# External Elliott Wave Claim Validation

Status: Permanent research design
Canonical location: `docs/research/external_elliott_wave_claim_validation_v1.md`
Scope: research-only, market-only
Runtime impact: none
Architecture boundary: this design grants no authority to `selection_engine`, `decision_gate`, `execution_planner`, executor/agents, or broker behavior. External Elliott Wave claims are structural hypotheses, not signals.

## Purpose

Investigate whether external Elliott Wave claims from PRO/Martee/media notes can be converted into structured, testable research inputs.

The goal is not to trust Elliott labels blindly, but to test whether externally supplied wave structures improve:

- target-zone quality
- pullback/retest timing
- trend-continuation recognition
- invalidation detection
- TP review timing

## Source context

External Elliott Wave claims originate from PRO/Martee notes and media forecasts (for example, article-level Elliott-style target commentary). PRO notes already carry Elliott/Fib structures for assets such as ENJ, VET, KITE, SOL, SUI, ADA, LINK, HYPE, DOGE, and BTC. These claims are archived per-asset as they are captured; see `docs/archive/external_research_ingestion_historical_examples_v1.md` for dated examples.

## Research lane

`external_elliott_wave_claim_validation_v1`

## Extracted fields

Required fields:

- asset
- source_name
- source_date
- source_type
- timeframe
- wave_structure_type
- wave_label
- current_wave_state
- correction_type
- impulse_start_price
- impulse_end_price
- correction_low
- shoulder_line
- confirmation_level
- invalidation_level
- target_1
- target_2
- target_zone_low
- target_zone_high
- fib_level
- source_quote_currency
- runtime_quote_currency
- fx_conversion_required
- notes

## Allowed wave_structure_type

- IMPULSE_12345
- ABC_CORRECTION
- WAVE_1_SETUP
- WAVE_2_PULLBACK
- WAVE_3_EXTENSION
- WAVE_4_CONSOLIDATION
- WAVE_5_COMPLETION
- GRAND_FIB_EXTENSION
- SHOULDER_LINE_RECLAIM
- UNKNOWN_EXTERNAL_LABEL

## Validation metrics

For each external Elliott claim:

- was_confirmation_level_reclaimed
- was_invalidation_hit_first
- did_target_1_hit
- did_target_2_hit
- max_drawdown_before_target
- time_to_target
- reaction_at_shoulder_line
- reaction_at_fib_target
- false_breakout_detected
- wave_label_quality_score
- manual_review_notes

## Important rules

- Do not treat external Elliott labels as truth.
- Treat them as external structural hypotheses.
- Validate against real OHLCV pivots.
- Do not promote to `selection_engine` until measured.
- Do not create buy/sell signals.
- Do not bypass `decision_gate`.
- Do not alter `execution_planner`.
- Do not create orders.

## Key research questions

- Are PRO Elliott shoulder lines useful confirmation levels?
- Are ABC correction zones useful entry/retest zones?
- Do 1.618 / 2.618 / 4.764 targets outperform random Fib extensions?
- Do external Elliott labels work better on majors or small alts?
- Are Elliott claims mainly useful for TP zones rather than entries?
- Does volume confirmation materially improve Elliott target reliability?
- Do wide Elliott macro targets need separate long-horizon scoring?

## Output targets

- Research report: this document.
- Runner (optional, later): `src/research/run_external_elliott_wave_claim_validation_v1.py`
- Data target (later): `data/research/external_elliott_wave_claims/`

## Related documents

- `docs/research/external_research_ingestion_v1.md`
- `docs/archive/external_research_ingestion_historical_examples_v1.md`
