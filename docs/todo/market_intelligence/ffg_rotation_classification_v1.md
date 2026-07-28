# FFG Rotation Classification v1

## Status

Open P3 research / read-only.

## Ownership

This file is the canonical owner for market-only classification of assets inside the externally curated FFG research universe.

Owned here:

- identity-resolved FFG universe membership as external research metadata;
- market-only rotation classifications such as `EARLY_ROTATION`, `CONFIRMED_ROTATION`, `LAGGARD_IMPROVING`, `LAGGARD_DORMANT`, `RUNNER_EXTENDED`, `DISTRIBUTION_RISK`, `STRUCTURALLY_WEAK`, and `DATA_UNAVAILABLE`;
- normalized flow, persistence, acceleration, RSI/MFI, volume, relative-strength, structure, liquidity, target-room, timestamp, confidence, and reason-code evidence;
- deterministic versioned classification and replay against matched controls.

Not owned here:

- account ownership, quantity, value, portfolio weight, or unrealized return;
- dashboard grouping, attention strips, filters, row layout, or links;
- Profit Plan map computation;
- permission, sizing, execution intent, order handling, or broker access.

## Source boundary

FFG membership is a universe label, not positive score evidence. Copied or methodologically unclear FFG flow values remain external low-confidence metadata and must never be written into Synth-native measured-flow fields.

Distance below ATH is context only. It cannot produce an opportunity, rotation, or action state without independent current market evidence.

## Canonical handoff

```text
external FFG membership metadata
+ canonical market evidence
-> market-only rotation classification
-> reporting/account overlay consumes read-only
```

## Related owners

- Historical umbrella specification: `../ffg_curated_rotation_radar_v1.md`
- External membership/provenance owner: `../external_research/ffg_universe_metadata_v1.md`
- Reporting/account overlay owner: `../reporting/ffg_rotation_radar_presentation_v1.md`
- Scanner research owner: `momentum_flow_scanner_research_v1.md`
- Board priority and execution order: `../README.md`

## Definition of done

- membership and market evidence are separately typed;
- classifications are deterministic, versioned, point-in-time, and replayable;
- matched non-FFG controls are included;
- account fields never enter market scoring or classification;
- no selection, permission, planning, execution, broker, or order authority is introduced.
