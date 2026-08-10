# `docs/todo/` Cleanup Batch 6G Execution Manifest

Status: **BATCH_6G_COMPLETED=1**

This manifest records the mechanical execution authorized by merged PR #349
(`aa3fdf120c6b569511c938ec0225a027bd846ef0`).

## Baseline and scope

```text
BASE_SHA=aa3fdf120c6b569511c938ec0225a027bd846ef0
BRANCH=docs/todo-cleanup-batch-6g-v1
HOST=devlap
WORKTREE=/tmp/synth-v2-batch-6g
TODO_FILES_BEFORE=56
TODO_FILES_AFTER=53
INFRASTRUCTURE_FILES_BEFORE=3
INFRASTRUCTURE_FILES_AFTER=0
```

No non-infrastructure `docs/todo/` file was moved or edited. The remaining
files are `FROZEN_LEGACY_REFERENCE` (50) or `NAVIGATION_RETAINED` (3), and
remain physically in place. They are not an active task system; GitHub Issues
are the sole active execution tracker. No new executable scope may be added
to the frozen files. Allowed maintenance remains limited to factual
corrections, Issue pointers, and dependency-safe reference maintenance.

## Exact changes and dispositions

Governance references repointed:

- `AGENTS.md`: now identifies GitHub Issues as the sole active execution
  tracker and `docs/todo/` as frozen legacy/reference material; retired
  infrastructure links removed.
- `docs/development/github_issues_workflow.md`: same sole-tracker rule and
  frozen-file maintenance policy; no infrastructure dependency remains.
- `docs/research/synth_v2_research_todo_index.md`: retained as superseded
  research navigation, with retired infrastructure links removed and the
  surviving files described as frozen reference material.

Infrastructure dispositions:

- `docs/todo/README.md` -> `docs/archive/docs_todo_infrastructure_legacy_v1/README.md`
  (archived historical inventory/navigation context).
- `docs/todo/MIGRATION_FREEZE.md` ->
  `docs/archive/docs_todo_infrastructure_legacy_v1/MIGRATION_FREEZE.md`
  (archived historical migration policy).
- `docs/todo/workflow_standard.md` ->
  `docs/archive/docs_todo_infrastructure_legacy_v1/workflow_standard.md`
  (archived superseded workflow context).

No redirect shells were left in `docs/todo/`. References in the archive are
historical material only and do not govern current execution.

## Gate and safety result

```text
R1=PASS
R2=PASS
R3=FAIL (forward-looking/non-blocking)
R4=PASS
R5=PASS
R6=PASS
R7=FAIL (literal physical-file metric: 53 frozen/reference files remain)
RETIREMENT_READY_FOR_6G=CONSUMED_COMPLETED

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
production_access=0
production_mutation=0
issues_created=0
issues_modified=0
```

## Verification evidence

The Batch 6G worktree was isolated because the primary checkout contained
unrelated changes. `git diff --check` passed. `git ls-files 'docs/todo/**' |
wc -l` returned `53`. Repository-wide search found no live governance
document treating the retired paths as canonical active infrastructure.
Frozen legacy files and prior governance/archive records may retain
historical references; those matches are not current authority. `git diff
--name-status` confirms
changes are limited to the governance documents, this manifest, and the three
specified infrastructure archive moves. No `src/`, `scripts/`, `tests/`,
`db/`, migration, runtime/service, broker, or production files changed.

```text
CODE_CHANGES=0
TEST_CHANGES=0
DATABASE_CHANGES=0
SCHEMA_CHANGES=0
RUNTIME_CHANGES=0
BATCH_6G_COMPLETED=1
```
