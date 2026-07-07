# External Research Overlay Contract v1

## Status

Design contract only. This document adds no runtime feed, parser, database table, selection behavior, decision permission, execution behavior, broker call, or order behavior.

## Purpose

External research can contain valuable structural maps, catalyst observations, money-flow snapshots, and narrative hypotheses. It must enter Synth as a traceable overlay, never as hidden market truth and never as a direct trade command.

This contract governs overlay material used by future `market_observer` and research-validation lanes.

## Hard Boundary

External research is not a substitute for:

- public market data
- internally rebuilt market structure
- canonical active-regime observations
- account-aware decision permission
- execution planning
- broker execution

Source confidence and Synth validation are separate fields.

A source may have a high user/source-confidence prior while its Synth validation status remains `UNVALIDATED`.

## Allowed Overlay Types

- `FLOW_SNAPSHOT`
- `CATALYST_EVENT`
- `EXTERNAL_LEVEL_MAP`
- `SUPPORT_ZONE`
- `RETEST_ZONE`
- `TARGET_ZONE`
- `INVALIDATION_ZONE`
- `TIMING_WINDOW`
- `NARRATIVE_THESIS`
- `MACRO_CONTEXT`

No type implies `BUY_READY`, `SELL_READY`, position sizing, allocation, stop placement, or order intent.

## Required Provenance

Each overlay record must carry:

- `overlay_id`
- `overlay_type`
- `source_name`
- `source_artifact_ref`
- `source_published_at_utc` or `UNKNOWN`
- `ingested_at_utc`
- `asset_or_scope`
- `source_venue` or `UNKNOWN`
- `source_pair` or `UNKNOWN`
- `source_timeframe` or `UNKNOWN`
- `source_quote_currency` or `UNKNOWN`
- `source_confidence_prior`
- `verification_status`
- `freshness_state`
- `expiry_policy`
- `evidence_note`

For price levels, additionally require:

- `level_role`
- `source_level_single` or `source_zone_low` + `source_zone_high`
- `runtime_quote_currency`
- conversion method and FX as-of when conversion is available
- `anchor_definition` or `UNKNOWN`
- map provenance: `EXTERNAL`, `INTERNAL_REBUILT`, or `UNVERIFIED`

## Verification States

- `SOURCE_RECORDED`
- `PARTIALLY_VERIFIED`
- `VERIFIED_FACTUAL_EVENT`
- `MEASURED_MARKET_CONFIRMATION_PENDING`
- `MEASURED_MARKET_CONFIRMED`
- `EXPIRED`
- `REJECTED`

A factual event may be verified while its forecast, map, or market implication remains unvalidated.

## Freshness and Expiry

An overlay must not be treated as current merely because it exists in storage.

Suggested policies:

- flow snapshot: expires after its declared observation window
- catalyst event: stays historical, but impact state expires unless refreshed
- intraday map: expires on invalidation, rebuild, or defined elapsed window
- medium/long-horizon map: remains visible with an explicit aging state
- narrative thesis: remains an archived hypothesis until independently refreshed

`UNKNOWN` freshness must lower confidence, not silently inherit fresh status from current market data.

## Fibo Map Separation

One screenshot zoom level does not create a second map. Conversely, visually similar maps must not be merged unless their anchors, pair, venue, timeframe, and construction are known to match.

Rules:

- preserve the original source levels unchanged
- store conversion separately from source currency
- keep external and internal-rebuilt maps distinct
- keep map anchors and construction method explicit or `UNKNOWN`
- treat retracement, reclaim, extension, and ABC-wave annotations as source claims until independently reconstructed or outcome-validated

## Observer Usage

A future market observer may attach overlay state such as:

- `FLOW_SUPPORTIVE`
- `CATALYST_ACTIVE`
- `EXTERNAL_MAP_AVAILABLE`
- `EXTERNAL_MAP_AGING`
- `EXTERNAL_MAP_INVALIDATED`
- `OVERLAY_CONFLICT`
- `NO_CURRENT_OVERLAY`

It may not emit trade commands from an overlay.

Measured market context must remain separately inspectable so the UI can show:

```text
external map says: reclaim zone
measured market says: no reclaim confirmation yet
```

This disagreement is useful evidence, not a reason to overwrite either source.

## Outcome Validation

External overlays are testable research inputs. Validation must record:

- touch/reach time
- reaction after touch
- maximum adverse excursion before reaction
- target/invalidation order
- time-to-target
- return and MFE/MAE at horizon-aligned windows
- measured confirmation present or absent
- overlapping-event handling

Broad, long-horizon zones must not be marked failed merely because a short validation window elapsed.

## Forbidden Shortcuts

```text
external fib target       -> sell order
external support zone     -> buy order
flow snapshot             -> automatic selection bonus
narrative confidence      -> decision_gate permission
source confidence prior   -> Synth validation status
external overlay          -> overwrite canonical regime
```

## Related Documents

- `docs/architecture/market_observer_contract_v1.md`
- `docs/todo/external_research_ingestion.md`
- `docs/research/canonical_regime_context_source_v1.md`
- `docs/research/shadow_heartbeat_outcome_validation_v1.md`
