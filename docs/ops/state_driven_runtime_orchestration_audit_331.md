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

- **canonical** — the current, authorized, in-production mechanism for its
  stated purpose.
- **legacy** — still running/authorized, superseded in part or scheduled for
  eventual consolidation, but not obsolete.
- **obsolete** — no longer authorized/invoked; retained only as history.
- **research-only** — used for backtest/replay/diagnostics, not runtime truth.

| # | Mechanism | File(s) / Module(s) | Layer | Classification | Trigger(s) | Lock / Authorization |
|---|-----------|----------------------|-------|-----------------|------------|-----------------------|
| 1 | `public_candle_freshness` | `scripts/run_market_candle_freshness_once.sh` → `src/etl/bitvavo/run_candles_etl.py` (writer path); `src/operations/persisted_market_candle_freshness_v1.py` + `run_persisted_market_candle_freshness_v1.py` (SELECT-only fail-closed boundary check, no write) | market_data / ETL | canonical | `synth-market-candle-freshness-writer.timer` (`OnCalendar=*-*-* *:02,17,32,47:00 UTC`) | `flock` on `/tmp/synth-market-candle-freshness-writer-v1.lock`; `src/operations/verify_writer_capability_authorization_v1.py --capability public_candle_freshness` against `deploy/ownership/writer_capability_ownership_v1.json` (host `gurkdb`, `AUTHORIZED`); `require_writer_mutation_authorization(...,"public_candle_freshness")` enforced inside `src/etl/bitvavo/etl_bitvavo_candles.py:392` |
| 2 | Fast recompute lifecycle worklist (P0-a) | `src/reporting/run_fast_recompute_lifecycle_v1.py` | reporting | canonical | manual run / cockpit render | read-only, no lock (no DB write) |
| 3 | Fast lifecycle classification | `src/reporting/fast_lifecycle_recompute_v1.py` | reporting | canonical | called by worklist builder (row #2) | pure function, no DB |
| 4 | Fast recompute lifecycle refresh (P0-b) | `src/advice/run_fast_recompute_lifecycle_refresh_v1.py`, doc `docs/ops/fast_recompute_lifecycle_refresh_v1.md` | advice (market-only, account-agnostic per doc) | canonical | consumes the P0-a worklist; wired into the Odroid market-context refresh lane (P0-c) before cockpit render | dry-run by default; `--write-db` required for any write; same-advice-asof cooldown marker in `paper_advice_observation.source_ref_json` provides idempotency/fairness, not a DB lock |
| 5 | Odroid market-context refresh wiring (P0-c) | `scripts/odroid/run_mvp_market_context_refresh_once.sh` | ops/runtime wiring | canonical | scheduled Odroid lane, runs between normal 4h baseline runs | inherits P0-b's dry-run/`--write-db` gate |
| 6 | Native SHORT scope-status chain | `src/market_data/run_native_short_scope_status_chain_v1.py` invoked by `scripts/run_native_short_scope_status_chain_once.sh`, itself invoked from `scripts/run_chain_4h.sh` | market_data | canonical | `synth-chain-4h.timer` (`OnCalendar=*-*-* 00,04,08,12,16,20:12:00 UTC`), part of the `native_short_4h_chain` writer capability | script-level lock in `run_native_short_scope_status_chain_once.sh`; `verify_writer_capability_authorization_v1 --capability native_short_4h_chain` against the same ownership registry (host `gurkdb`); `synth-chain-4h.service` additionally runs `run_synth_chain_4h_db_environment_preflight_v1` and `run_synth_chain_4h_db_grant_preflight_v1` as `ExecStartPre` |
| 7 | Native SHORT scope-status materializer (compute) | `src/market_data/native_short_scope_status_materializer_v1.py` | market_data | canonical | called by mechanism #6, not independently scheduled | writes `native_short_scope_status_v1` via `INSERT ... ON DUPLICATE KEY UPDATE`, no separate advisory lock beyond #6's script lock |
| 8 | Native SHORT scope-status schema/persistence | `src/market_data/native_short_scope_status_v1.py`, `native_short_scope_status_projection_v1.py` | market_data | canonical | consumed by mechanism #7 | provenance-enforced write (`98cd9fbb Enforce native SHORT writer provenance`) |
| 9 | Held-market enrollment | `src/market_data/run_held_market_enrollment_v1.py`, `held_market_coverage_v1.py`, `run_held_market_coverage_health_check_v1.py` | market_data | canonical | automatic/scheduled since Issue #238 (`c1f314d3 Make held-market enrollment automatic and scheduled (Issue #238)`) | not inspected as a DB-lock mechanism in this audit; enrolls positive wallet holdings into the canonical Fib publication cohort — no execution-intent or account-permission authority |
| 10 | Stale-market/stale-price worklist (account-wallet dashboard) | `src/reporting/account_wallet_dashboard_v1.py` (`stale_market_data_count`) | reporting | canonical | computed at render time from persisted market data | read-only, no lock |
| 11 | Stale-context worklist (Profit Plan) | `src/reporting/run_manual_short_trader_profit_plan_v1.py` (`supported_context_stale_markets`) | reporting | canonical | computed at render time | read-only, no lock |
| 12 | Profit Plan stale/missing classification (`MISSING CANDLES`) | `src/reporting/manual_short_trader_profit_plan_v1.py` (`_NATIVE_SOURCE_STALE_FRESHNESS_STATES`, `MISSING_CANDLES_DISPLAY_LABEL`), introduced in `dd47f44e` | reporting | canonical | passthrough of the row's own `native_context_freshness_status` (`FRESH` / `STALE_PRIMARY_4H` / `STALE_SUPPORT_1H`) sourced from `native_short_fib_context_v1` | read-only display label; explicitly no new machine status code and no change to `short_context_display_state`/`actionability_state`, per `state_model_discipline_v1.md` |
| 13 | Writer-capability ownership/authorization system | `docs/ops/writer_capability_host_ownership_contract_v1.md`, `deploy/ownership/writer_capability_ownership_v1.json`, `src/operations/verify_writer_capability_authorization_v1.py` | ops/runtime (cross-cutting) | canonical | enforced as `ExecStartPre` on every registered writer's systemd unit, and inline at each writer's mutation boundary (`require_writer_mutation_authorization`) | registry invariant: `at_most_one_authorized_active_owner_per_capability`; current registered capabilities: `public_price_snapshot`, `public_candle_freshness`, `market_rotation_pressure`, `native_short_4h_chain`, `sector_rotation_snapshot`, all host `gurkdb` |

Not found in the repository under the literal name "older freshness
lifecycle updater": no separate/earlier freshness updater predates mechanism
#2. What Issue #331 anticipates under that label is mechanism #4
(`run_fast_recompute_lifecycle_refresh_v1.py`, "P0-b"), which is an *older,
still-canonical companion* to the P0-a worklist (#2), not a deprecated
predecessor — see `docs/ops/fast_recompute_lifecycle_refresh_v1.md` for the
explicit P0-a/P0-b/P0-c relationship.

No mechanism in this inventory is legacy, obsolete, or research-only as of
this audit; all thirteen are currently authorized/invoked canonical paths.

## 3. Ownership & Data Flow (observed current state)

1. **ETL → candle freshness** — `run_candles_etl.py`, wrapped by
   `scripts/run_market_candle_freshness_once.sh`, is the registered
   `public_candle_freshness` writer (host `gurkdb`, capability-authorized).
   `persisted_market_candle_freshness_v1.py` is a separate SELECT-only
   validation helper (fail-closed boundary check), not a second writer.
2. **Paper advice → recompute worklist → refresh** — `run_fast_recompute_lifecycle_v1.py`
   (P0-a, read-only) computes a market-only worklist of stale/finished/
   reclaimed/invalidated advice maps; `run_fast_recompute_lifecycle_refresh_v1.py`
   (P0-b) consumes that worklist and can write market-only zone/advice
   refreshes (`--write-db`); `run_mvp_market_context_refresh_once.sh` (P0-c)
   wires P0-b into the Odroid cockpit-render lane. This is one existing
   chain, not two competing mechanisms.
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
5. **Held-market enrollment** feeds the canonical Fib publication cohort
   (Issue #238) independently of the freshness chains above; it determines
   which symbols are in scope for materialization, not their freshness.

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
- Mechanisms #2–#5, #9–#12 (reporting/advice worklists, held-market
  enrollment, Profit Plan display) are not registered writer capabilities:
  #2, #10, #11, #12 are read-only; #4/#5 gate writes behind an explicit
  `--write-db` flag rather than the capability-authorization registry; #9
  was not traced to a registry entry in this audit (flagged as a gap in
  §5).

## 5. Evidenced Gaps

| Gap | Evidence | Impact |
|-----|----------|--------|
| Held-market enrollment writer ownership not registered | `run_held_market_enrollment_v1.py` was not found as a `capability_id` in `deploy/ownership/writer_capability_ownership_v1.json` | Cannot confirm at-most-one-owner invariant applies to this writer the same way it does to the five registered capabilities; needs explicit confirmation, not assumed absence. |
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
  scheduled/cron-adjacent chain, not a state-triggered one; Issue #331 §7
  asks which fixed timers could eventually be replaced by state-driven
  dispatch — P0-c's Odroid cadence is the most direct candidate, since it
  already exists solely to poll P0-a's worklist between fixed 4h baseline
  runs.

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
advice/zone refresh; the existing `native_short_4h_chain` re-run path for
scope-status refresh) rather than any new runner. The dispatcher's own
read/schedule role would sit in `ops/runtime` per Issue #331's declared
architecture owner, and would not become a cross-layer authority.

No implementation, schema, or dispatcher code is authorized by this
document.

## 9. Proposed Follow-Up Scopes

No existing GitHub Issue was found in this repository that already covers a
state-driven dispatcher implementation; none is claimed here. The following
are proposed *scopes* only, to be filed as new Issues after this audit is
reviewed and accepted — filing itself is out of scope for this document:

1. Register `run_held_market_enrollment_v1.py`'s writer ownership in
   `deploy/ownership/writer_capability_ownership_v1.json` (or document why it
   is intentionally unregistered), closing the gap in §5.
2. Scope a minimal dispatcher (per §8) that polls the existing persisted
   freshness fields and calls existing refresh entrypoints — no new schema.
3. Evaluate whether the Odroid P0-c cadence (§7) is the first practical
   fixed-timer candidate for state-driven replacement.

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
