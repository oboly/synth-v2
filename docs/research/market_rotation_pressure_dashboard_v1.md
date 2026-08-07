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
- the market-data writer and dashboard publisher are separate runtime owners.

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
| `scripts/run_market_rotation_pressure_once.sh` | locked market-data history -> pressure writer sequence; no reporting |
| `scripts/odroid/run_market_rotation_pressure_dashboard_render_once.sh` | locked read-only Odroid HTML/JSON publication |
| `tests/test_market_rotation_pressure_dashboard_v1.py` | focused fail-closed, rendering, and ownership tests |

## Published Artifacts

Default output:

```text
/var/www/html/synth/rotation-pressure.html
/var/www/html/synth/rotation-pressure.json
```

The HTML refreshes itself every five minutes. New data only appears after the market-data owner writes a new hourly pressure snapshot and the Odroid publisher rerenders it.

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

## Runtime Ownership

The market-data writer requires explicit `--write-db`:

```bash
bash scripts/run_market_rotation_pressure_once.sh --write-db
```

Market-data sequence:

1. `run_market_rotation_history_v1 --write-db`;
2. `run_market_rotation_pressure_v1 --write-db`.

It does not import or invoke reporting. The canonical market-data runtime host owns these writes.

The Odroid publisher is separate and read-only:

```bash
bash scripts/odroid/run_market_rotation_pressure_dashboard_render_once.sh
```

It reads persisted pressure rows and publishes local HTML/JSON. It never passes `--write-db` and must not become the writer owner.

The market-data writer:

- uses a non-blocking host lock;
- fails fast on phase failure;
- emits bounded phase and safety markers;
- activates `venv` or `.venv` when needed;
- has no implicit write mode;
- does not install or enable a scheduler;
- does not render or publish dashboard artifacts.

Market-data writer overrides:

```text
SYNTH_REPO_DIR
SYNTH_ROTATION_PRESSURE_LOCK
SYNTH_ROTATION_PRESSURE_VENUE
```

Odroid read-only publisher overrides:

```text
SYNTH_REPO_DIR
SYNTH_ROTATION_PRESSURE_DASHBOARD_LOCK
SYNTH_ROTATION_PRESSURE_OUTPUT_ROOT
SYNTH_ROTATION_PRESSURE_VENUE
```

## Deployment Sequence

Repository merge does not authorize production deployment by itself.

Operator sequence:

1. apply `db/migrations/20260712_market_rotation_pressure_v1.sql` through the canonical migration process;
2. run the history runner with `--dry-run` on the canonical market-data host;
3. run the pressure runner with `--dry-run` on that same host;
4. inspect universe size, missing-pair count, score distribution, top IN/OUT, and freshness;
5. run the locked market-data writer once with explicit `--write-db`;
6. rerun it in the same hour and verify DB idempotency;
7. run the Odroid read-only publisher and verify HTML/JSON output;
8. choose canonical existing writer and publisher owners, or add separately reviewed timers only after runtime ownership is confirmed.

A reviewed runtime-owner candidate (devlap writer timer, Odroid read-only
publisher timer, cadence evidence, installation, and rollback) is recorded in
`docs/ops/market_rotation_pressure_runtime_owners_v1.md`. That document is a
repository-reviewed candidate only; it does not itself authorize host
installation or timer enablement.

Do not silently attach the market-data writer to Profit Plan rendering. Reporting must never become the owner of market-data writes.

## Profit Plan Embedding (Implemented)

Issue #255 implemented the Profit Plan embedding described below as a
read-only reporting projection. It is a reporting-only consumer; it does not
change runtime ownership, cadence, or writer/publisher timers described
above.

New files:

- `src/reporting/market_rotation_profit_plan_projection_v1.py` — pure,
  DB-free module. Reuses `market_rotation_pressure_dashboard_v1.build_dashboard`
  (and `header_from_mapping`/`row_from_mapping`/`classify_freshness`
  transitively) to build a `RotationProfitPlanProjection` (aggregate) plus a
  `RotationMarketProjection` per persisted observation row, keyed by the
  canonical `market` string (e.g. `AERO-EUR`).
- Wired into `src/reporting/run_manual_short_trader_profit_plan_v1.py::main()`
  as a read-only DB fetch (`check_schema_ready`/`fetch_latest_snapshot`/
  `fetch_snapshot_observations`, imported from
  `run_market_rotation_pressure_dashboard_v1`) that degrades to an
  unavailable projection on any failure rather than blocking the render.
- Rendered by `src/reporting/manual_short_trader_profit_plan_v1.py` via
  optional `rotation_projection` kwargs on `render_full_html()` and
  `build_json_snapshot()` (both default `None`, preserving prior behavior
  when omitted).

Read-only consumer contract:

- Profit Plan reads only already-persisted `market_rotation_pressure_snapshot_v1`
  and `market_rotation_pressure_observation_v1` rows (via the dashboard's own
  fetch helpers). It never recomputes rotation score, direction, evidence-light
  count, breadth, acceleration, confirmation, or concentration state -- those
  values are always carried through verbatim from the persisted snapshot.
- The only value derived inside the projection is a display-only top-5
  rotation-in / top-5 rotation-out ranking, computed the same way as this
  dashboard's own top-lists, over already-persisted per-asset scores within
  one snapshot. This is a ranking of existing data, not a new score.
- A market with no matching persisted observation row renders an explicit
  "no rotation row" state (`ROTATION DATA UNAVAILABLE`); a stale or
  future/invalid snapshot renders a visibly degraded state
  (`ROTATION DATA STALE` / `ROTATION DATA UNAVAILABLE`). Missing or invalid
  rotation data never fails the Profit Plan render as a whole, and Profit
  Plan continues to render using its existing canonical market/account
  inputs when rotation context is unavailable.
- Rotation pressure state is market-only and account-agnostic. The same
  persisted snapshot may be projected into multiple account Profit Plans
  without duplicating computation and without any account-scoped field
  appearing on the projection.
