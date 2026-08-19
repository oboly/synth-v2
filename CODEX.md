# CODEX.md — OpenAI Codex Integration Rules (Synth v2.6)

## Naming Note

This file concerns **OpenAI Codex coding agents**.

It is unrelated to the "Codex" / breathline symbolic research vocabulary used
in `docs/research/` (`CODEX_NODE`, `codex_note`, breath-curve Codex notes).
Do not conflate the two.

## Ownership

`AGENTS.md` is the canonical provider-neutral operating contract. Codex reads
`AGENTS.md` natively; it owns architecture boundaries, live-trading safety,
research separation, testing, security, git, documentation rules, and the
canonical effort-selection policy.

This file contains **Codex-specific integration rules only**. Do not duplicate
the shared contract here.

Supporting documents:

```text
docs/ops/agent_orchestration_contract_v1.md   orchestration / handoff / thread / host / model-routing rules
docs/ops/agent_search_hygiene_v1.md           untrusted search / log / tool-output handling
docs/ops/state_model_discipline_v1.md         lifecycle vs temporary health / degraded-state design
```

Scoped overrides still apply. Before editing files under `src/research/`, read
and obey `src/research/AGENTS.override.md`.

## Codex Repository Integration

- State `agent=codex` in every final task report.
- State the exact model and actual effort/reasoning setting used when one is
  exposed by the Codex client. If no real effort control is exposed, report
  `effort=default` or `effort=unknown`; do not infer an effort value from task
  depth or elapsed work.
- Follow the current OpenAI model-routing policy in
  `docs/ops/agent_orchestration_contract_v1.md`:
  - GPT-5.6 Luna + low/medium for cheap bounded bulk work.
  - GPT-5.6 Terra + medium as the default OpenAI project-manager, engineering,
    focused-review, and triage route.
  - GPT-5.6 Sol + medium only as escalation for genuinely difficult or
    high-risk unresolved work.
  - High effort is an exception on every model, not a default quality tier.
- When model choice is available, do not default a long-lived project-manager
  or worker session to Sol merely because Sol is stronger. Start with Terra
  Medium and escalate only for a named unresolved uncertainty. A host
  application that fixes the project-manager model to Sol may keep that host
  model, but generated workers still follow the routing policy.
- Use Luna first for repository search, inventories, mechanical documentation,
  bounded evidence collection, simple transformations, and similarly clear
  low-risk slices when Luna is capable of the task.
- **Use effort to resolve uncertainty, not to execute scope.** If the task
  contract already resolves the important architecture, requirements, and
  implementation choices, low or medium is normally sufficient even when the
  implementation itself is substantial.
- Subagents do not default to high effort. When Codex exposes an effort
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
- Before escalating model tier, ask the same question and state why Terra or
  Luna cannot reliably resolve it. If there is no concrete answer, do not
  escalate to Sol.
- Do not escalate a subagent to high merely because the parent task is an
  architecture audit, because the agent is a reviewer/auditor, or because
  parallel agents are available. Narrow the assigned slice first.
- Stop a subagent once enough evidence exists to answer its assigned question;
  do not let it chase adjacent history, cleanup, or redesigns that cannot
  materially change the conclusion.
- Follow the default terse output shape in `AGENTS.md` (`Files: / Checks: /
  Result: / Status: / Blockers:`).
- Before adding or tightening any gate, blocker, lifecycle transition,
  eligibility rule, degraded-state behavior, or special-case state, read and
  obey `docs/ops/state_model_discipline_v1.md`. Resolve desired steady-state,
  degraded-state, and downstream/user-visible semantics before implementation.
- Treat direct task instructions as additional constraints, not replacements
  for repository architecture and safety rules.
- Do not push unless explicitly requested.

## Pull Request Review Policy

GitHub automatically runs `Claude Code Review / claude-review (pull_request)`
on pull requests. Treat that GitHub check as the default code-review gate.

- After opening or updating a PR, do **not** start a separate manual Claude,
  Codex, `/ultrareview`, or other duplicate code review while the automatic
  GitHub Claude review is pending.
- Wait for the automatic GitHub Claude review to complete and use its exact
  result/comments as review evidence.
- If the automatic Claude review succeeds with no blocking findings, no second
  manual code review is required by default.
- Start an additional independent review only when the automatic review is
  absent, failed/cancelled, reports a blocker needing follow-up, the user
  explicitly requests another review, or the task is explicitly designated
  high-risk and requires a separate independent audit.
- Tests, CI, architecture checks, DB/runtime safety checks, and required human
  authorization remain separate gates. The automatic review does not replace
  them.
- Do not merge while the automatic Claude review is still in progress when it
  is configured for that PR.

## Cross-Provider Review

Codex is the OpenAI side of the cross-provider review contract.

- The automatic GitHub Claude review above is the default PR code-review gate
  and avoids duplicate manual review work.
- A separate cross-provider review is exception-based, not automatic: use it
  only for the conditions listed in the Pull Request Review Policy or when a
  task contract explicitly requires it.
- When Codex reviews Claude work manually, use a CLEAR thread and review the
  exact diff and evidence, not a summary.
- Cross-provider review supplements but never replaces tests, audits, or human
  authorization.
