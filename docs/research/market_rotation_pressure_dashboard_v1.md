# Market Rotation Pressure Dashboard V1

## Status

Repository implementation complete for review. Host migration, production-connected write validation, timer installation, timer enablement, and service restart are separate operator actions.

## Purpose

Expose `market_rotation_pressure_v1` as a read-only operational research page with:

- aggregate rotation direction;
- market score;
- zero to five evidence lights;
- positive and negative breadth;
- acceleration, 24h/7d confirmation, and concentration;
- top rotation-in and rotation-out markets;
- a complete per-market pressure table.

The page uses `ROTATION_IN` and `ROTATION_OUT`. It must not claim verified fund flow or capital flow.

## Architecture

```text
obs_market_candle
  -> market_rotation_history_v1
  -> market_rotation_pressure_v1
  -> market_rotation_pressure_dashboard_v1
  -> HTML + JSON publication
```

Ownership is strict:

- rotation history owns candle-derived 24h/7d measurements;
- rotation pressure owns score and state computation;
- dashboard reporting only reads and renders persisted pressure state;
- the dashboard does not recompute scores;
- the wrapper only sequences the three owners.

No component touches:

- `selection_engine`;
- `decision_gate`;
- `execution_planner`;
- executor or agents;
- broker, account, balance, position, or order state.

## Files

| File | Responsibility |
|---|---|
| `src/reporting/market_rotation_pressure_dashboard_v1.py` | pure read-model normalization, freshness, JSON projection, and HTML rendering |
| `src/reporting/run_market_rotation_pressure_dashboard_v1.py` | read-only DB adapter and atomic HTML/JSON publication |
| `scripts/run_market_rotation_pressure_once.sh` | locked history -> pressure -> dashboard sequence |
| `tests/test_market_rotation_pressure_dashboard_v1.py` | focused fail-closed and rendering tests |

## Published Artifacts

Default output:

```text
/var/www/html/synth/rotation-pressure.html
/var/www/html/synth/rotation-pressure.json
```

The HTML refreshes itself every five minutes. New data only appears after the market-only wrapper writes a new hourly pressure snapshot.

## Light Bar Contract

The dashboard renders the exact persisted `evidence_light_count` from Pressure V1. Reporting must not independently derive lights.

Direction controls active-light color:

- `ROTATION_IN`: positive;
- `ROTATION_OUT`: negative;
- `MIXED`: warning/mixed.

Inactive lights remain neutral.

The five underlying evidence checks remain owned and versioned by `market_rotation_pressure_v1`:

1. aggregate market score has directional magnitude;
2. directional breadth is material and dominant;
3. 24h and 7d direction confirm;
4. acceleration or persistence confirms;
5. movement is broad or selective rather than concentrated.

## Freshness and Fail-Closed Behavior

A snapshot is:

- `FRESH` up to 2 hours 30 minutes old;
- `STALE` after that;
- `FUTURE_TIMESTAMP` when more than five minutes ahead;
- `DATA_UNAVAILABLE` when no snapshot exists.

A stale or future snapshot renders as `DEGRADED` with a visible freshness state.

The dashboard refuses publication when:

- target tables are missing;
- no pressure snapshot exists;
- stored observation count differs from `eligible_asset_count`;
- persisted numeric fields are non-finite;
- persisted direction or light count violates the contract.

An existing good page is not overwritten by a failed render.

## Runtime Wrapper

The wrapper requires explicit `--write-db`:

```bash
bash scripts/run_market_rotation_pressure_once.sh --write-db
```

Sequence:

1. `run_market_rotation_history_v1 --write-db`;
2. `run_market_rotation_pressure_v1 --write-db`;
3. `run_market_rotation_pressure_dashboard_v1` read-only publication.

The wrapper:

- uses a non-blocking host lock;
- fails fast on phase failure;
- emits bounded phase and safety markers;
- activates `venv` or `.venv` when needed;
- has no implicit write mode;
- does not install or enable a scheduler.

Environment overrides:

```text
SYNTH_REPO_DIR
SYNTH_ROTATION_PRESSURE_LOCK
SYNTH_ROTATION_PRESSURE_OUTPUT_ROOT
SYNTH_ROTATION_PRESSURE_VENUE
```

## Deployment Sequence

Repository merge does not authorize production deployment by itself.

Operator sequence:

1. apply `db/migrations/20260712_market_rotation_pressure_v1.sql` through the canonical migration process;
2. run the history runner with `--dry-run`;
3. run the pressure runner with `--dry-run`;
4. inspect universe size, missing-pair count, score distribution, top IN/OUT, and freshness;
5. run the locked wrapper once with explicit `--write-db`;
6. verify HTML and JSON output plus DB idempotency with a second same-hour run;
7. choose a canonical existing hourly owner or add a separately reviewed timer only after runtime ownership is confirmed.

Do not silently attach this writer to Profit Plan rendering. Reporting must never become the owner of market-data writes.

## Deferred Follow-up

Embedding the strip in Profit Plan is a reporting-only follow-up after host acceptance. It should read the same published JSON or persisted pressure snapshot; it must not duplicate scoring or light logic inside `manual_short_trader_profit_plan_v1.py`.
