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
