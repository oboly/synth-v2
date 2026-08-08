# docs/todo Issue Migration — Batch 6C

agent=claude-code
role=implementer
model=claude-sonnet-5
effort=high

## 1. Status

```text
PARTIAL
```

12 of 13 source files reach `unmigrated_executable_scope=0`. One file
(`multi_account_asset_foundation_backlog.md`) is intentionally
`partially migrated`: only Phase 1 (the safe, additive schema skeleton) is
filed as an Issue; Phases 2-5 are deliberately deferred pending Phase 1
review, per the task's own file-specific guidance ("File Issue for Phase 1
... before further phases"). This is not a defect — it is the correct,
bounded outcome for a phased, risk-graded backlog.

## 2. Source matrix

| Source | Implemented | Existing Issue full | Existing Issue partial | Historical/superseded | Open migrated | Unmigrated | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `2026-05-19_product_cockpit_strategy_bundle.md` | 2 | 0 | 0 | 0 | 6 | 0 | migrated |
| `breath_curve.md` | 0 | 0 | 0 | 0 | 1 | 0 | migrated |
| `deploy_runtime.md` | 7 | 0 | 0 | 0 | 4 | 0 | migrated |
| `dev_ops_hygiene.md` | 2 | 0 | 0 | 0 | 1 | 0 | migrated |
| `invalidation_confirmation_backtest_v1.md` | 0 | 0 | 0 | 0 | 1 | 0 | migrated |
| `live_like_vertical_slice.md` | 1 | 0 | 0 | 1 | 1 | 0 | migrated |
| `martee_oracle_touch_semantics.md` | 0 | 0 | 0 | 0 | 1 | 0 | migrated |
| `multi_account_asset_foundation_backlog.md` | 0 | 0 | 0 | 0 | 1 | 4 | partially migrated |
| `multi_horizon_fib_dashboard_backlog.md` | 0 | 0 | 0 | 0 | 1 | 0 | migrated |
| `native_short_runtime_owner_and_scope_status_v1.md` | 0 | 0 | 2 | 1 | 1 | 0 | migrated |
| `paper_candidate_contract.md` | 0 | 0 | 0 | 1 | 0 | 0 | migrated |
| `parked_backlog.md` | 1 | 0 | 0 | 3 | 0 | 0 | migrated |
| `signal_matrix_dashboard.md` | 0 | 0 | 0 | 0 | 1 | 0 | migrated |

Notes on columns:

- "Existing Issue partial" for `native_short_runtime_owner_and_scope_status_v1.md`
  counts #201 (filesystem reader-group / snapshot publication host work,
  already owned there) and #276 (multi-scope rollout/promotion mechanics,
  confirmed distinct and already owned there).
- "Historical/superseded" for `live_like_vertical_slice.md` and
  `parked_backlog.md` includes the shared `MACRO_DIP_BUDGET_MODE_V1`
  speculative concept, deliberately parked with no Issue in both files
  (counted once per file).

## 3. Existing Issue overlap

Full open-issue list (`gh issue list --state open --limit 300`, 46 issues
at time of audit) was screened by title against all 13 files, plus
targeted `gh issue list --search` queries per file-specific guidance terms
and targeted `gh issue view` body inspection for every Issue named in the
task's file-specific guidance section.

Inspected in full (title + body):

```text
#198 #199 #200 #201 #206 #217 #227 #229 #239 #240 #243 #249 #254 #262
#270 #271 #276 (+ PR #287)
```

Results:

- **Full overlap (would have caused duplication if not caught)**: none
  found — no existing Issue fully owned any of the 13 files' residual
  scope before this batch.
- **Partial overlap (scope carved out to avoid duplication)**:
  - #201 — owns filesystem reader-group provisioning and native-SHORT
    snapshot publication host work; excluded from the new Issue #296
    (which owns only `synth_chain_4h_writer` DB identity + chain
    installed-host activation).
  - #276 / PR #287 — owns multi-scope rollout/promotion/bulk-enrollment
    mechanics for native SHORT; confirmed structurally distinct from the
    runtime-owner/chain-identity scope in
    `native_short_runtime_owner_and_scope_status_v1.md`. No overlap.
  - #254 / #262 / #206 / #217 — account-aware operator-intent, executor
    credential boundary, and Batch-4 Bitvavo read validation; confirmed
    distinct from both the multi-account **schema** backlog (Phase 1
    Issue #294) and the multi-user **cockpit/Bitvavo-linking** scope
    (Issue #280); cited as dependencies, not duplicated.
  - #243 / #270 / #271 / #249 — multi-horizon architecture contract and
    Fibo/zone research/reporting Issues from Batch 6B; confirmed none
    covers the multi-horizon **dashboard surface** backlog, which remains
    unowned and is now Issue #295 (explicitly gated on a still-unowned
    backtest foundation dependency).
  - #239 / #240 — bullrun-start dashboard and cockpit/wallet cleanup;
    confirmed distinct from the signal-matrix dashboard scope (#297).
  - #227 — decision_gate drawdown/loss/cooldown protection contract;
    confirmed distinct from the strategy-bucket activation/risk-config
    scope (#279).
- **None**: all remaining new Issues (#277, #278, #281, #282, #284, #285,
  #286, #288, #289, #290, #291, #292, #293, #294, #297) had no matching
  open or closed Issue on any searched term.

## 4. New Issues created

| Issue | Source | Architecture owner | Scope |
| --- | --- | --- | --- |
| #277 | `2026-05-19_product_cockpit_strategy_bundle.md` | reporting | Volume-flow candle classification for rotation preview |
| #278 | `2026-05-19_product_cockpit_strategy_bundle.md` | reporting | Expose research backtest/visual-review outputs through cockpit |
| #279 | `2026-05-19_product_cockpit_strategy_bundle.md` | decision_gate | Strategy bucket activation and per-account risk configuration |
| #280 | `2026-05-19_product_cockpit_strategy_bundle.md` | architecture/data-foundation | Multi-user cockpit account-access model + Bitvavo read-only linking |
| #281 | `2026-05-19_product_cockpit_strategy_bundle.md` | ops/runtime | Systemd ownership cleanup + Let's Encrypt/DuckDNS reliability |
| #282 | `breath_curve.md` | research | Breath Curve non-overlap and regime-difference validation continuation |
| #284 | `deploy_runtime.md` | ops/runtime | Activate authorized candle-ingestion production timer on gurkDB |
| #285 | `deploy_runtime.md` | research | Select and validate first paper-track strategy candidate |
| #286 | `deploy_runtime.md` | architecture/data-foundation | Market trigger engine watch/event/state schema decision |
| #288 | `2026-05-19_product_cockpit_strategy_bundle.md` | reporting | Friendly message for already-used email verification token |
| #289 | `deploy_runtime.md` | ops/runtime | Final Odroid runtime orchestration ownership/cadence doc |
| #290 | `dev_ops_hygiene.md` | ops/runtime | MariaDB manual export/backup procedure decision |
| #291 | `invalidation_confirmation_backtest_v1.md` | research | Graded invalidation-confirmation state-machine backtest |
| #292 | `live_like_vertical_slice.md` | research | NEAR shadow-chain reclaim thresholds and freshness rules |
| #293 | `martee_oracle_touch_semantics.md` | research | Martee Oracle target-box touch semantics field/validation |
| #294 | `multi_account_asset_foundation_backlog.md` | architecture/data-foundation | Phase 1 multi-account asset schema skeleton + backfill |
| #295 | `multi_horizon_fib_dashboard_backlog.md` | reporting | Multi-horizon Fib dashboard surfaces (gated on backtest foundation) |
| #296 | `native_short_runtime_owner_and_scope_status_v1.md` | ops/runtime | `native_short_4h_chain` DB writer identity + installed-host activation |
| #297 | `signal_matrix_dashboard.md` | reporting | Implement Signal Matrix Static Dashboard V1 |

`unique_new_issues_created=19`

## 5. Existing Issues reused

| Issue | Source | Scope |
| --- | --- | --- |
| #201 | `deploy_runtime.md`, `native_short_runtime_owner_and_scope_status_v1.md` | Linked-profile freshness/multi-cycle acceptance and native-SHORT snapshot filesystem/publication host work; cited to avoid duplicating scope, not re-tasked |
| #276 | `native_short_runtime_owner_and_scope_status_v1.md` | Multi-scope rollout/promotion mechanics; cited to confirm no overlap with the new chain-identity Issue #296 |
| #243 | `multi_horizon_fib_dashboard_backlog.md` | Multi-horizon strategy architecture contract; cited as a dependency for the gated dashboard Issue #295 |

## 6. Per-source migration details

### `2026-05-19_product_cockpit_strategy_bundle.md`

Decomposed per file-specific guidance rather than filed as one bundle
Issue. Dashboard-semantics label clarity (`RECLAIM_CONFIRMED`,
`HARVEST_REVIEW`, etc.) and the entry-candidate dashboard are already
implemented in `src/reporting/` — no Issue required. Six genuinely open,
architecturally distinct scopes were filed: volume-flow classification
(#277, reporting), backtest/visual-review cockpit exposure (#278,
reporting), strategy-bucket activation/risk config (#279, decision_gate),
multi-user cockpit + Bitvavo linking (#280, architecture/data-foundation),
already-used verification-token UX (#288, reporting), and systemd/HTTPS
ops cleanup (#281, ops/runtime). Status: migrated.

### `breath_curve.md`

Both open P2 sections (baseline/regime validation continuation,
non-overlap/regime-difference follow-up) share one research owner and
lifecycle; bundled into #282. Status: migrated.

### `deploy_runtime.md`

Most sections are marked done in the current file text (Odroid deployment,
webview refresh, 4h chain timer templates, setup-rank fixes) — no Issue.
Four genuinely open items, each with a distinct owner/lifecycle, were
filed: candle-ingestion production timer activation (#284, ops/runtime —
already `AUTHORIZED_INACTIVE` in `deploy/ownership/writer_capability_ownership_v1.json`,
confirmed via the registry), market trigger engine schema decision (#286,
architecture/data-foundation), first paper-track strategy candidate
selection under the canonical `strategy_proposal_contract_v1.md` (#285,
research), and the final runtime orchestration standard doc (#289,
ops/runtime). Status: migrated.

### `dev_ops_hygiene.md`

Codex smoke lane and DBeaver access recovery are done. MariaDB
backup/export procedure decision filed as #290 (ops/runtime). Local
untracked-file hygiene is already canonical in `AGENTS.md`. Status:
migrated.

### `invalidation_confirmation_backtest_v1.md`

Entire file is queued research with no prior Issue; filed as #291
(research). Status: migrated.

### `live_like_vertical_slice.md`

Verified via `find src -iname "*live_like*"` that the "Immediate Next
Steps" (candidate emitter, decision/execution-plan preview adapters,
shadow event log, dashboard) are fully implemented and actively running
in shadow mode — no Issue. Open Design Questions (reclaim-validity
thresholds, retest-depth, `STALE` rules, minimum candidate fields) filed
as #292 (research). `MACRO_DIP_BUDGET_MODE_V1` is explicitly parked with
no Issue (duplicate concept also appears in `parked_backlog.md`; recorded
once per file, no Issue in either). Status: migrated.

### `martee_oracle_touch_semantics.md`

Confirmed distinct from #270 (native Fib map touch-evaluator research —
different data source and field model). Filed as #293 (research). Status:
migrated.

### `multi_account_asset_foundation_backlog.md`

Per file-specific guidance, only Phase 1 (additive schema skeleton,
`venue_market`/`account_asset`, safe backfill) is filed as an Issue
(#294, architecture/data-foundation). Phases 2-5 (column-drop migrations
across 3/12/19 call sites, Hugo onboarding) are deliberately deferred
pending Phase 1 review — not filed this batch. Confirmed no overlap with
#254/#262 (account-scoped operator-intent layer, a different persistence
model). Status: **partially migrated**.

### `multi_horizon_fib_dashboard_backlog.md`

The planned dashboard surfaces depend on `multi_horizon_fib_backtest_v1`,
which itself has no owning Issue. Filed as #295 (reporting), explicitly
scoped so implementation cannot begin until that foundation lands —
preserves ownership without authorizing premature work. Status: migrated.

### `native_short_runtime_owner_and_scope_status_v1.md`

Re-verified against the concurrent #276 / PR #287 native-SHORT rollout
work per the resumed-task instruction: #276/#287 own multi-scope
rollout/promotion/bulk-enrollment mechanics (evidence-driven blocker
clearing, `PROMOTE_SCOPE` path); they do not touch the
`native_short_4h_chain` production-owner/DB-writer-identity/host-activation
scope this file describes. Filed #296 (ops/runtime) for the DB writer
identity + installed-host activation remainder only; explicitly excluded
the filesystem reader-group/snapshot-publication piece already owned by
#201. Status: migrated.

### `paper_candidate_contract.md`

The file's entire remaining scope (future decision_gate adapter design)
is superseded by the canonical, merged `docs/architecture/strategy_proposal_contract_v1.md`
(PR #257), which already defines the proposal -> decision_gate envelope.
No Issue required. Status: migrated.

### `parked_backlog.md`

Each of the four sections classified independently: A+ archive handling
is done/historical; PRO-narrative normalization backlog and the astro
context backlog are deliberately parked (no concrete validation question
/ prerequisite not yet met); `MACRO_DIP_BUDGET_MODE_V1` is the same
speculative concept parked in `live_like_vertical_slice.md`, recorded
once here with no Issue. No mega "parked backlog" Issue created. Status:
migrated.

### `signal_matrix_dashboard.md`

Verified `src/reporting/run_signal_matrix_static_dashboard_v1.py` does not
exist; the design doc (`docs/research/signal_matrix_static_dashboard_v1.md`)
does. Filed #297 (reporting) to implement per the existing design. Status:
migrated.

## 7. Architecture safety

- No new Issue crosses more than one architecture owner. Each of the 19
  Issues names exactly one of the eight approved owners.
- No Issue authorizes a shortcut from `research` or `reporting` directly
  into `decision_gate`/`execution_planner`/executor/broker/order state.
- `paper_candidate_contract.md`'s disposition (superseded by the canonical
  `strategy_proposal_contract_v1.md`) reinforces, not weakens, the
  research -> decision_gate boundary.
- The candle-ingestion activation Issue (#284) is the only Issue in this
  batch whose acceptance criterion is a real production timer-enable
  action. Per the independent-review correction (§9), #284 tracks the
  future controlled `public_candle_freshness` cutover on gurkDB — already
  recorded as human-accepted in
  `docs/ops/public_candle_freshness_gurkdb_acceptance_20260723.md` and the
  ownership registry — but the Issue's own creation and existence grant no
  runtime authorization; activation still requires separate explicit
  operational authorization at the time of the run.
- No legacy cross-layer shortcut text was found or preserved as valid
  architecture in any of the 13 files; multi-layer narration in
  `2026-05-19_product_cockpit_strategy_bundle.md`'s strategy-bucket
  section is documentation practice (explicit sequencing preserved), not
  an implemented bypass.

```text
architecture_boundary_violations=0
```

## 8. Retirement impact

```text
batch_6a_keep_temporarily_original=33
batch_6b_files_migrated=2
batch_6c_target_files=13
batch_6c_fully_migrated=12
batch_6c_partially_migrated=1
remaining_unowned_single_file_lanes=0
```

`remaining_unowned_single_file_lanes=0` counts only the single-file
`KEEP_TEMPORARILY` lanes targeted by this batch; the folder-based
`external_research/`, `market_intelligence/`, and `reporting/` lanes
(Batch 6D) and the 12 `ISSUE_OWNED (PARTIAL)` files (Batch 6E) are out of
scope and not counted here.

## 9. Independent review correction

Independent review of PR #299 found the original wording of Issue #284's
safety-boundaries section governance-ambiguous. The original text stated
that the Issue "explicitly authorizes" the already-approved production
timer cutover and carried:

```text
service_activation_not_performed=0
production_mutation_not_performed=0
```

This read as the Issue itself granting activation authorization, rather
than merely tracking future controlled cutover work that still requires
separate, explicit operational authorization at run time. The reviewer
corrected Issue #284 directly on GitHub to remove that ambiguity. #284
now carries:

```text
issue_creation_grants_runtime_authorization=0
activation_requires_explicit_operational_authorization=1
```

and explicitly states: "This Issue owns the future controlled cutover
work; it does not itself grant permission to mutate production runtime
state."

Summary:

- Issue #284 governance wording was corrected after initial Batch 6C
  creation.
- Scope and architecture owner remained `ops/runtime` — unchanged.
- No Issue ownership mapping changed; #284 remains the sole owner of the
  `deploy_runtime.md` candle-ingestion-activation scope.
- No runtime, service, timer, DB, or broker mutation was performed as
  part of this correction or its recording here.
- The correction restores the explicit boundary that Issue creation is
  never itself runtime authorization, consistent with every other Issue
  filed in this batch.

```text
issues_modified_during_initial_migration=0
issues_modified_during_independent_review=1
issues_modified_during_independent_review_numbers=284
```

## 10. Duplicate creation correction

During the first work session, `gh issue create` for the Breath Curve
scope was retried after an ambiguous/transient CLI response without first
confirming whether the first call had actually succeeded. Both calls
succeeded, producing two issues for the same scope. This was caught and
corrected before the session resumed further work:

```text
duplicate_issue_created=1
duplicate_issue_number=283
duplicate_of=282
duplicate_resolution=closed_state_reason_duplicate
canonical_owner=282
```

#283 is closed (`state=CLOSED`, verified via `gh issue view 283`) and is
not referenced by any source file or by `docs/todo/README.md`. All
canonical references point only to #282.

Process correction applied in the resumed session: every subsequent
`gh issue create` call was followed by `gh issue list`/`gh issue view`
verification of the exact returned URL before any retry was attempted,
and no further duplicates occurred across the remaining 10 create calls
(#288-#297).

## 11. Acceptance evidence

```text
source_files=13
source_files_fully_migrated=12
source_files_partially_migrated=1
existing_issues_inspected=46
existing_issues_reused=3
new_issue_create_events=20
unique_new_issues_created=19
new_issue_numbers=277,278,279,280,281,282,284,285,286,288,289,290,291,292,293,294,295,296,297
duplicate_issues_created=1
duplicate_issue_number=283
duplicate_issues_remaining_open=0
issues_modified_during_initial_migration=0
issues_modified_during_independent_review=1
issues_modified_during_independent_review_numbers=284
unmigrated_executable_scope_items=4
architecture_boundary_violations=0
source_files_deleted=0
source_files_moved=0
code_changes=0
test_changes=0
runtime_changes=0
database_changes=0
production_migrations_applied=0
broker_writes=0
order_submissions=0
service_timer_changes=0
```

`unmigrated_executable_scope_items=4` refers to
`multi_account_asset_foundation_backlog.md` Phases 2-5, each deliberately
deferred pending Phase 1 (#294) review, not omitted by oversight.
