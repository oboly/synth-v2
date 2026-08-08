# Market Rotation Pressure gurkDB Acceptance — 2026-08-08

## Outcome

Controlled gurkDB acceptance passed for `market_rotation_pressure`. One
`ACCEPTANCE`-mode writer invocation advanced both the rotation history and
rotation pressure persisted state from fresh canonical candles; an immediate
repeat invocation proved idempotency; zero duplicate snapshot headers were
observed at any check.

```text
capability=market_rotation_pressure
host=gurkdb
preflight_commit=34521cb459c350585efd5d8ce40f0ecbdb19ca2b
preflight_local_required_pass=12
preflight_local_required_fail=0
preflight_external=UNVERIFIED by this read-only runner (no separately
  produced external-evidence manifest was supplied); DB connectivity, source
  candle freshness, required tables, and lock writability were independently
  verified read-only, see "Preflight Evidence" below
acceptance_commit=34521cb459c350585efd5d8ce40f0ecbdb19ca2b
acceptance_status=ACCEPTED
production_runtime_owner=gurkdb
production_authorization_status=AUTHORIZED
runtime_lifecycle=AUTHORIZED_INACTIVE
production_authorization_file_present=true (installed manually by operator,
  commit_verification_mode=ANCESTOR, required_branch=main)
timer_enabled=false
timer_active=false
```

## Root Cause (Issue #266)

Read-only production audit traced the stale public rotation snapshot
(`freshness=STALE`, `source_ts_utc=2026-07-20T04:00:00Z` while current date
was 2026-08-07) to a production runtime-ownership gap: the devlap writer was
correctly disabled during the 2026-07-19 production-ownership reset, and
gurkDB was only ever `SELECTED_PENDING_PREFLIGHT` for this capability --
never taken through preflight/acceptance/authorization/activation, unlike
`public_price_snapshot` and `public_candle_freshness`. `obs_market_candle`,
the Odroid publisher, and Profit Plan's read-only projection were all working
correctly throughout. See PR #275 for the repository-only gurkDB cutover
preparation (`ConditionHost=gurkdb`, capability-distinct authorization file
path) and this document for the subsequent controlled acceptance.

## Preflight Evidence

Fresh read-only evidence collected on gurkDB at commit
`34521cb459c350585efd5d8ce40f0ecbdb19ca2b` (`git status --short` clean):

`python -m src.operations.run_host_preflight_v1 --capability
market_rotation_pressure --expected-host gurkdb --expected-commit
34521cb459c350585efd5d8ce40f0ecbdb19ca2b --checkout-path
/home/gurk/projects/synth-v2 --output json` reported every required
`PREFLIGHT_LOCAL` check `PASS`: `capability_identity`, `host_identity`,
`checkout_commit`, `os_and_architecture`, `cpu_and_load`, `ram_and_swap`,
`disk_space_and_inodes`, `python_and_virtualenv` (`.venv/bin/python`
3.14.4), `capability_module_imports`, `flock`, `systemd_availability`,
`systemd_unit_validation`.

Independently verified read-only (no mutation):

```text
DB connectivity: SELECT 1 -> ok
obs_market_candle (1h) MAX(close_ts_utc) = 2026-08-08T01:00:00Z (fresh)
market_rotation_snapshot_v1: exists, 220 rows before acceptance
market_rotation_pressure_snapshot_v1: exists, 110 rows before acceptance
market_rotation_observation_v1: exists, 28163 rows
market_rotation_pressure_observation_v1: exists, 11960 rows
lock path /tmp/synth-market-rotation-pressure-v1.lock: writable (touch ok)
no competing writer process (pgrep clean)
no rotation/pressure systemd unit previously installed on gurkDB
(systemctl list-unit-files clean before this lane's install)
```

Authorization guard independently confirmed fail-closed in `PRODUCTION` mode
before any authorization file existed:

```text
FAIL capability=market_rotation_pressure
  reason="production authorization file is not a regular file:
  /etc/synth/writer-capability-market-rotation-pressure-authorization-v1.json"
authorization_guard=fail_closed host_mutations=0 database_writes=0
  writer_invocations=0 systemctl_mutations=0
exit_status=3
```

## Systemd Unit Installation (gurkDB)

`deploy/systemd/synth-market-rotation-pressure-writer.{service,timer}`
installed to `/etc/systemd/system/` at commit
`34521cb459c350585efd5d8ce40f0ecbdb19ca2b`; `systemd-analyze verify` passed
for both units; `daemon-reload` completed. Confirmed `loaded`, `disabled`,
`inactive` for both service and timer after install -- no activation
performed as part of installation.

## Controlled Acceptance Run

An `ACCEPTANCE`-mode permit was issued under the canonical time-bounded
acceptance-permit mechanism
(`deploy/ownership/writer_capability_acceptance_permit_v1.schema.json`,
`src.operations.writer_capability_authorization_v1`), placed at
`/run/synth/writer-acceptance/market-rotation-pressure-acceptance-20260808.json`
(tmpfs, capability-bound, host-bound, exact-commit-bound,
issued `2026-08-08T02:00:51Z`, expiry `2026-08-08T02:30:51Z`,
`approval_reference="Issue #266 explicit user production cutover
authorization, gurkDB controlled acceptance run, 2026-08-08"`).

```bash
export SYNTH_WRITER_EXECUTION_MODE=ACCEPTANCE
export SYNTH_WRITER_ACCEPTANCE_PERMIT=/run/synth/writer-acceptance/market-rotation-pressure-acceptance-20260808.json
bash scripts/run_market_rotation_pressure_once.sh --write-db
```

### Cycle 1 (real write)

```text
as_of_ts_utc=2026-08-08T02:00:00Z
market_rotation_snapshot_v1: 220 -> 222 rows (snapshot_id 237 24h, 238 168h)
market_rotation_pressure_snapshot_v1: 110 -> 111 rows (pressure_snapshot_id 119)
market_direction=ROTATION_OUT market_score=-18.5934 eligible_asset_count=113
exit_status=0 elapsed_sec=4
```

### Cycle 2 (idempotency proof, same permit window)

```text
status=NOOP_ALREADY_COMPLETE observations_written=0
row counts unchanged: 222 / 111
exit_status=0 elapsed_sec=5
```

### Duplicate and integrity checks

```text
duplicate_pressure_headers (venue, as_of_ts_utc, model_version) = 0
duplicate_history_headers (venue, as_of_ts_utc, horizon_h) = 0
```

### Safety boundary

Every invocation logged `broker_private_calls=0 broker_writes=0
order_submission=0 live_orders=0` and `selection_engine=none
decision_gate=none execution_planner=none executor=none
reporting=none dashboard_publish=none`. No Profit Plan file touched. No SSH
or cross-host orchestration performed by the writer.

## Production Decision Evidence

```text
production_runtime_owner=gurkdb
production_authorization_status=AUTHORIZED
runtime_lifecycle=AUTHORIZED_INACTIVE
```

This is a controlled-acceptance decision only. `runtime_lifecycle` remains
`AUTHORIZED_INACTIVE`, not `ACTIVE`, until the timer is separately enabled and
at least one real scheduled cycle is observed, per the cutover order in
`docs/ops/writer_capability_host_ownership_contract_v1.md`. No host
`systemctl enable`/`start` has been performed for this capability as of this
point in this document's original 2026-08-08 acceptance record above.

**Superseded by activation** (same day, see the next section): the gurkDB
timer was subsequently enabled and observed to run successfully. The
acceptance record above is preserved unchanged as the truthful record of
what had and had not happened at acceptance time; it does not retroactively
describe activation.

## gurkDB Activation Evidence — 2026-08-08

Per explicit user production-cutover authorization for Issue #266, the
gurkDB timer was enabled the same day as acceptance:

```bash
sudo systemctl enable --now synth-market-rotation-pressure-writer.timer
```

### First observed run

A `Persistent=true` catch-up invocation fired immediately on enable (the
regularly scheduled `*:20:00 UTC` window had already passed for that hour):

```text
mode=PRODUCTION (confirmed via journal: "PASS capability=market_rotation_pressure
  ... mode=PRODUCTION authorization_guard=pass")
ExecMainStartTimestamp=2026-08-08T11:50:25Z
ExecMainExitTimestamp=2026-08-08T11:50:30Z
Result=success ExecMainStatus=0
InvocationID=5166cc97187342a29395fdd590bf4ec4
as_of_ts_utc=2026-08-08T11:00:00Z (matches obs_market_candle 1h MAX(close_ts_utc) exactly)
market_rotation_snapshot_v1: 222 -> 224 rows (snapshot_id 241 24h, 242 168h)
market_rotation_pressure_snapshot_v1: 111 -> 112 rows (pressure_snapshot_id 121,
  market_direction=MIXED, market_score=+8.266, eligible_asset_count=114)
duplicate_pressure_headers=0 duplicate_history_headers=0
broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0
selection_engine=none decision_gate=none execution_planner=none executor=none
reporting=none dashboard_publish=none
```

### Timer state observed post-activation

```text
timer: enabled, active, symlinked under timers.target.wants
NEXT=2026-08-08T12:22:37Z (next regular *:20:00 UTC window)
```

### Devlap fence re-verified at activation

```text
devlap: synth-market-rotation-pressure-writer.timer disabled, inactive
no writer process on devlap
```

### Duplicate-writer check at activation

```text
exactly one rotation-pressure systemd unit installed anywhere (gurkdb);
no unit installed on devlap or odroid beyond the pre-existing disabled
devlap artifact; no competing writer process on either host
```

### Downstream verification

- Odroid publisher: independent scheduled service, unaffected by writer
  activation; its own next natural cycle republishes the new persisted
  state without any writer-side trigger.
- Profit Plan: `src/reporting/run_manual_short_trader_profit_plan_v1.py`
  reads `market_rotation_pressure_snapshot_v1` directly from the database at
  its own render time (no dependency on the Odroid-published JSON cache, no
  rotation recomputation). A render captured after this activation
  (`2026-08-08T11:54Z`) already reported `rotation.available=true`,
  `rotation.freshness=FRESH`, `rotation.source_ts_utc=2026-08-08T11:00:00Z`,
  matching the persisted state above exactly, for the aggregate and every
  per-market entry.

### Production decision evidence (unchanged)

`production_decision_evidence` continues to point at
`docs/ops/market_rotation_pressure_gurkdb_acceptance_20260808.md#production-decision-evidence`
(this same document, acceptance section above). Activation does not require
or produce a separate authorization decision; the same 2026-08-08
authorization already covers `AUTHORIZED_INACTIVE` -> `ACTIVE` per
`docs/ops/writer_capability_host_ownership_contract_v1.md`'s lifecycle rules
(both lifecycles require identical `production_authorization_status`,
`acceptance_status`, and evidence fields; `ACTIVE` additionally requires an
authorized observed active runtime for the owner host, recorded above and in
the registry's `observed_runtime_state`).

## Devlap Fence (unchanged)

`synth-market-rotation-pressure-writer.timer` on devlap remains `disabled`,
`inactive`; no writer process observed. This document does not authorize or
imply re-enabling devlap.

## Non-Goals

Beyond the gurkDB timer activation recorded above, this document does not:

- change the Rotation Pressure scoring model or the writer/publisher
  wrapper responsibility split;
- grant live trading, broker write, or order-submission permission;
- change Profit Plan code or the Odroid publisher's semantics.
