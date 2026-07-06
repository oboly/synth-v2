# Incident — 2026-07-05 Odroid Disk Exhaustion and Stale Short Swing Data

## Status

Recovered / temporary operating state. Permanent prevention work is tracked in:

```text
docs/todo/short_swing_linked_profile_freshness_and_disk_reliability_v1.md
```

All timestamps in this record are UTC unless explicitly marked otherwise.

## Summary

The Odroid runtime host's root filesystem filled to 100%, which stopped the
public market-price snapshot writer and the linked-profile Short Swing page
renderer for Joost and Hugo. The static Short Swing pages kept displaying
their last successfully rendered content, including a frozen server-baked
"N min ago" price-age string, so a stale price was visually indistinguishable
from a fresh one until it was checked against Bitvavo and the canonical price
collector directly.

## User-Visible Symptom

- Short Swing (the linked-profile Profit Plan page) showed LIGHTER at
  approximately €1.9062 with a displayed age of "0.5 min ago".
- The direct Bitvavo public ticker and the canonical `market_price_snapshot`
  collector both showed LIGHTER at approximately €2.11 at the same wall-clock
  time.
- The displayed "0.5 min ago" label did not update and was not actually
  recent; it was the age computed at the last successful render, before the
  page stopped regenerating.
- Both `profit-plan.html` and `profit-plan.json` for Joost and Hugo had
  stopped rendering new content starting somewhere around 03:32–03:38 UTC.

## Timeline (UTC, approximate)

| Time | Event |
|---|---|
| ~03:32–03:38 | Joost/Hugo linked-profile Short Swing (`profit-plan.html` / `.json`) stop rendering new content. |
| ~03:47 | Wallet balance and open-order snapshots last observed fresh at/around this time; they do not advance past this point during the incident window. |
| ~03:53 | `market_price_snapshot` public price writer stops updating. |
| (discovery) | Short Swing observed showing LIGHTER at ~€1.9062 / "0.5 min ago" while Bitvavo public ticker and the canonical collector both show ~€2.11. |
| (investigation) | Manual run of `scripts/odroid/run_linked_profile_dashboard_refresh_once.sh` on Odroid: the public price refresh phase (`run_market_price_snapshot_v1`) completes successfully, then the run fails at an `mktemp` call. |
| (investigation) | Odroid root filesystem (`/dev/mmcblk0p2`, 15 GB eMMC) found at 100% full — the confirmed proximate cause of the `mktemp` failure and of the price-writer stall. |
| (recovery) | `/var/log` inspected: approximately 3.9 GB total; `/var/log/syslog` and `/var/log/syslog.1` each approximately 1.8 GB; rotated/older syslogs added roughly another 250 MB. `/tmp` was nearly empty and inode availability was normal — neither was the storage cause. |
| (recovery) | Logs reduced, freeing approximately 3.8 GB on the root filesystem. |
| (recovery) | `synth-paper-advice-lifecycle-refresh.timer` stopped on the host. |
| (recovery) | Manual `run_linked_profile_dashboard_refresh_once.sh` re-run: completes successfully for both Hugo and Joost. |
| ~18:36 | Latest market price snapshots and both linked-profile Short Swing pages (Hugo, Joost) regenerated; refreshed LIGHTER price approximately €2.11. |

## Verified Facts

- Odroid root filesystem `/dev/mmcblk0p2` (15 GB eMMC) reached 100% full.
- `/tmp` was nearly empty; inode availability was normal on the affected
  filesystem. Neither was a contributing storage cause.
- `/var/log` total size was approximately 3.9 GB.
- `/var/log/syslog` and `/var/log/syslog.1` were each approximately 1.8 GB.
- Additional rotated/older syslog files added roughly another 250 MB.
- The public price writer (`market_price_snapshot`) and the linked-profile
  Short Swing renderer both stopped producing new output while the
  filesystem was full, consistent with the `mktemp`-based atomic-publish
  pattern used by these scripts (`scripts/odroid/run_linked_profile_dashboard_refresh_once.sh`,
  `scripts/odroid/run_account_wallet_dashboard_render_once.sh`) failing closed
  when temp-file/temp-dir creation cannot succeed on a full filesystem.
- The static HTML/JSON Short Swing (Profit Plan) card price line is produced
  by `format_current_price_line()` in
  `src/reporting/manual_short_trader_profit_plan_v1.py` (around line
  2090–2101), which bakes a plain `"€X · Y min ago"` string into the card at
  render time from a relative-minutes value computed once by the runner
  (`src/reporting/run_manual_short_trader_profit_plan_v1.py`, around line
  1125). This string does not update after the page stops regenerating —
  it is a frozen snapshot of "age at last successful render," not a live
  value. This is confirmed by direct code inspection during this
  documentation pass, and is the exact mechanism that made a stale price
  look fresh.
- The JSON snapshot already carries separate absolute timestamp fields
  (`generated_ts_utc`, `account_snapshot_ts_utc`, `order_snapshot_ts_utc`,
  `market_price_snapshot_ts_utc` — see
  `docs/ops/manual_short_trader_profit_plan_v1.md`), but the HTML card's
  visible price line does not derive its displayed age from these absolute
  fields client-side.
- Wallet balance and open-order snapshots remained at their last-known
  values from around 03:47 UTC throughout the incident window. This is
  expected renderer behavior, not a separate bug: the linked-profile
  dashboard render path
  (`scripts/odroid/run_account_wallet_dashboard_render_once.sh`) only reads
  persisted DB snapshots — it deliberately does not call Bitvavo private
  endpoints (`broker_private_calls=0` in its own log banner). Refreshing
  wallet/open-order snapshots is the separate responsibility of the private
  read-only wallet refresh runner (`src/account/run_account_wallet_refresh_v1.py`,
  invoked by `scripts/odroid/run_account_wallet_refresh_once.sh`), and there
  is no verified evidence in this incident that that runner was invoked or
  succeeded during the incident window.
- `run_candles_etl.py` (invoked every 5 minutes by
  `scripts/odroid/run_paper_advice_lifecycle_refresh_once.sh` via
  `synth-paper-advice-lifecycle-refresh.timer`) iterates once per enabled
  asset and, per asset, `src/etl/bitvavo/etl_bitvavo_candles.py` prints an
  unconditional per-chunk line (`[ETL] chunk=... raw_count=... filtered_count=...`),
  a per-run completion line (`[ETL] done market=...`), and an unconditional
  `[ETL][WARN] intra-chunk gap detected ...` line for every detected gap.
  With a multi-asset enabled universe on a 5-minute cadence, this is a
  plausible high-volume stdout/journal source, and is a strong candidate
  location for the P0-A trace.

## Unverified Hypothesis

- `synth-paper-advice-lifecycle-refresh.service`/`.timer` is the **primary
  suspected** high-volume log emitter, based on the per-market ETL/gap-warning
  print statements identified above and its 5-minute cadence.
- The exact line-for-line contribution of this service to the ~1.8 GB
  `/var/log/syslog` growth, versus other possible contributors, has **not**
  been proven by direct measurement (e.g. `journalctl` disk-usage-per-unit
  accounting or a controlled before/after log-growth test). That
  measurement is exactly the first task of P0-A in the linked backlog.
- Do not treat the code inspection above as confirmation that this incident's
  specific syslog volume is fully explained. It is a strong, code-grounded
  lead, not a closed root cause.

## Explicitly Not True (guard against overstatement)

- Bitvavo did **not** return stale or null prices. The public ticker and the
  canonical collector both returned the correct, current price (~€2.11) when
  queried directly during the incident. The staleness was entirely on the
  Synth-side collection/render pipeline.
- The 4h market-only chain (`synth-4h-market-chain.service`/`.timer`,
  `scripts/run_chain_4h.sh`) is a separate lane from the linked-profile
  Short Swing pipeline and was not proven to be the owner of, or a
  contributor to, this incident's failure. Do not blame it based on this
  incident record.

## Recovery Actions Performed

1. Confirmed the proximate cause: Odroid root filesystem 100% full.
2. Inspected `/var/log`, `/tmp`, and rotated syslog files to rule out `/tmp`
   and inode exhaustion, and to identify `/var/log/syslog*` as the dominant
   consumer.
3. Safely reduced log volume, freeing approximately 3.8 GB. No market data,
   database data, research outputs, or dashboard artifacts were deleted as
   part of this step.
4. Stopped `synth-paper-advice-lifecycle-refresh.timer` on the host.
5. Re-ran `scripts/odroid/run_linked_profile_dashboard_refresh_once.sh`
   manually; it completed successfully for both linked profiles (Hugo,
   Joost).
6. Verified refreshed `market_price_snapshot` data and both linked-profile
   Short Swing pages (`profit-plan.html` / `.json`) regenerated with a
   correct LIGHTER price (~€2.11) at approximately 18:36 UTC.

## Known Recovered State (at time of writing)

- Public market price snapshots and both Hugo/Joost Short Swing pages were
  successfully regenerated around 18:36 UTC with correct current prices.
- `synth-paper-advice-lifecycle-refresh.timer` is stopped and must **not**
  be re-enabled until its logging/output behavior is fixed and verified
  under P0-A (see backlog).

## Important Limitation

The manual linked-profile refresh that recovered public price display did
**not** refresh wallet balances or open-order state. This is by design, not
a bug in the recovery: `scripts/odroid/run_account_wallet_dashboard_render_once.sh`
and the pipeline it is part of are renderer-only against persisted DB
snapshots (`broker_private_calls=0`). Wallet/open-order freshness depends on
the separate private read-only wallet refresh runner
(`src/account/run_account_wallet_refresh_v1.py`) having run successfully and
recently. As of the writing of this record, wallet/open-order snapshot
freshness after the incident has not been independently re-verified in this
documentation pass — see "Current Temporary Operating State" below.

## Current Temporary Operating State

- `synth-paper-advice-lifecycle-refresh.timer` was **stopped** (verified
  recovery action). Whether it is currently `active` and whether it is
  currently `enabled` are separate, independently-checkable facts that this
  record does not assert — a manual stop does not by itself mean the unit
  is disabled. A stopped/inactive state after a manual stop is expected
  behavior, not a newly discovered runtime defect.
- **Required policy, independent of current live state:** this timer must
  not be started or re-enabled before backlog item P0-A is verified.
- **Current live status must always be verified with commands at the time
  of reading, never assumed from this record.** This incident record
  describes a point-in-time investigation; it is not a live status page.
  See the verification commands (`systemctl is-active` /
  `systemctl is-enabled`) in:

  ```text
  docs/ops/synth_runtime_runners_v1.md
  ```

## Permanent Prevention Requirements

Tracked as an ordered backlog in:

```text
docs/todo/short_swing_linked_profile_freshness_and_disk_reliability_v1.md
```

Summary of required outcomes (see backlog for full acceptance criteria):

- Bounded, non-verbose default production logging for the paper-advice
  lifecycle refresh runner, with aggregated gap warnings and diagnostic
  detail gated behind an explicit debug flag.
- Disk/log health checks that detect a filling root filesystem before
  dashboard freshness silently fails.
- A single explicit orchestration owner for the linked-profile pipeline
  (public price refresh → read-only account snapshot refresh → dashboard
  render), replacing any implicit reliance on independently-scheduled
  timers.
- An auditable absolute-timestamp contract in the static UI/JSON, with
  explicit `FRESH` / `STALE` / `MISSING` / `UNAVAILABLE` status per data
  class, replacing the frozen relative-age string described above.
- A `STALE_ACCOUNT_DATA` fail-closed behavior for account-specific
  ladder/order/repair claims when wallet or open-order data exceeds the
  freshness SLO.

## Explicit Non-Goal

No production host migration is part of this incident response. Odroid
remains the live runtime host. Any future dedicated-runtime-host decision is
tracked separately and explicitly does not block or defer the P0/P1 work
above (see backlog item P1-D).
