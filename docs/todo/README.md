# Synth v2 TODO Index

## Purpose

`docs/todo/` is the working board for active and parked Synth v2 work.
Canonical architecture, research, status, and operations detail stays in its source documentation, but active task tracking must be represented here.

## Board rules

- Active and parked work belongs under `docs/todo/`.
- `docs/todo/README.md` owns the cross-lane execution order.
- Update the lane TODO and this index together when status or priority changes.
- Do not duplicate one task across multiple lane files.
- Completed lanes retain evidence and standing boundaries, not stale action bullets.

Workflow standard:

```text
docs/todo/workflow_standard.md
```

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

## Synth v2.23 execution order

Reference letters are stable names for easy discussion. Table order is the current execution order.

| Ref | Priority | Lane | What it is for | Board state | Next decision |
|---:|---:|---|---|---|---|
| **C** | P2 | Short Swing / runtime freshness hygiene | Make sure displayed pages are genuinely fresh and each public market-data writer capability has at most one authorized active host owner, with exactly one only after lifecycle `ACTIVE`. | current active lane — `public_candle_freshness` acceptance passed with 421/421 persisted coverage and zero Bitvavo EUR mismatch; production owner is authorized as gurkDB in `AUTHORIZED_INACTIVE`; devlap is disabled and Odroid candle units are masked | Merge the authorization change, deploy its exact merge to gurkDB, run one production service cycle, verify freshness and zero duplicate writers, then activate the timer. Rotation Pressure remains unchanged. |
| **E** | P0 | TODO reconciliation / board maintenance | Keep the repository board truthful so completed work, open work, priorities, and accepted deployment roadmaps are not lost or duplicated across chats. | ongoing maintenance; reconciliation merged in PR #92 | Keep `README.md` and each lane TODO synchronized whenever status, priority, or accepted deployment sequence changes. |
| **B** | P1 | IOST target lifecycle history truth | Stop a target that was already reached or passed from appearing as still `UPCOMING` after price pulls back below it. | contained / completed (original IOST defect) by PR #105; future monotonic hardening parked, evidence-gated | No active implementation PR. Reopen monotonic hardening only on real canonical evidence: a BTC `REACHED`/`PASSED`-then-pullback case or another explicitly approved canonical scope. |
| **A** | P1 | Profit Plan Live Ladder prerequisites | Make **Fix selected ladder** safe: trustworthy current-map rows, stable identities, fresh account data, and a reviewable server preview before any order mutation. | active, deliberately later | Resume after C unless a new dependency changes the order. |
| **D** | P3 | Research / FFG / scanners / cross-asset rotation | Find markets with improving participation, momentum reset, and enough target room without giving research or a scanner trading authority. | open, read-only, deliberately later | Resume as non-blocking research after C is controlled. |

Priority is execution order, not architectural importance.

Current shorthand:

```text
C first (current active lane)
E = ongoing board maintenance
B = contained; future evidence-gated hardening parked
A + D = later
```

Rotation Pressure runtime ownership, timers, freshness, disk/log bounds, rollback, and multi-cycle host acceptance belong to **C**. Rotation Pressure and cross-asset rotation research remain in **D**. Profit Plan **A** may later consume persisted pressure state read-only, but it must never trigger or own the writer.

The backtest capability contract and decision-gate account protections are cross-lane future-design guardrails. They do not change the current C/E/A/D execution order and authorize no runtime, account, or execution changes.

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

Keep this sequence synchronized with the implementation roadmap; do not create a duplicate Rotation Pressure TODO.

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

Multi-asset expansion is a separate blocked lane owned by
`native_short_multi_asset_rollout_contract_v1.md`. Its first proposed queue is
SOL -> ETH -> XRP, strictly one symbol at a time; the queue is not production
approval. The repository writer-provenance contract, the pure
scope-administration contracts, the forward-only schema, and the deterministic
`ADOPT_LEGACY_SCOPE` / `PROMOTE_SCOPE` / `REMOVE_SCOPE` repository transactions
are implemented; no production mutation, migration application, or operational
acceptance of those transactions has been performed. All 51 pre-contract writer
runs remain `LEGACY_UNATTRIBUTED`. One attributable BTC production run passed
devlap host acceptance, and its permanent evidence is reviewed in
`docs/ops/native_short_writer_provenance_operational_acceptance_20260717.md`;
`WRITER_PROVENANCE_UNATTRIBUTED` is closed by that evidence. Expansion remains
blocked on operational acceptance of the single-scope adoption/promotion/removal
transactions, writer commit-time fencing, `NO_CURRENT_MAP` bootstrap semantics,
and per-symbol failure isolation.

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
| `backtest_capability_contract_v1.md` | **future design P2 / cross-lane guardrail** | Machine-readable replay support, data scope, as-of, side-effect, and composition-preflight contract for backtestable components |
| `profit_plan_live_ladder.md` | **A — active P1 / later** | Safe prerequisites and ordered path from canonical ladder truth to authenticated preview, decision gate, execution plan, executor, and a tightly controlled live canary |
| `decision_gate_account_protections_v1.md` | **future design P2** | Account-aware drawdown, loss, stoploss-streak, and cooldown permission blocks inside `decision_gate`; no market ranking or execution authority |
| `credential_scope_and_manual_ladder_execution_boundary_v1.md` | open follow-up; credential contract migrated | Runtime wiring and execution-boundary tasks after canonical account-to-credential binding moved to `docs/architecture/account_credential_binding_contract_v1.md` |
| `profit_plan_target_lifecycle_history_truth_v1.md` | **B — contained/completed (original IOST defect) by PR #105; future monotonic hardening parked, evidence-gated** | Closure record: IOST never had canonical map/lifecycle truth; the transient-bridge reporting defect is contained by fail-closed handling. Future monotonic reached/passed hardening reopens only on real canonical evidence |
| `short_swing_linked_profile_freshness_and_disk_reliability_v1.md` | **C — open P2 / first (current active lane)** | Odroid/runtime ownership, absolute freshness timestamps, disk/log containment verification, rollout, and rollback hygiene |
| `momentum_flow_scanner_matrix_v1.md` | **D — open P3 research / later** | Read-only RSI/MFI momentum-flow scanner, target-room research gate, and validation path |
| `ffg_curated_rotation_radar_v1.md` | **D — open P3 research / later** | Curated-universe rotation radar, normalized flow and RSI/MFI confirmation, market-only classifications, and separate account ownership overlay |
| `sector_rotation_master_plan_v1.md` | **D — Phase A accepted; Phase B implementation complete for review; Phase B2 short audit open** | Research-only sector taxonomy, analytics, short market-filter candidate audit, dashboard, and optional future context sequence |
| `sector_taxonomy_database_seed_v1.md` | **D — Phase A done / accepted and activated** | Deterministic taxonomy, full enabled/research coverage, multi-cluster membership, and transactional metadata import |
| `sector_rotation_engine_v1.md` | **D — Phase B implementation complete for review; migration/write pending** | Participation, relative-strength, persistence, and proxy-rotation analytics |
| `sector_rotation_dashboard_v1.md` | **D — open / next after accepted Phase B snapshots** | Future read-only taxonomy and sector-rotation inspection surface |
| `cross_asset_metals_miners_food_rotation_v1.md` | **D — open P3 research / later** | Public-data-first metals, miners, and food/agriculture rotation research with manual broker execution and optional future IBKR API work in a separate lane |
| `profit_plan_dashboard_action_truth_and_breathline_demote_v1.md` | done / parked | Completed Profit Plan action fail-closed, PPP, map-switch, Breathline, evidence-row, and formatting guardrails |
| `native_short_runtime_owner_and_scope_status_v1.md` | repository unit and database least-privilege contracts/preflights complete; ownership and activation UNASSIGNED | Completed Native SHORT scope/map implementation and canonical devlap unit reconciliation; dedicated DB identity provisioning/grant acceptance and installed equivalence remain blockers |
| `native_short_map_level_status_v1.md` | done / parked | Completed native SHORT current map-level status contract and implementation evidence |
| `native_short_multi_asset_rollout_contract_v1.md` | blocked; ADOPT/PROMOTE/REMOVE repository transactions implemented, provenance accepted, writer commit-time fencing and operational acceptance pending | Canonical multi-asset readiness audit, scope-administration ownership, sequential SOL/ETH/XRP review queue, and blocked rollout sequence |
| `position_rotation_preview.md` | MVP implemented / parked follow-up | Account-aware read-only cockpit/rotation preview; no active v2.23 priority |
| `profit_plan_card_evidence_delta_visibility_v1.md` | done / parked | Deterministic current-vs-previous card evidence visibility |
| `manual_ladder_dashboard.md` | historical source / superseded | Earlier read-only ladder direction; active ladder work is tracked only in `profit_plan_live_ladder.md` |
| `deploy_runtime.md` | MVP cockpit implemented / ops follow-up | General Odroid cockpit and deployment follow-ups |
| `market_breath.md` | characterized / parked | Regime-dependent rhythm/phase research |
| `regime_research.md` | parked | Rotation replay, discovered regimes, symbol profiles, and interaction audits |
| `fibo_zones.md` | open research | Fib target maps, zone validation, and overlays |
| `ui_webview.md` | open / secondary | Non-blocking UI and styling work after correctness lanes |
| `signal_matrix_dashboard.md` | parked | Transparent primitive signal inventory |
| `breath_curve.md` | parked / open | Breath Curve validation continuation |
| `strategy_candidates.md` | parked / open research | Strategy audit and later classifier/policy research |
| `replay_parameter_study_harness_v1.md` | **D — planning / strategy-validation sublane** | Minimal market-only replay contracts, immutable provenance, Selection v2 point-in-time adapter, versioned evaluator, and one bounded score-weight grid study |
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
