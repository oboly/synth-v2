# CODEX.md — OpenAI Codex Integration Rules (Synth v2.6)

## Naming Note

This file concerns **OpenAI Codex coding agents**.

It is unrelated to the "Codex" / breathline symbolic research vocabulary used
in `docs/research/` (`CODEX_NODE`, `codex_note`, breath-curve Codex notes).
Do not conflate the two.

## Ownership

`AGENTS.md` is the canonical provider-neutral operating contract. Codex reads
`AGENTS.md` natively; it owns architecture boundaries, live-trading safety,
research separation, testing, security, git, and documentation rules.

This file contains **Codex-specific integration rules only**. Do not duplicate
the shared contract here.

Supporting documents:

```text
docs/ops/agent_orchestration_contract_v1.md   orchestration / handoff / thread / host rules
docs/ops/agent_search_hygiene_v1.md           untrusted search / log / tool-output handling
```

Scoped overrides still apply. Before editing files under `src/research/`, read
and obey `src/research/AGENTS.override.md`.

## Codex Repository Integration

- State `agent=codex` in every final task report.
- State the exact model and effort used, per the task header rules in
  `docs/ops/agent_orchestration_contract_v1.md`.
- Follow the default terse output shape in `AGENTS.md` (`Files: / Checks: /
  Result: / Status: / Blockers:`).
- Treat direct task instructions as additional constraints, not replacements
  for repository architecture and safety rules.
- Do not push unless explicitly requested.

## Cross-Provider Review

Codex is the OpenAI side of the cross-provider review contract.

- Codex implementation -> prefer an Anthropic Claude review.
- When Codex reviews Claude work, use a CLEAR thread and review the exact diff
  and evidence, not a summary.
- Cross-provider review supplements but never replaces tests, audits, or human
  authorization.
