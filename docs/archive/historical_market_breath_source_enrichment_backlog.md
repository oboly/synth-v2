Status: Archived historical record
Active ownership: none
Current work: see canonical documentation / GitHub Issues
Archived by: docs/TODO cleanup Batch 4A

Implementation: `src/research/run_historical_market_breath_source_enrichment_v1.py`
Note: this file's own `Status: active` framing below is stale as of archiving; retained verbatim for historical record.

---

# TODO — Historical Market Breath Source Enrichment

## Status

- `active`
- upstream coverage gap confirmed
- downstream densifier confirmed not sufficient

## Source docs

- `docs/research/historical_market_breath_source_enrichment_v1.md`
- `docs/research/historical_market_breath_densifier_v1.md`
- `docs/research/historical_breath_regime_context_coverage_audit_v1.md`
- `docs/research/historical_breath_regime_context_backbone_v1.md`

## Current facts

- `market_breath_outcome_validation_v1` is the main historical per-symbol market-breath source currently feeding the context builder.
- It stores `market_breath_phase` and `market_breath_state`, but downstream canonical coverage is still weak.
- `breath_phase` is structurally derivable now, but too many rows are `NEUTRAL_TRANSITION`.
- `breath_alignment` is structurally derivable now, but too many rows are `market_breath_state=UNKNOWN`.
- `symbol_regime` can already be derived from `relative_strength_score` and `momentum_score`.
- `historical_market_breath_densifier_v1` produced `enriched_rows=0`, which confirms the primary gap is upstream source quality, not nearest-row matching.

## Priority tasks

### P0

- Implement `historical_market_breath_source_enrichment_v1`.
- Replay historical market-breath observations at denser, event-relevant timestamps.
- Persist explicit canonical fields alongside raw market-breath labels:
  - `breath_phase`
  - `breath_alignment`
  - `market_regime`
  - `btc_context`
  - `symbol_regime`
  - `relative_strength_bucket`
  - `momentum_bucket`
  - `confidence_bucket`

### P1

- Use lifecycle/reaction/profile event timestamps as the primary enrichment spine.
- Add optional anchor timestamps from `selection_state` and `signal_engine_state` only if they improve coverage without widening leakage risk.
- Emit file outputs only under:
  `data/research/historical_market_breath_source_enrichment_v1/`

### P2

- Rebuild `historical_breath_regime_context_builder_v1` on the enriched source.
- Rerun `historical_breath_regime_context_coverage_audit_v1`.
- Rerun `symbol_reaction_profile_by_context_v1`.
- Compare:
  - `breath_phase` unknown rate before/after
  - `breath_alignment` unknown rate before/after
  - `symbol_regime` unknown rate before/after
  - context-enriched profile rows before/after

## Open design constraints

- Keep point-in-time replay discipline.
- Do not write DB in V1.
- Do not promote context labels into selection/decision/execution.
- Do not backfill runtime latest-state tables.
- Prefer `UNKNOWN` over guessed enrichment.

## Recommended next batch

- `src/research/run_historical_market_breath_source_enrichment_v1.py`
- `docs/research/historical_market_breath_source_enrichment_v1.md`
- `tests/test_historical_market_breath_source_enrichment_v1.py`

## Boundary

- research-only
- file-output only
- no broker calls
- no broker writes
- no order submission
- no selection_engine changes
- no decision_gate changes
- no execution_planner changes
- no executor changes
