# External Research TODOs

## GitHub Issue migration

Status: migrated

This file is navigation only. Executable child-file scope is owned by GitHub Issues as listed below.

Unmigrated executable scope:
- none

## Disposition (Batch 6F2 review)

Status: `ISSUE_OWNED_OPEN_NAVIGATION` (navigation-only, temporary).

Resolved in Batch 6F2 (`docs/development/docs_todo_cleanup_batch_6f2_v1.md`):
this file remains useful because `cross_asset_public_data_and_instrument_registry_v1.md`
is still `ISSUE_OWNED_OPEN` (#302) and this is the only current index pointing
to it. `ffg_universe_metadata_v1.md` was archived in the same batch; see
`docs/archive/external_research/ffg_universe_metadata_v1.md` for the
historical record and `docs/research/ffg_research_universe_v1.md` for current
canonical authority. Retire this file once `cross_asset_public_data_and_instrument_registry_v1.md`
also gets a terminal disposition.

## Scope

Source provenance, curated-universe membership, identity resolution, confidence, timestamps, public-data feasibility, neutral instrument mapping, and ingestion boundaries.

## Boundary

External research may create candidates, labels, mappings, observations, and provenance. It cannot assign canonical market state, account permission, execution intent, or order authority.

## Index rule

This file is navigation only. This board is frozen; current status, priority, and execution order are owned by GitHub Issues (`docs/development/github_issues_workflow.md`).

## Canonical files

- `cross_asset_public_data_and_instrument_registry_v1.md`

## Cross-asset split

```text
public-data sourcing and neutral registry
  -> external_research/cross_asset_public_data_and_instrument_registry_v1.md

market normalization and rotation research
  -> market_intelligence/cross_asset_rotation_research_v1.md
```

Authenticated broker integration is explicitly outside this folder.