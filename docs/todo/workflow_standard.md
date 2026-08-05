# TODO Workflow Standard

Status: **SUPERSEDED FOR NEW WORK**

The former `docs/todo/` board workflow is frozen during the controlled migration to GitHub Issues.

New executable work must follow:

```text
docs/development/github_issues_workflow.md
```

Migration constraints and allowed dispositions are defined in:

```text
docs/todo/MIGRATION_FREEZE.md
```

## Legacy-board rule

- Do not create new TODO lane files.
- Do not add new work to the legacy cross-lane board.
- Existing TODO files remain readable only until each receives a reviewed `issue`, `canonical`, `archive`, or `remove` disposition.
- Correct materially false or unsafe information immediately, but do not resume duplicate status tracking.
- Preserve unique PR, commit, runtime-acceptance, and rollback evidence before moving or removing any file.

## Architecture boundary

The migration changes work tracking only. It does not change canonical layer ownership:

```text
selection_engine  = market-only, account-agnostic candidate ranking
decision_gate     = account-aware permission and conflict resolution
execution_planner = execution intent only
executor / agents = order handling only
```

No issue or documentation migration authorizes a shortcut between these layers.

## Safety

- Runtime changes: none
- Database changes: none
- Broker writes: 0
- Order submissions: 0
- Service/timer changes: none
