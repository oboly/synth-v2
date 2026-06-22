# FFG Flow Snapshot Ingest

## Purpose

Research-only operator workflow for preserving saved FFG Forecast pages as raw artifacts plus append-only structured flow history.

This lane does not change:
- selection_engine
- decision_gate
- execution_planner
- executor / agents
- broker behavior
- orders
- balances / positions
- account_asset
- global asset flags
- Short Swing / Profit Plan visibility

## Input

Supported machine-ingest input:
- saved HTML page
- copy-pasted plain text page

Original input files remain preserved outside Git, for example:

```text
FFG page saved as HTML or copy-pasted text
→ ~/synth-data/ffg/inbox/
```

Screenshots remain visual provenance only. They are not machine-ingest input for this runner.

## Workflow

```text
FFG page saved as HTML or copy-pasted text
→ ~/synth-data/ffg/inbox/
→ python -m src.research.run_ffg_flow_snapshot_ingest --artifact-file PATH --validate-only
→ python -m src.research.run_ffg_flow_snapshot_ingest --artifact-file PATH --dry-run
→ python -m src.research.run_ffg_flow_snapshot_ingest --artifact-file PATH --write-db
```

Mode semantics:
- `--validate-only`
  validates saved HTML/text artifact parse integrity, duplicate symbols, and reported-vs-parsed count mismatches
  no database connection
- `--dry-run`
  validates the DB-backed ingest plan, exact-artifact idempotency, unresolved identities, and proposed reconciliation
  no database writes
- `--write-db`
  transactionally applies artifact, snapshot, and observation inserts
  only mutating mode

## Storage Contract

- `external_research_artifact`
  one row per unique `(source_name, content_sha256)` raw FFG HTML/TEXT input
- `external_research_flow_snapshot`
  append-only structured snapshot rows per artifact and list scope
- `external_research_flow_observation`
  append-only per-symbol rows per parsed snapshot

Exact re-upload of the same artifact content reuses the existing artifact row and creates no duplicate snapshot or observation rows.

Different content hashes create new append-only history rows.

## Identity Rules

- `FFG_LIST`
  resolves only through exact `source_symbol` lookup against `FFG_RESEARCH_UNIVERSE_V1`
- `OUTSIDE_FFG_RADAR`
  remains external by default
  no auto-add to FFG universe
  no asset row creation
  no account row creation
  no automatic ambiguous ticker linking

## Non-Goals

- no OCR
- no upload endpoint
- no watcher
- no dashboard
- no analytics / ranking
- no Theme Scanner linkage
- no account integration
- no A+ Breathline changes
