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
docs/ops/agent_orchestration_contract_v1.md   orchestration / handoff / thread / host rules
docs/ops/agent_search_hygiene_v1.md           untrusted search / log / tool-output handling
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
- Subagents do not default to high effort. When Claude exposes an effort
  control, use medium by default for subagents, low for simple mechanical
  slices, and high only for an individually scoped subtask that genuinely
  requires deep reasoning.
- Do not escalate a subagent to high merely because the parent task is an
  architecture audit, because the agent is a reviewer/auditor, or because
  parallel agents are available. Narrow the assigned slice first.
- Stop a subagent once enough evidence exists to answer its assigned question;
  do not let it chase adjacent history, cleanup, or redesigns that cannot
  materially change the conclusion.
- Before editing files under `src/research/`, read and obey
  `src/research/AGENTS.override.md`.
- Treat direct task instructions as additional constraints, not replacements
  for repository architecture and safety rules.
- Do not push unless explicitly requested.

## Cross-Provider Review

Claude is the Anthropic side of the cross-provider review contract.

- Claude implementation -> prefer an OpenAI Codex review.
- When Claude reviews Codex work, use a CLEAR thread and review the exact diff
  and evidence, not a summary.
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
