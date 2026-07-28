# FFG Universe Metadata v1

## Status

Open P3 external-research metadata lane.

## Ownership

This file owns source provenance and identity-resolved membership for the externally curated FFG research universe.

Owned here:

- source identifier and source version;
- observed and imported timestamps;
- canonical symbol and market identity resolution;
- active, removed, unresolved, and unavailable membership states;
- source confidence and reviewer notes;
- dynamic counts derived from current records.

Not owned here:

- market scoring or rotation classification;
- account ownership or exposure;
- dashboard behavior;
- selection, permission, planning, execution, broker, or order behavior.

## Boundary

FFG membership is external research metadata only. It may label or filter a research view, but it is not evidence that an asset will succeed and cannot grant market eligibility or trading authority.

Externally supplied flow or conviction claims must remain separately typed with provenance and confidence. They cannot be written into Synth-native measured-flow or canonical market-state fields.

## Related owners

- Market classification: `../market_intelligence/ffg_rotation_classification_v1.md`
- Reporting/account overlay: `../reporting/ffg_rotation_radar_presentation_v1.md`
- Historical umbrella specification: `../ffg_curated_rotation_radar_v1.md`
- Canonical research-universe contract: `../../research/ffg_research_universe_v1.md`

## Definition of done

- membership is deterministic, versioned, timestamped, and identity-resolved;
- unresolved identities fail closed;
- counts are dynamic, not hardcoded;
- external claims remain provenance-bearing metadata;
- no canonical market, account, or execution authority is introduced.
