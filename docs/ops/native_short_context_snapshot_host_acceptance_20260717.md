# Native SHORT Context Snapshot — PR A Host Acceptance — 2026-07-17

## Status

PASS.

This document records the formal installed-host acceptance for PR A
(**PR #106**, "Add market-only native SHORT context snapshot") on the Odroid
runtime host. It is an evidence record, not a replacement for live host checks.
Always re-check the host before enabling or changing recurring runtime owners.

This acceptance proves the installed 4h owner can safely produce the canonical
native SHORT snapshot contract through a no-publish dry-run and an isolated
temp publication. It does **not** authorize manual canonical publication,
systemd/timer/checkout mutation, PR B deployment, or legacy-unit retirement.

## Accepted scope

```text
formal host acceptance of the installed PR #106 native SHORT snapshot publisher
via manual no-publish dry-run + isolated temp publication + contract validation
```

Out of scope (unchanged, still gated):

```text
manual canonical native SHORT publication
PR #113 (safe Profit Plan render owner) merge/deploy
systemd/timer/checkout mutation
legacy user-level dashboard/refresh unit retirement
multi-cycle Lane C operational acceptance
Profit Plan render/publication
decision_gate / execution_planner / executor / broker writes / order submission
database mutation / account refresh
```

## Repository state at acceptance

```text
origin_main=3656e04 (Lane C P2-B classifier, PR #112 merged)
pr_106_merge=6b5f3ee (contained in origin/main)
pr_112_merged=true
pr_113_state=OPEN/draft (fix/profit-plan-safe-render-owner-v1) — untouched
contract=docs/architecture/native_short_fib_context_snapshot_contract_v1.md
publisher=src/market_data/run_native_short_fib_context_snapshot_v1.py
```

## Installed-host state (read-only audit)

Captured on Odroid; no host unit, timer, checkout, or canonical output mutated.

```text
hostname=odroid
service_user=theone
checkout_path=/home/theone/projects/synth-v2
git_branch=main
git_head=6b5f3ee (== PR #106 merge; PR #106 CONTAINED)
working_tree=clean
python=/home/theone/projects/synth-v2/venv/bin/python (chain-activated venv)
publisher_present=true
canonical_output_root=/var/www/html/synth/_runtime/native_short_context_snapshot_v1/
```

The installed host checkout is behind `origin/main` (it does not contain PR
#112, a docs/pure-classifier PR unrelated to the PR A publisher). The installed
code is exactly the PR #106 publisher, which is what this acceptance validates.

## Scheduler ownership

Exactly one scheduler drives the publisher. It runs as one step inside
`scripts/run_chain_4h.sh`, invoked by the single 4h timer. No systemd or cron
unit invokes the publisher directly, and no second native SHORT snapshot
publisher exists.

```text
native_short_snapshot_scheduler_count=1
canonical_owner=synth-4h-market-chain.timer -> synth-4h-market-chain.service
  -> /bin/bash -lc 'scripts/run_chain_4h.sh' (User=theone, WorkingDirectory=/home/theone/projects/synth-v2)
timer_state=active/enabled
last_fired=2026-07-17T00:12:22Z
next_trigger=2026-07-17T04:12:59Z
```

`synth-manual-short-trader-dashboard.timer` (user-level, disabled) is a render
surface, not a snapshot publisher.

## Canonical before-state fingerprint

```text
manifest_path=/var/www/html/synth/_runtime/native_short_context_snapshot_v1/manifest_v1.json
manifest_sha256=e412bd90af2b85c3f0cba6a89e71b8cf0163819588abbf61e07605259482c921
manifest_mtime=2026-07-17 00:13:29.240119907 +0000
snapshot_id=nsctx-v1-1c78bcd1c39431f6f1f50312
manifest.content_digest=sha256:1c78bcd1c39431f6f1f5031249d087fd2cecc9617dee858a6eeafe8ffca01408
manifest.publication_result=PUBLISHED
manifest.overall_freshness_state=FRESH
csv_sha256=9117fd1a56a67723c877cd7677a0afc45174537a1ab24da5945c1469d354a85c
csv_mtime=2026-07-17 00:13:29.176116886 +0000
snapshot_directories=6
```

The manifest's recorded `rows_csv_digest` equals the actual CSV sha256, so the
canonical output is internally digest-consistent before acceptance.

## Phase 2 — manual no-publish dry-run

Command (chain-activated venv, installed host checkout, production read-only
config, no `--publish`):

```bash
python -m src.market_data.run_native_short_fib_context_snapshot_v1 --output jsonl
```

Result:

```text
exit_code=0
mode=dry_run
result=DRY_RUN
scope=bitvavo/EUR/SHORT/4h/1h
scope_rows=1  map_rows=1  level_rows=3
row_count=1  counts={supported:1, fresh:1, stale:0, missing:0, unavailable:0}
overall_freshness_state=FRESH
content_digest=sha256:32fe24a67b314a7125ddf885b380d8b5f461e4fb2d95f29e4a837bc3b4631652
snapshot_id=nsctx-v1-32fe24a67b314a7125ddf885  (nsctx-v1-<first 24 hex of content_digest>)
STARTED / PHASE_FINISHED / FINISHED all emitted
db_writes=0
broker_private_calls=0  broker_writes=0  order_submission=0  live_orders=0
account_awareness=0  decision_gate=none  execution_planner=none  executor=none
```

Authorities were readable; the projection selected one map/cycle; freshness was
sourced from persisted timestamps (not producer run time); no geometry was
recomputed; no CSV/research fallback was used. The dry-run's content digest
differs from the 00:13 canonical digest only because the persisted authorities
advanced between cycles — expected deterministic behavior over current inputs.

## Phase 3 — isolated temp publication

Isolated acceptance root (never the canonical production path):

```text
/tmp/synth-native-short-pr-a-acceptance-20260717T035222Z/publish_root
```

Command:

```bash
python -m src.market_data.run_native_short_fib_context_snapshot_v1 \
  --publish --output-dir <acceptance_root>/publish_root --output jsonl
```

Publish #1:

```text
exit_code=0  result=PUBLISHED
snapshot_id=nsctx-v1-32fe24a67b314a7125ddf885
content_digest=sha256:32fe24a67b314a7125ddf885b380d8b5f461e4fb2d95f29e4a837bc3b4631652
overall_freshness_state=FRESH  row_count=1
```

Publish #2 (same isolated root, unchanged inputs):

```text
exit_code=0  result=UNCHANGED
snapshot_id=nsctx-v1-32fe24a67b314a7125ddf885 (identical; no duplicate directory)
```

Isolated tree (exactly one snapshot directory; no partial temp files):

```text
publish_root/manifest_v1.json
publish_root/.native_short_context_snapshot_v1.publish.lock
publish_root/snapshots/nsctx-v1-32fe24a67b314a7125ddf885/native_short_fib_context_rows_v1.csv
publish_root/snapshots/nsctx-v1-32fe24a67b314a7125ddf885/snapshot_bundle_v1.json
```

Immutable identity confirmed: re-publishing unchanged source truth returns
`UNCHANGED` and points the manifest at the same single snapshot.

## Phase 4 — contract validation (isolated publication)

Manifest:

```text
valid_json=true
schema_version=native_short_fib_context_snapshot_v1
row_schema_version=native_short_fib_context_snapshot_row_v1
snapshot_id=nsctx-v1-32fe24a67b314a7125ddf885
publication_result=PUBLISHED
overall_freshness_state=FRESH
generated_ts_utc=2026-07-17T03:52:53.442200Z
publication_ts_utc=2026-07-17T03:52:53.632679Z
rows_csv=snapshots/nsctx-v1-32fe24a67b314a7125ddf885/native_short_fib_context_rows_v1.csv (relative, no traversal)
snapshot_bundle=snapshots/nsctx-v1-32fe24a67b314a7125ddf885/snapshot_bundle_v1.json (relative, no traversal)
```

Digest verification (recomputed on host):

```text
rows_csv_digest      = sha256:8b39cf5ca6c57c7d47cf40224f84517752078b0483c1ddabc4aa0da75cd749ef
recomputed_csv_sha256= sha256:8b39cf5ca6c57c7d47cf40224f84517752078b0483c1ddabc4aa0da75cd749ef  MATCH
snapshot_bundle_digest    = sha256:de723f93266d22a5a05c48ffcf2f81e7a5daace42ce0fa034e38f1173963ec40
recomputed_bundle_sha256  = sha256:de723f93266d22a5a05c48ffcf2f81e7a5daace42ce0fa034e38f1173963ec40  MATCH
content_digest=sha256:32fe24a67b314a7125ddf885...
snapshot_id first-24-hex identity: nsctx-v1-32fe24a67b314a7125ddf885  MATCH
```

CSV:

```text
exists=true  non_empty=true  header_columns=65
data_rows=1  symbols=[BTC]  unique=true
context_freshness_status=FRESH (in closed family FRESH|STALE|MISSING|UNAVAILABLE)
context_status=NATIVE_SHORT_CONTEXT_AVAILABLE
actionability_state=ACTIONABLE_ACTIVE_MAP
naive_utc_values=NONE (every *_utc value is explicit UTC or empty)
```

Bundle self-consistency:

```text
bundle.envelope.snapshot_id=nsctx-v1-32fe24a67b314a7125ddf885 (== manifest)
bundle.envelope.content_digest=sha256:32fe24a67b314a7125ddf885... (== manifest)
bundle.envelope.overall_freshness_state=FRESH (== manifest)
bundle.envelope.row_count=1 (== manifest)
```

Freshness authority (from manifest `source_as_of_timestamps`):

```text
projection_as_of_max_utc=2026-07-17T02:15:53.725965Z
primary_candle_max_utc=2026-07-17T00:00:00Z
supporting_candle_max_utc=2026-07-17T02:00:00Z
```

Freshness is derived from persisted source timestamps; the producer run time
(03:52) is not an input. Missing timestamps fail closed per the contract.

## Phase 5 — canonical output untouched by acceptance

After the dry-run and both isolated publishes:

```text
manifest_sha256=e412bd90af2b85c3f0cba6a89e71b8cf0163819588abbf61e07605259482c921 (unchanged)
manifest_mtime=2026-07-17 00:13:29.240119907 +0000 (unchanged)
snapshot_id=nsctx-v1-1c78bcd1c39431f6f1f50312 (unchanged)
csv_sha256=9117fd1a56a67723c877cd7677a0afc45174537a1ab24da5945c1469d354a85c (unchanged)
snapshot_directories=6 (unchanged)
scheduled_cycle_during_acceptance=NO (timer last fired 00:12:22Z, next 04:12:59Z)
```

The scheduled 4h timer did not fire during the acceptance window. The manual
commands targeted only the isolated `/tmp` acceptance root. The canonical
production output is byte-identical to the before-state.

## Acceptance decision

```text
manual_no_publish_dry_run=PASS
isolated_temp_publication=PASS
manifest_contract=PASS
csv_bundle_contract=PASS
digest=PASS
unchanged_content_identity=PASS
canonical_path_untouched_by_manual_acceptance=PASS
single_scheduler=PASS
formal_pr_a_host_acceptance=PASS
```

Safety markers for all manual acceptance runs:

```text
db_writes=0
broker_private_calls=0
broker_writes=0
order_submission=0
account_refresh=0
canonical_publication=0
profit_plan_render=0
profit_plan_publication=0
host_checkout_changes=0
service_changes=0
timer_changes=0
legacy_unit_retirement=0
```

## What this acceptance unblocks and does not

Unblocked:

```text
PR #113 (safe Profit Plan render owner) may proceed to rebase/repository review;
PR A now has a proven valid canonical manifest + immutable CSV and a recorded
host-acceptance procedure.
```

Still open / not authorized:

```text
multi-cycle Lane C operational acceptance (P2-C) remains OPEN
manual canonical native SHORT publication — not performed, not authorized
legacy user-level unit retirement — separate host rollout, not authorized
PR #113 merge/deploy — not authorized
```

## Re-verification (read-only)

```bash
# on Odroid
cd /home/theone/projects/synth-v2
for c in venv .venv; do [ -f "$c/bin/activate" ] && . "$c/bin/activate" && python -c 'import pymysql' 2>/dev/null && break; done
# no-publish dry-run
python -m src.market_data.run_native_short_fib_context_snapshot_v1 --output jsonl
# isolated temp publication (never the canonical path)
python -m src.market_data.run_native_short_fib_context_snapshot_v1 \
  --publish --output-dir "/tmp/synth-native-short-pr-a-acceptance-$(date -u +%Y%m%dT%H%M%SZ)" --output jsonl
```

Expected safe markers:

```text
result in {DRY_RUN, PUBLISHED, UNCHANGED}
db_writes=0  broker_private_calls=0  broker_writes=0  order_submission=0
decision_gate=none  execution_planner=none  executor=none
```
