# Odroid live-like runtime retention v1

Status: proposed implementation for Issue #229. This document defines the bounded-retention owner for live-like runtime artifacts on Odroid.

## Scope and ownership

Retention is an operations concern. Research runners remain deterministic producers and are not responsible for deleting historical output.

The retention owner may act only on these five repository-relative roots:

- `data/research/live_like_shadow_event_v1`
- `data/research/live_like_shadow_chain_v1`
- `data/research/live_like_execution_plan_preview_v1`
- `data/research/live_like_decision_preview_v1`
- `data/research/intraday_retest_reclaim_candidate_v1`

No other research, runtime, database, web, or repository path is in scope.

## Retention contract

Default policy:

- retain every canonical run from the most recent 7 days;
- independently retain at least the newest 288 canonical runs in each root;
- delete a run only when it is both older than 7 days and outside the newest 288 runs for that root;
- the run timestamp is derived only from the canonical directory name `run_YYYYMMDDTHHMMSSZ`;
- dry-run is the command default; deletion requires explicit `--apply`.

At the current approximately five-minute producer cadence, 288 runs is approximately one day of minimum rollback/debug history even if timestamps or cadence are irregular.

## Fail-closed boundaries

The retention owner:

- uses an exact code-defined root allowlist;
- never follows a managed-root or run-directory symlink;
- fails if a canonical-looking `run_*` entry has a malformed timestamp;
- fails if a canonical run entry is not a directory;
- fails if a symlink occurs anywhere inside a deletion candidate while sizing it;
- revalidates each candidate immediately before deletion;
- does not use filesystem modification time as retention authority;
- does not archive, mutate, or rewrite artifact content.

Unrelated non-`run_*` files under a managed root are ignored and never eligible for deletion.

## Runtime

Canonical implementation:

`python -m src.ops.live_like_runtime_retention_v1`

Canonical Odroid entry point (wraps the implementation with the standard
`scripts/odroid/run_*_once.sh` pattern: `flock` serialization, venv
activation with a fail-closed fallback, and `STARTED`/`FINISHED`
observability markers):

`scripts/odroid/run_live_like_runtime_retention_once.sh`

Dry-run example (direct module invocation):

```text
python -m src.ops.live_like_runtime_retention_v1 \
  --repo-root /home/theone/projects/synth-v2 \
  --retention-days 7 \
  --min-recent-runs 288
```

Apply example (direct module invocation):

```text
python -m src.ops.live_like_runtime_retention_v1 \
  --repo-root /home/theone/projects/synth-v2 \
  --retention-days 7 \
  --min-recent-runs 288 \
  --apply
```

Wrapper dry-run example (mirrors the systemd default):

```text
SYNTH_REPO_DIR=/home/theone/projects/synth-v2 \
SYNTH_LIVE_LIKE_RETENTION_APPLY=0 \
bash scripts/odroid/run_live_like_runtime_retention_once.sh
```

Wrapper apply example (only after pre-activation acceptance below has
passed):

```text
SYNTH_REPO_DIR=/home/theone/projects/synth-v2 \
SYNTH_LIVE_LIKE_RETENTION_APPLY=1 \
bash scripts/odroid/run_live_like_runtime_retention_once.sh
```

Every run reports per-root run counts, planned deletion counts, and planned reclaim bytes. Dry-run lists exact candidates before any destructive mode is used.

The wrapper's destructive `--apply` pass-through is gated by the
`SYNTH_LIVE_LIKE_RETENTION_APPLY` environment variable, default `0`
(dry-run only). It is not baked into the systemd unit as a hardcoded flag; the
unit sets the same variable explicitly so the default stays visible and
auditable in one place.

## systemd ownership

Reference units:

- `docs/ops/systemd/synth-live-like-runtime-retention.service`
- `docs/ops/systemd/synth-live-like-runtime-retention.timer`

The service runs `scripts/odroid/run_live_like_runtime_retention_once.sh`,
not the Python module directly, so it gets the same lock serialization, venv
fallback, and observability markers as every other Odroid `run_*_once.sh`
job. The timer runs the retention owner every six hours with a small
randomized delay. The service is a separate oneshot and does not run inside
`synth-linked-profile-runtime-refresh.service`.

This separation is intentional: a retention failure must not alter or block the research producer chain.

## Pre-activation acceptance on Odroid

Before enabling the timer:

1. Deploy the merged code and reference units to the Odroid checkout/systemd location using the normal host deployment process.
2. Run the retention command without `--apply`.
3. Capture the exact candidate count and reclaim-byte estimate for all five roots.
4. Confirm there are no malformed entries or symlink failures.
5. Spot-check oldest retained and newest deletion candidates against the 7-day/288-run boundary.
6. Run focused tests for the retention module.
7. Only then run one manual apply invocation with `SYNTH_LIVE_LIKE_RETENTION_APPLY=1` (either the wrapper or the module's `--apply` flag).
8. Re-run dry-run and confirm there are no immediately eligible candidates left.
9. Verify linked-profile runtime refresh and dashboard behavior remain healthy.
10. Only after the manual apply acceptance passes: set `SYNTH_LIVE_LIKE_RETENTION_APPLY=1` in the deployed systemd unit and enable the timer.

## Rollback

The retention implementation changes no producer or consumer paths. Rollback is therefore:

- disable the retention timer;
- remove/disable the retention service unit if required;
- revert the code change.

Deleted artifacts are intentionally not reconstructable by the retention owner. Therefore activation must remain gated by the pre-activation dry-run and candidate review.

Long-term archival, if required, must be a separate explicit owner and is not part of this deletion policy.

## Relationship to other disk work

- Issue #229 owns bounded live-like runtime artifact retention.
- Issue #216 separately owns archival/removal of the inactive legacy MariaDB datadir on Odroid.
- SSD migration increases capacity but does not replace this retention requirement.
