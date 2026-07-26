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

## Independent review

- default effort = high
- broad path discovery is allowed
- no implementation changes

## Adjacent findings

- record in Remaining Blockers
- include path, impact, severity, recommended follow-up
- link existing TODO where possible
- do not create duplicate TODOs
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
