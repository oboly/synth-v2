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

## Acceptance criteria

## Required evidence

## Runtime/deployment impact

Choose and specify one:

- repository-only;
- migration required;
- controlled runtime action required.

## Safety

- Broker writes:
- Order submissions:
- Production database mutation:
- Service/timer changes:
- Rollback:
