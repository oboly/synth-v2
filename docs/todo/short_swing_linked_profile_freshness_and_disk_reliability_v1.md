# TODO — Short Swing Linked-Profile Freshness and Disk Reliability

> **Migration pointer.** Current execution status, priority, blockers, and
> next action for this lane are owned by GitHub Issue
> [#201 — Complete linked-profile freshness and multi-cycle runtime acceptance](https://github.com/oboly/synth-v2/issues/201).
> This file is retained as frozen historical/design context; do not update
> status, priority, or execution order here. See
> `docs/development/github_issues_first_batch_migration_v1.md`.

## Status

```text
open P2 operational / freshness hygiene
```

This lane originated from the 2026-07-05 Odroid disk-exhaustion and stale-static-page incident. Repository implementation has progressed, but installed-host activation and multi-cycle operational acceptance remain separate and must not be inferred from merged templates alone.

## 2026-07-18 public market-data ownership correction

Odroid validates and consumes persisted public prices/candles and retains only
account-refresh, account-snapshot persistence, reporting, and publication
responsibilities. The linked-profile orchestrator therefore keeps its intended
account/render ownership but loses its public-price writer stage.

## 2026-07-19 host-ownership contract correction

The earlier "devlap is the sole public market-data database writer" target is
retired. Each writer capability has at most one authorized active owner, and
exactly one only when its lifecycle is `ACTIVE`. All four capabilities are
`UNASSIGNED` by this correction, including `market_rotation_pressure`. Its
devlap acceptance (PR #100/#101) and last observed installed active timer are
preserved as historical audit context (SUPERSEDED as production authorization);
acceptance evidence and observed runtime state do not grant production
ownership. devlap is a candidate/acceptance host and gurkDB a preferred
candidate, not a proven owner. See
`docs/ops/writer_capability_host_ownership_contract_v1.md` and
`deploy/ownership/writer_capability_ownership_v1.json`. The Odroid
consumer/publisher split above is unchanged.

An installed timer may continue running operationally even after canonical
authorization is reset. Repository correction does not stop that timer.
Containment requires a separately authorized host action.

Host rollout remains open and must follow
`docs/ops/public_market_data_runtime_owners_v1.md`. No deployment or renewed
Native SHORT operational acceptance is claimed by the repository change.

Account-owner cleanup remains separate:

- `synth-linked-profile-runtime-refresh.timer` remains the intended linked
  profile account/render owner;
- `synth-mvp-account-refresh.timer` is a distinct duplicate-account-owner
  retirement task with its own evidence and rollback;
- website registration ownership is unchanged.

## Sources

```text
docs/incidents/2026-07-05_odroid_disk_exhaustion_and_stale_short_swing_data.md
docs/ops/synth_runtime_runners_v1.md
docs/ops/runtime_chain_ownership_v1.md
docs/ops/runtime_freshness_audit_v1.md
docs/ops/linked_profile_runtime_orchestrator_v1.md
docs/architecture/dashboard_time_display_policy_v1.md
```

## Completed repository work

### Disk/log containment

PR #54 merged the bounded candle-ETL logging and pre-run disk/log health gate.
Standing facts:

- default output is bounded;
- verbose per-market/per-gap output is debug-only;
- checkpoint state is persisted separately from journal volume;
- disk pressure can fail visibly before ETL;
- `synth-paper-advice-lifecycle-refresh.timer` must not be re-enabled as an implicit fallback.

The earlier production-connected smoke was write-capable even though inserts were later disproven. Future validation must use an explicit no-write path, isolated database, fixtures, or a separately authorized production operation.

### Linked-profile orchestration candidate

PR #72 merged one repository-level owner candidate for:

```text
disk health
-> public price snapshot
-> linked-profile discovery
-> read-only account refresh per profile
-> persisted-snapshot render per profile
```

The orchestrator keeps public ingestion, account ingestion, and rendering as separate modules and adds one global lock.
Repository systemd files are templates; their presence is not installed-host acceptance.

### Native SHORT runtime line

PR #87 closed the repository runtime wiring implementation for native SHORT reusing the existing 4h chain shape.
This is historical implementation evidence only. Production host ownership is now UNASSIGNED in the ownership
registry (`deploy/ownership/writer_capability_ownership_v1.json`, `native_short_4h_chain.production_runtime_owner=UNASSIGNED`);
there is no current canonical/production 4h owner. Installed service/timer activation was explicitly not performed and
remains separate from this lane's repository closure.

## P2-A — Installed-host ownership and activation truth

Before any installed-unit mutation:

1. inspect the actual Odroid checkout, branch/commit, service files, environment, and paths;
2. record `systemctl is-active` and `systemctl is-enabled` for relevant old and new units;
3. prove one owner per pipeline and no unordered duplicate timers;
4. keep the paper-advice lifecycle timer inactive/disabled unless a separate acceptance explicitly changes that decision;
5. run manual one-shots with timers disabled;
6. inspect bounded logs, locks, metadata, and rendered outputs;
7. define exact rollback before enabling or restarting anything.

Installed-host changes require explicit instruction. This docs lane authorizes none.

### Proven installed-host ownership — 2026-07-15 read-only audit

A read-only Odroid audit (host repo HEAD `4dce019`, equal to `origin/main` at audit time) established the current ownership truth. No host unit was mutated.

Two parallel 5-minute render owners are active for the same linked-profile runtime path:

```text
SYSTEM-level (safe, PR #72):
  synth-linked-profile-runtime-refresh.timer   active/enabled (~5 min)
  -> run_linked_profile_runtime_orchestrator_once.sh
  -> run_account_wallet_snapshot_dashboard_render_once.sh
     renders wallet + open-orders only
     prints profit_plan_render=disabled reason=NATIVE_SHORT_SNAPSHOT_CONTRACT_NOT_PERSISTED
     latest_run.json overall_result=ok, snapshot_render.success=2

USER-level (legacy, systemctl --user, cgroup user@1000.service):
  synth-account-wallet-dashboard@{joost,hugo}.timer  active (~5 min)
  -> run_account_wallet_dashboard_render_once.sh
     builds native SHORT context IN-RENDER (forbidden by PR #72)
     renders wallet + open-orders + Profit Plan
     calls run_manual_short_trader_profit_plan_v1 WITHOUT --previous-json
  synth-account-wallet-refresh@{joost,hugo}.timer    active (private read-only account refresh)
```

Proven consequences:

- The user-level legacy renderer is the live Profit Plan writer. Confirmed: joost `profit-plan.json` rewritten `2026-07-15T20:15:09Z`, `render_id=2d8621af…`, and 53/53 symbols `delta_status=NO_PREVIOUS_SNAPSHOT` because `--previous-json` is never passed.
- Both owners render wallet + open-orders, so those pages are written twice per cycle by two independent, unordered timers — the anti-pattern flagged as P0-B in `docs/ops/synth_runtime_runners_v1.md` and forbidden by the "Old timer disposition" rule in `docs/ops/linked_profile_runtime_orchestrator_v1.md`.

Corrections to earlier assumptions:

- `synth-account-wallet-dashboard@` and `synth-account-wallet-refresh@` are **user-level** (`systemctl --user`) units; system-level `is-enabled` returns `not-found` and `/etc/systemd/system` contains no reference. Any retirement is a `systemctl --user disable --now` action.
- `synth-static-dashboard.service` is **only** `python3 -m http.server` (the static webserver on port 5002); it is not a Profit Plan writer.

Host retirement targets (separate rollout, not authorized here). Both user-level unit families duplicate the system-level orchestrator and are retired **only after** the replacement path (orchestrator + PR B) is accepted:

- `synth-account-wallet-dashboard@{joost,hugo}` — legacy render + Profit-Plan-without-deltas + duplicate wallet/open-orders render (duplicates the orchestrator's `render_snapshot_dashboard` stage).
- `synth-account-wallet-refresh@{joost,hugo}` — private read-only account refresh (duplicates the orchestrator's `refresh_account_snapshot` stage).
- `synth-mvp-account-refresh.timer` — separate account-snapshot owner whose
  duplicate-owner retirement must not be folded into public market-data work.

Each family has its own rollback: re-enable that specific user-level family (`systemctl --user enable --now …`) independently if the corresponding replacement stage regresses. No host unit is mutated by this lane.

## P2-B — Absolute freshness authority

The renderer and any account-aware gate must consume persisted observations, not frozen presentation strings.

Required data classes:

```text
market_price_observed_ts_utc
wallet_observed_ts_utc
position_observed_ts_utc
open_orders_observed_ts_utc
dashboard_generated_ts_utc
```

Each class exposes an explicit status:

```text
FRESH
STALE
MISSING
UNAVAILABLE
```

Rules:

- relative age may be displayed only when derived client-side from an absolute timestamp;
- static HTML must never make stopped rendering look newly fresh;
- stale wallet, position, or open-order truth suppresses account-specific ladder/action claims;
- market-only context may remain visible under its own freshness contract;
- `decision_gate` consumes persisted freshness authority or a pure evaluator over it, never renderer HTML/JSON.

This requirement is a prerequisite for safe Profit Plan Live Ladder authority but remains operationally owned here rather than duplicated in its guardrail history file.

### Implemented — pure freshness-status classifier (repository)

`src/operations/freshness_status_v1.py` implements the pure, deterministic P2-B
classifier: `evaluate_freshness(...)` classifies one source into `FRESH | STALE |
MISSING | UNAVAILABLE`, and `evaluate_observation_classes(...)` reduces
caller-supplied classes to an overall freshness status. Scope is freshness only —
it computes **no** account/ladder/order permission; account-aware permission
stays exclusively in `decision_gate` (a later, separately reviewed wiring slice).

- No DB, broker, account-mutation, rendering, permission, or wall-clock
  dependency (`now` is always injected), so a stopped static renderer cannot
  fabricate freshness — a frozen `dashboard_generated_ts_utc` ages against an
  advancing `now` and deterministically becomes `STALE`.
- No built-in staleness thresholds: no canonical doc defines per-class P2-B
  limits (the only canonical freshness limits are native-SHORT-specific:
  `native_short_scope_status_contract_v1.md`), so callers must pass explicit
  `ObservationClassSpec` thresholds; the module ships none.
- Fail-closed timestamps: requires timezone-aware UTC and rejects naive
  datetimes with `ValueError`, matching the DB-boundary UTC-typing contract
  (`native_short_fib_context_snapshot_contract_v1.md`) and `docs/coding_standards.md`
  §3 ("never mix timezone-aware and naive timestamps in engine logic").

`decision_gate` and reporting may both import it (it lives outside both layers);
renderer HTML/JSON is never an input. Boundary tests:
`tests/test_freshness_status_v1.py`. This slice does **not** consume the PR A
snapshot and wires the classifier into no live gate.

## P2-C — Multi-cycle Odroid acceptance

Measure over several consecutive real cycles:

- runtime duration versus cadence;
- non-overlap and lock behavior;
- per-stage success/failure metadata;
- Joost and Hugo snapshot/render freshness;
- filesystem free space trend;
- journal/log growth in bytes per day;
- stale-source fail-closed behavior;
- rollback behavior.

A single manual run is not multi-cycle acceptance.

Status (2026-07-17): manual host acceptance = PASS (two manual cycles + lock test, see P2-A/host rollout). Multi-cycle P2-C acceptance across several consecutive real scheduled cycles remains **OPEN** and must not be inferred from the two manual runs.

## P2-D — Deferred runtime-host capacity decision

The Odroid remains the current runtime host until explicitly changed.
A later dedicated runtime server may be evaluated, but the database host and runtime host should remain separate failure domains.
Host replacement does not substitute for fixing ownership, freshness, and logging on the current host.

### 2026-07-26 repository filesystem-separation follow-up

The canonical Native SHORT snapshot publication path now has a repository-side
publisher/reader filesystem contract implemented for review:

```text
publisher=gurk
reader_group=synth-native-short-readers
raw_reader=theone
same_uid_reporting_consumer=forbidden
www-data_raw_access=not_required
```

The publisher applies deterministic setgid/read-only modes independent of
umask, and the new strictly read-only
`src.operations.run_native_short_snapshot_filesystem_preflight_v1` proves
owner/group/mode, parent traversal, symlink/escape denial, ACL absence,
publisher writes, consumer reads/write rejection, exact distinct identities,
and snapshot digests. The observed `0600` artifacts and any consumer running
as `gurk` remain host-acceptance failures.

This repository change performs no chmod/chown/setfacl, user/group creation,
publication, deployment, owner assignment, or activation.
`native_short_4h_chain` ownership and lifecycle remain `UNASSIGNED`; host
identity/group provisioning and a passing exact-host preflight are still
required in a separately authorized lane.

## Forward implementation plan — Profit Plan runtime ownership and native SHORT snapshot (PR A / PR B)

Two separate repository PRs, sequenced PR A before PR B (PR B consumes PR A's snapshot). Neither is implemented by this docs lane and neither performs host mutations. This is deliberately not a cosmetic or temporary owner-fix: the legacy in-render native SHORT build and the missing card deltas are corrected only by the persisted contract plus safe owner below — never by re-pointing a timer at the legacy renderer, and never by passing `--previous-json` into the legacy in-render path.

### Why the persisted contract is required first

`run_manual_short_trader_profit_plan_v1` reads native SHORT context only from a CSV rows file (`load_native_short_context_rows(path)`); it has no DB-backed loader. The only current producers of `native_short_fib_context_rows_v1.csv` are the two legacy render scripts (in-render build — forbidden by PR #72) and the manual research default. The accepted 4h owner persists native SHORT truth to the DB authorities `native_short_scope_status_v1` and `native_short_map_level_status_v1` (see `native_short_runtime_owner_and_scope_status_v1.md`), but nothing projects those into the persisted rows snapshot the reporting layer consumes. That missing projection is the "later slice" named in `docs/ops/linked_profile_runtime_orchestrator_v1.md`.

### PR A — market-only persisted native SHORT snapshot contract

Repository implementation is now defined by
`docs/architecture/native_short_fib_context_snapshot_contract_v1.md` and the
market-data runner wired into the existing 4h owner. Merge/review acceptance and
runtime-host publication remain separate; PR B must not start consuming the
snapshot until PR A is merged and accepted.

#### 2026-07-16 read-only reconciliation

A read-only repository + Odroid audit updated the state below. No host unit,
timer, checkout, or snapshot was mutated (`host_mutations=0`).

- **Repository merged.** PR A merged as **PR #106** (`6b5f3ee`). The earlier
  README/board wording "PR A repository implementation in review" is stale.
- **Installed on host.** Odroid `/home/theone/projects/synth-v2` HEAD is exactly
  `6b5f3ee` (the PR #106 merge; behind current `origin/main`). The publisher runs
  as one step in `scripts/run_chain_4h.sh` under the single 4h scheduler
  `synth-4h-market-chain.timer` — no second scheduler.
- **Canonical output present and valid.** `/var/www/html/synth/_runtime/native_short_context_snapshot_v1/manifest_v1.json`
  reports `publication_result=PUBLISHED`, `overall_freshness_state=FRESH`,
  content digest, and an immutable `native_short_fib_context_rows_v1.csv` (BTC
  row, `NATIVE_SHORT_CONTEXT_AVAILABLE`). At least five distinct `snapshot_id`
  directories exist, i.e. multiple cycles have published. This supersedes the
  2026-07-15 P2-A note that the orchestrator printed
  `NATIVE_SHORT_SNAPSHOT_CONTRACT_NOT_PERSISTED`.
- **Host acceptance recorded — 2026-07-17.** The documented manual
  dry-run/temp-publication acceptance procedure was performed on the Odroid and
  passed; evidence is in
  `docs/ops/native_short_context_snapshot_host_acceptance_20260717.md`. Installed
  host HEAD `6b5f3ee` (== PR #106); single scheduler proven; manual no-publish
  dry-run PASS (`DRY_RUN`, `db_writes=0`); isolated temp publication PASS
  (`PUBLISHED` then `UNCHANGED` on unchanged inputs, no duplicate snapshot);
  manifest/CSV/bundle contract and digests PASS; canonical output byte-identical
  before/after (no scheduled cycle interfered). No host unit, timer, checkout, or
  canonical output was mutated. This satisfies the single-cycle host-acceptance
  gate; **multi-cycle operational acceptance (P2-C) remains OPEN.**
- **PR B dependency unblocked for review.** With one valid canonical manifest +
  immutable CSV proven and the acceptance recorded, PR #113 (safe Profit Plan
  render owner) may proceed to rebase/repository review. Merge, deploy, and
  legacy-unit retirement remain separate and unauthorized here.

PR A acceptance has two distinct gates: repository review/merge, then host
acceptance. Merge alone changes no installed checkout or owner. After the host
checkout is deliberately updated, the existing 4h chain contains the publisher
automatically; before that updated owner is permitted to use the canonical path,
operators must run a manual no-publish dry-run and a manual publish to an
acceptance/temp path and validate the manifest plus immutable CSV/bundle.

- Owner: the existing 4h market chain (`synth-chain-4h` → `scripts/run_chain_4h.sh`, which already runs the native SHORT scope-status chain). No second scheduler.
- Market-only and account-agnostic.
- Publishes the canonical native SHORT rows snapshot **outside reporting**, replacing the forbidden in-render build. The renderer never writes market truth.
- Source authority — PR A must prove a **field-by-field source mapping** of every published row field to a canonical persisted authority. `native_short_scope_status_v1` (current scope/map selection + freshness) and `native_short_map_level_status_v1` (current SELL target lifecycle) alone are **not** sufficient: anchors, extension geometry, reload levels, invalidation, and map-cycle/generation identity must come from the immutable native SHORT map / generation / lifecycle ledgers (map materialization ledger). Canonical contracts: `docs/architecture/native_short_scope_status_contract_v1.md`, `docs/architecture/native_short_map_level_status_contract_v1.md`, `docs/ops/native_short_map_materializer_canary_v1.md`, `docs/ops/native_short_map_ledger_health_report_v1.md`. No geometry recomputation in PR A and no research/runtime CSV fallback — a field with no authoritative persisted source fails closed for that row; it is never synthesized.
- Atomic snapshot publication: temp file → flush → fsync → `os.replace` → parent-dir fsync, to a canonical path (e.g. `${OUTPUT_ROOT}/_runtime/native_short_context_snapshot_v1/`).
- Absolute `publication_ts_utc` and `generated_ts_utc`; fail closed when a required persisted source timestamp is absent — no wall-clock synthesis (SYSTEM_FACTS historical-timestamp-integrity correction).
- Explicit freshness status per row and per snapshot: `FRESH | STALE | MISSING | UNAVAILABLE` (the P2-B authority classes).
- Immutable snapshot identity (`snapshot_id` + content digest); unchanged geometry must not publish a duplicate snapshot (consistent with the native SHORT no-duplicate-publication invariant).
- The field-by-field mapping must cover every field the runner parses: `symbol, context_status, map_cycle_id, anchor_{start,end}_ts_utc, anchor_{low,high}_price, breakout_gate_price, ext_1_272/1_618/2_000_price, active_target_levels_json, previous_target_levels_json, reload_r382/r500/r618/r786_price, invalidation_price, primary_4h_lifecycle_state, supporting_1h_state, latest_primary/support_close_ts_utc, context_freshness_status, current_map_status, rollover_state, previous_map_cycle_id, source_*`.
- No account, decision, planning, or execution logic; no broker calls. `broker_writes=0`, `order_submission=0`, `executor=none`.
- New contract doc authored in PR A (e.g. `docs/architecture/native_short_fib_context_snapshot_contract_v1.md`); this extends — does not reopen — the accepted `native_short_runtime_owner_and_scope_status_v1.md` DB-authority lane.
- Required tests: field-by-field source-mapping proof (every row field traced to a canonical persisted authority; no geometry recompute; no research/runtime fallback); deterministic projection from fixture DB rows; atomic publish; immutable identity / no duplicate on unchanged geometry; fail-closed on any missing authoritative field or source timestamp; freshness classification; no `src.reporting` / account / decision / planner / executor import.

Implemented PR A dependency for PR B:

```text
/var/www/html/synth/_runtime/native_short_context_snapshot_v1/manifest_v1.json
-> snapshots/<snapshot_id>/native_short_fib_context_rows_v1.csv
```

The manifest is the only commit pointer. PR B must validate it and consume the
referenced immutable CSV read-only; it must not select the newest directory by
filesystem ordering. PR A host acceptance is complete
(`docs/ops/native_short_context_snapshot_host_acceptance_20260717.md`,
2026-07-17): a valid canonical manifest and immutable CSV are proven, so PR B is
unblocked for repository review. Multi-cycle operational acceptance and any host
rollout remain separate and unauthorized here.

### PR B — safe Profit Plan render-owner

- Consumes only persisted snapshots: the PR A native SHORT snapshot, `market_price_snapshot`, and the account authorities (`trading_account_balance_snapshot`, `account_open_order_snapshot`).
- Builds and publishes no native SHORT context; never calls `run_native_short_fib_context_v1`.
- Loads the current canonical `profit-plan.json` as the previous snapshot **before** render: freeze it to a temp copy, validate it (JSON object with a `symbols` list and a top-level `render_id`), then pass that frozen copy to `run_manual_short_trader_profit_plan_v1 --previous-json`. If the existing JSON is corrupt or contract-invalid, fail visibly and preserve the last valid published HTML/JSON (do not run the writer).
- Previous-snapshot absence handling: when no prior `profit-plan.json` exists, PR B **omits `--previous-json` entirely** (first run → every card `NO_PREVIOUS_SNAPSHOT`). It must **never** pass a nonexistent path, because the current CLI (`_load_previous_json_snapshot`) opens the path unconditionally and fails the whole run on a missing file. From the second successful run `previous_snapshot_loaded=true`.
- Atomic HTML/JSON publication (the runner already uses `atomic_text_write`; the owner freezes the previous snapshot first so the writer never reads the file it overwrites).
- Owner run-metadata (atomic JSON): `previous_snapshot_loaded, previous_render_id, current_render_id, previous_snapshot_path, card_count, delta_status_counts {NO_PREVIOUS_SNAPSHOT|UNCHANGED|UPDATED_NOW}, started_ts_utc, finished_ts_utc, result`, plus safety markers `broker_writes=0, order_submission=0, live_orders=0, decision_gate=none, execution_planner=none, executor=none, renderer_private_broker_calls=0, native_short_context_build_in_render_stage=false`.
- Single writer, orchestrator-sequenced. Preferred design: a separate Profit Plan runner/script with its own lock and metadata, invoked as an **explicit stage by the existing linked-profile orchestrator** (`run_linked_profile_runtime_orchestrator_once.sh`) after all account-refresh stages succeed. The orchestrator only sequences runners and absorbs no reporting logic; no second independent five-minute timer is introduced. The same-cycle dependency — account snapshot must be fresh before the Profit Plan render reads it — is what makes ordering deterministic, and an independent timer joined only by offset cannot guarantee it. The exact integration mechanism may instead be deferred to PR B, but PR B must not prescribe an independent Profit Plan owner or timer without a concrete same-cycle dependency.
- Legacy user-level duplicates — `synth-account-wallet-dashboard@{joost,hugo}` (render + Profit Plan) and `synth-account-wallet-refresh@{joost,hugo}` (account refresh) — are retired only during a separate host rollout, after the replacement path is accepted (see "Host retirement targets" above), never as a side effect of this PR. The single-writer invariant is enforced at repo level by a guard test; host retirement with per-family rollback is a documented rollout precondition.
- Consumes the delta mechanism already implemented and documented in `profit_plan_card_evidence_delta_visibility_v1.md`; it does not re-implement it. It implements no mutation/ladder-repair — that stays in `profit_plan_live_ladder.md` (Lane A). PR B is the read-only render-owner slice Lane A P0.0 depends on.
- Required tests: first render without previous → `NO_PREVIOUS_SNAPSHOT`; second render uses first JSON as previous; `UPDATED_NOW` on semantic change; `UNCHANGED` with no semantic change; corrupt previous JSON fails visibly without damaging current output; atomic publication; previous vs current render IDs differ; no native SHORT build/publish; no private broker calls; `broker_writes=0`, `order_submission=0`; no `selection_engine`/`decision_gate`/`execution_planner`/`executor` import or change; duplicate-writer guard / explicit single-owner invariant; Joost and Hugo remain profile-separated.

### Host rollout (separate operational action, not authorized here)

```text
1. accept PR A; run the 4h-owned native SHORT snapshot; verify field-by-field source mapping, freshness, and immutable identity across cycles.
2. accept PR B; run the orchestrator (or its Profit Plan stage) manually once; verify per-run metadata, previous/current render IDs, delta counts, and atomic outputs.
3. only after 1-2 are accepted, retire BOTH duplicate user-level families (systemctl --user disable --now):
     synth-account-wallet-dashboard@{joost,hugo}   (render + Profit Plan duplicate)
     synth-account-wallet-refresh@{joost,hugo}     (account-refresh duplicate)
4. rollback (per family, independent): systemctl --user enable --now the retired family if its replacement stage regresses.
5. confirm one Profit Plan writer, deltas populated, no duplicate wallet/open-orders/account render, and rollback exercised.
```

### Host rollout executed — 2026-07-17

Executed on the Odroid (evidence: `docs/ops/mvp_cockpit_linked_profile_ownership_host_acceptance_20260717.md`):

- host checkout already at the PR #113 merge (`587262e`); PR A (#115) and freshness classifier (#112) confirmed contained;
- two manual orchestrator cycles PASS (all timers stopped): account 2/0, render 2/0, Profit Plan 2/0, `overall_result=ok`; Joost and Hugo previous→current render-ID chaining verified across cycles; deltas summed to card_count with no `NO_PREVIOUS_SNAPSHOT` reset; controlled lock test showed one owner `ok` and the second `skipped_locked`;
- the four legacy user timers `synth-account-wallet-dashboard@{joost,hugo}.timer` and `synth-account-wallet-refresh@{joost,hugo}.timer` were disabled and stopped (unit files preserved); per-family rollback recorded;
- system-level `synth-linked-profile-runtime-refresh.timer` re-enabled/active as the single owner; native SHORT publication remains `synth-4h-market-chain.timer`;
- discovered and resolved a third, un-named duplicate: `synth-mvp-readonly-cockpit.timer` drove `run_linked_profile_dashboard_refresh_once.sh` (legacy Profit Plan/wallet writer + union native SHORT build). Decoupled in PR #117; guarded by tests. The MVP cockpit now owns only entry-candidates + about page.

Single-ownership counts after rollout: Profit Plan writer = 1, linked-profile wallet render = 1, joost/hugo account refresh = 1, native SHORT publisher = 1.

## Boundary

```text
public market ingestion    = market-only, account-agnostic
account snapshot ingestion = authenticated read-only persistence only
renderer                   = persisted snapshots only
selection_engine           = unchanged
decision_gate              = account-aware freshness permission only
execution_planner          = unchanged
executor                   = unchanged
```

Forbidden:

- live trading;
- broker writes;
- order submission;
- private broker calls from rendering;
- rendering that builds native market truth;
- systemd/timer mutation without explicit instruction;
- collapsing runtime and database onto one failure domain as incident remediation.

## Definition of done

- installed owner state is documented and non-duplicated;
- absolute timestamps/statuses prevent frozen freshness;
- both linked profiles meet the chosen SLO across a multi-hour window;
- disk/log growth is measured and bounded;
- rollback is documented and exercised safely;
- no trading or execution layer was touched.
