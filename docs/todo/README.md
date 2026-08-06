# Synth v2 TODO Index

Status: **MIGRATION_FROZEN — legacy migration inventory only**

## Purpose

This file is a **read-only migration inventory** of pre-existing `docs/todo/`
lanes. It no longer defines work intake, status, priority, or execution order.

GitHub Issues are the operational work inventory for Synth v2. The table below
is retained only so that each legacy lane can receive exactly one reviewed
`issue`, `canonical`, `archive`, or `remove` disposition. Priority and board
state recorded here are a **historical snapshot as of the freeze**, not current
truth, and must not be resynchronised.

## Board rules

- Do not add new work to this index or create new TODO lane files.
- Do not resume status, priority, or execution-order synchronisation here.
- New executable work belongs in GitHub Issues.
- Current status, priority, and execution order are owned by GitHub Issues.
- Existing entries may be edited only to correct unsafe or materially false
  information, point to an owning Issue, or record a reviewed disposition.
- Preserve unique PR, commit, runtime-acceptance, and rollback evidence before
  any lane is moved or removed.

Canonical workflow:

```text
docs/development/github_issues_workflow.md
```

Migration constraints and allowed dispositions:

```text
docs/todo/MIGRATION_FREEZE.md
```

Legacy vocabulary needed to read the frozen entries below (`P0`-`P4` and the
`active` / `open` / `parked` / `blocked` / `backlog` / `future design` states)
is retained in `docs/todo/workflow_standard.md`.

## Global boundaries

Unless a lane explicitly states otherwise:

- no live trading
- no broker writes
- no order submission
- no executor changes
- no shortcuts across architecture layers
- research remains market-only and account-agnostic

Architecture split:

```text
selection_engine  = market-only candidate ranking
decision_gate     = account-aware permission and conflict resolution
execution_planner = immutable execution intent only
executor / agents = order handling only
```

Reporting/UI may never call the broker directly.

## Synth v2.23 lane inventory (frozen snapshot)

Reference letters are stable names for easy discussion. This table is a frozen
historical snapshot captured at the migration freeze. Table order is **not** a
current execution order and must not be updated; each row is pending exactly
one reviewed `issue` / `canonical` / `archive` / `remove` disposition.

| Ref | Priority | Lane | What it is for | Board state | Next decision |
|---:|---:|---|---|---|---|
| **C** | P2 | Short Swing / runtime freshness hygiene | Make sure displayed pages are genuinely fresh and each public market-data writer capability has at most one authorized active host owner, with exactly one only after lifecycle `ACTIVE`. | current active lane — `public_candle_freshness` acceptance passed with 421/421 persisted coverage and zero Bitvavo EUR mismatch; production owner is authorized as gurkDB in `AUTHORIZED_INACTIVE`; devlap is disabled and Odroid candle units are masked; Native SHORT filesystem publisher/reader separation is implemented for review while its owner/activation remain `UNASSIGNED` | Merge the public-candle authorization change, deploy its exact merge to gurkDB, run one production service cycle, verify freshness and zero duplicate writers, then activate that timer; separately provision/accept the Native SHORT distinct reader identity/group before any owner selection or activation. Rotation Pressure remains unchanged. |
| **E** | — | TODO reconciliation / board maintenance | Historical lane that kept the legacy board truthful before GitHub Issues existed. | **closed by the migration freeze** — superseded by `docs/development/github_issues_workflow.md`; reconciliation merged in PR #92 | None. Do not resynchronise this index. Remaining migration work is tracked in `docs/development/github_issues_migration_proposal_v1.md` and its Issues. |
| **B** | P1 | IOST target lifecycle history truth | Stop a target that was already reached or passed from appearing as still `UPCOMING` after price pulls back below it. | contained / completed (original IOST defect) by PR #105; future monotonic hardening parked, evidence-gated | No active implementation PR. Reopen monotonic hardening only on real canonical evidence: a BTC `REACHED`/`PASSED`-then-pullback case or another explicitly approved canonical scope. |
| **A** | P1 | Profit Plan Live Ladder prerequisites | Make **Fix selected ladder** safe: trustworthy current-map rows, stable identities, fresh account data, and a reviewable server preview before any order mutation. | active, deliberately later | Resume after C unless a new dependency changes the order. |
| **D** | P3 | Research / FFG / scanners / cross-asset rotation | Find markets with improving participation, momentum reset, and enough target room without giving research or a scanner trading authority. | open, read-only, deliberately later | Resume as non-blocking research after C is controlled. |

Priority values above are the frozen historical snapshot. Current priority and
execution order are owned by GitHub Issues.

Frozen shorthand at the time of the freeze:

```text
C first (current active lane)
E = ongoing board maintenance
B = contained; future evidence-gated hardening parked
A + D = later
```

Rotation Pressure runtime ownership, timers, freshness, disk/log bounds, rollback, and multi-cycle host acceptance belong to **C**. Rotation Pressure and cross-asset rotation research remain in **D**. Profit Plan **A** may later consume persisted pressure state read-only, but it must never trigger or own the writer.

The backtest capability contract and decision-gate account protections are cross-lane future-design guardrails. They did not change the frozen C/E/A/D snapshot above and authorize no runtime, account, or execution changes.

## Lane C — Rotation Pressure runtime-owner operational sequence

**Steps 1-3 below (the Rotation Pressure runtime-owner operational sequence
itself) are CLOSED.** This closes only that specific sequence, not the
broader **C** lane (Short Swing / Odroid freshness hygiene), which may still
have unrelated open work tracked elsewhere. Full acceptance evidence is
recorded in `docs/ops/market_rotation_pressure_runtime_owners_v1.md`
("Host Activation & Multi-Cycle Acceptance Evidence").

This entry preserves the historical Rotation Pressure acceptance record from
`docs/ops/market_rotation_pressure_runtime_owners_v1.md`. It no longer assigns
devlap production ownership. The devlap writer acceptance and Odroid
read-only publisher evidence are historical/SUPERSEDED production-authorization
context; current canonical `market_rotation_pressure.production_runtime_owner`
is `UNASSIGNED`.

1. **Devlap acceptance** — DONE
   - use existing implementation only;
   - run the writer in a controlled way;
   - reconstruct devlap acceptance evidence (idempotency and reconciliation);
   - make no timer changes.
2. **Separate Runtime Owner PR** — DONE — repository-reviewed candidate
   recorded in `docs/ops/market_rotation_pressure_runtime_owners_v1.md`
   (merged PR #101).
   - record devlap writer acceptance as historical evidence only;
   - record Odroid publisher acceptance as historical read-only publication
     evidence only;
   - specify exact rollback;
   - assign no reporting ownership;
   - assign no Profit Plan ownership.
3. **Separate host acceptance** — DONE
   - accept the devlap writer first;
   - accept the Odroid publisher second;
   - observe multiple cycles — 3 of 3 real cycles PASS (18:00, 19:00, 20:00
     UTC on 2026-07-15), independently verified via per-invocation
     `LastTriggerUSec`/`InvocationID` correlation, not `TriggeredBy=` alone;
   - verify multi-cycle freshness, idempotency, duplicate prevention, lock behavior, and disk/log growth bounds — all PASS;
   - verify rollback — canonical rollback commands confirmed available and
     correctly scoped; not exercised (no failure occurred requiring it).
4. **Profit Plan lightbar** — remains DEFERRED
   - remains deferred, reporting-only follow-up work;
   - consumes persisted data only, read-only;
   - must never trigger or own the writer.

This sequence is a frozen historical record and is no longer synchronized with
the implementation roadmap. Any remaining Rotation Pressure work belongs to a
GitHub Issue; do not create a duplicate Rotation Pressure TODO.

## Sequencing rationale

The original Lane-B correctness work is no longer a prerequisite for C:

- **B is contained, not blocking.** PR #105 contained the non-canonical IOST reporting defect by failing closed when canonical native SHORT map and scope-status truth is unavailable. The accepted read-only forensic audit proved IOST never had a canonical scope, map, cycle, activation boundary, or lifecycle state — so there was no canonical lifecycle to regress and no active canonical IOST defect remains. Future monotonic-lifecycle hardening reopens only on real canonical evidence (a BTC `REACHED`/`PASSED`-then-pullback case or another explicitly approved canonical scope).
- **C is the current operational prerequisite.** It establishes absolute freshness, installed-host ownership, disk/log bounds, and multi-cycle acceptance that A must later trust. Its implementation surface is smaller than A, although multi-cycle observation may require elapsed runtime rather than more code.
- **A is the larger and higher-risk lane.** It spans canonical ladder consumption, deterministic row identity, authenticated preview, `decision_gate`, `execution_planner`, executor behavior, broker mutation, reconciliation, and a controlled live canary. C must still precede A so that A never builds execution authority on freshness or host-ownership assumptions that are still unresolved.

Therefore the working order is:

```text
C freshness and host acceptance
-> A manual ladder-to-trade path
(B contained; future evidence-gated hardening parked)
```

Making C the current active lane reduces ambiguity and prevents A from building execution authority on freshness or host-ownership assumptions that are still unresolved.

## Native SHORT baseline

The native SHORT map-level runtime line is **done / accepted** in repository scope.

A separate, additive companion ledger (append-only REACHED/PASSED target-event
history, prospective-only, authorized under the Synth Outcome & Reliability
Program) is documented in
`docs/architecture/native_short_map_level_status_contract_v1.md` and does not
change this baseline's status, priority, or reopen criteria; no canonical
BTC/IOST regression evidence was found or is implied.

Multi-asset expansion is a separate in-progress lane owned by
`native_short_multi_asset_rollout_contract_v1.md`. Its first proposed queue is
SOL -> ETH -> XRP, strictly one symbol at a time. SOL is promoted in
production (`docs/ops/native_short_sol_promotion_operational_acceptance_v1.md`)
and `PROMOTION_CONTRACT_MISSING` is closed globally; ETH and XRP are
explicitly, separately human-approved as the next two canaries
(`docs/ops/native_short_{eth,xrp}_bootstrap_promotion_approval_v1.md`) but not
yet production-promoted. `BOOTSTRAP_ORCHESTRATION_BLOCKED` and
`MULTI_SCOPE_FAILURE_ISOLATION_MISSING` remain unconditionally active in the
canonical audit evaluator; ETH/XRP reach the administration-decision layer
only via their own reviewed bootstrap-manifest entries, the same one-time
mechanism SOL used. All 51 pre-contract writer runs remain
`LEGACY_UNATTRIBUTED`. One attributable BTC production run passed devlap host
acceptance, and its permanent evidence is reviewed in
`docs/ops/native_short_writer_provenance_operational_acceptance_20260717.md`;
`WRITER_PROVENANCE_UNATTRIBUTED` is closed by that evidence.

Merged completion chain:

```text
PR #74 cadence profile seed
PR #71 map-level persistence
PR #76 map-level materializer
PR #77 map-level runner
PR #81 runner interruption/observability follow-up
PR #79 scope-status chain integration
PR #87 canonical runtime wiring
```

Accepted evidence:

- PR-branch host acceptance: PASS
- post-merge `origin/main` acceptance: PASS
- current `origin/main` is `38ce625` or newer
- writer-provenance operational acceptance: PASS (PR #118; run
  `b07d897d-6574-4380-98c3-8145c5c41b30`)
- local cleanup complete
- no broker/account/order/decision/planning/execution path was introduced

Installed-host service/timer activation was not part of that closure. Any activation or installed-unit change remains a separate P2 operational action with explicit review.

## Lane index

| File | Status | Purpose |
|---|---:|---|
| `README.md` | **E — ongoing board maintenance** | Cross-lane execution order, status reconciliation, and stable A–E references |
| `workflow_standard.md` | standard | TODO creation, update, closure, priority, boundary, and commit rules |
| `backtest_capability_contract_v1.md` | **future design P2 / cross-lane guardrail** — migrated: status/priority now owned by Issue #218 | Machine-readable replay support, data scope, as-of, side-effect, and composition-preflight contract for backtestable components |
| `profit_plan_live_ladder.md` | **A — active P1 / later** | Safe prerequisites and ordered path from canonical ladder truth to authenticated preview, decision gate, execution plan, executor, and a tightly controlled live canary |
| `manual_execution_ladder_future_readiness_backlog_v1.md` | **A — P0 items 1-6 remediation reviewed BLOCK/REJECT (2026-07-25); item 7 (F12) request contract + canonical service entrypoint implemented (2026-07-26), reservation/reconciliation/live wiring still open** — migrated: status/priority now owned by Issues #202, #203, #206 | Prioritized remediation backlog from the manual execution ladder future-readiness audit (`docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md`); feeds into lane A, does not reorder it |
| `decision_gate_account_protections_v1.md` | **future design P2** | Account-aware drawdown, loss, stoploss-streak, and cooldown permission blocks inside `decision_gate`; no market ranking or execution authority |
| `credential_scope_and_manual_ladder_execution_boundary_v1.md` | open follow-up; credential contract migrated — migrated: status/priority now owned by Issue #206 | Runtime wiring and execution-boundary tasks after canonical account-to-credential binding moved to `docs/architecture/account_credential_binding_contract_v1.md` |
| `profit_plan_target_lifecycle_history_truth_v1.md` | **B — contained/completed (original IOST defect) by PR #105; future monotonic hardening parked, evidence-gated** | Closure record: IOST never had canonical map/lifecycle truth; the transient-bridge reporting defect is contained by fail-closed handling. Future monotonic reached/passed hardening reopens only on real canonical evidence |
| `short_swing_linked_profile_freshness_and_disk_reliability_v1.md` | **C — open P2 / first (current active lane)** — migrated: status/priority now owned by Issue #201 | Odroid/runtime ownership, absolute freshness timestamps, disk/log containment verification, rollout, and rollback hygiene |
| `momentum_flow_scanner_matrix_v1.md` | **D — open P3 research / later** | Read-only RSI/MFI momentum-flow scanner, target-room research gate, and validation path |
| `ffg_curated_rotation_radar_v1.md` | **D — open P3 research / later** | Curated-universe rotation radar, normalized flow and RSI/MFI confirmation, market-only classifications, and separate account ownership overlay |
| `sector_rotation_master_plan_v1.md` | **D — Phase A/B accepted; dashboard Phase C1 implemented; Phase B2 short audit open** | Research-only sector taxonomy, analytics, short market-filter candidate audit, dashboard, and optional future context sequence |
| `sector_taxonomy_database_seed_v1.md` | **D — Phase A done / accepted and activated** | Deterministic taxonomy, full enabled/research coverage, multi-cluster membership, and transactional metadata import |
| `sector_rotation_engine_v1.md` | **D — Phase B accepted; migration applied and persisted cohort accepted** | Participation, relative-strength, persistence, and proxy-rotation analytics |
| `sector_rotation_dashboard_v1.md` | **D — Phase C1 implemented / ready for review** — migrated: status/priority now owned by Issue #204 | Read-only Sector Overview publisher over accepted Phase B snapshots; later dashboard capabilities remain open |
| `cross_asset_metals_miners_food_rotation_v1.md` | **D — open P3 research / later** | Public-data-first metals, miners, and food/agriculture rotation research with manual broker execution and optional future IBKR API work in a separate lane |
| `profit_plan_dashboard_action_truth_and_breathline_demote_v1.md` | done / parked | Completed Profit Plan action fail-closed, PPP, map-switch, Breathline, evidence-row, and formatting guardrails |
| `native_short_runtime_owner_and_scope_status_v1.md` | repository unit/database contracts complete; chain-scoped DB runtime binding and filesystem publisher/reader separation implemented for review; ownership and activation UNASSIGNED | Completed Native SHORT scope/map implementation and canonical devlap unit reconciliation; external DB secret/identity acceptance plus filesystem reader-group/distinct-UID host acceptance remain blockers |
| `native_short_map_level_status_v1.md` | done / parked | Completed native SHORT current map-level status contract and implementation evidence |
| `native_short_multi_asset_rollout_contract_v1.md` | in progress; SOL promoted and accepted, ETH/XRP approved (not yet promoted), bootstrap manifest generalized to a reviewed list — migrated: status/priority now owned by Issues #198, #199, #200 | Canonical multi-asset readiness audit, scope-administration ownership, sequential SOL->ETH->XRP rollout, bootstrap/isolation blockers still unconditionally active |
| `position_rotation_preview.md` | MVP implemented / parked follow-up | Account-aware read-only cockpit/rotation preview; no active v2.23 priority |
| `profit_plan_card_evidence_delta_visibility_v1.md` | done / parked | Deterministic current-vs-previous card evidence visibility |
| `manual_ladder_dashboard.md` | historical source / superseded | Earlier read-only ladder direction; active ladder work is tracked only in `profit_plan_live_ladder.md` |
| `deploy_runtime.md` | MVP cockpit implemented / ops follow-up | General Odroid cockpit and deployment follow-ups |
| `market_breath.md` | characterized / parked | Regime-dependent rhythm/phase research |
| `regime_research.md` | parked | Rotation replay, discovered regimes, symbol profiles, and interaction audits |
| `fibo_zones.md` | **P0 repository-ready / activation pending** | Recurring canonical 4h FibNavigationMap publication and existing cockpit visibility; merge/deploy/controlled activation remains |
| `ui_webview.md` | open / secondary | Non-blocking UI and styling work after correctness lanes |
| `signal_matrix_dashboard.md` | parked | Transparent primitive signal inventory |
| `breath_curve.md` | parked / open | Breath Curve validation continuation |
| `strategy_candidates.md` | parked / open research | Strategy audit and later classifier/policy research |
| `replay_parameter_study_harness_v1.md` | **D — planning / strategy-validation sublane** — migrated: status/priority now owned by Issue #205 | Minimal market-only replay contracts, immutable provenance, Selection v2 point-in-time adapter, versioned evaluator, and one bounded score-weight grid study |
| `multi_horizon_fib_dashboard_backlog.md` | parked | Dashboard follow-up depending on fib research outputs |
| `paper_candidate_contract.md` | future design | Safe adapter from validated research candidates to `decision_gate` |
| `dev_ops_hygiene.md` | mostly parked | Development, database-access, backup, worktree hygiene |
| `parked_backlog.md` | backlog | Archived A+ and external-narrative follow-ups |
| `watchlist_candidates.md` | open intake | Human-thesis watchlist intake before validation |

## Next-step rule

With the reconciliation merged:

1. Execute C first (current active lane).
2. Keep E running as board maintenance.
3. Keep A and D for later.
4. Do not reopen B without real canonical lifecycle evidence — a BTC `REACHED`/`PASSED`-then-pullback case or another explicitly approved canonical scope.
5. Do not reopen native SHORT implementation work unless new evidence identifies a concrete defect.
6. Do not create several parallel implementation chats merely because the board lists several lanes.

## Pre-live safety state

Until an explicitly reviewed live-canary phase is reached:

```text
broker_writes=0
order_submission=0
executor=none
```
