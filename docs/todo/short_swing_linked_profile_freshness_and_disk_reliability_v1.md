# TODO — Short Swing Linked-Profile Freshness and Disk Reliability

## Status

Active P0/P1 lane, opened from the 2026-07-05 Odroid disk-exhaustion incident.

Incident record:

```text
docs/incidents/2026-07-05_odroid_disk_exhaustion_and_stale_short_swing_data.md
```

Related canonical docs (do not duplicate; extend/reference):

```text
docs/ops/synth_runtime_runners_v1.md
docs/ops/runtime_chain_ownership_v1.md
docs/ops/runtime_freshness_audit_v1.md
docs/ops/market_price_snapshot_v1.md
docs/ops/multi_account_wallet_refresh_v1.md
docs/ops/account_wallet_dashboard_v1.md
docs/ops/manual_short_trader_profit_plan_v1.md
docs/architecture/dashboard_time_display_policy_v1.md
docs/todo/deploy_runtime.md
```

## Sources

```text
2026-07-05 incident: Odroid root filesystem exhaustion stopped public price
snapshot and linked-profile Short Swing rendering for Joost/Hugo; a frozen
server-baked "N min ago" string made stale data look fresh.
```

## Global boundaries (apply to every item below)

```text
public market ingestion       = market-only, account-agnostic
account snapshot ingestion    = read-only authenticated persistence only
renderer                      = reads persisted snapshots only; never polls Bitvavo privately
selection_engine               = market-only, unchanged by this lane
decision_gate                  = owns account-aware freshness/action permission, fails closed
execution_planner / executor   = unchanged by this lane
no live trading is part of this lane
```

---

## P0-A — Paper-advice log containment and disk/runtime health

Status: open / blocking `synth-paper-advice-lifecycle-refresh.timer` re-enable.

Goal: stop the paper-advice lifecycle refresh runner from being able to fill
the Odroid root filesystem again, and make a filling filesystem visible
before it silently breaks dashboard freshness.

Tasks:

- Trace and confirm the exact log emitter and volume. Strong candidate
  identified during incident documentation: `src/etl/bitvavo/etl_bitvavo_candles.py`
  prints an unconditional per-chunk line, a per-market completion line, and
  an unconditional `[ETL][WARN] intra-chunk gap detected ...` line per
  detected gap; `src/etl/bitvavo/run_candles_etl.py` invokes this once per
  enabled asset, every 5 minutes, via
  `scripts/odroid/run_paper_advice_lifecycle_refresh_once.sh` /
  `synth-paper-advice-lifecycle-refresh.timer`. Confirm with direct
  measurement (e.g. `journalctl` per-unit disk accounting, or a bounded
  before/after log-growth test), not code inspection alone.
- Change default production output to bounded summary logging: phase
  start/end, counts, elapsed time, failure summary. No per-market candle
  chunk rows and no repeated per-gap warning lines in normal mode.
- Aggregate repeated gap warnings by run, interval, and count (e.g. one line
  per run: `gap_warnings=N intervals=[...]`) instead of one line per gap.
- Gate current per-chunk/per-gap diagnostic detail behind an explicit debug
  flag or a bounded artifact file, not default stdout/journal.
- Add a disk/log health check that runs before (or alongside) scheduled
  refreshes and makes a filling root filesystem visible — e.g. a threshold
  check against `df` output for the filesystem backing the repo/output
  root, surfaced in run output and/or the freshness audit runner
  (`src/operations/run_runtime_freshness_audit_v1.py`).
- Define retention and size controls for this service's logs. Inspect the
  existing rsyslog/logrotate/journald configuration on the actual host
  before changing any global logging configuration; do not assume a config
  that has not been read.
- Test log growth across at least several scheduled cycles after the fix,
  on the actual Odroid host, before considering this item done.
- Keep `synth-paper-advice-lifecycle-refresh.timer` disabled until this
  item is verified.

Acceptance criteria:

- A single scheduled run of the paper-advice lifecycle refresh emits a
  bounded, small number of lines in normal mode (no per-market/per-gap
  rows), independent of enabled-asset-universe size.
- Log growth is measured across multiple real scheduled cycles and shown to
  be bounded (e.g. bytes/day within an explicitly stated budget).
- A disk-health check exists and is demonstrated to detect a filling root
  filesystem before dashboard freshness fails silently.
- No market data, database data, research outputs, or production artifacts
  were deleted to achieve this.

Boundary:

```text
No market-only chain (4h) logic changes.
No selection/advice/decision/execution changes.
No broker calls beyond existing public candle ETL.
No re-enabling of the timer before acceptance is verified.
```

---

## P0-B — Linked-profile scheduler ownership and public-price/dashboard freshness

Status: open. Verified gap: `scripts/odroid/run_linked_profile_dashboard_refresh_once.sh`
(the script actually used for incident recovery) has **no systemd unit** in
this repository (`docs/ops/systemd/` and `scripts/odroid/systemd/` were both
inspected; neither contains a unit for it). The only installed automated
timers touching this pipeline today are the older, independent per-profile
templates `synth-account-wallet-refresh@.timer` and
`synth-account-wallet-dashboard@.timer`, each on its own
`OnUnitActiveSec=5min` cadence with **no explicit ordering between them** —
this is exactly the "two independent timers" anti-pattern this item must
remove.

Goal: one explicit, sequential orchestration owner for the linked-profile
pipeline, replacing implicit reliance on independently-scheduled timers.

Tasks:

- Establish one explicit orchestration owner that runs, in order, for each
  scheduled cycle:
  1. public price snapshot refresh (`run_market_price_snapshot_v1`)
  2. read-only account snapshot refresh for each linked account (P1-A)
  3. linked-profile dashboard render using persisted snapshots only
     (`run_account_wallet_dashboard_render_once.sh` per profile, or its
     successor)
- The orchestrator may call the existing isolated per-stage runners in
  order; it must not merge their module responsibilities (public ingestion,
  account ingestion, and rendering stay separate modules/scripts).
- Do not rely on two independent timers joined only by `After=` or by
  offset scheduling. Use one timer driving one orchestration script (or an
  equivalent explicit dependency chain), with:
  - cadence sufficient to meet the five-minute SLO;
  - measured total runtime that fits inside the cadence;
  - `flock` or equivalent non-overlap protection for the whole
    orchestrated run;
  - per-account lock protection for the authenticated-read stage so
    Hugo/Joost reads never overlap each other;
  - explicit run/result metadata and timestamps recorded per stage.
- No stale public price may be presented as fresh: reuse/extend the
  existing `STALE_CURRENT_PRICE` fail-closed behavior
  (`docs/ops/manual_short_trader_profit_plan_v1.md`) and make sure it is
  driven by an absolute timestamp comparison, not a frozen render-time
  string (see P1-B for the display-contract fix).
- Static JSON must carry absolute timestamps for every data class it
  already partially carries (`generated_ts_utc`, `account_snapshot_ts_utc`,
  `order_snapshot_ts_utc`, `market_price_snapshot_ts_utc` already exist per
  `docs/ops/manual_short_trader_profit_plan_v1.md` — confirm all are
  populated from the orchestrated run's actual per-stage timestamps).
- Confirm no private broker call is ever made by the renderer stage
  (`broker_private_calls=0` must remain true for
  `run_account_wallet_dashboard_render_once.sh` and any successor).
- Decide and document the disposition of the existing
  `synth-account-wallet-refresh@.timer` / `synth-account-wallet-dashboard@.timer`
  templates once the new orchestrator exists (retire, or explicitly keep as
  a documented redundant path — do not leave both silently active and
  unordered).

Acceptance criteria:

- One timer/service (or equivalent) owns the full public-price →
  account-snapshot → render sequence for all linked profiles.
- A forced-stale public price test shows the pipeline fails closed
  (`STALE_CURRENT_PRICE`-equivalent) rather than showing a frozen fresh-looking
  value.
- No overlapping runs observed across several consecutive scheduled cycles.

Boundary:

```text
Orchestrator calls existing runners; it does not absorb their logic.
No broker private calls added to the renderer stage.
No decision_gate/execution_planner/executor changes.
```

---

## P1-A — Read-only authenticated account snapshot ingestion

Status: open. Note: a private read-only wallet/order refresh runner
**already exists** (`src/account/run_account_wallet_refresh_v1.py`, wrapped
by `scripts/odroid/run_account_wallet_refresh_once.sh`, documented in
`docs/ops/multi_account_wallet_refresh_v1.md`). This item is about wiring it
into the new P0-B orchestration path with proper locking/retry/rate-limit
behavior and persisted freshness/status metadata — not necessarily writing
it from scratch. Confirm during implementation whether the existing runner
already satisfies these requirements or needs extension.

Tasks:

- Confirm the existing runner fetches balances and open orders with
  read-only private calls only (`broker_writes=0`, `order_submission=0` —
  already asserted in its own log banner; re-verify against current code).
- Persist per-account observed timestamps and source status
  (`trading_account_balance_snapshot`, `account_open_order_snapshot` already
  exist per `docs/ops/multi_account_wallet_refresh_v1.md`; confirm these
  carry explicit per-run observed timestamps usable for the freshness
  contract in P1-B).
- Add/confirm per-account lock protection (the existing script already uses
  a per-profile `flock` — confirm this is sufficient once called from the
  new orchestrator rather than a standalone timer).
- Add explicit retry and rate-limit handling appropriate to Bitvavo's
  private/read endpoint behavior.
- **Before finalizing polling cadence**, verify current official Bitvavo
  API documentation for private/read-only endpoint rate limits — do not
  assume the existing 5-minute per-profile cadence
  (`synth-account-wallet-refresh@.timer`) is still correct without
  checking current published limits.
- No order-write behavior may be introduced by this item.

Acceptance criteria:

- Balances and open orders for Hugo and Joost are refreshed on a documented
  cadence with per-account non-overlap guaranteed.
- Every persisted snapshot row has an explicit observed timestamp and a
  status distinguishing success/failure/rate-limited.
- Documented Bitvavo rate-limit source (link or citation) supports the
  chosen cadence.

Boundary:

```text
Read-only private calls only.
No order writes, cancellations, or broker writes.
No decision_gate/execution_planner/executor changes.
```

---

## P1-B — Renderer and decision-gate account freshness contract

Status: open. Verified gap: the current Short Swing card price line is
produced by `format_current_price_line()` in
`src/reporting/manual_short_trader_profit_plan_v1.py` (~line 2090–2101),
which bakes a plain `"€X · Y min ago"` string from a relative-minutes value
computed once by the runner (`src/reporting/run_manual_short_trader_profit_plan_v1.py`,
~line 1125). This is the exact mechanism that made stale data look fresh
during the incident, and it must be replaced.

Tasks:

- Replace the frozen relative-age string with an auditable contract per
  data class:
  - absolute `market_price_observed_ts_utc`
  - absolute `wallet_observed_ts_utc`
  - absolute `open_orders_observed_ts_utc`
  - absolute `dashboard_generated_ts_utc`
  - explicit status per data class: `FRESH`, `STALE`, `MISSING`, or
    `UNAVAILABLE`
- A client-side relative age (e.g. "N min ago") may be displayed only when
  derived from the absolute timestamp at render/view time — not
  precomputed server-side and frozen into static HTML.
- Freshness SLO for active linked profiles: public market price snapshot
  age, wallet balance snapshot age, open-order snapshot age, and generated
  dashboard age must each be <= 5 minutes to count as `FRESH`. Do not
  invent a second (e.g. 15-minute) threshold unless separately justified
  and documented.
- When wallet/open-order data is older than 5 minutes:
  - show a prominent `STALE_ACCOUNT_DATA` state;
  - do not represent order coverage, ladder repair, open-order state, or
    any account-specific action as trustworthy while stale;
  - account-aware workflow/action output must fail closed;
  - market-only context (prices, zones, targets) may still render
    normally, following the existing `STALE_CURRENT_PRICE` precedent for
    the market-price axis specifically.
- `selection_engine` remains untouched and market-only; it must not receive
  wallet/order state as part of this work.
- `decision_gate` owns account-aware freshness/action permission semantics
  and fails closed; this item does not add new decision_gate behavior
  beyond consuming the freshness contract for its existing account-aware
  checks.
- `execution_planner` and executor are unchanged.

Acceptance criteria:

- Static JSON exposes all four absolute timestamps and a per-data-class
  status for every rendered card/page.
- A synthetic stale-wallet test shows `STALE_ACCOUNT_DATA` displayed and
  all account-specific action/ladder claims suppressed, while market-only
  content keeps rendering.
- No frozen server-baked relative-age string remains in the rendered HTML.

Boundary:

```text
No selection_engine changes.
No execution_planner/executor changes.
decision_gate changes are limited to consuming freshness status for
existing account-aware permission checks.
```

---

## P1-C — Production rollout, smoke checks, rollback

Status: open, depends on P0-A through P1-B.

Tasks:

- Systemd unit/timer installation procedure for the new P0-B orchestrator
  (review host user/path against actual Odroid conventions — `User=theone`,
  `WorkingDirectory=/home/theone/projects/synth-v2` — before installing;
  see `docs/ops/synth_runtime_runners_v1.md`).
- Dry-run/smoke workflow before enabling the timer.
- No-overlap verification across several consecutive scheduled cycles.
- Verify both Hugo and Joost linked profiles end-to-end (public price,
  wallet, open orders, dashboard render all within SLO).
- Verify logs do not grow abnormally across at least several scheduled
  cycles (bounded per P0-A acceptance criteria).
- Explicit rollback procedure: how to stop the new orchestrator and, if
  needed, temporarily fall back to a manual run of
  `scripts/odroid/run_linked_profile_dashboard_refresh_once.sh` without
  reintroducing the disk-exhaustion risk (i.e. rollback must not silently
  re-enable `synth-paper-advice-lifecycle-refresh.timer`).

Acceptance criteria:

- Both Hugo and Joost Short Swing pages meet the 5-minute SLO for all four
  data classes across a multi-hour observation window.
- Root filesystem usage remains stable (not trending toward full) across
  the same window.
- Rollback procedure has been exercised at least once in a non-production
  context.

Boundary:

```text
No live trading.
No broker write permission changes.
No decision_gate/execution_planner/executor changes beyond P1-B.
```

---

## P1-D — Deferred dedicated runtime-host decision

Status: open / deferred, explicitly non-blocking for P0-A through P1-C.

Tasks:

- Odroid remains the live runtime host now. Do not move live runtime to
  `gurkDB` as incident remediation — that would collapse the
  database/runtime failure-domain separation that limited the blast radius
  of this incident to rendering/freshness rather than data loss.
- Later this year, evaluate/purchase a dedicated runtime server separate
  from `gurkDB`, specifically to give the runtime host more headroom than a
  15 GB eMMC root filesystem.
- Preserve database/runtime failure-domain separation in any future
  hardware decision: the DB host and the runtime host must remain distinct
  failure domains.
- This decision does not defer, block, or substitute for P0-A or P0-B. Disk
  containment and orchestration ownership must be fixed on the current
  Odroid host regardless of any future hardware change.

Boundary:

```text
No host migration as part of this incident response.
No change to current DB host (gurkdb) ownership or role.
```

## Non-goals (entire lane)

- No live trading enablement.
- No broker write permission changes.
- No changes to `selection_engine`, `execution_planner`, or executor logic.
- No production host migration.
- No deletion of market data, database data, research outputs, or
  production dashboard artifacts as part of any item above.
