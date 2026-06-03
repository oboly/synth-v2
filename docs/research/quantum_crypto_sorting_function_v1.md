# Quantum Crypto Sorting Function V1

Status: research-only  
Runtime impact: none  
Decision/execution impact: none  
Live trading impact: none  

## Purpose

This note preserves the latest FFGRV research frame:

`FFGRV_2026_06_03_GOOGLE_QUANTUM_DISCLOSURE_CRYPTO_SORTING_FUNCTION`

Core idea:

Google's 2026 quantum disclosure does not mean "crypto breaks tomorrow."

It does mean 2026-2029 institutional diligence may increasingly ask:

which chains can credibly migrate to post-quantum cryptography?

The research implication is a new sorting function for post-cycle survivors, custody rails, tokenization infrastructure, and institutional review stacks.

## Boundary

Allowed downstream use:

- research-only labeling
- external narrative comparison
- institutional diligence review
- post-cycle survivor framework design
- public-claim verification queues
- watchlist review artifacts

Forbidden downstream use:

- selection engine ranking changes
- decision gate permission changes
- execution planner intent changes
- executor behavior changes
- broker writes
- order creation
- BUY_READY or tradeable labeling
- DB writes from this document alone

## Research framing

This is not an immediate exploit thesis.

Current interpretation:

- near-term market effect may be narrative and diligence-driven
- medium-term effect may be custody, treasury, tokenization, and settlement review pressure
- long-term effect may be survivor compression between assets with credible migration paths and assets with weak or non-credible upgrade paths

Research claim:

crypto quantum-readiness may become a sorting filter before it becomes an actual attack event.

## Labels

- `GOOGLE_QUANTUM_DISCLOSURE_2026`
- `QUANTUM_CRYPTO_SORTING_FUNCTION`
- `QUANTUM_2028_PROTOCOL_RISK`
- `POST_QUANTUM_MIGRATION_READINESS`
- `DOTCOM_STYLE_CRYPTO_SURVIVOR_COMPRESSION`
- `BTC_ETH_SOL_QUANTUM_UPGRADE_REQUIRED`
- `REGULATORY_TOKENIZATION_2026_2029_WINDOW`
- `POST_CYCLE_SURVIVOR_REVIEW`

## Basket model

### Bullrun basket

Use for rotation / momentum / narrative behavior.

Primary drivers:

- rotation
- momentum
- attention
- beta
- narrative heat

### Post-cycle survivor basket

Use for longer-duration institutional survivorship review.

Primary drivers:

- institutional rails
- real usage
- regulatory fit
- custody readiness
- credible post-quantum migration path

Important distinction:

an asset can score well in the bullrun basket and still score poorly in the post-cycle survivor basket.

## Field schema

Required research fields:

- `asset`
- `current_signature_scheme`
- `quantum_vulnerability_class`
- `pqc_migration_claimed`
- `pqc_migration_verified`
- `roadmap_url_or_source`
- `migration_timeline`
- `institutional_custody_readiness`
- `regulatory_fit`
- `post_cycle_survivor_score`
- `bullrun_only_score`
- `sunset_risk_score`
- `source_name`
- `source_date`
- `public_anchor_status`
- `synth_validation_status`

## Field semantics

- `current_signature_scheme`: current primary signing model as currently understood in research, not guaranteed canonical truth
- `quantum_vulnerability_class`: `LOWER_RELATIVE`, `MIGRATABLE`, `UPGRADE_REQUIRED`, `UNKNOWN`, or similar bounded research enum
- `pqc_migration_claimed`: whether a public claim or narrative says migration is possible
- `pqc_migration_verified`: whether Synth has verified a credible public technical path rather than a narrative-only claim
- `roadmap_url_or_source`: external note, public roadmap, foundation statement, or protocol discussion anchor
- `migration_timeline`: rough research bucket such as `UNKNOWN`, `POST_2028_POSSIBLE`, `ACTIVE_RESEARCH`, `NO_CLEAR_PATH`
- `institutional_custody_readiness`: research judgment about likely compatibility with custody / treasury / institutional review pipelines
- `regulatory_fit`: research judgment about likely fit for regulated tokenization / settlement / enterprise rails
- `post_cycle_survivor_score`: durability score for post-cycle institutional survival review
- `bullrun_only_score`: momentum/narrative suitability score that may not imply durability
- `sunset_risk_score`: risk that the asset underperforms in a post-cycle compression regime
- `public_anchor_status`: `PUBLIC_ANCHOR_PRESENT`, `PUBLIC_ANCHOR_PARTIAL`, `EXTERNAL_NOTE_ONLY`, or similar
- `synth_validation_status`: `UNVERIFIED`, `PARTIAL_REVIEW`, `PUBLIC_SOURCE_REVIEWED`, `RESEARCH_READY`

## Watch assets

Priority watch set:

- `BTC`
- `ETH`
- `SOL`
- `XRP`
- `XLM`
- `HBAR`
- `LINK`
- `CC`
- `ONDO`
- `QNT`
- `ALGO`
- `TAO`
- `QRL`

Interpretation note:

- `QRL` is a reference quantum-safe candidate set marker, not a Synth promotion decision
- `CC` remains a watch-symbol placeholder exactly as provided by the external note and should be normalized separately before any structured ingestion

## Initial watchlist framing

### Upgrade-required majors

- `BTC`
- `ETH`
- `SOL`

Research stance:

these assets may remain dominant near-term, but quantum-readiness review asks whether large ecosystems can coordinate credible signature migration without destroying custody, tooling, or social consensus.

### Institutional rails / tokenization / settlement review

- `XRP`
- `XLM`
- `HBAR`
- `QNT`
- `ONDO`
- `LINK`
- `ALGO`

Research stance:

these assets may face increased diligence if institutions want tokenization and settlement exposure with a believable post-quantum migration story.

### High-beta or uncertain-fit cohort

- `TAO`
- `CC`

Research stance:

these names may still matter in cycle rotation, but their post-cycle survivor case requires separate verification.

### Reference quantum-safe candidates

- `QRL`

Research stance:

reference candidates may benefit from thematic attention, but must not be upgraded into runtime truth or selection preference without actual validation.

## Initial scoring snapshot

- `quantum_sorting_function_relevance`: `8.5/10`
- `portfolio_reorientation_window`: `7.5/10`
- `immediate_crypto_attack_risk`: `2.5/10`
- `institutional_due_diligence_pressure`: `7/10`
- `post_2028_survivor_filter_importance`: `8/10`

## Working hypotheses

1. The first market effect is likely diligence pressure, not chain failure.
2. Institutional review from 2026-2029 may increasingly separate momentum assets from infrastructure-survivor assets.
3. Assets with vague "quantum-safe" marketing but no migration path may underperform once diligence moves from narrative to implementation.
4. Large incumbent chains may preserve dominance if they show credible migration governance, custody coordination, and ecosystem tooling support.
5. Post-cycle compression may resemble dotcom-style survivor filtering more than sudden universal crypto failure.

## Suggested research enums

### `quantum_vulnerability_class`

- `LOWER_RELATIVE`
- `MIGRATABLE`
- `UPGRADE_REQUIRED`
- `UNKNOWN`
- `NARRATIVE_ONLY`

### `public_anchor_status`

- `PUBLIC_ANCHOR_PRESENT`
- `PUBLIC_ANCHOR_PARTIAL`
- `EXTERNAL_NOTE_ONLY`

### `synth_validation_status`

- `UNVERIFIED`
- `PARTIAL_REVIEW`
- `PUBLIC_SOURCE_REVIEWED`
- `RESEARCH_READY`

## Example research row shape

```json
{
  "asset": "ALGO",
  "current_signature_scheme": "UNVERIFIED_IN_THIS_NOTE",
  "quantum_vulnerability_class": "MIGRATABLE",
  "pqc_migration_claimed": true,
  "pqc_migration_verified": false,
  "roadmap_url_or_source": "FFGRV_2026_06_03_GOOGLE_QUANTUM_DISCLOSURE_CRYPTO_SORTING_FUNCTION",
  "migration_timeline": "UNKNOWN",
  "institutional_custody_readiness": "MEDIUM",
  "regulatory_fit": "MEDIUM_HIGH",
  "post_cycle_survivor_score": null,
  "bullrun_only_score": null,
  "sunset_risk_score": null,
  "source_name": "FFGRV_2026_06_03_GOOGLE_QUANTUM_DISCLOSURE_CRYPTO_SORTING_FUNCTION",
  "source_date": "2026-06-03",
  "public_anchor_status": "EXTERNAL_NOTE_ONLY",
  "synth_validation_status": "UNVERIFIED"
}
```

## Validation queue

Questions to answer before any stronger Synth interpretation:

- Which chains have a concrete public migration path versus generic marketing?
- Which custody providers and institutional platforms explicitly discuss post-quantum migration compatibility?
- Which tokenization / settlement narratives survive regulatory and infrastructure review?
- Which assets are pure cycle beta versus credible post-cycle rails?
- Which "quantum-safe" claims are technical, social, or purely promotional?

## Architecture note

Correct path:

external note -> research document -> optional normalized research labels -> public-source validation -> comparative survivor review -> optional future research lane

Forbidden path:

external note -> asset promotion -> selection bias -> decision permission -> execution intent -> order behavior

This document is research-only and must not directly alter `selection_engine`, `decision_gate`, `execution_planner`, executor, broker state, or order flow.
