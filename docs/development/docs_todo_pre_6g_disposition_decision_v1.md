# `docs/todo/` Pre-6G Disposition Decision

agent=claude-code
model=claude-sonnet-5
effort=high (this task itself is the unresolved architectural/governance
decision flagged by PR #344 — "a reviewed disposition decision for
docs/todo/ while ISSUE_OWNED_OPEN and PARTIAL_OWNERSHIP content remain" —
with no prior design session resolving it; genuine judgment call, not
mechanical execution)
role=advisor (governance decision author)
thread=CLEAR

This is a **decision document only**. No `docs/todo/` file was moved,
archived, deleted, or edited. No GitHub Issue was created or modified. No
code, test, schema, runtime, database, or broker change was made. Batch 6G
itself is **not** executed by this task.

## 0. Baseline

```text
BASE_SHA=abba7816e9c63211d1d14943148ea9ee219eaa81
BASE_SUBJECT=Recalculate docs/todo retirement gates post multi-account
  follow-up (#344)
BRANCH=docs/todo-pre-6g-disposition-decision-v1 (from origin/main)
WORKTREE=isolated (primary devlap checkout is on an unrelated feature
  branch, feature/native-short-degraded-health-missing-candles-v1, with an
  uncommitted in-progress change; this task used a separate worktree cut
  from a freshly fetched origin/main to avoid touching that work)
```

PR #344's merge commit (`abba7816`) is confirmed as the current `origin/main`
HEAD (`git fetch origin main` shows no advance beyond it at task time).

Canonical docs read: `docs/development/docs_todo_retirement_state_post_6f_v1.md`
(post-6F audit, canonical gate definitions and full 60-file inventory),
`docs/development/docs_todo_retirement_readiness_recalculation_post_multi_account_v1.md`
(PR #344, current 56-file/R1-R7 recalculation), `docs/development/github_issues_workflow.md`,
`docs/todo/README.md`, `docs/todo/MIGRATION_FREEZE.md`,
`docs/todo/workflow_standard.md`, `docs/todo/multi_account_asset_foundation_backlog.md`,
`AGENTS.md`, `docs/research/synth_v2_research_todo_index.md`.

GitHub Issues confirmed via `gh issue view --json number,title,state,body`:
`#319` (OPEN, `account_id`/`trading_account_id` fragmentation, F6 — confirmed
no Phase 2-5 overlap), `#331` (**CLOSED**, `closed_at=2026-08-10T04:04:13Z`,
closed via PR #341 / commit `0a343269994b9c5d2b552d137b82e66d56fdb991`, which
produced `docs/ops/state_driven_runtime_orchestration_audit_331.md`; owned
`state_driven_runtime_orchestration_v1.md` — closed before this branch's own
`BASE_SHA` above, so this document's inventory below treats that file as
closed-Issue-owned, not open-Issue-owned), `#333` (OPEN, `account_asset`
settings-column drift, unrelated to Phase 1-5), `#342` (OPEN, owns Phase 3
tail — 5 named research-runner files, scope text matches the backlog file
exactly, no dependency), `#343` (OPEN, owns Phase 5.3 verification — bounded
read-only check, no dependency, explicit no-mutation authorization note in
the Issue body itself).

## 1. Decision summary

**Chosen disposition: Option C — Freeze legacy board as archival/reference
namespace, files retained in place.**

The 3 `docs/todo/` infrastructure files (`README.md`, `MIGRATION_FREEZE.md`,
`workflow_standard.md`) may be retired in Batch 6G now, without waiting for
the 53 remaining non-infrastructure files to close out. Those 53 files are
reclassified — not moved, not edited beyond what MIGRATION_FREEZE.md already
permitted — into two frozen, non-board categories (`FROZEN_LEGACY_REFERENCE`
and `NAVIGATION_RETAINED`) that are explicitly no longer an active parallel
task board. GitHub Issues become the sole active execution tracker with no
transitional exception. `multi_account_asset_foundation_backlog.md`'s two
undesigned phases (2 and 4) are explicitly declared `PARKED_DESIGN_PENDING`
rather than left as ambiguous partial ownership — this is the one governance
act this document is chartered to perform that the prior audits (correctly)
declined to perform themselves.

## 2. Options considered

### Option A — Wait for full board closure

- **Benefits:** simplest mental model; zero risk of a stale infra reference;
  no reclassification judgment required.
- **Risks:** ties infrastructure retirement to ~47 distinct, independently
  paced open Issues with no estimate; some (the sector-rotation and
  breathline specs) are large, multi-quarter lanes. Indefinite deferral of a
  purely mechanical governance repoint.
- **Migration cost:** none now; large deferred/unbounded cost.
- **Operational ambiguity:** low today, but the deferral itself is a form of
  ambiguity ("when is closure enough?").
- **Effect on R2:** unchanged (FAIL) until `#294`'s successors and Phase 2/4
  are separately resolved — not addressed by this option at all.
- **Effect on R7:** unchanged (FAIL) for the full wait, by construction.
- **Compatibility with Issues-as-source-of-truth:** compatible but wasteful —
  Issues already are the source of truth; nothing about deferring the infra
  retirement improves that.
- **Unnecessarily blocks 6G:** yes. This is exactly the scenario PR #344 and
  the post-6F audit both flagged as the real question needing a decision,
  not a default.

### Option B — Retire only infrastructure now

- **Benefits:** minimal, mechanical, exactly matches the narrow scope the
  post-6F audit already said Batch 6G owns (§10: "R6 ... exactly what Batch
  6G itself must retire"). No reclassification vocabulary needed.
- **Risks:** leaves the 53 remaining files' status ambiguous — are they
  still "the board," just orphaned from the retired workflow doc that used
  to say so? Without an explicit frozen-reference declaration, a future
  reader (or agent) could reasonably treat them as still-live board state
  and violate the "no active parallel board" governance intent.
- **Migration cost:** near zero (3 files + repoint edits).
- **Operational ambiguity:** moderate — the remaining files' active/inactive
  status is left implicit rather than stated.
- **Effect on R2:** unaddressed by this option alone.
- **Effect on R7:** unaddressed; literal count stays non-zero indefinitely.
- **Compatibility:** compatible.
- **Unnecessarily blocks 6G:** no, but leaves a governance gap this decision
  should close while it has the chance.

### Option C — Freeze legacy board as archival/legacy namespace (chosen)

- **Benefits:** does everything Option B does, plus removes the ambiguity
  Option B leaves: every remaining file gets an explicit, reviewed,
  non-board classification (`FROZEN_LEGACY_REFERENCE` /
  `NAVIGATION_RETAINED`), and the one file that was genuinely and
  legitimately ambiguous (`multi_account_asset_foundation_backlog.md`) gets
  the missing disposition act (Phase 2/4 → `PARKED_DESIGN_PENDING`) that
  both prior audits identified as needed but declined to perform themselves
  (correctly — it was out of scope for an audit).
- **Risks:** requires care that "frozen reference" is not silently read as
  license to stop maintaining accuracy — mitigated by an explicit edit
  policy (§4) rather than a blanket freeze.
- **Migration cost:** near zero — this decision does not move any file.
  Physical relocation under an explicit `docs/archive/`-style legacy
  namespace is available later as a zero-urgency housekeeping action, not
  performed now, per principle 2 (no destruction of files that may still
  contain unique content) and principle 7 (no new parallel system).
- **Operational ambiguity:** lowest of the four options — every file has an
  explicit, named class with an explicit edit policy.
- **Effect on R2:** legitimately flips to PASS for the one affected file —
  see §5.
- **Effect on R7:** stays FAIL by its literal, unchanged metric (raw
  non-infrastructure file count) — see §5. This decision does not redefine
  R7's metric; it decouples R7's literal FAIL from blocking 6G's narrow
  chartered scope, which the post-6F audit itself already scoped narrowly.
- **Compatibility with Issues-as-source-of-truth:** strongest of the four —
  explicitly states GitHub Issues are the sole active tracker, with no
  exception carved out for any remaining file.
- **Unnecessarily blocks 6G:** no.

### Option D — Another disposition

Considered and rejected: no cleaner disposition surfaced. A variant of
Option C that *moves* all 53 files under a new `docs/todo/legacy/` or
`docs/archive/todo_legacy/` subtree immediately was considered and rejected
for this decision specifically — principle 2 requires files not be
destroyed/relocated merely because Issues own execution, principle 3/7
forbid a new parallel system, and an immediate mass-move would touch 53
files' paths (breaking the two live code/test path dependencies identified
in the post-6F audit §8, and the many still-open Issue bodies/PR
descriptions that may reference these exact paths) for no operational
benefit beyond what in-place reclassification already achieves. Physical
relocation remains available later as an independently justified,
low-urgency batch — not forced by this decision.

## 3. Chosen canonical disposition model

### Canonical classes

```text
INFRASTRUCTURE            README.md, MIGRATION_FREEZE.md, workflow_standard.md
FROZEN_LEGACY_REFERENCE   48 open-Issue-owned files
                           + 1 closed-Issue-owned file:
                             state_driven_runtime_orchestration_v1.md
                             (#331 CLOSED, closed_at=2026-08-10T04:04:13Z,
                             via PR #341)
                           + 1 reclassified multi_account_asset_foundation_backlog.md
                           = 50 files
NAVIGATION_RETAINED       market_intelligence/README.md,
                           external_research/README.md, reporting/README.md
                           (3 files; live index pages to FROZEN_LEGACY_REFERENCE
                           children, no independent executable scope)
LIVE_DEPENDENCY_RETAINED  the subset of FROZEN_LEGACY_REFERENCE with a live
                           code/test path dependency: replay_parameter_study_harness_v1.md,
                           market_intelligence/sector_rotation_engine_v1.md,
                           sector_rotation_dashboard_v1.md (3 files, already
                           counted within the 50 above — this is a cross-cutting
                           tag, not a disjoint category)
```

`state_driven_runtime_orchestration_v1.md`'s owning Issue (`#331`) closed on
2026-08-10T04:04:13Z via PR #341 (commit `0a343269994b9c5d2b552d137b82e66d56fdb991`,
which produced `docs/ops/state_driven_runtime_orchestration_audit_331.md`) —
before this branch's own `BASE_SHA` (§0). That file is therefore
closed-Issue-owned, not open-Issue-owned, at the time of this decision. Per
§3's own "Future closed-Issue-owned files" rule below, it remains
`FROZEN_LEGACY_REFERENCE` for now: this document does not perform its
`canonical`/`archive`/`remove` disposition review here, and it is eligible
for that normal review in a future, separately scoped docs batch like any
other closed-Issue-owned file.

Reconciliation against PR #344's inventory: `3 (infra) + 48 (still-open
issue_owned_open, which becomes FROZEN_LEGACY_REFERENCE) + 1 (closed-Issue-
owned, #331, which becomes FROZEN_LEGACY_REFERENCE) + 1 (partial_ownership,
which becomes FROZEN_LEGACY_REFERENCE) + 3 (navigation-resolved, which
becomes NAVIGATION_RETAINED) = 56 = TOTAL_TODO_FILES`. ✓ (48 + 1 + 1 = 50
FROZEN_LEGACY_REFERENCE; 50 + 3 NAVIGATION_RETAINED + 3 INFRASTRUCTURE = 56
total.)

### Class definitions

**`INFRASTRUCTURE`**
- Physical location: retired in Batch 6G (removed or moved to
  `docs/archive/`, per Batch 6G's own execution choice — not decided here).
- Content: no longer governs anything after 6G's repoint lands.
- Edits: none needed post-retirement.
- New scope: N/A.

**`FROZEN_LEGACY_REFERENCE`** (the 50 files: 48 still-`ISSUE_OWNED_OPEN`
+ 1 now closed-Issue-owned (`state_driven_runtime_orchestration_v1.md`, #331
CLOSED) + `multi_account_asset_foundation_backlog.md`)
- Physical location: **unchanged now.** Remains in `docs/todo/` (or its
  existing subfolder) exactly where it is. No file is moved by this
  decision.
- Status: explicitly **not** an active task board. GitHub Issues are the
  sole active execution tracker for every item these files describe.
- Edits allowed: correcting unsafe or materially false information (per
  `MIGRATION_FREEZE.md`'s pre-existing rule, unchanged); adding or updating
  a `## GitHub Issue migration` pointer section; dependency-safe maintenance
  (e.g. repointing a code/test constant that hardcodes the file's path,
  fixing a broken cross-reference). This is the same edit policy
  `MIGRATION_FREEZE.md` already established — this decision does not loosen
  or tighten it.
- New scope: **forbidden.** No new task, phase, or step may be added to a
  `FROZEN_LEGACY_REFERENCE` file. New work is filed as a GitHub Issue, full
  stop, per `docs/development/github_issues_workflow.md`'s existing
  migration rule.
- Issue closure effect: when a file's owning Issue(s) all close, the file
  becomes a candidate for the normal `MIGRATION_FREEZE.md` disposition
  review (`canonical` / `archive` / `remove`) in a future, separately
  scoped docs batch — not automatic, not performed by this decision.

**`NAVIGATION_RETAINED`** (3 files)
- Same physical-location and edit policy as `FROZEN_LEGACY_REFERENCE` above.
  Distinguished only in that these are index/pointer pages with no
  independent executable scope of their own (already established by PR #344
  §3: "each carries 'Unmigrated executable scope: none' and a reviewed
  retain/correct disposition").

**`LIVE_DEPENDENCY_RETAINED` tag** (3 files, subset of `FROZEN_LEGACY_REFERENCE`)
- Additional constraint beyond the base class: these 3 files must not be
  archived, removed, or path-moved until the dependency remediation named in
  the post-6F audit §8 (repoint `CONTROLLED_CHAIN_4H_UNTRACKED_PATH` and the
  two `tests/test_sector_taxonomy_import_v1.py` assertions) lands first. This
  decision does not perform that remediation and does not require it before
  6G — it is optional, non-blocking housekeeping per the post-6F audit's own
  §11 item "6F3."

**`PARTIAL_OWNERSHIP` (retired as a top-level file category by this decision)**
- `multi_account_asset_foundation_backlog.md` moves from `PARTIAL_OWNERSHIP`
  into `FROZEN_LEGACY_REFERENCE`, per §4 below — its two previously-unowned
  phases now have an explicit, reviewed non-executable disposition rather
  than an open-ended "no Issue yet."

**Future closed-Issue-owned files**
- No special new category. A file whose owning Issue(s) close simply becomes
  eligible for the pre-existing `MIGRATION_FREEZE.md` disposition review
  (`canonical`/`archive`/`remove`) — unchanged from current governance, not
  altered by this decision.

## 4. `multi_account_asset_foundation_backlog.md` — explicit disposition

```text
Phase 1 (skeleton)              DONE — Issue #294 owned this phase; already
                                  implemented and production-applied
                                  (confirmed live-verified per the file's own
                                  "reality-corrected 2026-08-09" note).
Phase 2 (is_portfolio)           PARKED_DESIGN_PENDING. No owning Issue. Not
                                  filed by this decision — filing an Issue for
                                  a design question with no concrete next
                                  action would itself violate
                                  github_issues_workflow.md's "what does not
                                  belong in Issues: loose ideas without
                                  executable scope." A fresh
                                  architecture/call-site review against
                                  current main (the "Phase 2-5 review gate"
                                  already written into the file itself) is
                                  the named precondition before this phase
                                  can become executable and receive an
                                  Issue. Reclassified here from "no Issue
                                  yet" (open-ended) to an explicit parked
                                  state (bounded: stays parked until the
                                  named review happens, not indefinitely
                                  ambiguous).
Phase 3 (quote_asset)            OWNED by Issue #342 (OPEN, confirmed). Scope
                                  matches the backlog file's Phase 3 section
                                  exactly (5 named research-runner files, no
                                  dependency).
Phase 4 (is_tradeable)           PARKED_DESIGN_PENDING, same reasoning as
                                  Phase 2 — an unresolved selection_engine
                                  venue-context threading architecture
                                  decision (how to add venue-awareness
                                  without breaking selection_engine's
                                  account-agnostic hard boundary per
                                  AGENTS.md), not a bounded executable task.
Phase 5.1/5.2 (Hugo onboarding)  DONE — implemented and live-verified per the
                                  file's own reality-correction note.
Phase 5.3 (open-order discovery) OWNED by Issue #343 (OPEN, confirmed).
                                  Bounded, read-only verification scope,
                                  explicit no-mutation authorization note in
                                  the Issue body.
Phase 5.4 (dashboard filter)     DONE — the audit chain (PR #337, restated in
                                  PR #344 §5) classifies 5.1/5.2/5.4 together
                                  as DONE with prior live evidence; no
                                  executable gap identified.
```

**New canonical disposition:** `multi_account_asset_foundation_backlog.md`
moves from `PARTIAL_OWNERSHIP` to `FROZEN_LEGACY_REFERENCE`. Every phase now
has one of exactly three states — `DONE`, `OWNED` (an open Issue), or
`PARKED_DESIGN_PENDING` (bounded: requires the file's own named review gate
before it can become executable) — and none is silently unaccounted for.
This decision does **not** file Phase 2 or Phase 4 Issues, per the task's
explicit instruction and per `github_issues_workflow.md`'s own rule against
filing Issues for non-executable design questions. It also does not edit the
`docs/todo/` file itself (per instruction) — the phase-by-phase disposition
above is recorded canonically in this document, and the file's own
`## GitHub Issue migration` section may be brought into sync with it in a
future dependency-safe maintenance edit (permitted, not required, by §3's
`FROZEN_LEGACY_REFERENCE` edit policy).

## 5. R2 / R7 re-evaluation

Per instruction, neither gate's literal definition is redefined here. Both
are re-evaluated against whether §3/§4's disposition changes the underlying
per-file classification the gate counts.

**R2 (`partially_issue_owned_files=0`): FAIL → PASS.**

R2 counts files whose disposition category is `PARTIAL_OWNERSHIP`. Before
this decision, exactly one file held that category —
`multi_account_asset_foundation_backlog.md` — because Phase 2 and Phase 4
had no owning Issue *and* no explicit disposition of their own (the PR #344
recalculation, §5, states exactly this: reclassifying the file "would
require Phase 2 and Phase 4 to either gain an owning Issue or receive an
explicit non-executable/parked disposition of their own... neither has
happened, and this audit does not perform either... that would be scope
creep for an audit-only task"). This document is the task explicitly
chartered to perform that governance act (§C/§D of the task instructions),
and §4 above performs it: Phase 2 and Phase 4 now carry an explicit,
reviewed `PARKED_DESIGN_PENDING` disposition, bounded by the file's own
pre-existing "Phase 2-5 review gate" section. With that disposition given,
the file's top-level category is no longer `PARTIAL_OWNERSHIP` — every
section is `DONE`, `OWNED`, or `PARKED_DESIGN_PENDING`, none unaccounted.
`partially_issue_owned_files=0` is therefore literally true, counted the
same way the gate always counted it. **R2_AFTER=PASS.**

**R7 (only retirement infrastructure remains): FAIL, unchanged.**

R7 has always been measured as a literal directory-content count
(`non_infrastructure_files=0`, per the post-6F audit's own acceptance
evidence block). §3's reclassification does not move or delete any file, so
that literal count stays at 53 (or effectively 56 minus the 3 infra files,
whatever the count is at execution time) — this decision does not claim
otherwise, and does not redefine R7's metric to make it appear to pass.
**R7_AFTER=FAIL**, honestly unchanged.

What *does* change is R7's relationship to Batch 6G's authorized scope. The
post-6F audit's own §10 already scoped R6 (governance dependencies) as
"exactly what Batch 6G itself must retire," not a separate prerequisite —
and PR #344 §7 already established that the *only* genuine pre-6G blocker
is this reviewed disposition decision, not R7's literal count reaching zero.
This document performs that decision: Batch 6G's chartered scope was always
the 3-file infrastructure retirement plus the governance repoint (§6 below),
never full-directory emptiness. R7 remaining FAIL by its literal,
un-redefined metric is therefore **expected and non-blocking** for that
narrow scope — exactly as R5 (PASS "for the 3 infra files specifically")
already modeled a scope-bounded gate reading in the prior audits. R7 will
continue to legitimately read FAIL until the ~47 distinct owning Issues
close through ordinary engineering work; no docs batch accelerates that, and
none should try to.

```text
R1_STATUS=PASS (unchanged, resolved Batch 6F2)
R2_BEFORE=FAIL
R2_AFTER=PASS
R3_STATUS=FAIL (unchanged, forward-looking, non-blocking)
R4_STATUS=PASS (unchanged, resolved Batch 6F2)
R5_STATUS=PASS (unchanged, scoped to the 3 infra files)
R6_AFTER_DECISION=FAIL (unchanged — 6G's own job to resolve, not a
  precondition for dispatching 6G)
R7_BEFORE=FAIL
R7_AFTER=FAIL (literal metric unchanged; decoupled as a 6G blocker — see
  above)
RETIREMENT_READY_FOR_6G=1 (for Batch 6G's narrow, chartered scope in §6 —
  not a claim that all 7 gates now literally pass; R3/R6/R7 remaining FAIL
  under their own metrics is expected and explicitly non-blocking for this
  scope per this decision)
```

## 6. Batch 6G authorized scope

Minimal, mechanical, matches the post-6F audit's own framing of what 6G was
always meant to be:

```text
1. Repoint AGENTS.md away from docs/todo/ infrastructure references
   (Project Structure, Documentation Rules, Instruction File Ownership
   sections — lines identified in post-6F audit §8 and PR #344 §4 R6 row).
2. Repoint docs/development/github_issues_workflow.md away from
   docs/todo/README.md / MIGRATION_FREEZE.md as canonical infrastructure
   (its "Frozen legacy board" table row and migration-rule reference).
3. Repoint or archive docs/research/synth_v2_research_todo_index.md's links
   to docs/todo/README.md and docs/todo/MIGRATION_FREEZE.md.
4. Retire docs/todo/README.md, docs/todo/MIGRATION_FREEZE.md,
   docs/todo/workflow_standard.md (remove or move to docs/archive/ — exact
   mechanism is Batch 6G's own execution choice, not decided here).
5. Preserve all 53 non-infrastructure files in place, reclassified per §3 —
   no move, no archive, no content rewrite as part of 6G.
6. Do not touch the 3 LIVE_DEPENDENCY_RETAINED files' code/test
   dependencies (out of scope, optional 6F3 remediation only).
7. Do not file Phase 2/Phase 4 Issues, and do not otherwise expand scope
   beyond the mechanical repoint + 3-file retirement above.
```

Explicit non-goals for Batch 6G:

```text
- No full-directory emptying or renaming of docs/todo/.
- No mass reclassification edits to the 50 FROZEN_LEGACY_REFERENCE / 3
  NAVIGATION_RETAINED files beyond what MIGRATION_FREEZE.md's existing edit
  policy already allowed.
- No new Issues filed as a side effect of the repoint.
- No code/test/schema/runtime change.
- No repointing of the 3 LIVE_DEPENDENCY_RETAINED files' hardcoded paths
  (separate, optional, non-blocking follow-up).
```

## 7. Non-goals of this decision document

```text
- Does not execute Batch 6G.
- Does not move, archive, delete, or edit any docs/todo/ file.
- Does not create or modify a GitHub Issue.
- Does not change code, tests, schema, runtime, production, or broker state.
- Does not file Phase 2/Phase 4 Issues for
  multi_account_asset_foundation_backlog.md.
- Does not claim R3, R6, or R7 literally pass — only that their continued
  FAIL is expected and does not block Batch 6G's narrow authorized scope.
```

## 8. Migration / rollback considerations

- This decision is purely a classification/governance act; there is nothing
  to roll back at the file-system level (no file was touched).
- If a future review determines a `FROZEN_LEGACY_REFERENCE` file was
  misclassified (e.g. it actually contains unowned executable scope), the
  fix is a normal Issue filing against that one file, not a reversal of this
  document.
- If Batch 6G is later found to have exceeded §6's authorized scope, revert
  Batch 6G's specific commits; this document's classifications remain valid
  independent of whether 6G has executed yet.
- Physical relocation of the 53 files under an explicit
  `docs/todo/legacy/`-style namespace remains available as a future,
  independently justified, low-urgency batch (Option D's rejected immediate
  variant) — nothing in this decision forecloses it, and nothing requires it.

## 9. Safety markers

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
production_db_access_used=0
production_mutation=0
github_issues_created=0
github_issues_modified=0
docs_todo_files_edited=0
code_changes=0
test_changes=0
schema_changes=0
runtime_changes=0
```
