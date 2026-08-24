# Agent Dispatch Cost Contract v1

## Status

Operational orchestration guidance only. This document grants no deployment,
runtime, database, broker, credential, or live-trading permission.

## Purpose

Define how the ChatGPT project-management/control-plane session chooses the
cheapest reliable execution lane for Synth v2 work without unnecessarily
putting the user in the routing loop.

This document supplements, and does not replace:

- `AGENTS.md`
- `docs/ops/agent_orchestration_contract_v1.md`
- `CLAUDE.md`
- `CODEX.md`

Architecture, safety, git, review, host, and permission rules in those files
remain authoritative.

## 1. Default behavior: route automatically

When the requested work is clear enough to execute safely, ChatGPT should
choose the execution lane itself. Do not ask the user to choose between
ChatGPT, GitHub Actions, Claude, Codex, or a local CLI merely as a routing
question.

Ask the user only when a real authorization or unavailable-state boundary is
reached, for example:

- live trading or broker/private API permission,
- destructive or production runtime mutation,
- required secret/credential provisioning,
- local host/data access that is unavailable to the chosen lane,
- an unresolved product or architecture decision that materially changes the
  implementation.

If the user has already granted the necessary permission and the selected lane
can complete the task, proceed without another routing confirmation.

## 2. Execution lanes

### Lane A: ChatGPT + GitHub connector

Use directly for small control-plane work where repository-local execution is
not needed:

- create/update issues,
- issue/PR comments,
- labels/metadata,
- PR status and review evidence,
- small GitHub file/document changes,
- workflow inspection and retry,
- narrowly bounded repository reads.

Do not launch a coding agent for work that is cheaper and clearer as one or a
few GitHub API operations.

### Lane B: GitHub-hosted Codex coding agent

Use Codex for repo-only implementation that can run in a clean GitHub-backed
coding environment and does not require Synth host state.

Model routing follows `docs/ops/agent_orchestration_contract_v1.md` and
`CODEX.md`:

```text
GPT-5.6 Luna  + low/medium = cheap bounded bulk/mechanical work
GPT-5.6 Terra + medium     = default implementation / engineering route
GPT-5.6 Sol   + medium     = escalation for named unresolved difficult/high-risk work
```

Codex workers do not implicitly have access to devlap, gurkdb, Odroid, local
historical datasets, local virtualenvs, local databases, or runtime services.

### Lane C: local coding agent

Use a local coding agent on the appropriate host when the task materially
benefits from or requires:

- large or iterative multi-file implementation,
- local historical data/backtests,
- database/runtime inspection,
- host-specific acceptance,
- existing local worktree state,
- tooling or services not available in the GitHub-backed coding environment,
- repeated test/debug cycles that would be wasteful as separate hosted runs.

The existing host, architecture, permission, and live-trading rules still
apply. Local availability does not grant mutation permission.

### Lane D: user handoff

Use only when the system cannot safely continue without a human action or
choice. Prefer one precise required action over asking the user to manually
coordinate agents.

## 3. Cost-first routing

Choose the cheapest lane that can reliably complete the task.

Default order for repo work:

```text
ChatGPT GitHub operation
-> Codex Luna for mechanical bounded work where capable
-> Codex Terra for normal bounded implementation
-> Codex Sol only for named unresolved difficult/high-risk work
-> local coding agent only for named unresolved host/data/runtime need
```

Do not select a stronger model merely because a task touches many lines. Select
it only when the worker must resolve material uncertainty.

Do not run two implementation agents for the same task by default. Parallel
work is justified only by distinct non-overlapping slices or a named
independent-review requirement.

A failed cheap lane may be escalated automatically after inspecting the
failure. Do not blindly retry at a more expensive tier when the failure is a
workflow, secret, permission, syntax, or environment problem.

## 4. ChatGPT dispatch behavior

When ChatGPT decides that a hosted Codex coding worker is the appropriate lane,
it may dispatch that worker itself through the available Codex/GitHub
integration. User confirmation is not required merely to select a worker when
the requested task already authorizes the underlying repository change.

Do not use `@claude` as the default hosted implementation dispatch route. The
Claude GitHub workflow is not the canonical hosted implementation lane for this
project and may be unavailable or broken. Use Codex unless the user explicitly
requests Claude or a specific exception requires it.

ChatGPT should then, where tool access permits:

1. inspect the resulting task/PR status,
2. avoid duplicate manual reviews while configured automatic Codex review is
   pending,
3. surface blockers only when intervention is actually required,
4. continue the workflow through review/readiness without asking the user to
   shuttle messages between agents.

ChatGPT must not infer deployment, runtime, DB write, broker, or live-trading
permission from permission to implement repository code.

## 5. Worker prompt discipline

Hosted coding workers must:

- read `AGENTS.md`, `CODEX.md`, and applicable scoped instructions first,
- stay inside the issue contract,
- inspect only relevant files,
- avoid broad repository dumps and unnecessary history excavation,
- use focused tests rather than full suites by habit,
- stop when acceptance evidence is sufficient,
- not reopen settled architecture decisions,
- not access network search unless the execution environment explicitly permits it,
- not assume access to Synth runtime hosts or local data,
- not deploy, mutate runtime/DB state, or call private broker APIs unless
  explicitly authorized by the task contract.

## 6. Token/context discipline

Token minimization is an execution requirement, subordinate only to correctness
and safety.

Workers should:

- start from the issue body and canonical docs rather than reconstructing
  project history,
- search before reading full files,
- read the smallest useful file/range set,
- avoid repeating source content in final reports,
- cap investigation once enough evidence exists,
- return terse status/evidence,
- prefer low effort when the task contract already resolves architecture and
  implementation direction.

Do not save tokens by skipping a required safety check or test.

## 7. Dispatch ownership

The dispatch mechanism selects an execution lane, not additional task scope.
The issue body remains the task contract. Dispatch instructions may narrow the
scope or permissions but must not silently broaden them.

When a provider-specific trigger syntax is used, verify that it is actually
supported by the current integration before relying on it. Do not document a
synthetic trigger token as canonical unless the active integration consumes it.
