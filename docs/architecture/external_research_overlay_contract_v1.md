# External Research Overlay Contract v1

## Status

Design contract only. No runtime feed, parser, database table, selection behavior, decision permission, execution behavior, broker call, or order behavior is introduced here.

## Purpose

External research may contain structural maps, catalyst observations, money-flow snapshots, and narrative hypotheses. It enters Synth as a traceable overlay, never as hidden market truth or a direct trade command.

## Hard Boundary

External research is not a substitute for public market data, internally rebuilt structure, canonical regime observations, account-aware permission, execution planning, or broker execution.

`source_confidence_prior` and `synth_validation_status` are distinct.

## Allowed Overlay Types

```text
FLOW_SNAPSHOT
CATALYST_EVENT
EXTERNAL_LEVEL_MAP
SUPPORT_ZONE
RETEST_ZONE
TARGET_ZONE
INVALIDATION_ZONE
TIMING_WINDOW
NARRATIVE_THESIS
MACRO_CONTEXT
```

No type implies `BUY_READY`, `SELL_READY`, sizing, allocation, stop placement, or order intent.

## Required Provenance

Each record requires:

- `overlay_id`, `overlay_type`, `asset_or_scope`
- `source_name`, `source_artifact_ref`, `ingested_at_utc`
- `source_published_at_utc` or `UNKNOWN`
- `source_event_at_utc` or `UNKNOWN`
- `market_observation_asof_utc` or `UNKNOWN`
- `timestamp_quality`
- `source_venue`, `source_pair`, `source_timeframe`, `source_quote_currency` or `UNKNOWN`
- `source_confidence_prior`, `verification_status`, `synth_validation_status`
- `freshness_state`, `expiry_policy`, `evidence_note`

Price-level records also require `level_role`, source level/zone, runtime currency, conversion method and FX as-of when available, `anchor_definition` or `UNKNOWN`, and map provenance: `EXTERNAL`, `INTERNAL_REBUILT`, or `UNVERIFIED`.

## Timestamp Semantics

One artifact can have three different relevant times:

- `source_published_at_utc`: when the article/note became available.
- `source_event_at_utc`: when its underlying interview, meeting, video, or research call happened.
- `market_observation_asof_utc`: when its price, signal, chart, flow, or factual market claim was observed.

For price, technical-signal, map, and flow currentness, freshness is derived from `market_observation_asof_utc`, **not** publication time.

### `timestamp_quality`

```text
EXACT
INFERRED
PARTIAL
CONFLICTING
UNKNOWN
```

A newer article must never refresh an older market snapshot. A source can be new as an artifact while its embedded technical claim is stale.

When an article contains claims with different market as-of times, create separate overlay assertions/subrecords. Do not store a historical chart reading and a future timing thesis as one current-market record.

Example:

```text
source_published_at_utc: 2026-07-07
source_event_at_utc: 2026-06-06
market_observation_asof_utc: 2026-06-06
```

The price/signal claim ages from June 6; a July/August timing-window hypothesis receives its own explicit expiry policy.

## Verification and Freshness Are Separate

### `verification_status`

Verification answers whether source facts were checked. It does not change merely because an overlay becomes old.

```text
SOURCE_RECORDED
PARTIALLY_VERIFIED
VERIFIED_FACTUAL_EVENT
REJECTED
```

### `synth_validation_status`

Synth validation answers whether the asserted market implication has been measured.

```text
UNVALIDATED
MEASURED_MARKET_CONFIRMATION_PENDING
MEASURED_MARKET_CONFIRMED
MEASURED_MARKET_REJECTED
```

### `freshness_state`

Freshness answers whether an overlay is current enough to influence present observation.

```text
FRESH
AGING
STALE
EXPIRED
UNKNOWN
```

Expiry never erases verification or validation history. A UI must represent `VERIFIED_FACTUAL_EVENT + STALE` and `MEASURED_MARKET_CONFIRMED + EXPIRED`.

## Freshness and Expiry Policy

- flow snapshot: expires after its declared observation window, measured from market as-of
- catalyst: remains historically verified; its impact context ages/expires unless refreshed
- intraday map: expires on invalidation, rebuild, or declared elapsed window, measured from market as-of
- medium/long-horizon map: remains visible with explicit aging
- narrative thesis: remains archived until independently refreshed
- timing-window hypothesis: exposes its source/event time and an explicit expiry/review window

`UNKNOWN` freshness lowers confidence and must not inherit freshness from current market data or a newer publication timestamp.

## Fibo Map Separation

A screenshot zoom level does not create a new map. Similar maps must not be merged unless anchors, pair, venue, timeframe, and construction match.

Preserve source levels unchanged; store FX conversion separately; keep external and internal maps distinct; record anchors/construction or `UNKNOWN`; treat ABC, reclaim, retracement, and extension annotations as source claims until independently reconstructed or outcome-validated.

## Observer Usage

A future observer may expose:

```text
FLOW_SUPPORTIVE
CATALYST_ACTIVE
EXTERNAL_MAP_AVAILABLE
EXTERNAL_MAP_AGING
EXTERNAL_MAP_INVALIDATED
OVERLAY_CONFLICT
NO_CURRENT_OVERLAY
```

It may not emit trade commands. Measured context and overlay context remain separately inspectable.

## Outcome Validation

Validation records touch/reach time, reaction, maximum adverse excursion, target/invalidation order, time-to-target, horizon-aligned return/MFE/MAE, measured confirmation, and overlap handling.

Use `market_observation_asof_utc` as the outcome anchor unless a more specific event timestamp is recorded.

## Forbidden Shortcuts

```text
publication timestamp    -> freshness override for older market observation
external fib target       -> sell order
external support zone     -> buy order
flow snapshot             -> automatic selection bonus
narrative confidence      -> decision_gate permission
source confidence prior   -> Synth validation status
external overlay          -> overwrite canonical regime
```

## Related Documents

- `docs/architecture/market_observer_contract_v1.md`
- `docs/research/external_research_ingestion_v1.md`
- `docs/research/external_elliott_wave_claim_validation_v1.md`
- `docs/research/canonical_regime_context_source_v1.md`
- `docs/research/shadow_heartbeat_outcome_validation_v1.md`
