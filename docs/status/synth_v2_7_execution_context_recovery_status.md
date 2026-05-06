# Synth v2.7 Execution Context Recovery Status

## Current state

Last confirmed HEAD:

- `eaa8fa7 Move trade setup filter observation DDL to migration`

Recent relevant commits:

- `eaa8fa7 Move trade setup filter observation DDL to migration`
- `d25cb4c Remove plan lifecycle from paused chains`
- `066a7d4 Document execution context recovery status`
- `91eac01 Keep operational zone context latest-only`
- `e25154d Document Synth v2.6 execution schema status`

Branch status at last confirmation:

- `main == origin/main`
- working tree clean after push
- live trading permission: `NOT_GRANTED`
- chains remain paused in crontab

## Recovery outcome

Operational `execution_zone_context` recovery succeeded.

Verified:

- latest-only 4h operational context restored
- LINK context restored
- no missing/stale context rows for enabled tracked assets
- no contaminated/historical rows in operational `execution_zone_context`
- `src.zone.run_zone_engine_v1` import works
- zone context generation writes current/latest operational rows only

The zone runner was hardened:

- default `--limit-assets` increased from 40 to 100
- before write, current scope is deleted by:
  - venue
  - interval_code
  - sleeve_code
  - optional asset_id
- this keeps operational `execution_zone_context` latest-only

## Chain safety cleanup

The paused chain scripts were cleaned:

- removed `src.plan_lifecycle.run_plan_lifecycle` from:
  - `scripts/run_chain_1h.sh`
  - `scripts/run_chain_4h.sh`
  - `scripts/run_chain_1d.sh`
- replaced `set -euo pipefail` with `set -u`
- added explicit `run_step` wrappers
- preserved flock overlap protection
- added 4h zone context restore to `scripts/run_chain_4h.sh`

Current intended 4h chain shape:

1. candles ETL
2. feature build
3. signal state ETL
4. advice engine
5. ranking engine
6. asset interval quality snapshot
7. selection engine
8. trade setup filter observation
9. latest-only zone context restore

Forbidden runtime modules remain out of the paused chains:

- decision_gate
- execution_planner
- executor
- broker/order handling
- plan_lifecycle

## Crontab safety

Crontab status:

- chain jobs remain commented with `PAUSED_FOR_SIGNAL_BACKFILL`
- backup DDL log typo was corrected from `synt-v2` to `synth-v2`
- exact bad path `/home/gurk/projects/synt-v2` no longer present

Active cron jobs are limited to:

- Bitvavo ticker24h ETL
- CoinGecko asset/global ETL
- backups

## Trade setup filter cleanup

Runtime DDL was removed from `src/trade_setup_filter/observation_repository.py`.

The schema now lives in:

- `db/migrations/20260507_trade_setup_filter_observation_v1.sql`

Runtime now only verifies table existence before writing observations.

Verified:

- Python compile passes
- no `CREATE TABLE`, `DROP TABLE`, or `ALTER TABLE` remains in `src/trade_setup_filter`
- `synth.trade_setup_filter_observation` exists in the current dev DB

## Important boundary

`trade_setup_filter` is still market-only / observation-only.

Allowed:

- read latest selection/ranking/BTC context
- evaluate market-only setup filter state
- write market-only observation rows

Forbidden:

- account state
- balance state
- position state
- open order state
- execution plans
- execution events
- broker/order calls

## Next verification

Wait for the next completed 4h candle, then run one manual 4h chain smoke while cron remains paused.

The manual smoke should verify:

- chain exits cleanly
- `execution_zone_context` contains exactly latest 4h operational context rows
- no missing/stale context rows
- no contaminated/historical operational context rows
- no execution/decision/planner/executor/order tables are touched by the chain

Do not resume cron chains until this manual 4h smoke passes.
