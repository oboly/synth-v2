# Agent Autonomy and Minimal Guardrails v1

## Purpose

This document defines the preferred execution posture for coding agents working on Synth v2. It supplements the canonical rules in `AGENTS.md`; it does not override architecture, security, live-trading, or explicit human-authorization boundaries.

## Default autonomy

Prefer larger coherent work packages over prompt-by-prompt micro-steering.

When the user supplies a clear objective, hard constraints, and prohibited changes, the agent should normally own the path from current state to the requested end state. This includes planning, investigation, implementation, focused tests, CI/review follow-up, repair of ordinary failures, and safe continuation through dependent slices.

Do not stop merely to ask for `go`, `check`, or confirmation after an ordinary successful intermediate step when the next step is already implied by the accepted task contract.

A coherent lane may span multiple issues, branches, or pull requests when that decomposition improves reviewability or dependency management. Keep each slice scoped and reviewable, but preserve the lane-level objective and state across slices.

Parallelize only genuinely independent work. Do not create parallel agents that compete for the same contract, schema, or central file without a deliberate integration plan.

## Human gates

Return to the user only for a genuine decision or authorization boundary, including:

- irreversible or materially external impact not already authorized;
- live broker writes, order submission, or execution authority;
- credentials, secrets, or security-sensitive permission changes;
- production runtime activation, service/timer activation, or equivalent operational mutation when not already explicitly authorized;
- production database mutations or migrations when not already explicitly authorized;
- a fundamental architecture or semantic-contract choice with multiple materially different valid directions;
- an empirical/model-freeze decision where the observed result itself determines which path should be chosen;
- required information that cannot be recovered reliably from repository, tools, existing evidence, or prior task context.

Ordinary implementation problems, test failures, CI failures, review feedback, bounded research findings, merge conflicts, and safe alternative implementation paths are not human gates by themselves. Resolve them autonomously where possible.

## No safety bloat

Respect all existing safety, architecture, security, and authorization contracts. Do not weaken or bypass them.

At the same time, do not add new safety machinery by reflex. A new guardrail must mitigate a specific plausible risk, known failure mode, explicit requirement, or demonstrated incident and must be proportionate to that risk.

Do not automatically add extra:

- approval gates;
- confirmation prompts or flags;
- dry-run modes;
- validators;
- fallback layers;
- rollback mechanisms;
- duplicate guards;
- lifecycle states;
- defensive abstractions;
- audit ceremony;
- documentation ceremony.

Prefer existing controls when they already cover the risk. Prefer the smallest direct solution that satisfies the actual contract.

A theoretical possibility alone is not sufficient justification for new safety complexity. If a proposed guard has no named risk or failure mode, do not add it.

## Execution pattern

Preferred default:

```text
understand objective
-> identify hard constraints and true human gates
-> plan the coherent lane
-> execute
-> test and review
-> repair ordinary failures autonomously
-> continue through safe dependent steps
-> stop only at completion or a true human gate
```

Avoid this pattern when it adds no value:

```text
execute one obvious step
-> ask for confirmation
-> execute next obvious step
-> ask again
```

The goal is not fewer safeguards. The goal is less unnecessary interaction and less defensive complexity while preserving the safeguards that correspond to real risk.
