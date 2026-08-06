---
name: Synth work item
about: Executable Synth v2 work with explicit architecture and acceptance boundaries
title: ""
labels: "status:needs-design"
assignees: ""
---

## Objective

## Current state

## Scope

## Out of scope

## Architecture boundary

Primary owner:

- `selection_engine` — market-only, account-agnostic candidate ranking; or
- `decision_gate` — account-aware permission and conflict resolution; or
- `execution_planner` — execution intent only; or
- `executor` / agents — order handling only; or
- `data`, `dashboard`, `infra`, or `docs`.

Forbidden shortcuts:

- No account-aware behavior in `selection_engine`.
- No decision-gate bypass.
- No order placement or reconciliation in `execution_planner`.
- No strategy decisions in executor or agents.
- No direct broker access from reporting or dashboard code.

## Labels

Before submitting, apply (see `docs/development/github_issues_workflow.md`):

- exactly one `type:*`;
- one or more `area:*` — use `area:execution-planning` or `area:executor`,
  never a combined execution area;
- at most one `status:*`;
- exactly one `priority:*`.

## Acceptance criteria

State verifiable conditions. Each must be checkable from a merged PR, a
recorded command result, or a named artifact — not from an impression.

## Required evidence

Name the exact tests, commands, safety markers, or artifacts that will prove
the acceptance criteria. "Tests pass" alone is not sufficient.

## Runtime/deployment impact

Choose and specify exactly one:

- repository-only — merge completes this issue;
- migration required — name the migration file and its rollback;
- controlled runtime action required — name the host, the exact command, and
  who authorizes it.

For the last two, the issue stays open after merge until runtime or deployment
acceptance is recorded.

## Safety

- Broker writes:
- Order submissions:
- Production database mutation:
- Service/timer changes:
- Rollback:
