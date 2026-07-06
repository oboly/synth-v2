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

Status: **implemented in a dev worktree; pending Odroid host verification.**
`synth-paper-advice-lifecycle-refresh.timer` remains stopped and must not be
started or re-enabled until the host-verification tasks below are done.

Goal: stop the paper-advice lifecycle refresh runner from being able to fill
the Odroid root filesystem again, and make a filling filesystem visible
before it silently breaks dashboard freshness.

Tasks and evidence:

- **Traced and confirmed** the exact log emitter and volume. Verified chain:
  `synth-paper-advice-lifecycle-refresh.timer` (every 5 min) →
  `scripts/odroid/run_paper_advice_lifecycle_refresh_once.sh` →
  `python -m src.etl.bitvavo.run_candles_etl --interval 15m` (no `--asset`
  filter) → `run_candles_etl.py` loops every enabled asset × 1 interval →
  `etl_bitvavo_candles.py` prints per-chunk/per-gap/done lines. **Verified
  measurement** (not code inspection alone): a live read-only query against
  the production DB during this work found **429 enabled assets**
  (`SELECT COUNT(*) FROM asset WHERE is_enabled=1`), and a partial local
  smoke run of the actual (fixed) script against the same DB confirmed
  `QUERY_RESULT name=load_assets rows=429`. Before this fix, this chain
  unconditionally printed at least ~6 lines/asset/cycle (~2,574+
  lines/cycle before gap warnings). The exact byte-for-byte share of the
  2026-07-05 `/var/log/syslog` growth attributable to this specific chain
  was not separately measured (e.g. no `journalctl` per-unit before/after
  byte accounting was run against the actual incident window) — this
  remains a strong, now-measurement-backed lead, not a fully closed
  root-cause proof.
- **Implemented** bounded default production output: phase start/end,
  aggregate counts, elapsed time, concise failure summary. No per-market
  candle chunk rows, no repeated per-gap warning lines, and no per-commit
  checkpoint syslog flood in normal mode.
  (`src/etl/bitvavo/run_candles_etl.py`, `src/etl/bitvavo/etl_bitvavo_candles.py`)
- **Implemented** exact per-commit checkpoint preservation without journal
  spam: after every successful DB commit, `run_candles_etl.py` atomically
  replaces a single last-success artifact at
  `/tmp/synth_runtime/run_candles_etl_last_checkpoint.json` by default
  (override via `SYNTH_CANDLES_ETL_CHECKPOINT_STATE_PATH`). It records the
  run identifier, status, UTC timestamp, venue, market, interval,
  completed/total, rows written, skipped count, and aggregate gap-warning
  count. The file is intentionally preserved across interruption/failure so
  operators can inspect the exact final successful checkpoint after a run
  aborts.
- **Implemented** gap-warning aggregation: each chunk's gap count is summed
  into a single `gap_warnings_total=N` on the run's `FINISHED` line, instead
  of one `[ETL][WARN]` line per gap.
- **Implemented** an explicit debug switch (`SYNTH_CANDLES_ETL_DEBUG=1` env
  var, or `--debug-logging` CLI flag) that restores the full original
  per-task/per-chunk/per-gap verbose output for manual debugging only.
- **Implemented** a disk/log health check
  (`src/operations/run_runtime_disk_log_health_v1.py`) and wired it into
  `scripts/odroid/run_paper_advice_lifecycle_refresh_once.sh` immediately
  after lock acquisition, before any candle ETL. Read-only
  (`shutil.disk_usage` / `os.path.getsize`; no DB, no network, no broker
  call). Reports `OK`/`WARN`/`CRITICAL` for the filesystem backing the repo
  directory, with an optional named-log-file size check and optional
  `SYNTH_DISK_HEALTH_LOG_WARN_BYTES` /
  `SYNTH_DISK_HEALTH_LOG_CRITICAL_BYTES` overrides forwarded through to the
  runner. On `CRITICAL`, the
  wrapper prints `[DISK_HEALTH][CRITICAL]` and exits non-zero **before**
  reaching the ETL window computation — confirmed by a local smoke test
  that forced `CRITICAL` via threshold override and observed the script
  abort before ever printing `etl_window_start=`.
- Retention/size controls for this service's logs, and inspection of the
  actual host rsyslog/logrotate/journald configuration, remain **not done**
  — that requires the real Odroid host and is out of scope for a
  documentation/code worktree. Do not assume a configuration that has not
  been read on that host.
- Log growth across multiple real scheduled cycles has **not** been tested
  on the actual Odroid host — only a single partial local smoke run
  **connected to and executing against the real production DB** was
  performed from this worktree (429 real enabled assets; 6 real inactive
  markets correctly aggregated into one `SKIPPED_MARKETS_INACTIVE` line;
  `logging_mode=bounded` confirmed in the real `STARTED`/`FINISHED` lines).
  This is real-data evidence that the logic is correct, not proof of
  multi-cycle log growth on the host. **Correction — the
  production-connected smoke was not dry/read-only**: the smoke run ran the
  actual write-capable ETL command against the live production database. It
  involved no private broker calls, no account state, no orders, no
  `decision_gate`, no `execution_planner`, and no executor — but it was
  not read-only, and describing it as "dry/read-safe" in an earlier report
  was inaccurate. See the DB-mutation-scope note and the new validation
  rule below.
- `synth-paper-advice-lifecycle-refresh.timer` remains stopped; it must not
  be started or re-enabled until the host-verification tasks above are
  done. Its current `active`/`enabled` state must be checked on-host with
  `systemctl is-active` / `systemctl is-enabled` (see
  `docs/ops/synth_runtime_runners_v1.md`) rather than assumed from this
  backlog entry.

Acceptance criteria:

- [x] A single run of the paper-advice lifecycle refresh emits a bounded,
  small number of lines in normal mode (no per-market/per-gap rows),
  independent of enabled-asset-universe size — verified against the real
  429-asset production universe via a smoke run that connected to and
  executed against the live production database (interrupted partway
  through; **this production-connected smoke was not dry/read-only** — see
  DB-mutation-scope evidence and the new validation rule below).
- [ ] Log growth is measured across multiple real scheduled cycles **on the
  actual Odroid host** and shown to be bounded (e.g. bytes/day within an
  explicitly stated budget). **Not yet done — requires host access.**
- [x] A disk-health check exists and is demonstrated (by test and by local
  smoke run) to detect disk pressure and fail visibly before ETL runs.
  **Not yet demonstrated against a genuinely full Odroid root filesystem**
  — demonstrated via threshold-override simulation only.
- [x] Exact per-commit checkpoint state is preserved in a deterministic
  non-public artifact even when normal journal output is bounded, and the
  final successful checkpoint remains inspectable after interruption/failure.
- [x] No market data, database data, research outputs, or production
  artifacts were **deleted** to achieve this — confirmed, no delete/rotate
  logic was ever invoked. However, correcting a prior overstatement: the
  local smoke run was **not** dry/read-only. It executed the actual
  write-capable `run_candles_etl` command against the shared production
  database (`obs_market_candle`), i.e. a real production-state mutation in
  scope, even though it involved no private broker calls, account state,
  orders, `decision_gate`, `execution_planner`, or executor. See
  "DB-mutation-scope evidence" immediately below for exactly what could and
  could not have been written, and the confidence level behind that.

**DB-mutation-scope evidence (read-only verification performed after the
fact, added during this correction pass):**

- `upsert_candles()` in `src/etl/bitvavo/etl_bitvavo_candles.py` issues
  `INSERT ... ON DUPLICATE KEY UPDATE` against `obs_market_candle`. By
  design this statement **can** either insert a new row (previously-unseen
  `(asset_id, venue, interval_code, open_ts_utc)`) or update an existing
  one (refreshing `close_ts_utc`, `open_price`, `high_price`, `low_price`,
  `close_price`, `volume_base`, `volume_quote_eur` only) — it is not
  restricted to updates-only by construction.
- The table's `ingest_ts_utc` column defaults to `current_timestamp()` and
  is **not** included in the `INSERT` column list or the
  `ON DUPLICATE KEY UPDATE` clause. This means a genuine INSERT stamps
  `ingest_ts_utc` to the insert time, while an UPDATE (matching an existing
  row) never touches `ingest_ts_utc`, leaving it at whatever value the row
  originally had. This makes `ingest_ts_utc` a reliable, read-only signal
  for "was a new row inserted here."
- **Read-only query run against the production DB during this correction
  pass** (`SELECT COUNT(*), MIN(ingest_ts_utc), MAX(ingest_ts_utc) FROM
  obs_market_candle WHERE interval_code='15m' AND venue='bitvavo' AND
  ingest_ts_utc BETWEEN '2026-07-06 02:04:00' AND '2026-07-06 02:05:30'`,
  covering the exact smoke-run window) returned **0 rows**. Zero inserts
  confirmed.
- **Confidence: CONFIRMED (direct query evidence)** — no new candle rows
  were inserted by the smoke run.
- **Confidence: MEDIUM-HIGH, not fully provable (process/output evidence,
  not query evidence)** — update-only write not fully excluded. The
  captured stdout from the smoke run shows execution reached only through
  `SKIPPED_MARKETS_INACTIVE count=6 ...` inside the `filter_active_markets`
  phase (a public-API-only, no-DB-write phase) and never printed
  `PHASE_FINISHED filter_active_markets`, any `CHECKPOINT_WRITTEN`, any
  `PROGRESS run_candles_etl` line, or `FINISHED run_candles_etl` — i.e. the
  main per-asset loop that calls `upsert_candles()` was very likely never
  reached before the process was cut off (`timeout 8` piped through
  `head -20`, which closes the pipe deterministically after 20 lines but
  whose exact effect on an in-flight Python process is not something this
  worktree can prove with certainty after the fact). Because
  `obs_market_candle` has no per-row "last updated" audit column separate
  from `ingest_ts_utc`, an UPDATE-only write to an already-existing row
  cannot be excluded by query alone the way an INSERT can.
- **Net assessment**: the smoke run had the *capability* to insert or
  update; empirically it is **confirmed** to have inserted nothing, and is
  **likely (not certain)** to have written nothing at all. Any write that
  did occur would have been strictly limited to public OHLC candle fields
  on `obs_market_candle` — never account, order, decision, or execution
  data.

**New rule — future P0-A validation must not repeat this risk:**

Future validation of this runner (including any repeat of the above smoke
test) must use one of:

1. `--dry-run` / a no-write mode that skips `upsert_candles()` entirely, or
2. an isolated/test database connection, never the shared production DB, or
3. static fixtures / mocked DB and network layers (as the unit tests in
   `tests/test_run_candles_etl_v1.py`, `tests/test_etl_bitvavo_candles_v1.py`,
   and `tests/test_runtime_disk_log_health_v1.py` already do).

Do not rerun the production-connected `run_candles_etl` smoke test again
from a dev/documentation worktree. Real end-to-end verification against
production belongs in P1-C ("Production rollout, smoke checks, rollback"),
on the actual Odroid host, under its own explicit review — not as an
incidental side effect of a P0-A documentation/logging change.

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
  and fails closed. It must consume the same persisted snapshot
  timestamps/statuses as the renderer (`market_price_snapshot`,
  `trading_account_balance_snapshot`, `account_open_order_snapshot`), or a
  pure account-freshness evaluator derived directly from those persisted
  observations — **never the renderer's HTML/JSON output** as an authority
  for account permission. This item does not add new decision_gate
  behavior beyond consuming that freshness status from the persisted
  observations for its existing account-aware checks.
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
decision_gate changes are limited to consuming freshness status directly
from persisted snapshot observations (or a pure evaluator over them) for
existing account-aware permission checks. decision_gate must never read
renderer HTML/JSON/output as its freshness authority.
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
