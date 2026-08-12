# Odroid disk containment host fix — 2026-08-06

## Status

```text
host execution: PASS (partial scope — DB archiving deferred)
repository canonicalization: N/A (host-local cleanup only, no scripts changed)
runtime/broker impact: NONE
```

## Host roles

```text
devlap  = development-only, orchestrates cross-host operations, holds legacy archives
odroid  = lightweight 24/7 runtime host, dashboard/webserver, read-only db client
gurkdb  = production/database host, owns canonical MariaDB `synth` and `synth_bt`
```

Odroid ran a local, orphaned MariaDB instance in addition to being a client of gurkdb. No active
Odroid service or script referenced the local database; the active `.env` on Odroid points to
`DB_HOST=192.168.1.221` (gurkdb) exclusively.

## Scope executed

1. Legacy Synth v1 directories archived from Odroid to devlap and removed from Odroid after
   verification.
2. Duplicate Python virtualenv removed on Odroid.
3. Stale Claude Code version removed on Odroid.
4. journald size-capped and syslog family rotated on Odroid; root cause of log volume
   investigated first.
5. `data/` directory on Odroid classified; nothing removed.

## Scope deferred

Local MariaDB archiving/removal on Odroid (`synth`, `synth_bt` local schemas, 3.7G) is
**deferred to GitHub Issue #216** ("Odroid: archive legacy MariaDB schemas blocked by invalid
view"). MariaDB was stopped again and confirmed `inactive`/`disabled` after the blocked attempt;
no database files were removed and no `apt purge` was run. **This document does not claim the
database archive or database cleanup is complete** — that work remains open in Issue #216.

Unbounded growth of the `data/research/live_like_*` runtime artifacts (see FASE 7 below) is
**tracked separately in Issue #229** and is not addressed by this operation.

## Legacy directory archival (FASE 3)

Archived from `/home/theone/` on Odroid to `~/archives/synth/odroid-legacy/20260806/` on devlap,
via streamed `tar` (no intermediate file left on Odroid):

```text
synthesizer_legacy_dirty_20260617_223325  (1.2G source, 21008 files, 66 symlinks, 2173 dirs)
synthesizer_legacy_dirty_20260617_225645  (208M source, 6963 files, 4 symlinks, 847 dirs)
synth_bt_migration_20260509_111401        (32M source, 5 files, 0 symlinks, 1 dir)
```

Verification performed before source removal:

- `tar -tzf` integrity: PASS on all three archives.
- Entry counts: archive totals match source `files + symlinks + dirs` exactly (23247 / 7814 / 6).
- Byte totals: archive regular-file bytes match source regular-file bytes exactly
  (1127761336 / 198452838 / matches). The small raw `find -printf %s` deltas (1048 and 33 bytes)
  are fully explained by symlink target-path-length accounting, not data loss.
- SHA-256 checksums recorded in `~/archives/synth/odroid-legacy/20260806/SHA256SUMS` and
  re-verified `OK` after archival.

Source directories were removed from Odroid only after all of the above passed. Freed
approximately 1.3G on Odroid (93%→84% used, 1.1G→2.4G available).

## Virtualenv cleanup (FASE 5)

`/home/theone/projects/synth-v2/venv` and `.venv` both existed (207M / 203M). Evidence for `venv`
as canonical:

- `synth-market-rotation-pressure-publisher.service` sources `venv/bin/activate` unconditionally.
- All script fallback logic (`if [ -f "venv/bin/activate" ]; then ... elif [ -f ".venv/bin/activate" ]`)
  checks `venv` first.
- `venv/bin` was touched 2026-08-01; `.venv/bin` was stale since 2026-06-11.

`.venv` removed. Post-removal smoke check: `source venv/bin/activate && python -m
src.reporting.run_paper_advice_static_dashboard_v1 --help` succeeded.

## Claude Code version cleanup (FASE 5)

Active symlink: `/home/theone/.local/bin/claude -> /home/theone/.local/share/claude/versions/2.1.212`.
`2.1.206` existed as an unreferenced versioned install (244M), confirmed via no running process
and no lock-file reference. Removed. `claude --version` confirmed `2.1.212` still functional
afterward. Codex was not touched, per explicit scope instruction.

## Logging root cause and limits (FASE 6)

Investigated before any rotation or masking, per fail-closed instruction.

Findings:

- `/var/log` was 436M, dominated by the `syslog`/`syslog.1` family (~230M) plus `journal` (178M).
- Growth rate from file span: `syslog` covered ~113h at 96.5M ≈ 0.85 MB/hour — steady-state, not
  an accelerating leak.
- Dominant source: `synth-linked-profile-runtime-refresh.timer` (fires every 5 minutes, ~266
  runs/24h, matching the timer schedule exactly). Each run fans out across 2 profiles
  (`joost`, `hugo`) into account-wallet-refresh, dashboard-render, profit-plan, and paper-advice
  sub-runners, each emitting a full safety-marker block (`order_submission=0`, `executor=none`,
  etc.) plus per-asset price lines.
- Classification: **normal scheduler-driven verbose INFO logging, not an error loop.** The
  recurring `DISK ... status=WARN` lines were a legitimate, correctly-functioning health checker
  flagging the pre-cleanup disk pressure (81-93% used), not a bug.
- One anomaly found: 14× `pam_unix(sudo:auth): conversation failed` — self-inflicted by
  non-interactive sudo probing during this operation's own investigation, not a pre-existing
  condition. No fix required.
- No fixable error loop existed, so no application logging change was made.

Changes applied:

```text
/etc/systemd/journald.conf.d/99-synth-odroid-limits.conf (canonical, retained):
  SystemMaxUse=200M
  RuntimeMaxUse=50M
  MaxRetentionSec=14day

/etc/systemd/journald.conf.d/20-synth-disk-limits.conf: removed (redundant duplicate)
```

`rsyslog` logrotate stanza (`/etc/logrotate.d/rsyslog`) confirmed standard: `weekly`, `rotate 4`,
`compress`, `delaycompress`. A `su root syslog` directive was added to the stanza to eliminate
permission warnings during forced rotation. One safe rotation was forced
(`logrotate -f /etc/logrotate.d/rsyslog`); active logs were recreated with correct
`syslog:adm` ownership and confirmed receiving new writes (test line injected via `logger`,
file size delta confirmed).

Result: `/var/log` 436M → 322M. Journal disk usage 158.0M (within the 200M cap).

## `data/` directory classification (FASE 7)

`/home/theone/projects/synth-v2/data` (1.6G total) on Odroid:

```text
data/research/live_like_shadow_event_v1              302M  ACTIVE RUNTIME DEPENDENCY
data/research/live_like_shadow_chain_v1               302M  ACTIVE RUNTIME DEPENDENCY
data/research/live_like_execution_plan_preview_v1     302M  ACTIVE RUNTIME DEPENDENCY
data/research/live_like_decision_preview_v1            302M  ACTIVE RUNTIME DEPENDENCY
data/research/intraday_retest_reclaim_candidate_v1     302M  ACTIVE RUNTIME DEPENDENCY
data/research/reload_reaction_scalp_parameter_sweep_v1  32M  HISTORICAL OUTPUT
data/research/breathline_lattice_shift_calibration_v2   22M  HISTORICAL OUTPUT
data/research/<other smaller validation dirs>          ~36M  HISTORICAL OUTPUT
data/aplus_raw, data/external, data/aplus_prompt_out   228K  reference/archive input, negligible
```

The five `live_like_*` directories contain 19,231 `run_*` subdirectories each, with the latest
run timestamped roughly two minutes before inspection — confirmed to be actively written every
~5 minutes by the same runtime-refresh cadence identified in FASE 6. These are not caches and
have an active producer; they were not touched.

The historical validation/sweep outputs have no active writer but also no documented reproducible
rebuild path, so they do not meet the deletion bar (reproducible cache + no active consumer +
documented safe rebuild) and were not touched.

**Nothing was removed from `data/`.**

## Space freed (Odroid root filesystem)

```text
before (start of session): 93% used, 1.1G available
after FASE 3:               84% used, 2.4G available
after FASE 5:                81% used, 2.9G available
after FASE 6 rotation:       80% used, 3.0G available
```

Total freed on Odroid root filesystem: approximately 1.8G (93%→80%).

## Rollback / recovery

- Legacy directories: restorable from `~/archives/synth/odroid-legacy/20260806/*.tar.gz` on
  devlap (SHA-256 verified); `tar -xzpf` to restore.
- `.venv`: recreatable via `python3 -m venv .venv && pip install -r requirements.txt` if ever
  needed; `venv` remains canonical and untouched.
- Claude 2.1.206: reinstallable via the standard Claude Code installer if ever needed; 2.1.212
  remains active and unaffected.
- journald/logrotate config: revert by restoring `20-synth-disk-limits.conf` or editing
  `99-synth-odroid-limits.conf`; no data was deleted by the journald change itself (only future
  retention was capped).
- Local Odroid MariaDB: untouched, still present, still `inactive`/`disabled`. Blocked by an
  invalid view during dump; see Issue #216 for resolution and eventual archival.

## Remaining risks

1. Local Odroid MariaDB (`synth` local 3.1G, `synth_bt` local 391M) is still present and consumes
   3.7G of the 15G Odroid root filesystem. Tracked in Issue #216.
2. `data/research/live_like_*` directories are growing unbounded (19,231+ runs each, no visible
   retention/pruning policy observed). Not addressed in this operation. Tracked in Issue #229.
3. No canonical repository-tracked disk-cleanup script exists yet for this class of operation;
   all steps above were run manually/interactively due to sudo constraints (see below).

## Sudo/authentication note

A scoped NOPASSWD sudoers drop-in was added and later found non-persistent/reverted mid-operation.
For the remainder of the operation, all sudo-requiring steps (MariaDB stop, journald edits,
logrotate force, drop-in removal) were run interactively by the human operator via one exact
command per step, with output relayed back for verification — no sudo password was ever typed
into or exposed via the agent session.
