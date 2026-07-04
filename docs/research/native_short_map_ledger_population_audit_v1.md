# Native SHORT Map Ledger Population Audit v1

Date: 2026-07-04

## Result

Single root-cause classification: `UNMERGED_IMPLEMENTATION`.

The production database has the native SHORT map lifecycle schema applied, but the only implementation found that writes the append-only ledger exists on the unmerged local branch/worktree `feature/native-short-map-materializer-v1` at commits `cc4b919` and `4956178`. `main` has the PR1a schema/projection contract and read-only/research consumers, but no production writer for `native_short_map_v1`, `native_short_map_generation_event_v1`, or `native_short_map_lifecycle_event_v1`.

Secondary gap: even on the materializer branch, no systemd unit, Odroid wrapper, cron entry, or production scheduler was found for `python -m src.market_data.run_native_short_map_materializer_v1`; the documented trigger is a bounded manual canary run after explicit scope seeding.

## Tables Audited

- `native_short_map_v1`
- `native_short_map_generation_event_v1`
- `native_short_map_lifecycle_event_v1`

Related prerequisite/current-state table:

- `native_short_map_scope_v1`

## Production DB Evidence

Read-only command used:

```bash
python - <<'PY'
from src.common.db import get_connection

TABLES = [
    "native_short_map_scope_v1",
    "native_short_map_v1",
    "native_short_map_generation_event_v1",
    "native_short_map_lifecycle_event_v1",
    "native_short_map_current_lifecycle_v1",
]
conn = get_connection()
try:
    with conn.cursor() as cur:
        cur.execute("SELECT DATABASE() AS db_name, USER() AS user_name, @@hostname AS db_host")
        print(cur.fetchone())
        for table in TABLES:
            cur.execute(
                """
                SELECT TABLE_TYPE
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                """,
                (table,),
            )
            exists = cur.fetchone()
            if exists is None:
                print(f"{table}: MISSING")
                continue
            cur.execute(f"SELECT COUNT(*) AS row_count FROM `{table}`")
            row = cur.fetchone()
            print(f"{table}: {exists['TABLE_TYPE']} row_count={row['row_count']}")
finally:
    conn.rollback()
    conn.close()
PY
```

Observed configured database:

```text
db_name=synth
user_name=synth@192.168.1.64
db_host=gurkdb
native_short_map_scope_v1 row_count=0
native_short_map_v1 row_count=0
native_short_map_generation_event_v1 row_count=0
native_short_map_lifecycle_event_v1 row_count=0
native_short_map_current_lifecycle_v1 row_count=0
```

Cross-database read-only check:

```text
database=synth
  native_short_map_scope_v1: BASE TABLE row_count=0
  native_short_map_v1: BASE TABLE row_count=0
  native_short_map_generation_event_v1: BASE TABLE row_count=0
  native_short_map_lifecycle_event_v1: BASE TABLE row_count=0
database=synth_bt
  native_short_map_scope_v1: MISSING
  native_short_map_v1: MISSING
  native_short_map_generation_event_v1: MISSING
  native_short_map_lifecycle_event_v1: MISSING
```

Conclusion: the schema is applied in `synth`, the configured runtime DB is `synth`, and the append-only ledger is empty because neither scope seeding nor ledger materialization has populated it there. The rows are not hidden in `synth_bt`.

## Expected Producer

Expected producer found only in:

```text
/home/gurk/projects/synth-v2-native-short-map-materializer-v1
branch: feature/native-short-map-materializer-v1
commits:
  cc4b919 feat: add native short map materialiser PR1b (scope seeder + DB writer)
  4956178 test: add behavioral event-contract tests for materialise_scope_symbol
```

Entrypoints on that branch:

- Scope seeder: `scripts/seed_native_short_map_scopes_v1.py`
- Ledger materializer CLI: `src/market_data/run_native_short_map_materializer_v1.py`
- Ledger writer module: `src/market_data/native_short_map_materializer_v1.py`

Producer identity:

- `GENERATOR_NAME = "native_short_map_materializer_v1"`
- `GENERATOR_VERSION = "0.1"`
- `FIB_MODEL_NAME = "native_short_fib_context_v1"`
- `FIB_MODEL_VERSION = "0.1"`
- `TRIGGER_TYPE = "MANUAL_MATERIALISER_RUN"`

Evidence:

- `src/market_data/native_short_map_materializer_v1.py` lines 3-11 declare market-only safety markers and the exact read/write tables.
- `src/market_data/native_short_map_materializer_v1.py` lines 38-42 define the producer names and manual trigger type.
- `src/market_data/run_native_short_map_materializer_v1.py` lines 44-61 define the CLI and require explicit `--symbols`.
- `src/market_data/run_native_short_map_materializer_v1.py` lines 98-118 fetch supported scopes and fail when no `native_short_map_scope_v1` rows exist.

## Intended Trigger and Cadence

No recurring production cadence was found.

The materializer branch documents and implements a bounded manual canary trigger:

```bash
python -m scripts.seed_native_short_map_scopes_v1 --symbols BTC,ETH,SOL,XRP
python -m src.market_data.run_native_short_map_materializer_v1 --venue bitvavo --symbols BTC,ETH,SOL,XRP --dry-run
python -m src.market_data.run_native_short_map_materializer_v1 --venue bitvavo --symbols BTC,ETH,SOL,XRP
```

Evidence:

- `scripts/seed_native_short_map_scopes_v1.py` lines 12-19 document explicit canary scope seeding.
- `scripts/seed_native_short_map_scopes_v1.py` lines 95-112 write only `native_short_map_scope_v1`.
- `docs/architecture/native_short_map_lifecycle_v1.md` on `feature/native-short-map-materializer-v1` documents the canary rollout and expected four-symbol counts.
- Current `main` Odroid wrappers build and publish CSV native SHORT context files, not ledger rows:
  - `scripts/odroid/run_linked_profile_dashboard_refresh_once.sh` lines 105-142 runs `python -m src.market_data.run_native_short_fib_context_v1 --write-files`.
  - `scripts/odroid/run_account_wallet_dashboard_render_once.sh` lines 86-155 builds/validates/publishes `native_short_fib_context_rows_v1.csv`.
  - `docs/ops/account_wallet_dashboard_v1.md` lines 194-205 documents the five-minute wrapper output path under `/var/www/html/synth/.../_runtime/native_short_context_v1/`.

## Required Write Sequence and Transaction Boundary

The unmerged materializer performs one DB transaction per symbol.

Runner transaction evidence:

- `src/market_data/run_native_short_map_materializer_v1.py` lines 145-168 open a connection, call `conn.begin()`, run `materialise_scope_symbol(...)`, then `conn.commit()`.
- On exception it rolls back and records that symbol as failed; other symbols are independent.

Required successful publish sequence in `materialise_scope_symbol(...)`:

1. Read existing maps, generation events, lifecycle events for the scope.
2. Insert `ATTEMPT_STARTED` into `native_short_map_generation_event_v1`.
3. Insert immutable map row into `native_short_map_v1`.
4. Insert `PUBLISHED` generation event into `native_short_map_generation_event_v1` with `map_id`.
5. Insert `ACTIVATED` lifecycle event into `native_short_map_lifecycle_event_v1`.
6. If replacing an active map, insert `SUPERSEDED` lifecycle event for the previous map.
7. Run in-memory `validate_native_short_map_write_intent(...)` before commit.

Evidence:

- Generation insert helper: `src/market_data/native_short_map_materializer_v1.py` lines 345-383.
- Map insert helper: `src/market_data/native_short_map_materializer_v1.py` lines 386-473.
- Lifecycle insert helper: `src/market_data/native_short_map_materializer_v1.py` lines 476-502.
- Publish sequence: `src/market_data/native_short_map_materializer_v1.py` lines 604-648.
- Validation call: `src/market_data/native_short_map_materializer_v1.py` lines 700-705.

Rejected/unavailable context sequence:

- Insert `ATTEMPT_STARTED`.
- Insert terminal `REJECTED`.
- Do not insert `native_short_map_v1` or lifecycle event rows.

Evidence: `src/market_data/native_short_map_materializer_v1.py` lines 530-555.

Unchanged structure sequence:

- Insert `ATTEMPT_STARTED`.
- Insert terminal `SKIPPED`.
- Do not insert a duplicate map.

Evidence: `src/market_data/native_short_map_materializer_v1.py` lines 571-595.

## Schema and Contract Evidence on Main

Merged PR that introduced the lifecycle schema:

```text
c7dd99d Merge pull request #32 from oboly/feat/map-lifecycle-audit-core
```

Files introduced by that PR:

- `.github/workflows/pr_mariadb_ddl_validation.yml`
- `db/migrations/20260626_native_short_map_lifecycle_v1.sql`
- `src/market_data/native_short_map_lifecycle_v1.py`
- `tests/test_native_short_map_lifecycle_migration_v1.py`
- `tests/test_native_short_map_lifecycle_v1.py`

Important boundary evidence:

- `db/migrations/20260626_native_short_map_lifecycle_v1.sql` lines 1-11 explicitly says this migration is market-only, account-agnostic, and has no generator/runtime integration, no scheduler, no UI/API wiring, no wallet/account state, and no decision/planner/executor changes.
- `src/market_data/native_short_map_lifecycle_v1.py` lines 3-10 says PR1a owns immutable map shape, append-only event shapes, lifecycle projection, and write-intent validation only; PR1b writes must call the validator.
- `db/migrations/20260626_native_short_map_lifecycle_v1.sql` lines 45-88 define `native_short_map_v1`.
- `db/migrations/20260626_native_short_map_lifecycle_v1.sql` lines 149-233 define `native_short_map_generation_event_v1`.
- `db/migrations/20260626_native_short_map_lifecycle_v1.sql` lines 236-283 define `native_short_map_lifecycle_event_v1`.
- `db/migrations/20260626_native_short_map_lifecycle_v1.sql` lines 463-565 define `native_short_map_current_lifecycle_v1`, which projects from scope, map, generation, and lifecycle rows.

Main has no production writer:

```bash
rg -n "INSERT INTO native_short_map|native_short_map_materializer|run_native_short_map_materializer" .
```

Finding: no production materializer or insert path exists on current `main`; references are DDL, tests, lifecycle validation/projection, research readers, and dashboard CSV context generation.

## Reference Inventory Across Worktrees

Search commands used:

```bash
rg -n "native_short_map_v1|native_short_map_generation_event_v1|native_short_map_lifecycle_event_v1|native_short_map_scope_v1|native_short_map_current_lifecycle_v1|validate_native_short_map_write_intent|INSERT INTO native_short_map" .
rg -n "run_native_short_map_materializer|native_short_map_materializer|seed_native_short_map_scopes" scripts docs deploy apps src
```

Current audit branch / `origin/main`:

- DDL and views: `db/migrations/20260626_native_short_map_lifecycle_v1.sql`.
- Pure contract/projection/validation: `src/market_data/native_short_map_lifecycle_v1.py`.
- Tests: `tests/test_native_short_map_lifecycle_v1.py`, `tests/test_native_short_map_lifecycle_migration_v1.py`, `tests/test_short_swing_map_outcome_baseline_v1.py`.
- Research reader: `src/research/run_short_swing_map_outcome_baseline_v1.py` reads all three audited tables but does not write them.
- Signal inventory docs/tests reference native SHORT map context lineage/freshness but do not populate the ledger.
- No `INSERT INTO native_short_map...` production path was found outside tests.

`/home/gurk/projects/synth-v2-map-lifecycle-audit-core`:

- Branch: `feat/map-lifecycle-audit-core`.
- Contains PR1a schema/contract/testing work through `f0dfea4`, `3425ed0`, and `389bdfa`.
- No materializer, scope seeder, scheduler, or production writer found.

`/home/gurk/projects/synth-v2-map-rollover`:

- Branch: `fix/native-short-map-lifecycle-rollover-v1`.
- Contains native SHORT context bridge/dashboard refresh work (`426d49d`, `d28e101`, `adcd4c6`, `dc3fe79`) and P0 fast recompute docs.
- No audited-table writer found; the branch builds native SHORT CSV context and dashboard/runtime refresh context, not the append-only ledger.

`/home/gurk/projects/synth-v2-native-short-map-audit-v1`:

- Branch: `feature/native-short-map-audit-v1`.
- Points at the older merged PR #36 baseline and contains PR1a lifecycle schema/contract references.
- No materializer, scope seeder, scheduler, or production writer found.

`/home/gurk/projects/synth-v2-native-short-map-materializer-v1`:

- Branch: `feature/native-short-map-materializer-v1`.
- Contains the only writer implementation:
  - `scripts/seed_native_short_map_scopes_v1.py`
  - `src/market_data/native_short_map_materializer_v1.py`
  - `src/market_data/run_native_short_map_materializer_v1.py`
  - `tests/test_native_short_map_materializer_v1.py`
  - `docs/architecture/native_short_map_lifecycle_v1.md`
- No systemd/timer/cron/Odroid wrapper invoking `run_native_short_map_materializer_v1` was found.

Lifecycle observer status:

- No separate production observer was found for terminal lifecycle events such as `COMPLETED`, `EXPIRED`, or `INVALIDATED`.
- The unmerged materializer writes `ACTIVATED` for new maps and `SUPERSEDED` when replacing an active map.

## P0-A / Wrong Database Assessment

`WRONG_DATABASE` is not the root cause.

Evidence:

- `src/common/db.py` lines 32 and 67-77 default normal runtime connections to `DB_NAME`/`MYSQL_DATABASE`, defaulting to `synth`.
- `compose.yaml` lines 4-8 and 27-33 configure the runtime database as `synth`.
- The read-only DB probe connected to `synth` on `gurkdb` and found the tables present but zero-row.
- The read-only cross-DB probe found these tables missing in `synth_bt`.
- `docs/status/synth_gurkdb_migration_status.md` lines 146-170 describe `synth_bt` as a separately migrated research/backtest DB, not the runtime native SHORT ledger target.

The P0-a smoke references found in related branches are unrelated to this ledger. They refer to fast recompute lifecycle work:

- `docs/ops/fast_recompute_lifecycle_refresh_v1.md` lines 1-7 define P0-a as `src/reporting/run_fast_recompute_lifecycle_v1.py`, P0-b as an advice/zone refresh consumer, and P0-c as Odroid market-context refresh wiring.
- `docs/ops/fast_recompute_lifecycle_refresh_v1.md` lines 11-17 state that lane is market-only but is about zone/advice refresh, not native SHORT ledger materialization.

Conclusion: if a P0-a smoke returned no native SHORT map ledger rows, that result was expected because P0-a does not populate these tables. The configured readonly DB returned zero rows because the relevant producer was never merged/run against `synth`, not because the smoke targeted `synth_bt`.

## Table Population Status

`native_short_map_scope_v1`

- Currently populated anywhere in configured DB: no.
- Current row count in `synth`: 0.
- Needed before materialization: yes.
- Producer found only on unmerged branch: `scripts/seed_native_short_map_scopes_v1.py`.

`native_short_map_v1`

- Currently populated anywhere in configured DB: no.
- Current row count in `synth`: 0.
- Intended producer: `src.market_data.run_native_short_map_materializer_v1` calling `materialise_scope_symbol(...)`.
- Main status: no writer exists.
- Unmerged implementation status: writer exists on `feature/native-short-map-materializer-v1`.

`native_short_map_generation_event_v1`

- Currently populated anywhere in configured DB: no.
- Current row count in `synth`: 0.
- Intended producer: same materializer; writes `ATTEMPT_STARTED` plus terminal `PUBLISHED`, `REJECTED`, or `SKIPPED`.
- Main status: no writer exists.
- Unmerged implementation status: writer exists on `feature/native-short-map-materializer-v1`.

`native_short_map_lifecycle_event_v1`

- Currently populated anywhere in configured DB: no.
- Current row count in `synth`: 0.
- Intended producer: same materializer; writes `ACTIVATED` and optional `SUPERSEDED` during publish.
- Main status: no writer exists.
- Unmerged implementation status: writer exists on `feature/native-short-map-materializer-v1`.

## Gap Classification Matrix

- `NOT_IMPLEMENTED`: false for the repo family overall; true only on current `main`.
- `IMPLEMENTED_NOT_SCHEDULED`: true as a secondary condition on the materializer branch.
- `WRONG_DATABASE`: false.
- `MIGRATION_NOT_APPLIED`: false.
- `PRODUCER_FAILED`: no evidence.
- `DATA_PRUNED`: no evidence; tables are append-only and no pruning path was found.
- `UNMERGED_IMPLEMENTATION`: true; root cause.
- `UNKNOWN`: false.

## Smallest Safe Next Implementation Slice

Recommended next branch name:

```text
feature/native-short-map-ledger-materializer-canary-v1
```

Smallest safe slice:

1. Bring the unmerged materializer implementation into a new branch from current `main`, preserving market-only boundaries and current PR47 baseline files.
2. Include only:
   - `scripts/seed_native_short_map_scopes_v1.py`
   - `src/market_data/native_short_map_materializer_v1.py`
   - `src/market_data/run_native_short_map_materializer_v1.py`
   - focused tests for write-intent/order/idempotency behavior
   - one ops doc with manual canary commands and SELECT verification
3. Do not add systemd, cron, Odroid scheduling, dashboard writes, broker/account reads, decision gate, execution planner, executor, backfills, or production config changes.
4. Keep the first run manual and bounded:
   - dry-run scope seeder
   - apply scope seeder for `BTC,ETH,SOL,XRP` only after explicit operator approval
   - materializer `--dry-run`
   - one manual materializer write canary only after review
   - verify with `SELECT COUNT(*)`, generation event summary, current lifecycle view, and open-attempt view

Safety boundary to preserve:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```
