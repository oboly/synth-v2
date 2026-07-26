# Manual Execution Ladder P0 Round 5 — Independent Review

```text
HOST: devlap
MODEL: Claude Sonnet 5
EFFORT: medium
ROLE: reviewer
THREAD: CLEAR
REPOSITORY: /home/gurk/projects/synth-v2
BRANCH: agent/canonical-agent-orchestration-contract-v1
BASE SHA (repo HEAD at review time): 9cef987
WORKING TREE: uncommitted (same uncommitted diff present before and after
  this review; this review did not stage, commit, or modify it)
DEPLOYMENT PERMISSION: not granted
RUNTIME MUTATION PERMISSION: not granted
DB WRITE PERMISSION: not granted
BROKER / PRIVATE API PERMISSION: not granted
```

Scope: independently verify the claims in
`docs/reviews/manual_execution_ladder_p0_round4_implementation_20260726.md`
against Round 3's required fixes 1–6
(`docs/reviews/manual_execution_ladder_p0_round3_independent_review_20260726.md`).
Nothing in the round 2/3/4 documents, or in this document itself, was taken
on trust; every claim below was checked against source and by running tests
directly in this session.

## Finding 1 (process/evidence defect) — Round 4's "committed by this task" claim is false

`docs/reviews/manual_execution_ladder_p0_round4_implementation_20260726.md`
states in its own header:

```text
WORKING TREE: uncommitted at task start, committed by this task
```

Independent check:

```text
git log --oneline -3
  9cef987 Document agent scope and effort discipline
  d15cb5f Implement P0 safety remediation for manual execution ladder lane
  88a57a8 docs: use effort in agent handoff contract

git status --short
  27 modified tracked files + 15 untracked files/dirs (manual_execution_*,
  decision_gate/manual_execution_*, execution_planner/sell_authority_guard_v1.py,
  db/migrations/2026072*, docs/reviews/, tests/test_manual_execution_*)
```

HEAD is still `9cef987`. There is no Round-4 commit. All Round-4 code exists
only as uncommitted working-tree state — the same state that was present
before this review started. The claim of "committed by this task" does not
match observable git history. This is a factual defect in the implementation
report, independent of whether the underlying code changes are correct.

## Finding 2 (substance) — Round 3's six decisive failures are independently confirmed fixed

Each Round 3 decisive failure was re-derived from source, not from the
Round 4 narrative:

1. **Non-substitutable resolver.** `build_manual_sell_execution_plan_preview`
   (`src/execution_planner/contract_preview_v1.py:614`) now takes only
   `request_id: int`, `approval_id: int`, `planning_inputs` — no
   caller-suppliable repository/reader argument exists on this signature.
   `resolve_persisted_manual_execution_authority`
   (`src/decision_gate/manual_execution_approval_v1.py:213`) constructs
   `ManualExecutionRequestRepository()` and the private
   `_ManualExecutionApprovalRepository()` internally with no caller override
   point. Verified: the previously-exploitable fake-repository injection
   path from Round 3's probe no longer has a parameter to receive a fake
   repository.
2. **ID binding.** `resolve_persisted_manual_execution_authority` explicitly
   checks `request.request_id != request_id` and
   `approval.approval_id != approval_id` and raises `LookupError` on
   mismatch; `contract_preview_v1.py` repeats the same checks
   (`_reject_mismatch`, lines 644–651). Round 3's finding #2 is closed.
3. **No caller-controlled clock.** Grepped `src/decision_gate`,
   `src/execution_planner`, `src/manual_execution` for `now:` parameters:
   the only production `process()` (`manual_execution_service_v1.py:98`)
   and `approve_and_reserve()` (`manual_execution_gate_v1.py:356`) take no
   `now`/`clock` argument. Freshness in `contract_preview_v1.py:482` reads
   `trusted_clock.utc_now()` (`src/manual_execution/_trusted_clock_v1.py`),
   which wraps `datetime.now(timezone.utc)` with no override seam in the
   production module. Round 3's finding #3 (caller-backdated `now`) is
   closed. Maximum-TTL enforcement (a Round 3 sub-finding under "binding/
   freshness gaps") is also present: `expires_ts - approved_ts >
   APPROVAL_TTL_SECONDS` (5 minutes) is rejected at `contract_preview_v1.py:485`.
4. **Generic SELL paths hard-blocked.** Independently read, not just
   grepped for the exception name:
   - `execution_planner_v1.build_execution_plan` raises
     `UnauthorizedManualExecutionCallError` at the top before touching
     `decision`/`config` (line 25), before the `now_utc` computation Round 3
     flagged as reachable.
   - `execution_planner_v1.build_exit_plan_from_position` raises
     unconditionally as its first statement (line 197); the remaining body
     is genuinely dead code below a `raise`.
   - `policy/exit_policy_v1.run_exit_policy_v1` raises unconditionally as
     its first statement (line 167).
   - `execution_planner/repository.py` rejects `plan.side == "SELL"` /
     `plan.requested_side == "SELL"` before any INSERT (line 47) and
     `create_exit_plan_without_reservation` raises unconditionally
     (line 265).
   - `src/execution/worker.py` rejects `side == "SELL"` /
     `plan.requested_side == "SELL"` before order construction.
   - CLIs: `run_execution_planner_v1.py:34` and
     `run_paper_cycle_v1.py:72` restrict `--requested-side` to
     `choices=("BUY",)` at the argparse level (not just a runtime check),
     so a CLI-supplied `SELL` is rejected by argument parsing itself.
   Round 3's finding #5 (generic SELL planner paths) is closed for every
   path Round 3 named.
5. **Discovery-based inventory.** `tests/manual_sell_entrypoint_discovery_v1.py`
   is a genuine `ast`-based walk over `DISCOVERY_ROOTS` (9 real source
   directories) using literal/name-token/prefix heuristics, not a
   hand-maintained dict masquerading as discovery — confirmed by reading the
   file, not by trusting its docstring.
6. **Negative tests.** `tests/test_manual_execution_round4_enforcement_v1.py`
   and the round3 enforcement/migration test files exist and were executed
   (see Test evidence below) alongside the discovery test.

Fix 7 (real MariaDB migration validation against clean/repeat/partial/
concurrency cases) is explicitly out of scope per the Round 4 report and
per this session's DB-write permission (`not granted`). This review makes
no claim about migration readiness; Round 3's `MIGRATION_READINESS=BLOCKED`
stands unless and until a task with DB-write permission validates it.

## Test evidence (run independently in this session, not copied from any report)

```bash
python -m pytest -q \
  tests/test_bitvavo_venue_adapter_v1.py tests/test_canonical_rounding_v1.py \
  tests/test_free_base_quantity_v1.py tests/test_limit_sell_ladder_v1.py \
  tests/test_manual_execution_p0_architecture_boundaries_v1.py \
  tests/test_manual_execution_p0_integration_v1.py tests/test_research_provenance_v1.py \
  tests/test_sell_reservation_v1.py tests/test_venue_execution_constraints_v1.py \
  tests/test_manual_execution_request_v1.py tests/test_manual_execution_gate_v1.py \
  tests/test_manual_execution_service_v1.py tests/test_manual_execution_atomic_approval_v1.py \
  tests/test_manual_execution_round3_enforcement_v1.py tests/test_manual_execution_round3_migration_v1.py \
  tests/test_manual_execution_round4_enforcement_v1.py tests/test_execution_ladder_profiles_v1.py \
  tests/test_execution_planner_explicit_intent_v1.py tests/test_execution_worker_fail_closed_v1.py \
  tests/test_executor_paper_contract_v1.py tests/manual_sell_entrypoint_discovery_v1.py
```

Result: `300 passed` — matches the Round 4 claim exactly.

```bash
python -m pytest -q tests --ignore=tests/db_test.py
```

Result: `3791 passed, 41 skipped, 1 failed` — matches the Round 4 claim
exactly. The one failure
(`tests/test_breathline_v2_canonical_campaign_archive_v1.py::test_canonical_archive_has_all_required_files`,
missing `run.log` fixture) was independently confirmed to be an unrelated
research-archive fixture issue, not a manual-execution regression.

## Minor finding — new file retains a caller-controlled `now` parameter (currently dead)

`src/decision_gate/research_provenance_v1.py:172` (new in this diff) has a
function taking `now: datetime` as a caller-suppliable argument, checking
provenance expiry against it. Grepped for callers: no other file under
`src/` or `scripts/` imports `research_provenance_v1`, so this is currently
unreachable from any production SELL path and does not reopen Round 3's
finding #3. Flagged because it is new code, in the same diff, that
reintroduces the exact caller-controlled-clock pattern the diff otherwise
eliminates — if this module is wired into the manual execution or decision
gate path in a later round without revisiting the `now` parameter, it would
reopen a closed finding.

## Verdict

```text
ROUND5_INDEPENDENT_REVIEW=SUBSTANCE_CONFIRMED_PROCESS_DEFECT_FOUND
```

The six code-level fixes Round 4 claims for Round 3's decisive failures are
independently verified against source and confirmed by test runs performed
in this session. Round 3's `BLOCK_REJECT` verdict is not reproducible against
the current working tree for reasons 1–6 above.

However, Round 4's own report contains a false claim ("committed by this
task") that does not match `git log`/`git status`. Nothing here should be
represented as merged, committed, or ready for any wider process step
(deployment, DB write, migration, Odroid, live, or PR merge) until:

- the working tree is actually committed (or the report is corrected to
  stop claiming it was), and
- fix 7 (real MariaDB migration validation) is completed under explicit
  DB-write permission, per Round 3/Round 4's own scope boundary.

No broker/private API call, order, DB write, or migration was performed
during this review. No implementation or test file was modified.

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
db_writes=0
files_modified=0
files_committed=0
```
