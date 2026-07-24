# Sector Taxonomy Quality Refresh v1.1

## Status

**open / approved planning lane** — Phase A.1 correction and quality audit.

This lane must complete before Phase B sector-rotation snapshots are accepted as
operationally trustworthy. Phase B implementation may continue in repository
scope, but no Phase B database acceptance should treat the current taxonomy as
final while this lane is open.

## Recommended implementation agent

```text
Tool: Claude Code
Model: Claude Opus 4.8
Reasoning: High
```

## Objective

Improve the existing deterministic sector taxonomy without introducing a new
parallel taxonomy, changing architecture boundaries, or forcing uncertain
assets into invented categories.

The refresh must:

1. correct verified misclassifications;
2. review high-value `UNCLASSIFIED` assets;
3. preserve explicit uncertainty where evidence is insufficient;
4. improve primary-sector and secondary-cluster quality;
5. preserve versioned history and importer idempotency;
6. produce a reviewable evidence report for every changed asset;
7. keep sector metadata market-only and account-agnostic.

## Current baseline

Phase A v1 is accepted and operationally activated. The canonical baseline is:

```text
canonical asset identities = 448
reviewed named sectors      = 103
explicit UNCLASSIFIED       = 345
active memberships          = 473
sector definitions          = 29
liquidity definitions       = 7
```

`UNCLASSIFIED` is a valid fail-closed state. The goal is not to maximize the
number of labels. The goal is to remove avoidable errors and improve the
classification quality of assets that materially contribute to Synth research.

## Mandatory first correction: HOT

Current seed state:

```text
HOT
primary_sector = STORAGE
liquidity_market_cap_code = MID_ALT
secondary_clusters = []
```

Expected reviewed correction:

```text
HOT
primary_sector = CLOUD_INFRA
liquidity_market_cap_code = MID_ALT
secondary_clusters:
- DEPIN
```

Rationale to verify against primary project sources before changing the seed:
Holo is primarily distributed hosting/cloud infrastructure. It must not be
classified as decentralized storage merely because storage may be part of the
hosting stack.

Do not add `PAYMENTS` solely because HoloFuel exists. A secondary membership
requires evidence that payments are a material protocol role rather than only a
settlement mechanism inside the hosting economy.

If primary-source review contradicts the expected correction, stop and document
the evidence rather than applying it blindly.

## Review scope and order

### Pass 1 — canonical high-value universe

Review every asset in:

```text
FFG_RESEARCH_UNIVERSE_V1
```

Also review every enabled asset that already has a named primary sector. This
catches incorrect labels that would otherwise contaminate sector snapshots.

### Pass 2 — obvious `UNCLASSIFIED` candidates

Review enabled `UNCLASSIFIED` assets where primary-source evidence supports a
stable canonical category with high confidence.

Prioritize by market-only criteria:

```text
liquidity
market coverage
research-universe membership
current Synth data coverage
sector relevance
```

Do not use account ownership, position size, PnL, or trade history as taxonomy
inputs.

### Pass 3 — ambiguity report

Retain `UNCLASSIFIED` where:

- the project spans multiple categories with no defensible primary role;
- the existing taxonomy lacks a precise category;
- the symbol or project identity is ambiguous;
- primary-source evidence is insufficient;
- a classification would be narrative speculation.

Record the exact reason and the missing taxonomy capability.

## Required category audit

Review at minimum:

```text
STORAGE vs CLOUD_INFRA
AI_COMPUTE vs DECENTRALIZED_AI
DEPIN as primary vs secondary
L1 vs L2 vs MODULAR_BLOCKCHAIN
RWA vs RWA_INFRA
DEX vs PERP_DEX
DATA_INFRA vs ORACLE vs CROSS_CHAIN
PAYMENTS vs settlement-only utility
ETH_ECOSYSTEM as secondary only where appropriate
```

Explicitly re-evaluate:

```text
HOT
ADA
BTC
DEEP
```

Do not preserve a known weak classification merely because it was accepted in
Phase A v1. Phase A acceptance proves deterministic import behavior, not that
every narrative classification is permanently correct.

## Canonical ownership and architecture

Use the existing ownership model exactly:

```text
asset.sector
= canonical primary narrative sector for local assets

asset_cluster_membership
= primary and secondary narrative memberships with validity history

asset_taxonomy_profile
= canonical identity, universe scope, static liquidity/market-cap metadata,
  provenance, and review notes

asset_profile_snapshot.sector_group_code
= empirical point-in-time co-movement cluster only
= never populated by this lane
```

This lane belongs to:

```text
research/data metadata
```

It must not change:

```text
selection_engine
decision_gate
execution_planner
executor / agents
reporting behavior
broker access
order behavior
runtime timers
Phase B score logic
```

## Evidence requirements

Every changed asset must have an evidence row in:

```text
docs/research/sector_taxonomy_quality_refresh_v1_1.md
```

Required fields:

```text
asset_symbol
old_primary_sector
new_primary_sector
old_secondary_clusters
new_secondary_clusters
liquidity_market_cap_change
primary_sources
classification_rationale
confidence
ambiguity_notes
review_decision
```

Allowed review decisions:

```text
CHANGE_PRIMARY
CHANGE_SECONDARY
CHANGE_PRIMARY_AND_SECONDARY
KEEP_EXISTING
KEEP_UNCLASSIFIED
ADD_TAXONOMY_GAP
```

Use primary project documentation, official technical documentation, official
roadmaps, and official repositories where available. Market-cap/liquidity tiers
may use deterministic market-data evidence. Do not use anonymous social-media
claims, price predictions, or model-only recollection as classification proof.

## Versioning rules

Do not silently mutate the meaning of the accepted v1 seed without explicit
versioning.

Preferred refresh identity:

```text
schema_version = sector_taxonomy_seed_v1_1
valid_from_ts_utc = explicit activation timestamp
```

Preserve existing importer behavior:

- changed active memberships expire at the new validity timestamp;
- replacements start at the same timestamp;
- unchanged memberships retain their original validity start;
- invalid or backward validity intervals fail closed;
- one active primary membership per canonical asset;
- one active membership per asset/sector pair;
- no invented assets or venue mappings;
- no destructive `UNCLASSIFIED` downgrade of non-empty `asset.sector`;
- `asset.asset_class` remains read-only.

If the current importer assumes exactly `sector_taxonomy_seed_v1`, update the
validation contract explicitly and add tests. Do not weaken schema validation.

## Repository implementation scope

Expected files:

```text
data/research/sector_taxonomy_seed_v1.json
src/research/run_sector_taxonomy_import_v1.py
src/research/sector_rotation_data_v1.py
scripts/audit_sector_taxonomy_quality_v1.py
tests/test_sector_taxonomy_import_v1.py
tests/test_sector_rotation_engine_v1.py
docs/research/sector_taxonomy_quality_refresh_v1_1.md
docs/todo/sector_taxonomy_quality_refresh_v1_1.md
docs/todo/sector_taxonomy_database_seed_v1.md
docs/todo/sector_rotation_master_plan_v1.md
docs/todo/README.md
```

Only modify files that are actually required. Do not create a second importer or
a second taxonomy seed with duplicated ownership unless the existing versioning
contract demonstrably cannot support the refresh.

## Required audit tooling

Add or extend deterministic tooling that reports:

```text
assets reviewed
primary changes
secondary changes
kept classifications
kept UNCLASSIFIED
new taxonomy gaps
unknown sector codes
duplicate active memberships
primary-membership violations
orphan identities
source/provenance omissions
confidence omissions
liquidity-tier changes
```

The audit must support repository-only validation without opening a database
connection.

## Repository acceptance

Required checks:

```text
python -m src.research.run_sector_taxonomy_import_v1 --validate-only
focused taxonomy tests
focused sector-rotation tests
git diff --check
JSON parse and deterministic ordering checks
```

Acceptance conditions:

- HOT is correctly reviewed and classified or a documented primary-source
  blocker explains why not;
- all FFG research-universe assets have a fresh review decision;
- every changed asset has evidence and provenance;
- no unknown codes;
- no duplicate active memberships;
- exactly one primary membership per canonical asset;
- explicit `UNCLASSIFIED` remains allowed;
- importer remains deterministic and fail-closed;
- no selection, decision, planning, execution, broker, reporting, timer, or
  runtime behavior changes;
- no database write is performed from the repository PR.

## Post-merge database acceptance

Database activation is a separate operational action after the implementation
PR is merged.

Required sequence:

```text
record exact merged SHA
backup current taxonomy counts and fingerprints
run validate-only from merged SHA
run dry-run against canonical database
review inserts/updates/stale memberships/asset.sector changes
verify destructive downgrades = 0
run transactional write-db
verify counts, constraints, history, and asset.asset_class fingerprint
run idempotent second write
rerun Phase B sector snapshots only after taxonomy acceptance
```

Do not combine taxonomy database activation with Phase B migration/write
acceptance in one unreviewed operation.

## Required final report

```text
agent=
model=
reasoning=

BASE_SHA=
BRANCH=
HEAD_SHA=
PR_NUMBER=

AUDIT:
canonical_assets=
ffg_assets_reviewed=
enabled_named_assets_reviewed=
unclassified_candidates_reviewed=
primary_changes=
secondary_changes=
kept_existing=
kept_unclassified=
taxonomy_gaps=

HOT:
old_primary=
new_primary=
old_secondary=
new_secondary=
confidence=
primary_sources=

VALIDATION:
validate_only=
json_determinism=
focused_taxonomy_tests=
focused_rotation_tests=
git_diff_check=
unknown_codes=
primary_violations=
duplicate_memberships=
orphans=

BOUNDARIES:
selection_engine_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_calls=0
broker_writes=0
order_submission=0
reporting_changes=0
runtime_timer_changes=0
database_writes=0

BLOCKERS:
NEXT_EXACT_ACTION:
```

Stop after opening the implementation PR. Do not merge it and do not activate
the database from the repository task.
