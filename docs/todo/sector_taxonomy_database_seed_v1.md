# Sector Taxonomy & Database Seed v1

## Purpose

Create a deterministic, reviewable taxonomy for Synth assets and load primary sectors plus multi-cluster memberships into the database.

This phase collects and stores metadata only. It does not score sectors, change eligibility, or affect execution.

## Scope

### Taxonomy

Define canonical sector and cluster codes with:

- stable machine code;
- display name;
- description;
- optional parent sector;
- active flag;
- sort order.

Initial codes should cover at least:

- `DEFI_LENDING`
- `DEFI_YIELD`
- `RWA`
- `RWA_INFRA`
- `AI_COMPUTE`
- `DECENTRALIZED_AI`
- `DEPIN`
- `L1`
- `L2`
- `PERP_DEX`
- `ORACLE`
- `CROSS_CHAIN`
- `PAYMENTS`
- `GAMING`
- `STABLECOIN_INFRA`

### Asset classification

For every enabled or research-universe asset, collect:

- primary sector;
- zero or more secondary cluster memberships;
- membership weight;
- membership type;
- classification confidence;
- source/provenance;
- validity interval;
- reviewer notes for ambiguous assets.

Examples:

```text
PENDLE
primary_sector = DEFI_YIELD
memberships:
- DEFI_YIELD      1.00
- ETH_ECOSYSTEM   0.70
- RESTAKING       0.55
```

```text
AKT
primary_sector = AI_COMPUTE
memberships:
- AI_COMPUTE      0.90
- DEPIN           1.00
- CLOUD_INFRA     0.90
```

```text
LINK
primary_sector = ORACLE
memberships:
- ORACLE          1.00
- CROSS_CHAIN     0.80
- RWA_INFRA       0.65
```

## Proposed schema

### `sector_definition`

```sql
sector_code         VARCHAR(...)
display_name        VARCHAR(...)
description         TEXT
parent_sector_code  VARCHAR(...) NULL
is_active            TINYINT(1)
sort_order           INT
created_ts           DATETIME
updated_ts           DATETIME
```

### `asset_cluster_membership`

```sql
asset_id             BIGINT
sector_code          VARCHAR(...)
membership_weight    DECIMAL(...)
membership_type      VARCHAR(...)
confidence           DECIMAL(...)
source               VARCHAR(...)
valid_from_ts        DATETIME
valid_to_ts          DATETIME NULL
notes                TEXT NULL
```

Use `asset.sector` only for the canonical primary sector. Multi-cluster membership belongs in the separate table.

## Seed and importer

Provide a versioned seed plus importer with:

```text
--validate-only
--dry-run
--write-db
```

Required behavior:

- deterministic reconciliation;
- inserts, updates, unchanged rows, and stale memberships reported separately;
- unknown sector codes fail closed;
- duplicate active memberships fail closed;
- invalid weight/confidence ranges fail closed;
- no invented venue mappings;
- no direct loose SQL edits outside the reproducible import path.

## Initial required classifications

At minimum classify and review:

- PENDLE
- AKT
- LINK
- TAO
- RENDER
- AAVE
- ENA
- ONDO
- PLUME
- POL
- HYPE
- LIT
- NEAR
- VET
- DEEP
- CHIP

## GUI-readiness

The stored metadata must support later display of:

- primary sector badge;
- secondary cluster badges;
- sector and cluster filters;
- classification confidence;
- provenance/debug view.

No GUI changes are part of this phase.

## Acceptance

- All enabled assets have a primary sector or an explicit `UNCLASSIFIED` status.
- All research-universe assets have a reviewed classification status.
- Multi-cluster membership is supported.
- PENDLE and AKT are present and correctly classified.
- Seed validation is deterministic.
- Dry-run requires no writes.
- Write mode is transactional.
- Stale memberships are reconciled intentionally.
- Tests cover invalid codes, duplicates, invalid weights, and ambiguous classifications.
- No changes to selection, decision, planning, execution, or broker behavior.

## Layer and boundaries

```text
Owner: data / database / research metadata
Depends on: none
DB writes: taxonomy seed/import only
Broker writes: 0
Order submissions: 0
Execution impact: none
```
