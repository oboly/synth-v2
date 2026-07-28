# Market Intelligence TODOs

## Scope

Research-only, market-only, account-agnostic observation and classification lanes, including sector rotation, macro regime, narrative, catalyst, breadth, flow, scanner research, cross-asset rotation, and composite market context.

## Boundary

This folder owns no account permissions, execution intent, order handling, or broker access.

## Index rule

This file is navigation only. Status, priority, and cross-lane execution order remain owned exclusively by `docs/todo/README.md`.

## Canonical files

- `sector_rotation_master_plan_v1.md`
- `sector_rotation_engine_v1.md`
- `macro_regime_engine_v1.md`
- `composite_market_regime_v1.md`
- `narrative_engine_v1.md`
- `catalyst_engine_v1.md`
- `momentum_flow_scanner_research_v1.md`
- `ffg_rotation_classification_v1.md`
- `cross_asset_rotation_research_v1.md`

## Completed dependency

- `../completed/sector_taxonomy_database_seed_v1.md` — accepted Phase A taxonomy seed and operational acceptance record.

## Split ownership

The former umbrella TODOs remain historical specifications while active ownership is separated:

```text
momentum_flow_scanner_matrix_v1.md
  market research       -> market_intelligence/momentum_flow_scanner_research_v1.md
  Profit Plan display   -> reporting/profit_plan_opportunity_presentation_v1.md

ffg_curated_rotation_radar_v1.md
  source membership     -> external_research/ffg_universe_metadata_v1.md
  market classification -> market_intelligence/ffg_rotation_classification_v1.md
  account/UI overlay    -> reporting/ffg_rotation_radar_presentation_v1.md

cross_asset_metals_miners_food_rotation_v1.md
  public data + identity -> external_research/cross_asset_public_data_and_instrument_registry_v1.md
  market research        -> market_intelligence/cross_asset_rotation_research_v1.md
```

The umbrella files own no account permission, execution intent, order handling, or broker access.

## Compatibility pointers

Former top-level paths for moved, completed, or split TODOs may remain as non-owning migration or umbrella references. They prevent broken links while exact references are retired and own no cross-lane status or priority.