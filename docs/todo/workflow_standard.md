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

## Legacy vocabulary (reading the frozen board only)

These definitions are retained solely so the frozen `docs/todo/` files remain
readable. They define no current workflow and must not be applied to new work.
43 of the 89 frozen files still use the `P0`-`P4` tokens and 13 still use the
status words below.

Legacy priority tokens:

```text
P0 = former board blocker or required cleanup
P1 = former next implementation/review decision
P2 = former operational continuation after P1
P3 = former research, future design, or non-blocking work
P4 = former backlog
```

Legacy status words:

- `active`: was the current working lane.
- `open`: was valid work, not necessarily current focus.
- `parked`: was intentionally paused and preserved.
- `blocked`: could not proceed until a named dependency was satisfied.
- `done / parked`: implementation closed; evidence and standing hygiene only.
- `backlog`: was low-priority future work.
- `future design`: architecture concept only; no implementation authority.

Current priority and status vocabulary is the GitHub label taxonomy in
`docs/development/github_issues_workflow.md`. Do not map legacy `P0`-`P4`
values onto `priority:*` labels mechanically; revalidate scope against current
`main` and runtime truth when an Issue is created.

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
