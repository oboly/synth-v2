# Agent Orchestration Contract v1

## Status

Documentation only. No runtime service, systemd timer, database, broker
credential, nginx/certbot config, generated output, or Odroid host state is
touched or implied by this document.

```text
runtime_mutations=0
systemd_mutations=0
database_writes=0
broker_calls=0
host_state_changes=0
```

## Scope

This document provides provider-neutral supporting detail for how AI coding
agents are selected, briefed, reviewed, and reported across Synth v2 work.
It applies to Anthropic Claude agents, OpenAI Codex agents, and any other
provider used on this repository.

`AGENTS.md` is the sole canonical owner of the shared engineering and agent
orchestration rules. This document expands the orchestration detail. Provider
files (`CLAUDE.md`, `CODEX.md`) contain integration specifics only and
reference both.

This document grants no new permission. It does not enable live trading,
broker writes, DB writes, deployment, or runtime mutation. It only governs
how agent work is organized and evidenced.

## 1. Model Orchestration

Match model capability to task risk, not to habit.

Use a strong frontier model as **advisor** for:

```text
architectural change
security-sensitive work
runtime / host ownership change
database schema or write-path change
decision_gate / execution_planner / executor work
broker-adjacent work
broad or cross-module refactor
ambiguous or high-blast-radius tasks
```

Less-capable or cheaper agents may execute **bounded implementation work**
under an explicit advisor contract.

The advisor defines, before implementation starts:

- architecture boundaries that apply
- permitted files and scope
- host ownership
- risk areas
- minimal required tests
- minimal required audits
- completion evidence

The advisor reviews deviations and difficult decisions. The advisor does not
duplicate all implementation work.

Do not use the most expensive model for routine mechanical work unless there
is a stated reason.

Select effort proportionally:

```text
low     = bounded mechanical work with low risk
medium  = normal implementation or focused review
high    = architecture, security, runtime, database, execution, broad
          refactors, ambiguous failures, or final high-risk review
```

Use the exact effort or reasoning value supported by the selected model or
client where known. Otherwise use `low`, `medium`, or `high`. Do not invent
unsupported effort values.

Effort does not replace ROLE. It does not authorize broader scope, additional
mutations, or any permission not stated in the task.

An implementer that hits a boundary question, an architecture ambiguity, or a
permission question must stop and return to the advisor rather than deciding
unilaterally.

## 2. Cross-Provider Review

Important changes should, where practical, receive an independent review from
a **different AI provider** than the implementing agent.

```text
Anthropic implementation -> prefer OpenAI review
OpenAI implementation    -> prefer Anthropic review
```

Rules:

- Cross-provider review supplements tests, audits, and human authorization.
  It never replaces them.
- Independent reviewers must use a CLEAR thread.
- Reviewers must review exact diffs and evidence, not summaries alone.
- The reviewer is given the branch, base SHA, head SHA, and the evidence
  bundle — not a narrative retelling of the work.

## 3. Required Task Header

Every generated agent handoff must explicitly contain:

```text
HOST: <exact host>
MODEL: <exact model>
EFFORT: <low | medium | high, or exact supported runtime value>
ROLE: <advisor | implementer | reviewer | auditor>
THREAD: <CLEAR | CONTINUE>
```

Also include, as applicable:

```text
REPOSITORY / WORKTREE: <path>
BRANCH: <branch>
BASE SHA: <sha when relevant>
HEAD SHA: <sha when reviewing>
DEPLOYMENT PERMISSION: <granted | not granted>
RUNTIME MUTATION PERMISSION: <granted | not granted>
DB WRITE PERMISSION: <granted | not granted>
BROKER / PRIVATE API PERMISSION: <granted | not granted>
```

Host, model, and effort selection must never be left implicit. Provider
identity is not a required header field and may be inferred from MODEL where
relevant.

Permission fields default to **not granted**. An absent permission line is
read as not granted, never as permission.

## 4. Thread Selection

Use **CLEAR** by default for:

- independent review
- cross-provider review
- audits
- security-sensitive work
- architecture review
- role changes
- a new bounded task
- context that may contain stale or conflicting assumptions

Use **CONTINUE** only when all of the following hold:

- continuing the same lane
- same role
- same branch / worktree
- previous context is required
- the thread remains manageable
- no independent review is intended

Prompt requirements:

- A CLEAR prompt must be fully self-contained.
- A CONTINUE prompt must state branch, commit, task contract, completed work,
  remaining work, and blockers.

## 5. Host Discipline

Always state whether work runs on `devlap`, Odroid, the DB host, a Windows
host, GitHub-only, or another named VM/server.

Never assume the following are identical across hosts:

```text
repository path
virtualenv
service user
database socket
credential file
runtime owner
```

Rules:

- Verify host ownership before runtime changes.
- Prevent duplicate writers across hosts.
- Runtime ownership questions resolve against the canonical runtime-owner
  documents under `docs/ops/`, not against agent memory or prior transcripts.

## 6. SSH Output Rule

This is an output-format rule for commands handed to the user.

- Do not place an `ssh ...` wrapper inside a code block intended for the user.
- Name the target host outside the code block.
- Put only the command to execute on that host inside the code block.
- Avoid nested SSH quoting and SSH-wrapped heredocs.

Correct shape — on the Odroid host:

```bash
systemctl --user status synth-4h-market-chain.timer
```

This rule does not prohibit an agent from using SSH internally when
explicitly authorized.

## 7. Proportional Testing

Use the smallest test scope that gives credible evidence.

Documentation-only change:

```bash
git diff --check
```

plus path/link/consistency validation where relevant.

Narrow Python change:

```bash
python -m py_compile <changed_file.py>
git diff --check
```

plus focused affected tests.

Cross-module or contract change:

- focused contract tests
- affected integration tests
- broader suite only when justified by impact

Runtime, security, authentication, database, account, decision, planner,
executor, or broker-adjacent change:

- focused tests
- relevant bounded preflight or audit
- explicit safety markers
- explicit statement of writes / calls / mutations

Rules:

- Do not run full suites or broad audits by habit.
- Do not omit a required test merely to save tokens.
- Never claim checks that were not run.

## 8. Token and Context Discipline

- Read canonical docs first.
- Search and fetch only relevant files.
- Do not dump full repositories, long logs, entire diffs, or repeated context.
- Provide worker and reviewer agents only the minimum self-contained evidence
  bundle.
- Stop investigating once the task is sufficiently proven.
- Run broad audits only for a named risk.
- Report exceptions, relevant evidence, blockers, and final status.
- Do not repeat repository content already available to the receiving agent.
- Prefer exact paths, SHAs, commands, and compact evidence over narrative.

Token discipline never justifies skipping a required safety check, weakening
a boundary statement, or reporting an unrun check as run.

## 9. Instruction Ownership

```text
AGENTS.md                     = provider-neutral canonical operating contract
docs/ops/agent_orchestration_contract_v1.md = orchestration/handoff detail
docs/ops/agent_search_hygiene_v1.md         = untrusted-input detail
CLAUDE.md                     = Claude integration only, references AGENTS.md
CODEX.md                      = Codex integration only, references AGENTS.md
src/research/AGENTS.override.md = scoped research overrides
```

Rules:

- Do not duplicate the complete shared contract across provider files.
- Preserve scoped `AGENTS.override.md` behavior.
- Permanent supporting documentation belongs under `docs/ops/`.
- Update canonical docs rather than creating loose notes.
- Do not create a second policy document covering the same ground.

## Relationship to Existing Rules

This document does not weaken any existing Synth rule. All layer boundaries,
live-trading restrictions, research separation, credential safety, runtime
ownership rules, documentation workflow, and minimal-change requirements in
`AGENTS.md` remain in force.

Where this document and a task instruction disagree on safety, the stricter
reading applies.
