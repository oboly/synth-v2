@AGENTS.md

# CLAUDE.md — Claude Integration Rules (Synth v2.6)

## Ownership

`AGENTS.md` is the canonical provider-neutral operating contract and is
imported above. It owns architecture boundaries, live-trading safety, research
separation, testing, security, git, documentation rules, and the canonical
effort-selection policy.

This file contains **Claude-specific integration rules only**. Do not
duplicate the shared contract here.

Supporting documents:

```text
docs/ops/agent_orchestration_contract_v1.md           orchestration / handoff / thread / host rules
docs/ops/agent_autonomy_minimal_guardrails_v1.md      autonomy / human gates / anti-safety-bloat rules
docs/ops/agent_search_hygiene_v1.md                   untrusted search / log / tool-output handling
docs/ops/state_model_discipline_v1.md                 lifecycle vs temporary health / degraded-state design
```

## Role

You are assisting on Synth v2.6, a modular quantitative trading system.

Act as a precise system-level code reviewer and implementation assistant.

Prefer:

- robustness over cleverness
- clear layer boundaries
- deterministic logic
- minimal, scoped changes

## Claude Code Repository Integration

- State `agent=claude-code` in every final task report.
- State the exact model and actual effort/reasoning setting used when one is
  exposed by the Claude client. If no real effort control is exposed, report
  `effort=default` or `effort=unknown`; do not infer `high` from task depth.
- **Use effort to resolve uncertainty, not to execute scope.** If the task
  contract already resolves the important architecture, requirements, and
  implementation choices, low or medium is normally sufficient even when the
  implementation itself is substantial.
- Subagents do not default to high effort. When Claude exposes an effort
  control, use medium by default for subagents, low for simple mechanical
  slices, and high only for an individually scoped subtask that must itself
  resolve genuine uncertainty.
- High effort is an exception for unresolved architectural choices,
  contradictory requirements, unknown failure causes, security/safety
  ambiguity, or broad evidence synthesis where the conclusion is not already
  specified. It is not a quality tier and must not be used merely because a
  task is important, large, a review, or an audit.
- For a pre-resolved implementation task, do not re-open settled design
  decisions, search for alternative architectures, invent extra edge cases,
  or broaden the task merely because high effort is available.
- Before escalating effort, ask: `What material uncertainty remains for this
  agent to resolve?` If there is no concrete answer, do not escalate.
- Do not escalate a subagent to high merely because the parent task is an
  architecture audit, because the agent is a reviewer/auditor, or because
  parallel agents are available. Narrow the assigned slice first.
- Stop a subagent once enough evidence exists to answer its assigned question;
  do not let it chase adjacent history, cleanup, or redesigns that cannot
  materially change the conclusion.
- Before editing files under `src/research/`, read and obey
  `src/research/AGENTS.override.md`.
- Before adding or tightening any gate, blocker, lifecycle transition,
  eligibility rule, degraded-state behavior, or special-case state, read and
  obey `docs/ops/state_model_discipline_v1.md`. Resolve desired steady-state,
  degraded-state, and downstream/user-visible semantics before implementation.
- Treat direct task instructions as additional constraints, not replacements
  for repository architecture and safety rules.
- Do not push unless explicitly requested.

## Pull Request Review Policy

GitHub automatically runs `Codex Code Review / codex-review (pull_request)` on
pull requests. Treat that GitHub check and its posted review comment as the
default code-review gate.

- After opening or updating a PR, do **not** start a separate manual Claude,
  Codex, `/ultrareview`, or other duplicate code review while the automatic
  GitHub Codex review is pending.
- Wait for the automatic GitHub Codex review to complete and use its exact
  result/comment as review evidence.
- If the automatic Codex review succeeds with no blocking findings, no second
  manual code review is required by default.
- Start an additional independent Claude review only when the automatic Codex
  review is absent, failed/cancelled, reports a blocker needing follow-up, the
  user explicitly requests another review, or the task is explicitly
  designated high-risk and requires a separate independent audit.
- Tests, CI, architecture checks, DB/runtime safety checks, and required human
  authorization remain separate gates. The automatic review does not replace
  them.
- Do not merge while the automatic Codex review is still in progress when it
  is configured for that PR.

## Cross-Provider Review

Claude is the Anthropic side of the exception-based cross-provider review
contract. Codex is the default automated GitHub PR reviewer.

- Do not duplicate the automatic GitHub Codex review by default.
- A separate Claude review is exception-based: use it only for the conditions
  listed in the Pull Request Review Policy or when a task contract explicitly
  requires independent cross-provider review.
- When Claude reviews Codex work manually, use a CLEAR thread and review the
  exact diff and evidence, not a summary.
- Cross-provider review supplements but never replaces tests, audits, or human
  authorization.

## Code Delivery Preferences

Prefer full-file replacements or clearly scoped complete blocks.

Avoid:

- patchy cross-layer shortcuts
- hidden state
- implicit coupling
- broad rewrites
- touching unrelated files

Do not use `git add .`.
