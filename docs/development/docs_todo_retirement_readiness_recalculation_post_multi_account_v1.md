# `docs/todo/` Retirement Readiness Recalculation — Post Multi-Account Follow-Up

agent=claude-code
model=claude-sonnet-5
effort=medium (canonical gate definitions, disposition taxonomy, and Issue
ownership rules were already resolved by prior audits; this task applies
them to current-`main` state and reconciles two newly filed Issues — no
unresolved architecture/design question is being decided here)
role=auditor
thread=CLEAR

This is an **audit-only** document. No `docs/todo/` file was moved,
archived, deleted, or edited. No GitHub Issue was created or modified. No
code, test, runtime, database, broker, or timer changes were made.

## 1. Scope / non-goals

In scope: recalculate the `docs/todo/` retirement gates (R1-R7) against
current `origin/main`, given PR #337 (Phase 2-5 current-state audit merged),
Issue #342 (Phase 3 tail), and Issue #343 (Phase 5.3 verification) filed
since the post-6F audit. Reconcile R2 specifically against the corrected
`R2_AFTER=FAIL` conclusion in the merged Phase 2-5 audit.

Out of scope (explicitly not performed): implementing Issues #342/#343,
filing new Issues (none were found to be genuinely unowned executable
scope), moving/archiving/editing any `docs/todo/` file, code/test/schema
changes, production DB access, broker access.

## 2. Baseline

```text
BASE_SHA=ef27395a37572a09f8959e66719e0466b0fdbabb
BASE_SUBJECT=Audit multi-account asset foundation Phase 2-5 current state (#337)
BRANCH=docs/todo-retirement-recalc-post-multi-account-v1 (from origin/main)
WORKTREE=isolated (primary checkout was mid-work on an unrelated feature
  branch with untracked docs; this task used a separate worktree cut from
  a freshly fetched origin/main)
```

Prior chain verified by commit ancestry (`git log --oneline -- docs/todo/
docs/development/`):

```text
d86b332c  Archive completed TODO records and remove redirect (Batch 6F)      [post-6F audit baseline]
c024f4aa  Resolve post-6F TODO retirement blockers (Batch 6F2) (#332)
d82f7a95  Correct multi-account asset foundation docs to reflect production reality (#334)
ef27395a  Audit multi-account asset foundation Phase 2-5 current state (#337) [= current BASE_SHA]
```

Canonical docs read: `docs/development/docs_todo_retirement_state_post_6f_v1.md`
(post-6F audit, gate definitions), `docs/development/docs_todo_cleanup_batch_6f2_v1.md`
(Batch 6F2 execution manifest), `docs/development/multi_account_asset_foundation_phase_2_5_current_state_audit_v1.md`
(PR #337, as merged — already contains the corrected `R2_AFTER=FAIL` /
`BACKLOG_UNMIGRATED_EXECUTABLE_SCOPE_COUNT=2` revision), `docs/todo/multi_account_asset_foundation_backlog.md`,
`docs/development/github_issues_workflow.md`.

GitHub Issues read (via `gh issue view`): #294 (CLOSED), #319 (OPEN), #331
(OPEN), #333 (OPEN), #342 (OPEN), #343 (OPEN).

## 3. Current inventory

```text
git ls-files 'docs/todo/**' | wc -l   -> 56   (was 60 at post-6F baseline)
```

Diff against the post-6F 60-file list (`comm -23`/`comm -13`) shows exactly
4 files removed, 0 added — matching Batch 6F2's archive moves precisely:

```text
docs/todo/external_research/ffg_mega_run_target_scenarios_v1.md   -> archived (docs/archive/...)
docs/todo/external_research/ffg_universe_metadata_v1.md           -> archived (docs/archive/...)
docs/todo/paper_candidate_contract.md                              -> archived (docs/archive/...)
docs/todo/parked_backlog.md                                        -> archived (docs/archive/...)
```

`git diff --stat d86b332c..HEAD -- docs/todo/ docs/development/
docs/research/synth_v2_research_todo_index.md` confirms the **only**
`docs/todo/` files touched since post-6F are the 4 archived files plus:
`README.md` (2 lane-index repoints), `external_research/README.md`
(AMBIGUOUS -> resolved), `market_intelligence/README.md` (disposition note
added), `multi_account_asset_foundation_backlog.md` (Phase 1 reality
correction, PR #334), `reporting/README.md` (stale section corrected),
`state_driven_runtime_orchestration_v1.md` (Issue #331 migration section
added), `live_like_vertical_slice.md` (reference repair). No other file in
the 48 `ISSUE_OWNED_OPEN` set from the post-6F audit changed — their
disposition text is unchanged evidence, not reused-blindly.

Every Issue number referenced across the post-6F inventory table (81 unique
numbers, plus #331/#342/#343) was re-queried via `gh issue list --state all
--json number,state` in one bulk call. Results match the post-6F audit's
recorded states exactly for every file's owning Issue set — no additional
Issue closed since the post-6F audit among the 48 `ISSUE_OWNED_OPEN` files'
owners (only #200, #256, #283, #294 are `CLOSED`, all already known/expected
as closed implementation history or, for #294, the Phase 1 completion this
task accounts for). No file's disposition changes from this check.

### Disposition breakdown (56 files)

```text
infrastructure=3                        (README.md, MIGRATION_FREEZE.md, workflow_standard.md — unchanged)
issue_owned_open=49                     (48 unchanged + state_driven_runtime_orchestration_v1.md, now owned by #331)
issue_owned_closed_archive_ready=0
partial_ownership=1                     (multi_account_asset_foundation_backlog.md)
unowned_executable=0                    (state_driven_runtime_orchestration_v1.md resolved by #331; no other file is unowned executable scope)
historical_archive_ready=0              (5 at post-6F; 4 archived by Batch 6F2, market_intelligence/README.md reclassified — see below)
ambiguous=0                             (external_research/README.md resolved by Batch 6F2)
remove=0                                (reporting/README.md corrected by Batch 6F2)
other_navigation_resolved=3             (market_intelligence/README.md, external_research/README.md, reporting/README.md — each carries "Unmigrated executable scope: none" and a reviewed retain/correct disposition; not archive-ready because they remain live navigation to still-open child files, not ambiguous/REMOVE because their disposition is now explicit)
```

Reconciliation: `3 + 49 + 0 + 1 + 0 + 0 + 0 + 0 + 3 = 56` = `tracked_todo_files`. ✓

```text
TOTAL_TODO_FILES=56
INFRASTRUCTURE_FILES=3
NON_INFRASTRUCTURE_FILES=53
```

## 4. R1-R7 recalculation

| Gate | Requirement | Result | Exact blockers |
|---|---|---|---|
| R1 | `unowned_executable_scope_files=0` | **PASS** | None. `state_driven_runtime_orchestration_v1.md` now carries a `## GitHub Issue migration` section owning it to Issue #331 (confirmed OPEN via `gh issue view 331`). Resolved by Batch 6F2 (PR #332); independently re-verified here, not reused blindly. |
| R2 | `partially_issue_owned_files=0` (recalculated per this task's ownership-not-completion criterion — see §5) | **PASS** | `multi_account_asset_foundation_backlog.md` remains disposition-category `PARTIAL_OWNERSHIP` (mixed CLOSED/owned/non-executable phases within one file), but zero **executable** scope inside it is unowned: Phase 1 done (#294 CLOSED), Phase 3 tail owned by #342 (OPEN), Phase 5.3 owned by #343 (OPEN), Phase 2/Phase 4 remain genuinely design-blocked (non-executable, correctly unowned per the canonical rule). See §5 for full proof. |
| R3 | `files_needing_canonicalization=0` | **FAIL** (forward-looking, non-blocking, unchanged) | Same 7 files as post-6F (§7 of that audit): none archived/reclassified since, all remain `ISSUE_OWNED_OPEN` with open owning Issues, so none are due for canonicalization yet. |
| R4 | `files_needing_archive=0`, `files_needing_remove=0` | **PASS** | Resolved by Batch 6F2 (PR #332): 4 of 5 archive-ready files archived; `market_intelligence/README.md` re-verified and reclassified (retained — still live navigation to 8 open child files, not archive-ready); `reporting/README.md`'s stale REMOVE-triggering section corrected in place. Re-scan of current 56-file set found no newly archive-ready or REMOVE-flagged file. |
| R5 | `live_operational_dependencies_on_todo_infrastructure=0` (for the 3 infra files specifically) | **PASS** | Unchanged: no code/test reads `README.md`, `MIGRATION_FREEZE.md`, or `workflow_standard.md` directly (grep-confirmed). Live code/test dependencies on 3 *non-infra* files (`replay_parameter_study_harness_v1.md`; `market_intelligence/sector_rotation_engine_v1.md`; `sector_rotation_dashboard_v1.md`) remain, unchanged since post-6F — out of scope for this specific gate, relevant only to eventual full-directory removal. |
| R6 | `live_governance_dependencies_on_todo_infrastructure=0` | **FAIL** | `AGENTS.md` (lines 273, 588, 596-603, 619), `docs/development/github_issues_workflow.md` (lines 22, 146), `docs/research/synth_v2_research_todo_index.md` all still name the infra trio (grep-confirmed on current `main`). Unchanged — this is Batch 6G's own scope. |
| R7 | Only retirement infrastructure remains | **FAIL** | 53 non-infrastructure files remain: 49 `ISSUE_OWNED_OPEN` (legitimate — normal open backlog), 1 `PARTIAL_OWNERSHIP` (backlog file, R2-clean per above), 3 navigation-resolved (legitimately retained, no independent executable scope). None of these need a disposition *action* before 6G; R7 fails only because the board is not yet empty of non-infrastructure content, which is expected given ~47 distinct Issues are still open. |

## 5. Detailed R2 ownership proof

Per task instruction: *"Do not require Issues to be completed for R2;
ownership is the criterion."* Applying that criterion to
`docs/todo/multi_account_asset_foundation_backlog.md`'s five phases plus
the related unowned-scope item from the post-6F audit:

```text
Phase 1 (skeleton)          -> #294, CLOSED. Implemented, production-applied. No executable tail. OWNED (complete).
Phase 2 (is_portfolio)      -> no Issue. PR #337 §3/§10: superseded by an unplanned semantic split;
                                requires a naming/disambiguation DESIGN decision before any migration is
                                mechanical. Non-executable today. Correctly unowned (matches canonical rule:
                                "future ideas, contingent migrations, design questions... do NOT count as
                                unmigrated executable scope").
Phase 3 (quote_asset)       -> tail (5 named research runners) is OWNED by Issue #342 (OPEN, confirmed via
                                `gh issue view 342`). Scope in #342's body matches PR #337 §4/§10/§11 item 1
                                exactly (same 5 file paths, same "no dependency, no design question" framing).
Phase 4 (is_tradeable)      -> no Issue. PR #337 §5/§10: selection_engine venue-context threading is an
                                unresolved architecture DESIGN decision (how to thread venue-awareness without
                                breaking selection_engine's account-agnostic hard boundary). Non-executable
                                today. Correctly unowned.
Phase 5.1/5.2/5.4           -> DONE (code + prior live evidence, PR #337 §6). No executable gap.
Phase 5.3 (Hugo open-order  -> OWNED by Issue #343 (OPEN, confirmed via `gh issue view 343`). Scope matches
  freshness verification)      PR #337 §6/§10/§11 item 4 exactly (bounded read-only DB check, no dependency).
state_driven_runtime_        -> OWNED by Issue #331 (OPEN, confirmed). Unrelated to multi-account backlog but
  orchestration_v1.md            was the post-6F audit's other R1/R2-adjacent open item; resolved by Batch 6F2.
```

```text
UNOWNED_EXECUTABLE_SCOPE_IN_BACKLOG=0
DESIGN_BLOCKED_NON_EXECUTABLE=2   (Phase 2, Phase 4 — correctly excluded, not a gap)
OWNED_EXECUTABLE=2                (Phase 3 tail -> #342; Phase 5.3 -> #343)
DONE=2                            (Phase 1; Phase 5.1/5.2/5.4)
```

Cross-check against Issue #319 (`account_id` vs `trading_account_id`
fragmentation, OPEN): PR #337 §7 already determined no Phase 2-5 item
structurally overlaps #319 (different tables/layers); #342/#343 do not
duplicate #319's scope. Cross-check against Issue #333 (`account_asset`
settings-column drift, OPEN): explicitly out of Phase 1-5 scope by the
backlog file's own text; #342/#343 do not touch it.

**R2_AFTER=PASS.** No executable multi-account scope is unowned. The
backlog file itself is still recorded as `PARTIAL_OWNERSHIP` in the
disposition inventory (§3) because it is a single file spanning
done/owned/non-executable phases — that is a bookkeeping fact about the
file, not a gate failure, per the task's explicit "ownership is the
criterion" instruction.

Note: `docs/todo/multi_account_asset_foundation_backlog.md` itself was
**not** edited to reference #342/#343 (PR #337 landed after the file's last
edit in PR #334, and this task does not edit `docs/todo/` files). The file's
in-repo text still reads "no Issue yet" for Phase 3/5.3. This is a stale-text
observation, not a retirement blocker — GitHub Issues, not file text, are
the ownership source of truth per `docs/development/github_issues_workflow.md`,
and both Issues explicitly cite this exact backlog/audit lineage in their
bodies.

## 6. 6G readiness decision

```text
RETIREMENT_READY_FOR_6G=0
```

R2 and R4 flip to `PASS` since the post-6F baseline (R1 was already resolved
by Batch 6F2 before this task). `RETIREMENT_READY_FOR_6G` remains `0`
because R6 and R7 still fail, and R3 remains an open forward-looking item:

- **R6 (FAIL):** `AGENTS.md`, `github_issues_workflow.md`, and the research
  index still govern by naming the infra trio. This is Batch 6G's own job to
  resolve, not a precondition Batch 6G is waiting on elsewhere.
- **R7 (FAIL):** 53 non-infrastructure files remain, the large majority
  (49) legitimately `ISSUE_OWNED_OPEN` against ~47 distinct open Issues.
  This is the normal, healthy state of an active backlog, not a process
  defect — matching the post-6F audit's own framing.
- **R3 (FAIL, non-blocking):** 7 files still carry uncanonicalized unique
  design content; none are due for canonicalization since their owning
  Issues remain open.

Do not interpret R2/R4 `PASS` as 6G readiness by itself — R6/R7 are the
actual remaining gates, and they were always going to require either full
Issue-closure of the backlog (impractical to wait for) or an explicit
reviewed decision about `docs/todo/`'s fate while `ISSUE_OWNED_OPEN` files
remain, exactly as the post-6F audit's own §12 preconditions state.

## 7. Minimum bounded path to 6G

Ordinary Issue lifecycle closure (not a docs batch, no action needed here):

```text
- The 49 ISSUE_OWNED_OPEN files clear naturally as their owning Issues
  close through regular engineering work (no docs/todo batch accelerates
  this without duplicating Issue tracking).
- Issues #342 and #343 close through their own bounded execution (out of
  scope for this audit-only task).
```

Actual docs-cleanup batches remaining before 6G can run:

```text
1. A reviewed decision on docs/todo/'s fate while ISSUE_OWNED_OPEN files
   remain (delete infra trio only vs. wait for full board closure vs. some
   other disposition) — this is the one genuine open design question
   blocking 6G, unchanged since the post-6F audit's §12. Not resolved by
   this recalculation (out of scope: this is audit-only, not a design
   decision task).
2. Once that decision is made: a bounded repoint batch — retire AGENTS.md,
   docs/development/github_issues_workflow.md, and
   docs/research/synth_v2_research_todo_index.md references to the infra
   trio (resolves R6), consistent with whatever the decision in (1)
   determines for the trio's replacement/successor governance location.
3. (Optional, not blocking 6G) 6F3 remediation: repoint
   CONTROLLED_CHAIN_4H_UNTRACKED_PATH and the two
   test_sector_taxonomy_import_v1.py assertions away from their exact
   docs/todo/ file dependencies, only required before those 3 specific
   files could ever be deleted.
4. (Optional, not blocking 6G) Canonicalize the 7 R3 files once their
   owning Issues close, so unique design content is not lost at eventual
   archive time.
```

No redundant migration is proposed: Phase 1 (done), the Batch 6F2 archive
moves, and the Phase 3/5.3 Issue filings are all already complete and are
not re-proposed here.

## 8. Exact commands / evidence

```bash
git fetch origin main
git rev-parse origin/main   # ef27395a37572a09f8959e66719e0466b0fdbabb
git worktree add <path> -b docs/todo-retirement-recalc-post-multi-account-v1 origin/main
git ls-files 'docs/todo/**' | wc -l                       # 56
git diff --stat d86b332c..HEAD -- docs/todo/ docs/development/ \
  docs/research/synth_v2_research_todo_index.md
git log --oneline --all -- docs/todo/ | head -20
gh issue view 294 342 343 319 331 333 --json number,title,state,body,url
gh issue list --repo oboly/synth-v2 --state all --json number,state --limit 400
grep -n "docs/todo" AGENTS.md docs/development/github_issues_workflow.md \
  docs/research/synth_v2_research_todo_index.md
grep -rn "docs/todo/replay_parameter_study_harness_v1.md" src scripts tests
grep -rln "sector_rotation_engine_v1.md\|sector_rotation_dashboard_v1.md" tests
```

```text
production_db_access_used=0
production_mutation=0
broker_writes=0
order_submission=0
github_issues_created=0
github_issues_modified=0
code_changes=0
test_changes=0
schema_changes=0
runtime_changes=0
docs_todo_files_edited=0
```

## 9. Safety markers

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```
