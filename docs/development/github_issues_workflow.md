# GitHub Issues Operating Workflow

## Purpose

GitHub Issues are the operational work inventory for Synth v2.

Permanent system truth remains in canonical documentation. Pull requests own implementation, review, tests, and acceptance evidence. Issues own executable scope, current status, dependencies, and closure.

## Source-of-truth split

| Source | Responsibility |
|---|---|
| GitHub Issues | Executable work, priority, blockers, acceptance criteria, and current work status |
| Branch | Bounded implementation for an issue |
| Pull request | Implementation, review, test evidence, and repository acceptance |
| `docs/strategy/` | Product direction, outcomes, and durable priority rationale |
| `docs/architecture/` | Permanent contracts and responsibility boundaries |
| `docs/research/` | Durable research methods, hypotheses, and findings |
| `docs/ops/` and `docs/deployment/` | Permanent operational contracts and procedures |
| `docs/status/` and `docs/incidents/` | Dated audits, accepted snapshots, and incidents |
| `docs/archive/` | Obsolete or superseded documentation |
| `docs/todo/` | Frozen legacy/reference files retained for navigation and history; never an active tracker |

An issue may link to canonical documentation but must not duplicate its full contract. Canonical documentation may link to an issue for open execution but must not maintain a competing task status or priority list.

## Workflow

```text
Issue
-> branch
-> implementation
-> pull request
-> repository acceptance
-> runtime/deployment acceptance when required
-> issue close
```

Preferred branch name:

```text
issue/<number>-<short-slug>
```

A pull request references its owning issue. Use `Closes #<number>` only when merge and all required acceptance steps actually complete the issue.

When repository work is merged but controlled deployment or runtime acceptance remains, keep the issue open and record the remaining action explicitly.

## What belongs in Issues

- bugs;
- bounded features;
- operations and deployment work;
- audits with an executable outcome;
- technical debt and cleanup;
- research likely to produce implementation or a bounded go/no-go decision.

## What does not belong in Issues

- permanent architecture documentation;
- loose ideas without executable scope;
- duplicates of canonical documents;
- historical acceptance evidence already owned by a merged PR or permanent ops/status document;
- parked collections with no concrete next action.

## Required issue structure

Use `.github/ISSUE_TEMPLATE/synth_work_item.md` and include:

- Objective;
- Current state;
- Scope;
- Out of scope;
- Architecture boundary;
- Acceptance criteria;
- Required evidence;
- Runtime/deployment impact;
- Safety.

## Architecture discipline

Canonical responsibility split:

```text
selection_engine  = market-only, account-agnostic candidate ranking
decision_gate     = account-aware permission and conflict resolution
execution_planner = execution intent only
executor / agents = order handling only
```

Every implementation issue has one primary owner layer. Umbrella issues may coordinate multiple layers, but implementation issues must remain bounded by responsibility. No issue authorizes a shortcut between layers.

Reporting and dashboards are read-only consumers unless an explicitly separate input contract says otherwise. They never call the broker directly and presentation output never grants execution authority.

## Labels

Apply exactly one `type:*` label:

- `type:bug`
- `type:feature`
- `type:ops`
- `type:research`
- `type:cleanup`
- `type:docs`

Apply one or more `area:*` labels:

- `area:data`
- `area:selection`
- `area:decision-gate`
- `area:execution-planning`
- `area:executor`
- `area:dashboard`
- `area:infra`
- `area:docs`

Apply at most one workflow-status label:

- `status:needs-design`
- `status:ready`
- `status:blocked`

A branch or open pull request is the source of truth for work in progress; no `status:in-progress` label is needed.

Apply exactly one priority label to executable issues:

- `priority:critical`
- `priority:high`
- `priority:normal`
- `priority:low`

Priority represents execution order and urgency, not architectural importance.

## Closure criteria

Close an issue only when all applicable conditions are true:

1. implementation is merged;
2. repository acceptance passed;
3. required migration or deployment completed;
4. required runtime evidence is recorded;
5. canonical documentation is updated;
6. remaining work is either absent or represented by a separate linked issue.

## Migration rule

GitHub Issues are the sole active execution tracker. The remaining
`docs/todo/` files are frozen legacy/reference material, not a parallel
backlog or workflow. Do not add executable scope to them or use them as a
source of current status, priority, or execution order.

Do not mass-convert `docs/todo/` files into Issues.

Migrate only work that is active, bounded, and has a concrete next action.
Preserve permanent design in canonical documentation, archive superseded
material, and remove only content proven to be duplicated elsewhere. Any
future maintenance of a surviving `docs/todo/` file is limited to factual
corrections, Issue pointers, and dependency-safe reference maintenance.

## Worktree policy for concurrent agents

- Normal branch workflow (branch, commit, push in place) is allowed in a
  clean, idle, task-exclusive checkout.
- Use an isolated worktree when the shared checkout is active, concurrent
  (another agent/process is using it), branch-unstable, or contaminated
  (unrelated uncommitted/untracked changes present).
- Never switch branches or commit in a checkout that another agent or
  process is actively using.
- If concurrency appears mid-task, stop and relocate the task to an
  isolated worktree rather than continuing in the shared checkout.
- Do not silently delete or reuse an existing task branch or worktree
  created by another agent or a prior run.
- When a worktree is used, report its path, branch, and base commit in the
  task's final report.
