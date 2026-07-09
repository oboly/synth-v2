# Linked-Profile Runtime Orchestrator v1

Status: P0 implementation candidate.

This document defines the explicit linked-profile refresh owner for the public-price → account-snapshot → render pipeline.

## Why this exists

The 2026-07-05 incident exposed two separate runtime risks:

1. public/account/dashboard stages could stall independently;
2. rendered static pages could make stale data look fresh.

The current backlog already requires one explicit orchestration owner for the linked-profile path: public price snapshot refresh, then read-only account snapshot refresh per linked profile, then dashboard render from persisted snapshots only. The backlog also explicitly forbids relying on two independent timers joined only by offsets or ordering assumptions.

## Hard boundaries

```text
public market ingestion       = market-only, account-agnostic
account snapshot ingestion    = authenticated read-only persistence only
renderer                      = reads persisted snapshots only
selection_engine              = unchanged
decision_gate                 = unchanged in this slice
execution_planner             = unchanged
executor                      = unchanged
broker writes                 = forbidden
order submission              = forbidden
live trading                  = out of scope
```

## New owner

```text
scripts/odroid/run_linked_profile_runtime_orchestrator_once.sh
```

This script owns one scheduled cycle. It uses a single global `flock` before running any stage.

Stage order:

1. disk/log health check via `src.operations.run_runtime_disk_log_health_v1`;
2. public price snapshot refresh via `src.market_data.run_market_price_snapshot_v1 --write-db`;
3. linked-profile discovery via `src.account.run_linked_profile_dashboard_refresh_v1 --output profile-list`;
4. read-only account refresh per linked profile via `scripts/odroid/run_account_wallet_refresh_once.sh`;
5. safe snapshot render per linked profile via `scripts/odroid/run_account_wallet_snapshot_dashboard_render_once.sh`.

The orchestrator does not absorb module responsibilities. It only orders existing stage runners, records result metadata, and fails visibly when any stage degrades.

## Safe render successor

```text
scripts/odroid/run_account_wallet_snapshot_dashboard_render_once.sh
```

This is intentionally not a rename of the older account wallet dashboard wrapper.

It renders only pages that read persisted snapshots:

- account wallet dashboard;
- open-orders monitor.

It deliberately does **not**:

- refresh public prices;
- make private broker calls;
- build native SHORT context;
- publish native SHORT runtime files;
- render Profit Plan / Short Swing from generated native context.

Profit Plan / Short Swing remains blocked for this orchestrated path until its native SHORT/freshness input is promoted to a persisted snapshot contract. That is a later slice, not a renderer-side shortcut.

## Why the older linked wrapper is not reused

```text
scripts/odroid/run_linked_profile_dashboard_refresh_once.sh
```

That wrapper refreshes public prices and then builds a union native SHORT context before per-profile render. It also passes a native SHORT rows file into the per-profile render wrapper.

That behavior is useful as legacy operational evidence, but it is not a valid P0 orchestrator foundation because it mixes render orchestration with native SHORT context generation/publication.

The new orchestrator avoids that shortcut by using the safe snapshot renderer.

## Metadata contract

Every orchestrator run atomically writes:

```text
/var/www/html/synth/_runtime/linked_profile_orchestrator_v1/latest_run.json
```

Override:

```text
SYNTH_LINKED_PROFILE_RUNTIME_METADATA_PATH=/custom/path/latest_run.json
```

Schema:

```json
{
  "schema": "linked_profile_runtime_orchestrator_v1",
  "run_id": "...",
  "started_ts_utc": "...",
  "finished_ts_utc": "...",
  "overall_result": "ok|degraded",
  "venue": "bitvavo",
  "quote": "EUR",
  "profiles": ["joost", "hugo"],
  "profile_count": 2,
  "public_price_result": "ok|failed_continuing",
  "account_refresh": {
    "success": 2,
    "failure": 0
  },
  "snapshot_render": {
    "success": 2,
    "failure": 0
  },
  "stages": [
    {
      "phase": "refresh_public_prices",
      "profile": null,
      "result": "ok",
      "started_ts_utc": "...",
      "finished_ts_utc": "...",
      "elapsed_s": 1
    }
  ],
  "safety": {
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
    "renderer_private_broker_calls": 0,
    "native_short_context_build_in_render_stage": false
  }
}
```

## Systemd templates

```text
docs/ops/systemd/synth-linked-profile-runtime-refresh.service
docs/ops/systemd/synth-linked-profile-runtime-refresh.timer
```

These are templates only. Do not install them blindly.

Before installing on Odroid:

1. verify `/home/theone/projects/synth-v2` is the intended checkout;
2. verify `/home/theone/.config/synth/web-auth.env` contains the account credential master key source required by the account refresh runner;
3. verify the old independent account timers are disabled or intentionally not installed;
4. run a manual one-shot with the new timer disabled;
5. inspect `latest_run.json` and static rendered outputs;
6. only then consider enabling the new single timer.

## Old timer disposition

The old per-profile templates are superseded for the linked-profile runtime path:

```text
docs/ops/systemd/synth-account-wallet-refresh@.timer
docs/ops/systemd/synth-account-wallet-dashboard@.timer
```

They may remain in the repository as manual/legacy templates, but they must not be enabled alongside the new orchestrator for the same linked-profile runtime path.

Host rule:

```text
new orchestrator timer enabled  => old account refresh/dashboard timers disabled
old account timers enabled      => new orchestrator timer disabled
never both silently active
```

## Acceptance checklist

- [ ] Unit/smoke tests pass for the orchestrator and safe snapshot renderer.
- [ ] Manual Odroid one-shot succeeds with `synth-linked-profile-runtime-refresh.timer` disabled.
- [ ] `latest_run.json` contains per-stage timestamps and results.
- [ ] The old account refresh/dashboard timers are verified disabled or absent on Odroid.
- [ ] No native SHORT context build/publish appears in the new render path.
- [ ] No renderer private broker calls appear in logs.
- [ ] No broker writes, order submission, decision gate, planner, or executor path appears in logs.
- [ ] Several scheduled cycles show no overlap before this becomes the default runtime path.

## Non-goals

- No decision gate implementation.
- No selection engine change.
- No execution planner or executor change.
- No Profit Plan / Short Swing native map contract implementation.
- No automatic re-enable of `synth-paper-advice-lifecycle-refresh.timer`.
