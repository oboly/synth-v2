# State-Driven Runtime Orchestration Audit — Issue #331

## 1. Scope & Purpose

This document audits the existing freshness/staleness/recompute/retry
mechanisms named in Issue #331, with concrete repository evidence, before any
state-driven orchestration schema or dispatcher is designed or built. Per the
issue, this is an **audit and design-proposal document only**: no new schema,
no new dispatcher, no runtime change, no timer removal, no service
activation.

Design note preserved as context only, not implementation authorization:
`docs/todo/state_driven_runtime_orchestration_v1.md`.

Section 8 (`docs/ops/state_model_discipline_v1.md`) is the canonical
reference for the structural-lifecycle-vs-temporary-health distinction used
throughout this audit.

## 2. Mechanism Inventory

Each row below is evidenced by the file(s) shown and, where applicable, by
the systemd unit and/or writer-capability-ownership registry entry that
governs it. Classification legend:

- **canonical-active** — a current mechanism with evidence of an active
  authorized owner or an active read-only consumer path.
- **canonical-authorized-inactive** — current and authorized, but the
  ownership registry records it as authorized-inactive rather than active.
- **canonical-read-only** — current reporting/classification logic that has
  no writer authority to register.
- **legacy** — still running/authorized, superseded in part or scheduled for
  eventual consolidation, but not obsolete.
- **obsolete** — no longer authorized/invoked; retained only as history.
- **research-only** — used for backtest/replay/diagnostics, not runtime truth.
- **governance-gap / unregistered** — a committed scheduled or write-capable
  path for which this audit found no writer-capability registration or
  authorization/lock coverage sufficient to call it canonical-active. This
  describes governance evidence, not a new lifecycle state.

| # | Mechanism | File(s) / Module(s) | Layer | Classification | Trigger(s) | Lock / Authorization |
|---|-----------|----------------------|-------|-----------------|------------|-----------------------|
| 1 | `public_candle_freshness` | `scripts/run_market_candle_freshness_once.sh` → `src/etl/bitvavo/run_candles_etl.py` (writer path); `src/operations/persisted_market_candle_freshness_v1.py` + `run_persisted_market_candle_freshness_v1.py` (SELECT-only fail-closed boundary check, no write) | market_data / ETL | canonical-authorized-inactive | directly scheduled by `deploy/systemd/synth-market-candle-freshness-writer.timer` (`OnCalendar=*-*-* *:02,17,32,47:00 UTC`) | `flock` on `/tmp/synth-market-candle-freshness-writer-v1.lock`; registry records `production_runtime_owner=gurkdb`, `runtime_lifecycle=AUTHORIZED_INACTIVE`; service and inline mutation guard enforce `public_candle_freshness` |
| 2 | Fast recompute lifecycle worklist (P0-a) | `src/reporting/run_fast_recompute_lifecycle_v1.py` | reporting | canonical-read-only | manual invocation or invoked as the P0-b input worklist; no direct scheduler evidence found | read-only, no lock (no DB write) |
| 3 | Fast lifecycle classification | `src/reporting/fast_lifecycle_recompute_v1.py` | reporting | canonical-read-only | invoked by mechanism #2, not independently scheduled | pure function, no DB |
| 4 | Fast recompute lifecycle refresh (P0-b) | `src/advice/run_fast_recompute_lifecycle_refresh_v1.py`, `docs/ops/fast_recompute_lifecycle_refresh_v1.md` | advice, market-only by documented input boundary | governance-gap / unregistered | invoked by P0-c; dry-run by default, but P0-c passes `--write-db` | `--write-db` reaches zone/advice mutation (`upsert_zone_observation`, `delete_execution_zone_context_scope`, `upsert_execution_zone_context`); no `flock`, writer-capability registration, or host authorization was found for this runner |
| 5 | Odroid market-context refresh wiring (P0-c) | `scripts/odroid/run_mvp_market_context_refresh_once.sh`; `scripts/odroid/systemd/synth-mvp-market-context-refresh.service` and `.timer` | ops/runtime wiring | governance-gap / unregistered | directly scheduled every five minutes by `scripts/odroid/systemd/synth-mvp-market-context-refresh.timer` | invokes P0-b with `--write-db`; registry explicitly lists this script under `consumers_with_zero_writer_capabilities`; no explicit `flock` or registered writer authorization found |
| 6 | Native SHORT scope-status chain | `src/market_data/run_native_short_scope_status_chain_v1.py` invoked by `scripts/run_native_short_scope_status_chain_once.sh`, itself invoked from `scripts/run_chain_4h.sh` | market_data | canonical-active | directly scheduled by `deploy/systemd/synth-chain-4h.timer` (`OnCalendar=*-*-* 00,04,08,12,16,20:12:00 UTC`) | script-level lock in `run_native_short_scope_status_chain_once.sh`; `native_short_4h_chain` registry/service authorization and preflights |
| 7 | Native SHORT scope-status materializer (compute) | `src/market_data/native_short_scope_status_materializer_v1.py` | market_data | canonical-active (via #6 owner) | invoked by #6, not independently scheduled | writes `native_short_scope_status_v1`; inherits #6 lock and `native_short_4h_chain` mutation authorization |
| 8 | Native SHORT scope-status schema/persistence | `src/market_data/native_short_scope_status_v1.py`, `native_short_scope_status_projection_v1.py` | market_data | canonical-active (via #6 owner) | consumed by #7, not independently scheduled | provenance-enforced write through the #6 chain (`98cd9fbb`) |
| 9 | Held-market enrollment | `src/market_data/run_held_market_enrollment_v1.py`, `held_market_coverage_v1.py`, `run_held_market_coverage_health_check_v1.py`, `scripts/odroid/run_held_market_enrollment_once.sh` | account-informed orchestration/coverage | governance-gap / unregistered | invoked by `scripts/odroid/run_linked_profile_runtime_orchestrator_once.sh`, directly scheduled every five minutes by `docs/ops/systemd/synth-linked-profile-runtime-refresh.service` and `.timer` | phase wrapper `flock` on `/tmp/synth-held-market-enrollment.lock`; parent orchestrator `flock` on `/tmp/synth-linked-profile-runtime-orchestrator.lock`; reads `trading_account_balance_snapshot` and writes `asset.is_portfolio`; no registered capability/host authorization found |
| 10 | Stale-market/stale-price worklist (account-wallet dashboard) | `src/reporting/account_wallet_dashboard_v1.py` (`stale_market_data_count`) | reporting | canonical-read-only | computed at render time from persisted market data | read-only, no lock |
| 11 | Stale-context worklist (Profit Plan) | `src/reporting/run_manual_short_trader_profit_plan_v1.py` (`supported_context_stale_markets`) | reporting | canonical-read-only | computed at render time | read-only, no lock |
| 12 | Profit Plan stale/missing classification (`MISSING CANDLES`) | `src/reporting/manual_short_trader_profit_plan_v1.py` (`_NATIVE_SOURCE_STALE_FRESHNESS_STATES`, `MISSING_CANDLES_DISPLAY_LABEL`) | reporting | canonical-read-only | invoked by the Profit Plan rendering path | read-only display label; no new machine status code and no change to `short_context_display_state`/`actionability_state`, per `state_model_discipline_v1.md` |
| 13 | Writer-capability ownership/authorization system | `docs/ops/writer_capability_host_ownership_contract_v1.md`, `deploy/ownership/writer_capability_ownership_v1.json`, `src/operations/verify_writer_capability_authorization_v1.py` | ops/runtime (cross-cutting) | canonical-active governance system | invoked as `ExecStartPre` only for registered writers and inline at their mutation boundaries | registry invariant is `at_most_one_authorized_active_owner_per_capability`; it does not authorize mechanisms #4, #5, or #9 |

Not found in the repository under the literal name "older freshness
lifecycle updater": no separate/earlier freshness updater predates mechanism
#2. What Issue #331 anticipates under that label is mechanism #4
(`run_fast_recompute_lifecycle_refresh_v1.py`, "P0-b"), which is an older
companion to the P0-a worklist (#2), not a deprecated predecessor — see
`docs/ops/fast_recompute_lifecycle_refresh_v1.md` for the explicit
P0-a/P0-b/P0-c relationship. Its governance-gap classification remains
separate from that functional relationship.

No inventoried mechanism has repository evidence that it is obsolete or
research-only. The audit does not call every committed path canonical-active:
row #1 is authorized-inactive, rows #4/#5/#9 are unregistered governance
gaps, and the reporting/classification rows are read-only.

### 2.1 Mechanism-Specific Git History

All SHAs below were verified with `git cat-file -e <sha>^{commit}`. They are
evidence of the listed mechanism's history, not proof of currently installed
host state.

| Mechanism(s) | Verified history evidence |
|---|---|
| #1 | `12bba7e5af56dc59b091bf0ac7741e85534b4a38` — enforce writer-capability authorization at every mutation boundary. |
| #2 | `1eabc9efc4ff2fb8f3a1bbfd65f3ace945b52185` — add fast recompute lifecycle runner; `66b78fe9701d2f953710466a6329a62e25a675a5` — later cross-profile correction. |
| #3 | `e11a1e27a2e215f1289726073045de38e342cc15` — add fast lifecycle recompute request preview; `ad3de4f4ae5b51a7380209e3ae9509f497bcd8b1` — clarify reclaim/stale-map semantics. |
| #4 | `cd434b9bd62d9f1abc9adfdfb578fe9295854034` — add fast recompute refresh consumer; `bbcd0b627099cefe483dd9466cf1c365bddfc10b` — clarify backlog states. |
| #5 | `043b16202396e6d96a4a58bd1398dfc85e688e88` — split dashboard rendering from runtime refresh; `7d025c22648ccb8556a3773c116bd1a95f38ba65` — later writer-assignment change touching the runner. |
| #6/#7 | `a119389bf449f5fc75d1de9696001f5bdd8a1e3e` — wire native SHORT runtime chain; `e2279f7360de9dae3c004c981af9a1eb404ea6b3` — bootstrap lifecycle correction. |
| #8 | `05ed9397996460aa97310edf2333de0c2c8c7277` — add native SHORT scope-status persistence; `98cd9fbbbb4473301b7a9d1fb1e1facdb51f777d` — enforce writer provenance. |
| #9 | `6883400b7d8b873ebdc632ce37039b9f88e277f2` — add held-market enrollment; `c1f314d32c05e459af04770f1a0985c050235ae2` — make enrollment automatic and scheduled. |
| #10 | `7bdd0c18e70bd6834e089f41f9226b7a755baaf1` — add account-wallet dashboard and timer templates; `2816d105e024618264ac8a82aaa8f13e157c1bff` — later dashboard repair. |
| #11 | `037288e03e0e520b51dee3467a35fe72f3c35fbc` — add manual short trader Profit Plan dashboard v1; `dd47f44e59eb106c156dfa3a0f6e7ee9cdf14fc1` — stale-source display change in its runner. |
| #12 | `dd47f44e59eb106c156dfa3a0f6e7ee9cdf14fc1` — display `MISSING CANDLES` for stale-source Native SHORT scopes; `c02255b808bfe63566ac5abfab671ea5bacfbbc6` — later Profit Plan display adjustment. |
| #13 | `023b1d28a7240012e00d0a0bce6eeaac54455575` — add Native SHORT ownership preflight; `73dae43ca57a5c398b2b8ff05636d08d6045b037` — record active registry observation. |

## 3. Ownership & Data Flow (observed current state)

1. **ETL → candle freshness** — `run_candles_etl.py`, wrapped by
   `scripts/run_market_candle_freshness_once.sh`, is the registered
   `public_candle_freshness` writer (host `gurkdb`, capability-authorized).
   `persisted_market_candle_freshness_v1.py` is a separate SELECT-only
   validation helper (fail-closed boundary check), not a second writer.
2. **Paper advice → recompute worklist → refresh** — `run_fast_recompute_lifecycle_v1.py`
   (P0-a, read-only) computes a market-only worklist of stale/finished/
   reclaimed/invalidated advice maps. P0-b can mutate zone/advice state only
   with `--write-db`: it calls `upsert_zone_observation`,
   `delete_execution_zone_context_scope`, and
   `upsert_execution_zone_context`. P0-c invokes that write mode from the
   five-minute `synth-mvp-market-context-refresh` timer/service pair. This is
   one existing chain, not two competing mechanisms, but repository evidence
   does not register a writer capability, host authorization, or explicit lock
   for its write path.
3. **Native SHORT 4h chain → scope status** — `run_chain_4h.sh`, under the
   `native_short_4h_chain` writer capability, invokes
   `run_native_short_scope_status_chain_once.sh` →
   `run_native_short_scope_status_chain_v1.py`, which calls the materializer
   (`native_short_scope_status_materializer_v1.py`) to write
   `native_short_scope_status_v1`.
4. **Scope status → Profit Plan display** — `manual_short_trader_profit_plan_v1.py`
   reads the persisted `native_context_freshness_status` field (sourced from
   `native_short_fib_context_v1`, populated via mechanism #3's chain) and
   passes it through to a truthful degraded-state label
   (`MISSING CANDLES`) without introducing a new machine state, per
   `state_model_discipline_v1.md`.
5. **Held-market enrollment** is account-informed coverage orchestration: it
   reads `trading_account_balance_snapshot`, then conditionally writes the
   market-wide `asset.is_portfolio` flag. The locked phase wrapper
   (`scripts/odroid/run_held_market_enrollment_once.sh`) runs inside the
   separately locked linked-profile orchestrator, scheduled by
   `docs/ops/systemd/synth-linked-profile-runtime-refresh.timer` and `.service`.
   It determines the next canonical Fib publication cohort, not freshness.
   It grants no trade permission, execution intent, or order-handling
   authority, and does not move responsibility into `selection_engine`,
   `decision_gate`, `execution_planner`, or `executor`.

Execution Planner, decision_gate, and executor do not read any of the
mechanisms above. `native_short_4h_chain` runs in `SYNTH_EXECUTION_MODE=paper`
with `SYNTH_LIVE_EXECUTION_PERMISSION=NOT_GRANTED` and
`SYNTH_BROKER_WRITE_PERMISSION=NOT_GRANTED`.

## 4. Ownership / Lock Mapping (writer-capability chain)

For every registered writer mechanism, ownership and locking is governed by
one shared system, not per-mechanism ad hoc locks:

- **Contract**: `docs/ops/writer_capability_host_ownership_contract_v1.md`
  defines host-authorization states (`UNVERIFIED` → `CANDIDATE` →
  `SELECTED` → `ACCEPTED` → `AUTHORIZED` → `ACTIVE` → `SUPERSEDED`) and the
  invariant that at most one host may be an authorized active owner per
  capability.
- **Registry**: `deploy/ownership/writer_capability_ownership_v1.json` is the
  machine-readable source of truth. Current `host_status`: `gurkdb`
  `AUTHORIZED`, `devlap` `AUTHORIZED`, `odroid` `UNVERIFIED`. All five
  registered `public_market_data_writer`/`market_only_chain` capabilities
  (`public_price_snapshot`, `public_candle_freshness`,
  `market_rotation_pressure`, `native_short_4h_chain`,
  `sector_rotation_snapshot`) are bound to service/timer unit pairs under
  `deploy/systemd/`.
- **Enforcement**: `src/operations/verify_writer_capability_authorization_v1.py`
  is run as `ExecStartPre` on every governed systemd service (verified above
  for `synth-market-candle-freshness-writer.service` and
  `synth-chain-4h.service`) and is additionally called inline at the
  mutation boundary inside the writer code itself
  (`require_writer_mutation_authorization(...)` in `etl_bitvavo_candles.py:392`).
  This double-enforcement (service start gate + inline mutation gate) is the
  actual lock/ownership mechanism protecting these writers — not an ad hoc
  per-file DB lock.
- Native SHORT scope-status writes are covered by the same registry entry as
  `native_short_4h_chain` (they are invoked from within that chain, see §3
  item 3), not a separate capability.
- Mechanisms #2/#3/#10–#12 are read-only and need no writer capability.
  Mechanisms #4/#5 are write-capable when P0-c supplies `--write-db`, but
  neither has a writer-capability entry, host authorization, or explicit
  `flock`; the registry explicitly calls P0-c a consumer with zero writer
  capabilities. This is an evidenced governance gap, not authorization by
  implication. Mechanism #9 has two host-local `flock` boundaries (the
  enrollment wrapper and its parent orchestrator), but no
  writer-capability-registration or host authorization. Its account-informed
  input must not be relabeled market-only merely because its output is a
  market-wide flag.

## 5. Evidenced Gaps

| Gap | Evidence | Impact |
|-----|----------|--------|
| P0-b/P0-c write ownership is unregistered | P0-c supplies `--write-db` to P0-b, which mutates zone/advice state; `deploy/ownership/writer_capability_ownership_v1.json` lists P0-c as a zero-writer-capability consumer and no matching capability was found. | Cannot establish authorized host ownership or an at-most-one-writer invariant for this scheduled write path. |
| Held-market enrollment writer ownership is unregistered | `run_held_market_enrollment_v1.py` reads account balances and writes `asset.is_portfolio`; its wrapper and parent orchestrator use host-local `flock`, but no `capability_id` was found in `deploy/ownership/writer_capability_ownership_v1.json`. | The locks prevent overlapping local invocations but do not establish registry-based host ownership; account-informed coverage logic must remain outside trade/execution authority. |
| No single freshness source-of-truth across domains | Candle freshness (`public_candle_freshness`), advice-map freshness (P0-a/P0-b), and native-short context freshness (`native_context_freshness_status`) are three independently computed and independently consumed signals with no shared schema or cross-reference. | Increases design surface for any future orchestration; a dispatcher would need three distinct read paths, not one. |
| P0-a worklist has no automatic downstream consumer outside the Odroid P0-c lane | `run_fast_recompute_lifecycle_v1.py` output is read by cockpit dashboards and by P0-b/P0-c; no evidence of a third consumer. | Any additional automation should reuse P0-b's existing dry-run/`--write-db` gate rather than add a new consumer path. |
| Issue #331's named item "older freshness lifecycle updater(s)" does not map to a distinct legacy mechanism | See §2 note. | Nothing to deprecate or replace under this label; it already names the canonical P0-b file. |

## 6. Duplicates

No duplicate writer was found for the same freshness signal. The previous
draft of this audit claimed `public_candle_freshness` (ETL) and the Native
SHORT scope-status materializer both independently evaluate candle
freshness for the same symbol/interval; that claim is not supported by
evidence in §3/§4 — the materializer chain (`native_short_4h_chain`) reads
persisted candle data as an input but does not re-derive or write
`public_candle_freshness`'s own freshness classification. This claim is
withdrawn.

## 7. Missing State Transitions

- No dedicated lifecycle *event* is emitted when
  `native_short_scope_status_v1`'s freshness field transitions (e.g. to
  `STALE_PRIMARY_4H`); consumers (Profit Plan, §2 row 12) read the
  persisted field directly at render time rather than reacting to a
  transition event. This is consistent with `state_model_discipline_v1.md`'s
  guidance to keep temporary health state as a read field rather than
  inventing a state-machine transition, and is not, by itself, a defect.
- P0-a (worklist) → P0-b (refresh) → P0-c (Odroid wiring) is currently a
  scheduled chain, not a state-triggered one; Issue #331 §7 asks which fixed
  timers could eventually be replaced by state-driven dispatch. P0-c's
  five-minute timer is the most direct candidate, but its writer-governance
  gap must be resolved before any such change is considered.

## 8. Proposed Architecture (future design — not authorized by this issue)

This section is a **proposal**, clearly separated from the observed current
state in §§2–4 and the gaps in §5. It requires no new schema, no new
service, and no removal of any existing mechanism.

Reuse-only constraints satisfied by this proposal:

- No new DB table or schema.
- No second computation path for any existing freshness signal.
- No authority moves across `selection_engine` / `decision_gate` /
  `execution_planner` / `executor` boundaries — none of those layers is
  touched.
- `reporting` stays read-only.
- `selection_engine` stays market-only/account-agnostic (not in scope here;
  none of the audited mechanisms feed it).
- `decision_gate` stays permission-only, `execution_planner` stays
  intent-only, `executor` stays order-handling only (none of the audited
  mechanisms are upstream of these layers today).

Proposal: rather than introducing a new event/trigger table, a future
dispatcher (out of scope to build here) could poll the **existing**
persisted freshness fields already inventoried in §2 — `public_candle_freshness`'s
own persisted state, `native_short_scope_status_v1.observation_freshness_state`/
`source_freshness_state`, and the P0-a worklist's `RecomputeLifecycleRow`
output — on the existing writer cadences, and invoke the **existing**
refresh entrypoints (P0-b's `run_fast_recompute_lifecycle_refresh_v1.py` for
advice/zone refresh only after its existing-owner governance gap is resolved;
the existing `native_short_4h_chain` re-run path for scope-status refresh)
rather than any new runner. The dispatcher's own read/schedule role would sit
in `ops/runtime` per Issue #331's declared architecture owner, and would not
become a cross-layer authority.

No implementation, schema, or dispatcher code is authorized by this
document.

## 9. Proposed Follow-Up Scopes

No existing GitHub Issue was found in this repository that already covers a
state-driven dispatcher implementation; none is claimed here. The following
are proposed *scopes* only, to be filed as new Issues after this audit is
reviewed and accepted — filing itself is out of scope for this document:

1. Resolve the evidenced writer-governance gaps for P0-b/P0-c and held-market
   enrollment: register each owner in
   `deploy/ownership/writer_capability_ownership_v1.json`, or document the
   deliberate exception and its host/lock invariant.
2. Scope a minimal dispatcher (per §8) that polls the existing persisted
   freshness fields and calls existing refresh entrypoints — no new schema.
3. After scope 1, evaluate whether the Odroid P0-c cadence (§7) is the first
   practical fixed-timer candidate for state-driven replacement.

## 10. State Model Cross-Reference

`docs/ops/state_model_discipline_v1.md` governs how freshness/staleness
should be represented across all mechanisms above:

- Candle/context freshness (`STALE_PRIMARY_4H`, `STALE_SUPPORT_1H`,
  `native_context_freshness_status`) is temporary runtime/data-health state,
  orthogonal to structural lifecycle/support state (`SUPPORTED`).
- Mechanism #12 (`MISSING CANDLES` label, commit `dd47f44e`) is the current
  reference implementation of this discipline: a `SUPPORTED` scope with a
  stale canonical source remains visible and blocked, labeled truthfully
  from the existing field, with no new machine status code and no change to
  `short_context_display_state`/`actionability_state`.
- Any future dispatcher (§8) must keep this distinction: it may read
  temporary health fields to decide *when* to re-run an existing writer, but
  must not use temporary health state to alter structural lifecycle/support
  state, and must not push health-state logic into `decision_gate`,
  `execution_planner`, or `executor`.

## 11. Removed From Prior Draft

The following were in the previous version of this document and are removed
as unsupported or out of scope per independent review:

- Proposal to introduce a new `native_short_refresh_trigger_v1` table.
- Proposal to remove/consolidate the `public_candle_freshness` module.
- Proposal to deprecate/replace `run_fast_recompute_lifecycle_v1.py`.
- Reference to `psycopg2` (Synth uses MariaDB via `pymysql`/MariaDB
  connectors; `psycopg2` is a PostgreSQL driver and does not appear
  anywhere in this codebase).
- The unsupported "duplicate freshness detection" claim (§6).
- Any implementation-level dispatcher/service design; §8 is a proposal
  outline only.

---
Safety markers: `broker_private_calls=0 broker_writes=0 order_submission=0
live_orders=0 decision_gate=none execution_planner=none executor=none
selection_engine_account_awareness=0 reporting_authority=0
runtime_activation=0 production_db_changes=0`. No code, schema, service,
timer, DB, or runtime changes were made by this audit.
