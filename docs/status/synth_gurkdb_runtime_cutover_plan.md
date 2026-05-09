# Synth gurkDB Runtime Cutover Plan

Date: 2026-05-09  
Status: plan only, runtime not enabled.

## Goal

Move Synth operational runtime from Odroid/lapgurk-style development execution toward gurkDB as the primary live server, without accidentally enabling writers or live trading.

This plan follows the current infrastructure direction:

- lapgurk: dev/control plane
- gurkDB: MariaDB plus later controlled Synth runtime
- Odroid: fallback/watchdog/light monitor or retired source role
- game PC: heavy backtests, ML, research compute

## Current proven state

The following chain has already been verified:

    lapgurk
    -> ssh gurkdb
    -> rsynced repo at ~/projects/synth-v2
    -> gurkDB .venv
    -> gurkDB .env
    -> MariaDB on gurkDB:/Data/mariadb
    -> migrated synth data
    -> v_signal_rule_state_latest restored
    -> read-only live advice report works

The operational `synth` database has been migrated and row counts matched the Odroid source for the core tables.

## Non-goals for this phase

Do not enable:

- live trading
- broker/order calls
- executor agents
- execution planner runtime
- decision gate runtime
- cron chains
- automatic ETL writers
- automatic feature writers
- signal/advice/ranking writers
- any loop that writes continuously

Live trading permission remains not granted.

## Runtime cutover stages

### Stage 0 - Frozen source state

Status: current baseline.

Rules:

- Keep Odroid source DB read_only = ON.
- Do not resume old Odroid cron chains.
- Do not start duplicate writers on lapgurk or gurkDB.
- Keep gurkDB as the tested target database.

Exit criteria:

- gurkDB read-only report works.
- No obvious writer processes are running.
- Migration status is documented.

### Stage 1 - gurkDB read-only runtime checks

Allowed:

- read-only reports
- schema inspection
- row-count checks
- latest timestamp checks
- repo/version checks
- DB connection tests

Forbidden:

- ETL writes
- feature writes
- signal/advice/ranking writes
- decision/execution writes
- cron activation

Recommended commands:

    python -m src.reporting.run_live_advice_report_extended --venue bitvavo --limit 5

Exit criteria:

- Read-only report succeeds on gurkDB.
- Required views are restored only as needed.
- No missing table/view errors for chosen read-only checks.

### Stage 2 - Controlled single-shot ETL test

Purpose:

Validate that one explicitly bounded ETL write can run safely on gurkDB.

Allowed only after explicit approval.

Rules:

- Use a tiny bounded window.
- Run manually.
- Log output.
- Verify exact affected row counts.
- Do not enable cron.
- Do not run the full chain.

Candidate scope:

- one interval
- one short time window
- preferably non-critical or already-current data window

Exit criteria:

- No duplicate/unstable writes.
- ETL idempotency is verified.
- DB row growth matches expectation.

### Stage 3 - Controlled feature write test

Purpose:

Validate feature generation on gurkDB after ETL.

Rules:

- Must run only after Stage 2 passes.
- Use bounded write window.
- Keep warmup/source window explicit.
- Do not run unbounded feature rebuilds.
- Do not enable cron.

Relevant current stash on lapgurk:

    stash@{0}: On main: wip bounded 1h chain and feature write window before gurkdb migration

This stash may be reviewed before enabling bounded feature updates.

Exit criteria:

- feat_candle updates are bounded.
- latest timestamps are correct.
- no broad unintended backfill occurs.

### Stage 4 - Signal/advice/ranking single-shot test

Purpose:

Validate the write chain after features are proven safe.

Allowed sequence:

1. signal_engine_state
2. advice_state
3. ranking_state / selection state if applicable

Rules:

- Manual only.
- One interval only.
- No cron.
- No execution/decision runtime.
- Compare latest snapshots before and after.
- Verify no duplicate active states.

Exit criteria:

- Latest snapshot updates are correct.
- Report still works.
- No unexpected rows in decision/execution tables.

### Stage 5 - Paper/runtime planning

Purpose:

Design runtime orchestration without enabling it yet.

Must explicitly define:

- which scripts run
- cadence
- expected write tables
- log paths
- lock behavior
- health checks
- rollback command
- disabled live trading guard
- whether Odroid acts as watchdog

Forbidden until this stage is approved:

- execution planner runtime
- decision gate runtime
- executor runtime
- broker calls
- live order placement

### Stage 6 - Cron activation

Only after all previous stages pass.

Rules:

- Enable one chain at a time.
- Start with read-only or lowest-risk writer.
- Use clear log paths.
- Confirm no overlap locks.
- Confirm no old Odroid cron is active.
- Confirm no duplicate runtime on lapgurk.

## Rollback posture

Current rollback posture:

- Odroid source DB remains read_only = ON.
- gurkDB DB is primary migration target.
- Do not destroy Odroid source DB yet.
- Do not delete migration dumps yet.
- Do not remove incoming_synth_db_migration yet.

If gurkDB runtime fails before writers are enabled:

- keep gurkDB DB intact
- fix runtime/repo/env
- no database rollback needed

If writer tests corrupt target data:

- stop all writers
- inspect affected tables
- restore from migration dump if needed
- keep Odroid read_only source as reference

## Known open items

- MariaDB AppArmor on gurkDB remains in complain mode.
- `synth_bt` is not migrated yet.
- Most historical/research views are not migrated.
- Only `v_signal_rule_state_latest` has been restored.
- `.env` exists on lapgurk and gurkDB with DB credentials; do not commit it.
- Source Odroid DB remains read_only = ON.

## Hard rule

Do not enable automated writers or cron until a specific GO is given for the exact stage.

Runtime cutover must remain explicit, bounded, and reversible.
