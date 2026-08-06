# Agent Execution Scope and Effort v1

Canonical workflow rule for effort level and scope discipline during agent
task execution. Supplements `AGENTS.md` effort-selection guidance; does not
replace it.

## Implementation

- default effort = medium
- scope is frozen at task start
- adjacent findings are documented, not implemented
- make the smallest structurally correct change
- stop when acceptance criteria pass

## Goal revalidation on repetition or scope growth

Before continuing, re-check the original operator goal when any of these occurs:

- the same action or proposal has already required one correction cycle;
- the task gains a new tool, credential, host, prerequisite, abstraction, or
  provisioning layer;
- the proposed solution becomes materially longer or broader than the original
  objective;
- work shifts from the required outcome to debugging an optional helper or
  interface;
- the operator reports repetition, overengineering, or loss of momentum.

At that checkpoint, state explicitly:

- `original_goal`;
- `current_blocker`;
- whether the blocker is actually required by the canonical contract;
- the shortest architecture-compliant route to the goal;
- which optional steps, tools, or abstractions can be removed.

Do not continue patching the current route by default. After one repeated
correction, compare at least one simpler route and choose the shortest route
that preserves architecture, safety, and acceptance requirements.

Continue the existing route only when repository contracts or concrete safety
evidence require it. Do not introduce a new framework, installer, credential
path, documentation artifact, or execution layer merely to rescue an optional
approach.

Keep proposed actions separate from observed execution state. A command, SQL
block, or plan returned by an agent is not evidence that it was executed.

## Independent review

- default effort = high
- broad path discovery is allowed
- no implementation changes

## Adjacent findings

- record in Remaining Blockers
- include path, impact, severity, recommended follow-up
- link an existing GitHub Issue where possible
- propose a new bounded Issue only when no owner exists; do not create it unless authorized
- do not create or extend legacy `docs/todo/` entries
- do not expand current scope

## Model and effort commentary

The operator may intentionally distribute work across Claude Code, Codex, and
different effort levels to balance token budgets and available capacity.

Do not comment on a selected model or effort level merely because it differs
from an earlier suggestion.

Mention model or effort selection only when it creates a concrete problem for
the task, such as:

- the selected tool cannot perform the required operation;
- the context window is insufficient;
- the requested effort materially weakens required validation;
- the model choice conflicts with an explicit acceptance contract.

Otherwise, continue the task without commentary.

## Composer and UI suggestion text

Text displayed by the client below the active agent output, such as:

`Run /review on my current changes`

is UI suggestion text unless the operator explicitly submits it as an
instruction.

Do not:

- treat it as an executed command;
- warn the operator not to run it;
- include it in task-state analysis;
- interrupt ongoing work because it is visible.

Discuss such UI text only when the operator explicitly asks about it or
actually submits the command.
