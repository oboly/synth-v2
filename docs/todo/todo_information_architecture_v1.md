# TODO — TODO Information Architecture v1

## Status

**SUPERSEDED — no remaining authority.** Retained as historical context only,
pending an `archive` disposition under `docs/todo/MIGRATION_FREEZE.md`.

`docs/todo/` is frozen and must not gain further structure: MIGRATION_FREEZE
explicitly forbids extending the TODO subfolder information architecture, and
GitHub Issues now own status, priority, and execution order. The plan below is
**not** authorized for execution. Do not create the unbuilt folders it targets
and do not treat its `docs/todo/README.md` ownership claims as current.

Canonical workflow: `docs/development/github_issues_workflow.md`.

## Goal (historical — no longer authorized)

Kept `docs/todo/README.md` as the sole cross-lane execution-order owner while grouping lane files by responsibility.

Target structure:

```text
docs/todo/
├── README.md
├── workflow_standard.md
├── execution/
├── runtime/
├── market_intelligence/
├── research_validation/
├── reporting/
├── completed/
└── backlog/
```

## Rules

- `docs/todo/README.md` remains the only priority and execution-order index.
- Subfolder `README.md` files provide navigation and boundaries only.
- A task has one owning TODO file; no duplicate task bullets across folders.
- Canonical design, contracts, evidence, and research remain under `docs/architecture/`, `docs/research/`, `docs/ops/`, or `docs/status/`.
- Moves must use path-preserving history where possible and update all references in the same change.
- No runtime, database, broker, account, order, or execution behavior changes.

## Migration order

### P1 — Establish structure

- Create subfolder navigation READMEs.
- Add folder ownership rules to `workflow_standard.md`.
- Add categorized links to the central TODO index without duplicating priority state.

### P1 — Move active lanes first

Move files in small reviewed batches:

1. `market_intelligence/`
2. `reporting/`
3. `execution/`
4. `runtime/`
5. `research_validation/`

Each batch must update:

- `docs/todo/README.md`;
- all Markdown links and path references;
- scripts or checks that reference exact TODO paths;
- PR and operations documentation where paths are canonical.

### P2 — Move closed and parked work

Move only fully closed owners to `completed/`. Mixed active/completed lanes remain with their active responsibility.

Move low-priority intake and parked collections to `backlog/` only when they are not active dependencies.

### P2 — Verification

Run repository-wide checks for:

```text
old docs/todo paths
broken Markdown links
duplicate TODO owners
subfolder priority duplication
unindexed active files
```

## Boundary

```text
Owner: docs / board maintenance
Behavior changes: none
Runtime changes: none
Database changes: none
Broker writes: 0
Order submissions: 0
```

## Completion criteria

- Every active or parked TODO appears once in the central index.
- Every TODO belongs to exactly one responsibility folder or one approved top-level exception.
- No subfolder owns cross-lane priority.
- No stale references to moved paths remain.
- The final structure is documented in `workflow_standard.md`.
