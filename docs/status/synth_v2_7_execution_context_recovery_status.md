# Synth v2.7 Execution Context Recovery Status

Last updated: 2026-05-06

## Current state

- Live trading permission: NOT_GRANTED.
- 1h, 4h, and 1d chains remain paused in crontab.
- Planner/executor/runtime integration was not touched.
- No broker/order calls were made.
- `execution_zone_context` has been restored as a latest-only operational table.

## Operational context scope

- Venue: `bitvavo`
- Interval: `4h`
- Sleeve: `SWING_STRUCTURAL`
- Context rows: 41
- Covered assets: 41
- Current `asof_ts_utc`: `2026-05-06 16:00:00`
- Contaminated historical backfill rows: 0
- LINK asset_id 70 is included and no longer missing.

## Code hardening committed

Latest relevant commit:

- `91eac01 Keep operational zone context latest-only`

Changes:

- `src/zone/repository.py`
  - Added `delete_execution_zone_context_scope()`.
  - Deletes existing context rows for venue + interval + sleeve, optionally scoped to one asset.

- `src/zone/run_zone_engine_v1.py`
  - Deletes existing scoped context before `--write-db`.
  - Default `--limit-assets` increased from 40 to 100 to avoid silently excluding LINK/other enabled assets.

## Crontab status

Chains remain paused:

- `run_chain_1h.sh`
- `run_chain_4h.sh`
- `run_chain_1d.sh`

Backup DDL typo was fixed:

- Correct path:
  `/home/gurk/projects/synth-v2/logs/backup_ddl.log`

## Architecture invariants

- `selection_engine` remains market-only and account-agnostic.
- `decision_gate` remains the account-aware permission layer.
- `execution_planner` remains execution intent/planning only.
- `executor` / agents remain order handling only.
- Historical/research context backfills must not write into `synth.execution_zone_context`.
- Research/backtest history belongs in `synth_bt` or dedicated research tables.

## Next TODO

1. Verify repo clean and `main == origin/main`.
2. Inspect the 4h chain script before unpausing anything.
3. Confirm the chain order is candle-close safe:
   - market ETL complete
   - features complete
   - signals complete
   - selection/advice/replay complete
   - only then downstream consumers
4. Add or verify a guard that fails if `execution_zone_context` is missing/stale for enabled tradeable assets.
5. Do not resume planner/executor/live loops without explicit approval.
