# GitHub Issues Migration Proposal v1

## Status

Proposal only. This document authorizes no mass Issue creation, file move, archive, deletion, deployment, or runtime change.

## Objective

Migrate the active Synth v2 work inventory from `docs/todo/` to GitHub Issues without creating duplicate sources of truth or losing canonical contracts and acceptance evidence.

## First migration batch

Create Issues only for active, bounded work with a concrete next action. Target: 8-12 Issues after this governance change is accepted.

Candidate first batch:

1. controlled canonical Fib publication repair deployment and acceptance after PR #193;
2. canonical 4h Fib publication activation;
3. Short Swing/runtime freshness and writer-ownership completion;
4. native SHORT ETH promotion;
5. native SHORT XRP promotion;
6. native SHORT multi-scope failure isolation/orchestration blocker;
7. manual execution reservation and reconciliation work, split by owner layer;
8. credential/runtime execution-boundary completion;
9. Sector Rotation dashboard review and acceptance;
10. replay parameter-study harness;
11. asset-universe expansion already tracked by issue #131.

Exact scope must be revalidated against current `main`, open pull requests, and runtime state immediately before each Issue is created.

## Classification rules

Each existing TODO file receives exactly one disposition.

### Issue

Use when the remaining work is active or deliberately queued, bounded, executable, and has a concrete next action.

### Canonical

Use when the file primarily contains permanent architecture, strategy, research, operations, deployment, or status truth. Move or merge that content into the correct canonical location; track only the remaining execution in an Issue.

Likely candidates include:

- backtest capability contracts;
- decision-gate protection design;
- sector-rotation master plans;
- market-intelligence regime, narrative, macro, catalyst, and scanner research;
- durable external-research overlay contracts.

### Archive

Use when the material is obsolete or superseded but retains historical value, unique decisions, or acceptance context.

Likely candidates include:

- `docs/todo/todo_information_architecture_v1.md`;
- completed defect/containment narratives;
- completed native SHORT implementation TODOs whose contracts and evidence are canonical elsewhere;
- superseded manual-ladder and version-specific backlog documents.

### Remove

Use only when repository history and reference checks prove the file contains no unique contract, decision, evidence, rollback procedure, or unresolved work.

## Explicit no-go items

- No automatic one-file-to-one-Issue conversion.
- No continued priority ownership by `docs/todo/README.md` after Issue migration begins.
- No copying permanent contracts into Issue bodies.
- No cross-layer implementation Issue that mixes market selection, account permission, execution planning, and order handling.
- No deletion based only on file names or apparent age.
- No expansion of the legacy TODO subfolder architecture.

## Migration sequence

### Phase 1 — Governance cut-over

- add the Issue template;
- add the canonical GitHub workflow;
- freeze new TODO intake;
- establish labels;
- improve issue #131 as the reference example.

### Phase 2 — Active-work migration

- revalidate candidate work against current repository and runtime truth;
- create only the first bounded Issue batch;
- add Issue pointers to migrated legacy files;
- stop updating duplicate status and priority fields in those files.

### Phase 3 — Canonicalization and archive

- move durable contracts and research to canonical locations;
- archive superseded historical material;
- consolidate duplicate owners;
- run repository-wide path and reference checks.

### Phase 4 — Legacy-board retirement

- verify every TODO file has one disposition;
- remove the legacy priority board;
- retain only an archive manifest when useful;
- make GitHub Issues the sole operational inventory.

## Acceptance evidence for each migration PR

```text
files_classified=
issues_created=
canonical_moves=
archived_files=
removed_files=
duplicate_status_owners=0
broken_references=0
runtime_changes=0
database_changes=0
broker_writes=0
order_submissions=0
```
