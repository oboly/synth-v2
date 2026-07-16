# Sector Taxonomy & Database Seed v1

## Status

Repository implementation complete for review. Database migration and
`--write-db` import remain explicit post-merge operator actions.

## Boundary

This is research/data metadata only. It has no selection, decision, planning,
execution, reporting, GUI, broker, or order behavior.

Safety markers:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

## Existing-schema resolution

`asset.sector` remains the canonical primary narrative sector for local asset
rows. The importer reconciles it from the versioned seed.

`asset_profile_snapshot.sector_group_code` is not reused. That field remains
reserved for empirically derived point-in-time co-movement groups.

`asset.asset_class` and `asset_profile_snapshot.liquidity_class` already mix
static and derived concerns. Phase A therefore adds an explicit static reviewed
`liquidity_market_cap_code` dimension. `SEMI_MAJOR` exists only in that
dimension and validation rejects it as a sector code.

Research-universe symbols do not always have local `asset` rows. Taxonomy
profiles and memberships therefore use a canonical symbol plus nullable
`asset_id`; the importer never invents an asset row or venue mapping.

## Schema

Migration:

```text
db/migrations/20260716_sector_taxonomy_database_seed_v1.sql
```

Tables:

- `sector_definition`: stable sector/cluster code, display metadata, optional
  parent, active flag, deterministic sort order, and seed version.
- `liquidity_market_cap_definition`: separate static tier definitions,
  including `SEMI_MAJOR` and `UNCLASSIFIED`.
- `asset_taxonomy_profile`: one canonical asset identity, nullable local
  `asset_id`, source aliases, universe scope, liquidity/market-cap code,
  provenance, notes, and seed version.
- `asset_cluster_membership`: versioned primary and secondary memberships with
  weight, type, confidence, provenance, validity interval, reviewer notes, and
  seed version.

Generated unique keys enforce one active primary membership per canonical
asset and one active membership per asset/sector pair while preserving expired
history.

## Seed and identity rules

Canonical seed:

```text
data/research/sector_taxonomy_seed_v1.json
```

Seed version and validity start are explicit. Every enabled or FFG
research-universe source symbol is represented. Research aliases are mapped to
one canonical identity:

- `RNDR` -> `RENDER`;
- `LIT` -> `LIGHTER`, with the source-name conflict retained in reviewer notes.

LINK and XLM each remain one asset with primary plus secondary memberships.
They are not duplicated per cluster.

CC is explicitly reviewed as:

```text
primary_sector=INSTITUTIONAL_FINANCE_INFRA
secondary=RWA_INFRA
secondary=SETTLEMENT_INTEROPERABILITY
secondary=TOKENIZED_CAPITAL_MARKETS
```

## Import modes

```bash
python -m src.research.run_sector_taxonomy_import_v1 --validate-only
python -m src.research.run_sector_taxonomy_import_v1 --dry-run
python -m src.research.run_sector_taxonomy_import_v1 --write-db
```

`--validate-only` opens no DB connection. `--dry-run` validates the current DB
universe, computes inserts/updates/unchanged/stale rows, and rolls back with no
writes. It can produce a pre-migration insert plan while clearly reporting the
missing migration. `--write-db` fails closed unless every target table exists,
uses a named single-writer lock, and commits definitions, profiles,
memberships, validity reconciliation, and `asset.sector` changes in one
transaction.

Stale active memberships are expired at the seed validity timestamp. Changed
memberships are expired and replaced. Unchanged memberships retain their
original validity start. A seed timestamp that cannot produce a valid interval
fails closed.

## Phase A coverage evidence

Evidence captured against the canonical database on 2026-07-16:

```text
enabled source symbols:           429 / 429
research-universe source symbols: 100 / 100
canonical asset identities:       448
reviewed named sectors:            103
explicit UNCLASSIFIED:             345
active memberships planned:        473
sector/cluster definitions:         29
liquidity/market-cap definitions:     7
```

`UNCLASSIFIED` is intentional, not a missing value. Each such row has a
reviewer note stating that evidence was insufficient for a deterministic v1
narrative classification. DEEP is specifically reviewed and left
`UNCLASSIFIED` because the v1 taxonomy lacks a precise primary category for its
spot order-book/liquidity role.

## Safety and follow-up

Applying the migration and running `--write-db` are not host/runtime changes.
They remain deliberate operator steps after merge. Phase B sector scoring must
not begin until the imported taxonomy is reviewed and accepted.
