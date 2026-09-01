# Market Rotation Pressure Freshness SLA Measurement V1

Status: Measurement/observability record (no threshold adopted)
Measurement decision: **`MEASUREMENT_INSUFFICIENT`** for the full
end-to-end (publisher) leg -- see §5.3. The producer-owned
source→writer→persist leg (§4) is `MEASUREMENT_SUFFICIENT_FOR_OWNER_DECISION`
on its own (n=417, continuous, 2026-08-08..2026-09-01).
Canonical location: `docs/research/market_rotation_pressure_freshness_sla_measurement_v1.md`
Scope: #547 Phase B -- the `BLOCKED_NEEDS_MEASUREMENT` measurement contract
recorded in `docs/architecture/rotation_pressure_v1_canonical_promotion_v1.md`
§4
Runtime impact: none (read-only measurement; no DB writes, no Rotation
formula change, no #593 change, no timer/orchestration change)
Harness: `src/research/measure_rotation_pressure_freshness_sla_v1.py`
Raw evidence (writer leg, gurkDB): `data/research/rotation_pressure_freshness_sla_v1/gurkdb_writer_observed_20260808_20260901.json`
Raw evidence (publisher leg, Odroid, partial): `data/research/rotation_pressure_freshness_sla_v1/odroid_publisher_journal_raw_20260831_20260901.txt`

## 1. What this document is and is not

This is a measurement report. It answers the exact three questions #547
Phase A left open (canonical promotion doc §4):

1. What is the measured end-to-end persist-lag distribution (not just writer
   runtime), across a materially larger, continuous sample?
2. Is there an owner-reviewed safety-margin decision recorded?
3. Can each worst-case component now be described precisely as either a
   deterministic configured fact or a measured statistic, never as
   "directly measured" when it is actually an estimate?

It does **not** adopt a `ROTATION_STALE_AFTER` value. That remains a
separate, explicit owner decision (§6). No code in this repository is
changed by this document.

## 2. Method

The harness (`measure_rotation_pressure_freshness_sla_v1.py`) was run
directly on gurkDB (the canonical production writer host, per
`docs/ops/market_rotation_pressure_runtime_owners_v1.md`), reading:

- the local systemd journal for `synth-market-rotation-pressure-writer.service`
  (per-invocation `STARTED`/`FINISHED` markers with `ts=`, `elapsed_sec=`,
  and the persisted `MARKET ROTATION as_of=` value -- all emitted by
  `scripts/run_market_rotation_pressure_once.sh`, unchanged by this task);
- the local systemd journal for `synth-market-candle-freshness-writer.service`
  (the rolling 1h-interval refresh's own `PHASE_FINISHED ... interval=1h`
  marker -- the deterministic "this refresh of the closed-1h candle universe
  is done" event);
- `market_rotation_pressure_snapshot_v1.created_at` (a `DATETIME(6)
  DEFAULT CURRENT_TIMESTAMP(6)` column -- the real DB commit time, not a
  log-derived estimate) via direct DB query.

For the publisher leg (§5), the measuring session had no network path to
Odroid; a read-only `journalctl -u
synth-market-rotation-pressure-publisher.service --no-pager -o short-iso`
export was collected manually by the repository owner directly on Odroid
and supplied as a pasted transcript, saved byte-for-byte at
`data/research/rotation_pressure_freshness_sla_v1/odroid_publisher_journal_raw_20260831_20260901.txt`
and parsed by the same harness (`--publisher-journal <path>`).

Observation window: `2026-08-08T12:00:00Z` (first full hour after gurkDB
production activation, excluding the `Persistent=true` catch-up invocation)
through `2026-09-01T16:00:00Z`, gurkDB local time, UTC throughout, for the
writer leg. The publisher journal export only covers
`2026-08-31T06:36:33Z` through `2026-09-01T15:36:39Z` (§5.3).

**Sample size: 417 real hourly cycles** for the writer leg (vs. the 3
cycles available at Phase A), continuous, unbroken except for the known
anomalies noted in §4. The publisher leg has 34 successful + 6 failed
cycles over its shorter ~33-hour coverage window (§5).

### 2.1 A data-quality correction made during this measurement

An initial version of this harness computed source-completion lag as
`MAX(obs_market_candle.ingest_ts_utc)` grouped by `close_ts_utc`. That
produced a bimodal, mostly-nonsensical distribution (p50=270s but
p90=452,245s / ~5 days) because `ingest_ts_utc` is bumped whenever a
**newly onboarded** symbol's historical candles are backfilled, long after
the original hour -- 293 of the first 418 sample hours were contaminated
this way. This is an artifact of asset-onboarding backfill, not a real
completion delay, and does not reflect what the rotation-pressure writer
actually saw at the time. The harness was corrected to use the candle-freshness
writer's own per-cycle `PHASE_FINISHED interval=1h` marker instead (§2),
which is unambiguous and unaffected by later backfills. This correction is
recorded here so the method is auditable, per the same rigor Phase A applied
to the "directly measured" wording issue.

## 3. Configured schedule facts (verified, not measured)

```text
writer_oncalendar_utc     = *:20:00 UTC   (deploy/systemd/synth-market-rotation-pressure-writer.timer)
writer_randomized_delay   = 180s          (RandomizedDelaySec=180)
publisher_oncalendar_utc  = *:35:00 UTC   (docs/ops/systemd/synth-market-rotation-pressure-publisher.timer)
publisher_randomized_delay = 180s         (RandomizedDelaySec=180)
```

These are read directly from the deployed unit files, unchanged by this
task.

## 4. Observed metrics — source→writer→persist leg (n=417)

All values in seconds unless noted. Full precision in the raw JSON artifact
(`gurkdb_writer_observed_20260808_20260901.json`).

| metric | count | min | p50 | p90 | p95 | p99 | max |
|---|---|---|---|---|---|---|---|
| source_completion_lag (candle-freshness 1h cycle finish - asof) | 417 | 218.0 | 258.0 | 273.0 | 281.6 | 1174.2 | 39874.0 |
| writer_scheduling_lag (writer start - `:20:00`) | 417 | 0.0 | 93.0 | 178.0 | 178.0 | 212.0 | 213.0 |
| writer_runtime (writer start -> finish) | 417 | 4.0 | 5.0 | 5.0 | 6.0 | 6.0 | 9.0 |
| asof_to_persist_lag (DB `created_at` - asof), raw | 417 | 263.8 | 1297.9 | 1382.8 | 1383.2 | 1416.7 | 1418.2 |
| asof_to_persist_lag_steady_state (raw minus 3 off-schedule completions, §4.2) | 414 | 1205.6 | 1298.3 | 1382.8 | 1383.2 | 1416.8 | 1418.2 |

### 4.1 Reading these numbers

- **`writer_runtime` is trivial** (4-9s, p99=6s). The historical "~1-2 min
  runtime" figure from three anecdotal cycles (Phase A) is not supported by
  417 real cycles; actual runtime is an order of magnitude smaller and very
  tight. Runtime variance is not a meaningful driver of persist lag.
- **`asof_to_persist_lag` is dominated by the deliberate `:20:00` schedule
  offset**, not by runtime or upstream contention: p50=1297.9s (~21.6 min),
  p99=1416.7s (~23.6 min), max=1418.2s (~23.6 min). The distribution is
  tight (p50 to max spans only ~2 minutes), consistent with
  `scheduled_start (:20:00) + writer_scheduling_lag (0-213s, itself bounded
  by RandomizedDelaySec=180 + ~30s dispatch jitter) + writer_runtime
  (4-9s)`.
- **`source_completion_lag` has two extreme outliers** (2026-08-25T13:00Z
  and 14:00Z, ~11h and ~10h) that do not propagate into
  `asof_to_persist_lag` for those same hours (which are normal, ~1418s and
  ~1298s respectively) -- i.e. whatever the candle-freshness-writer-cycle
  proxy measured that day, the rotation-history writer's actual read of
  `obs_market_candle` was unaffected. This proxy metric is a diagnostic
  signal for the **upstream, non-producer-owned** candle-freshness lane
  (`docs/ops/market_rotation_pressure_runtime_owners_v1.md`'s "candle
  chain"), not a component of the Rotation Pressure producer's own SLA; it
  is reported for completeness but the two-outlier anomaly is not
  root-caused here (out of scope: no candle-freshness formula/timer change
  in this slice).

### 4.2 Off-schedule completions (excluded from the steady-state row only)

3 of 417 hours (`2026-08-08T13:00Z`, `2026-08-15T06:00Z`,
`2026-08-23T17:00Z`) show `asof_to_persist_lag` well below the ~21.6-minute
median (824.7s / 263.8s / 434.0s respectively) because the DB row's
`created_at` predates that hour's regular `:20:00`-window writer invocation
-- an earlier off-schedule/manual/catch-up run already persisted the data,
and the regular cycle then observed `NOOP_ALREADY_COMPLETE`
(`scripts/run_market_rotation_pressure_once.sh`'s existing idempotency
behavior, unchanged). These are real, correctly-measured events (the data
genuinely was available that early on those 3 hours), not measurement
error; they are called out and excluded only from the `_steady_state` row
because they do not represent the unattended, timer-only cadence a
freshness rule would need to bound. The raw row already includes them and
is barely different (p99 1416.7s vs. 1416.8s), so this exclusion does not
change the practical conclusion.

## 5. Publisher leg — partially observed (34h window only)

Odroid was unreachable directly from the measuring session (no DNS, absent
from gurkDB's SSH config, gurkDB's key not authorized there), so the raw
publisher journal was collected manually by the repository owner and
supplied as a pasted export, saved unmodified at
`data/research/rotation_pressure_freshness_sla_v1/odroid_publisher_journal_raw_20260831_20260901.txt`,
and parsed by the same harness (`parse_publisher_journal_export()`,
`--publisher-journal <path>`).

### 5.1 What the raw publisher journal shows

Coverage: `2026-08-31T06:36:33Z` through `2026-09-01T15:36:39Z` (**~33
hours**, not the ~410 hours needed to match the writer sample -- see §5.3).
Within that window:

- **34 successful cycles** (`STARTED runner=run_market_rotation_pressure_dashboard_render_once`
  ... `PUBLISHED ...` ... `FINISHED ... exit_status=0`), steady hourly
  cadence around `:35`-`:37 UTC`, runtime consistently 1-2s.
- **6 failed cycles**, all `NETWORK_UNREACHABLE`
  (`pymysql.err.OperationalError: (2003, "Can't connect to MySQL server on
  '192.168.1.221' ([Errno 101] Network is unreachable)")`), spanning
  `2026-09-01T07:47Z` through `09:27Z`, each preceded by a `-- Boot ... --`
  journal boundary (6 reboot boundaries total) -- i.e. Odroid was
  repeatedly rebooting and losing its route to the DB host during this
  interval, not a publisher-code defect. Recovery cycles at `08:42:38Z`
  and `10:07:16Z` succeeded once network connectivity returned.
- The publisher's `PUBLISHED ... freshness=STALE|FRESH` field is a
  **reporting-owned legacy classification**
  (`src/reporting/market_rotation_pressure_dashboard_v1.py`'s
  `DEFAULT_STALE_AFTER=2h30`) and is parsed here only as informational
  context -- it is never used to compute any lag in this report, per the
  #547 task contract's requirement that the producer-owned SLA not be
  derived from that consumer rule.

### 5.2 Matched steady-state and recovery cohorts

Each writer-persisted asof is matched to **at most one** successful
publisher cycle (and vice versa), because a publish call always serves
whichever row is currently latest in the DB -- if two hours were persisted
before the next publish fired (as happened during the outage), that one
publish reflects only the later hour; the earlier hour was genuinely never
independently published and is correctly left unmatched, not force-matched.
17 asofs matched (all within the publisher journal's ~33h coverage window;
0 unmatched within coverage).

| metric (steady_state, n=15) | min | p50 | p90 | p95 | p99 | max |
|---|---|---|---|---|---|---|
| persist_to_publisher_start_lag_sec | 748.7 | 914.3 | 990.9 | 1011.4 | 1038.9 | 1045.8 |
| persist_to_published_lag_sec | 749.7 | 915.3 | 991.9 | 1012.4 | 1039.9 | 1046.8 |
| publisher_runtime_sec | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| total_asof_to_published_lag_sec | 2123.0 | 2201.0 | 2229.6 | 2242.3 | 2265.3 | 2271.0 |

| metric (recovery, n=2 -- outage-affected hours only) | min | p50 | max |
|---|---|---|---|
| persist_to_publisher_start_lag_sec | 1300.6 | 2049.0 | 2797.5 |
| persist_to_published_lag_sec | 1301.6 | 2050.0 | 2798.5 |
| publisher_runtime_sec | 1.0 | 1.0 | 1.0 |
| total_asof_to_published_lag_sec | 2559.0 | 3298.0 | 4037.0 |

`publisher_runtime` (1-2s) is trivial in both cohorts, same conclusion as
the writer's own runtime (§4.1) -- persist-to-publish lag is entirely
schedule offset (`:35:00`), not execution time. The 2-hour recovery cohort
is far too small to characterize a worst-case recovery distribution (n=2);
it is reported only to show that recovery lag scales with how long the
outage lasted, not as a candidate SLA input.

### 5.3 Coverage is insufficient to match the full 417-hour writer sample

The publisher journal export covers only `2026-08-31T06:36Z` onward. The
writer sample runs from `2026-08-08T12:00Z`. Per the harness's own
sufficiency check:

```text
publisher_leg_sufficiency = MEASUREMENT_INSUFFICIENT_PARTIAL_COVERAGE
missing_publisher_history_hours_needed = 546.6   (~22.8 days)
```

Per the #547 task contract ("If this raw tail does not cover enough
publisher history to match the existing writer cycles, do NOT extrapolate.
Return MEASUREMENT_INSUFFICIENT"), the §5.2 steady-state/recovery figures
are reported as real, correctly-computed observations over their actual
(~33h) window, but they are **not** treated as equivalent in sample size or
evidentiary weight to the 417-cycle writer-leg distribution in §4, and no
percentile from §5.2 is proposed as a candidate SLA input on its own (§6).
Odroid's journal disk footprint was previously observed tight
(`docs/ops/market_rotation_pressure_runtime_owners_v1.md`: `2.1-2.2G avail
/ 86% used`, journal `~183-199M`), so a full ~23-day back-fill may not
exist; this must be confirmed directly on Odroid
(`journalctl --disk-usage`, `journalctl -u
synth-market-rotation-pressure-publisher.service --no-pager -o short-iso |
head -1`) before assuming more history is recoverable at all.

## 6. Candidate SLA inputs (NOT adopted here)

Per the #547 task contract, this document reports candidate inputs for a
future explicit owner decision; it does not adopt a threshold.

```text
producer-owned, fully OBSERVED and MEASUREMENT_SUFFICIENT_FOR_OWNER_DECISION
(n=417, gurkDB, continuous, 2026-08-08..2026-09-01):
  asof_to_persist_lag_steady_state:  p50=1298.3s  p95=1383.2s  p99=1416.8s  max=1418.2s

publisher leg, OBSERVED but MEASUREMENT_INSUFFICIENT (n=15 steady-state /
n=2 recovery, ~33h window only -- see §5.3, not directly comparable to the
417-sample writer leg):
  persist_to_published_lag_steady_state:      p50=915.3s   p99=1039.9s  max=1046.8s
  total_asof_to_published_lag_steady_state:   p50=2201.0s  p99=2265.3s  max=2271.0s

CONFIGURED-only facts (schedule, not a distribution):
  writer_oncalendar=*:20:00 UTC RandomizedDelaySec=180
  publisher_oncalendar=*:35:00 UTC RandomizedDelaySec=180
```

A reviewed safety-margin policy (e.g. "producer-owned `ROTATION_STALE_AFTER`
= observed p99 + fixed constant, re-derived periodically" or a different
rule) is an explicit follow-up owner decision, not made by this document.
Any adopted value should state which of the `asof_to_persist_lag` figures
in §4 (raw vs. steady-state) it is built on, and, if it also aims to bound
the full `asof -> operator-visible` chain, should treat the §5 publisher
figures as a preliminary/insufficient-sample signal only until a larger
publisher-journal sample is collected (§7).

## 7. Reproducing this measurement

```bash
# on gurkDB, as gurk -- read-only: no DB writes, no host mutation
python -m src.research.measure_rotation_pressure_freshness_sla_v1 \
  --since "2026-08-08 12:00:00 UTC" \
  --out data/research/rotation_pressure_freshness_sla_v1/<new_run>.json
```

To extend the publisher leg to a sufficient sample (needs ~23 more days of
Odroid publisher-journal history than currently supplied, per §5.3):

```bash
# on Odroid, as theone -- read-only; check retention first
journalctl --disk-usage
journalctl -u synth-market-rotation-pressure-publisher.service \
  --no-pager -o short-iso --since "2026-08-08 12:00:00 UTC" > publisher_journal.txt
# then, on gurkDB or any host with DB access:
python -m src.research.measure_rotation_pressure_freshness_sla_v1 \
  --since "2026-08-08 12:00:00 UTC" \
  --publisher-journal publisher_journal.txt \
  --out data/research/rotation_pressure_freshness_sla_v1/<new_run_with_publisher>.json
```

## 8. Non-goals (explicit)

This measurement does not:

- adopt or invent a `ROTATION_STALE_AFTER` value or change
  `compute_freshness`/`rotation_evidence_contract_v1`;
- change any Rotation Pressure V1 formula, weight, threshold, or state enum;
- touch #593's C1/C2/C3 candidates;
- change any systemd timer, `OnCalendar`, or `RandomizedDelaySec`;
- touch `selection_engine`, `decision_gate`, `execution_planner`,
  `executor`, account awareness, or broker calls;
- perform any DB write (verified: harness issues `SELECT` only, and every
  `db_cursor()` use in this module rolls back, never commits).

## 9. Safety

```text
measurement_only=1
db_writes=0
rotation_formula_changed=0
rotation_593_changed=0
timer_changed=0
selection_engine_changed=0
decision_gate_changed=0
execution_planner_changed=0
executor_changed=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
threshold_adopted=0
```

## 10. Related documents

- `docs/architecture/rotation_pressure_v1_canonical_promotion_v1.md` (§4,
  the `BLOCKED_NEEDS_MEASUREMENT` contract this fulfils)
- `docs/ops/market_rotation_pressure_runtime_owners_v1.md` (runtime owner /
  cadence-decision record)
- `src/research/measure_rotation_pressure_freshness_sla_v1.py` (harness)
- `data/research/rotation_pressure_freshness_sla_v1/gurkdb_writer_observed_20260808_20260901.json`
  (raw evidence + full report, 417 writer samples, joined publisher cohorts)
- `data/research/rotation_pressure_freshness_sla_v1/odroid_publisher_journal_raw_20260831_20260901.txt`
  (raw Odroid publisher journal export, unmodified, 34 successful + 6 failed
  cycles, ~33h coverage)
- #547 (this issue), #676 (evidence-contract promotion this unblocks)
