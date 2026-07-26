# Native SHORT Fib Context Snapshot Contract V1

## Status and purpose

This contract defines the persisted, market-only native SHORT rows snapshot
consumed by a later read-only Profit Plan owner. It replaces no database
authority and does not authorize reporting to produce market truth.

The producer is:

```text
src.market_data.native_short_fib_context_snapshot_v1
src.market_data.run_native_short_fib_context_snapshot_v1
```

It is account-agnostic and reads only persisted public-market authorities. It
does not import reporting, account, selection, decision, planning, execution,
broker, or research packages.

## Canonical publication path and unassigned owner

The only repository publication path is the 4h market chain. Publication runs
exactly once immediately after:

```text
scripts/run_native_short_scope_status_chain_once.sh
```

That predecessor completes map evaluation, scope-status projection, and
map-level status projection. A snapshot failure exits the existing 4h chain
non-zero through `run_step`; the producer never falls back to an older snapshot.
No service, timer, cron entry, or second scheduler is introduced. Runtime
ownership remains `UNASSIGNED` in
`deploy/ownership/writer_capability_ownership_v1.json`; the committed
`synth-chain-4h.service` is a devlap-bound candidate, not activation or
production-owner evidence.

Default runtime directory:

```text
/var/www/html/synth/_runtime/native_short_context_snapshot_v1/
```

Direct override:

```text
SYNTH_NATIVE_SHORT_CONTEXT_SNAPSHOT_DIR
--output-dir
```

The publisher and every raw-snapshot consumer must use the same host-local
filesystem. This version defines no cross-host transport or replication.

## Producer and consumer matrix

| Script/module | Expected host | Service identity | Required access | Raw snapshot access necessary |
|---|---|---|---|---|
| `deploy/systemd/synth-chain-4h.service` | `devlap` candidate only; production owner `UNASSIGNED` | `gurk` | invoke the single chain; write publication root through its child | yes |
| `scripts/run_chain_4h.sh` | selected `native_short_4h_chain` host; currently `UNASSIGNED` | inherited `gurk` candidate identity | invoke exactly one publisher; no reporting write | yes |
| `src.market_data.run_native_short_fib_context_snapshot_v1` | same host/filesystem as the selected chain | `gurk` | read DB authorities; create/replace snapshot artifacts and manifest; acquire publication lock | yes |
| `src.market_data.native_short_fib_context_snapshot_v1` | same host/filesystem as the selected chain | `gurk` | sole filesystem write implementation; validate immutable collisions and digests | yes |
| `docs/ops/systemd/synth-linked-profile-runtime-refresh.service` and `scripts/odroid/run_linked_profile_runtime_orchestrator_once.sh` | same host/filesystem as publisher before this consumer may be activated; historical template host is Odroid | `theone` | sequence reporting only; no snapshot write or lock acquisition | yes, through its Profit Plan child |
| `scripts/odroid/run_account_profit_plan_snapshot_render_once.sh` | same host/filesystem as publisher | `theone` | read-only pass-through of the canonical root | yes |
| `src.reporting.run_account_profit_plan_snapshot_render_owner_v1` | same host/filesystem as publisher | `theone` | read manifest, referenced CSV, and bundle; validate paths and digests | yes |
| `src.reporting.run_manual_short_trader_profit_plan_v1` | same host/filesystem as publisher | inherited `theone` identity | read only the already-validated immutable CSV | yes, CSV only |
| `src.operations.run_native_short_snapshot_filesystem_preflight_v1` | candidate/selected publication host, manual audit only | invoking operator; no scheduled identity | lstat/read only; never chmod/chown/create/replace/acquire lock | yes, for digest validation |
| nginx/static serving | web host | `www-data` | read rendered Profit Plan HTML/JSON only | no |

`scripts/odroid/run_account_wallet_dashboard_render_once.sh` writes a
profile-local compatibility path, not this canonical publication root.
Research `manifest_v1.json` files and the manual research CSV default are also
outside this contract.

## Filesystem authority contract

The exact runtime identities are:

```text
publisher user = gurk
reader group   = synth-native-short-readers
group members  = gurk,theone
raw reader     = theone
www-data       = not a raw reader
```

The root must already exist with mode `02750` and ownership
`gurk:synth-native-short-readers` before publication. The publisher validates
its type, symlink/ACL state, mode, owner, and group and never creates, chmods,
or repairs it. Setgid on the mutable directories makes publisher-created
descendants inherit the exact reader group without a writable reader group.
The group contains `gurk` so an unprivileged publisher can deterministically
retain `S_ISGID` when it applies canonical modes to newly created directories.
This membership grants `gurk` no additional authority because `gurk` already
owns the publication tree. `theone` remains the only raw reporting consumer;
`www-data` remains excluded.

| Path class | Mode | Mutation authority |
|---|---:|---|
| publication root | `02750` | publisher may create snapshots and atomically replace the manifest |
| `snapshots/` | `02750` | publisher may create one new immutable snapshot directory |
| finalized `snapshots/<snapshot_id>/` | `02550` | direct write bits absent; content immutability is application-enforced |
| `manifest_v1.json` | `0640` | publisher owner only; reader group read-only |
| immutable CSV and bundle | `0440` | direct write bits absent; collision/digest checks enforce publisher-side immutability |
| `.native_short_context_snapshot_v1.publish.lock` | `0600` | publisher only |

Modes are applied explicitly only to newly created paths and are independent of
process umask. Every existing path is validated for type, owner, group, ACL,
and exact canonical mode before any mutation; drift fails without repair. No
contract path is group-writable, world-writable, or world-readable. Extended
access/default POSIX ACLs are forbidden because they would make mode analysis
incomplete. The reader group has read/traverse only.

Mode bits separate consumers from the publisher and deny direct in-place writes
on finalized artifacts. They do not make the owning publisher incapable of
`chmod`. Publisher-side immutability is application-enforced through exact
content collision checks, digests, and manifest-last publication. Temp files
remain same-directory staging files; file and directory fsync, `os.replace`,
digest validation, immutable collision rejection, and `flock` behavior are
preserved.

A process that shares UID `gurk` is a publisher-equivalent process regardless
of its service name or mode bits. It is therefore forbidden as a reporting
consumer. The canonical reporting identity is `theone`; any installed
reporting unit running as `gurk` must remain inactive until moved to that
distinct identity and admitted to `synth-native-short-readers`. The required
reader-group membership is exactly `gurk,theone`; extra members fail closed.
User/group creation, membership changes, chmod/chown/setfacl, deployment, and
activation are separate host actions and are not authorized by this repository
contract.

All existing path components and publication targets must be real directories
or regular files. Symlinked roots, parents, manifests, locks, snapshot
directories, or artifacts fail closed. Manifest paths remain exact relative
paths bound to the manifest snapshot ID; absolute paths, traversal, identity
mismatch, and resolved escape are rejected.

## Field-by-field source authority

The full canonical scope key applies to every lookup:

```text
venue / symbol / quote_currency / SHORT / 4h / 1h
```

| Snapshot field(s) | Canonical persisted source | Projection rule |
|---|---|---|
| `symbol`, `venue`, `quote_currency`, `fib_trading_horizon`, `primary_interval`, `supporting_interval`, `scope_id`, `scope_support_state` | `native_short_map_scope_v1` | Current inventory only; `NOT_APPLICABLE` produces an explicit `UNAVAILABLE` row. |
| `scope_status_id`, `scope_status_code`, `scope_status_reason_code`, `source_freshness_state`, `observation_freshness_state`, `actionability_state` | `native_short_scope_status_v1` | Forwarded verbatim; the producer does not repeat precedence logic. |
| `native_map_id`, `map_cycle_id`, `primary_4h_lifecycle_state` | `native_short_scope_status_v1.current_map_id`, `current_map_cycle_id`, `map_lifecycle_state` | The projection is the sole current-map selector and lifecycle authority. |
| `latest_primary_close_ts_utc`, `latest_support_close_ts_utc` | `native_short_scope_status_v1.primary_latest_candle_ts_utc`, `supporting_latest_candle_ts_utc` | Absolute persisted timestamps; absence fails closed as `MISSING`. |
| `projection_as_of_utc`, `projection_rebuilt_at_utc`, `latest_observation_id`, `latest_run_id`, `latest_observed_at_utc` | `native_short_scope_status_v1` | Forwarded provenance. `projection_as_of_utc` is the semantic freshness clock. |
| `latest_generation_event_id`, `latest_lifecycle_event_id` | `native_short_scope_status_v1` | Forwarded exact selected IDs. |
| `latest_generation_event_ts_utc` | `native_short_map_generation_event_v1`, by the exact projection ID | Provenance only; never used to select a map or infer freshness. |
| `latest_lifecycle_event_ts_utc` | `native_short_map_lifecycle_event_v1`, by the exact projection ID and selected map | Provenance only; lifecycle state remains projection-owned. |
| `anchor_start_ts_utc`, `anchor_low_price` | selected `native_short_map_v1.anchor_low_ts_utc`, `anchor_low_price` | Verbatim immutable geometry. |
| `anchor_end_ts_utc`, `anchor_high_price` | selected `native_short_map_v1.anchor_high_ts_utc`, `anchor_high_price` | Verbatim immutable geometry. |
| `breakout_gate_price`, `ext_1_272_price`, `ext_1_618_price`, `ext_2_000_price` | selected `native_short_map_v1.fib_ratios_json` named keys | Strict named extraction; no price ordering and no Fib calculation. |
| `reload_r382_price`, `reload_r500_price`, `reload_r618_price`, `reload_r786_price` | selected `native_short_map_v1.fib_ratios_json` named keys | Strict named extraction; no reentry calculation. |
| `invalidation_price` | selected `native_short_map_v1.invalidation_price` | Verbatim immutable geometry. |
| `map_published_at_utc`, `map_structure_hash`, `previous_map_cycle_id` | selected `native_short_map_v1` | Verbatim immutable provenance. |
| `source_primary_ref`, `source_support_ref`, `source_primary_candle_count`, `source_support_candle_count` | selected `native_short_map_v1` | Geometry-source provenance at immutable map publication. |
| `active_target_levels_json` | `native_short_map_level_status_v1` rows for the projection-selected map | Exact named roles whose persisted state is `ACTIVE`. |
| `previous_target_levels_json` | `native_short_map_level_status_v1` rows for the projection-selected map | Exact named roles whose persisted state is `REACHED`, `PASSED`, or `COMPLETED`. `HISTORICAL` is not reinterpreted. |
| `level_status_ids_json`, `level_status_as_of_utc` | `native_short_map_level_status_v1` | IDs are sorted by closed role order; every row as-of must equal projection as-of. |
| `context_freshness_status` | adapter over persisted scope/source/observation status plus authority completeness | Closed family `FRESH`, `STALE`, `MISSING`, `UNAVAILABLE`; producer run time is never an input. |
| `context_status` | compatibility adapter over `context_freshness_status`, projection lifecycle, and completeness | `NATIVE_SHORT_CONTEXT_AVAILABLE` only for complete `FRESH` active/completed authority; otherwise existing fail-closed bridge statuses. |
| `source_name`, `source_version` | snapshot contract | Producer identity, not market freshness. |
| `field_availability_json` | snapshot validation | Explicit status for compatibility fields and projected fields; never presentation inference. |

### Explicitly unavailable current semantics

No accepted persisted current authority exists for these legacy bridge fields:

```text
latest_primary_close_price
supporting_1h_state
max_primary_high_since_anchor
min_primary_low_since_anchor
current_map_status
previous_map_lifecycle_state
rollover_state
```

They are emitted as empty/`UNAVAILABLE` compatibility values and recorded as
`UNAVAILABLE` in `field_availability_json`. In particular, the producer does
not read immutable `map_payload_json` as if its publication-time supporting or
lifecycle interpretation were current.

`previous_map_cycle_id` is available directly from immutable map provenance.
The lifecycle of that previous map is not joined or reconstructed.

## Validation and fail-closed behavior

A row can expose `NATIVE_SHORT_CONTEXT_AVAILABLE` only when all of the
following hold:

- scope is `SUPPORTED` and its current projection exists;
- primary and supporting persisted source timestamps are absolute and present;
- the projection selects one map ID and cycle;
- the exact selected immutable map exists and its cycle matches;
- every required named geometry field is finite and positive;
- exact generation and lifecycle provenance IDs resolve;
- exactly one row exists for each closed V1 SELL role;
- each level row matches map ID, cycle, projection as-of, and immutable named
  geometry price numerically; differing MariaDB decimal scale/trailing zeros
  are canonicalized without changing value;
- persisted source and observation states are current;
- projection lifecycle is `MAP_ACTIVE` or `MAP_COMPLETED`.

Missing authorities remain visible as a `MISSING` or `UNAVAILABLE` row. Stale
persisted authority remains `STALE`. The producer never fills a missing source
timestamp with `datetime.now()`, database `NOW()`, publication time, an
immutable map timestamp, a CSV, or a research artifact.

MariaDB stores these canonical UTC authorities as `DATETIME(6)`, and PyMySQL
returns that SQL type without `tzinfo`. The DB boundary therefore types a
present persisted `DATETIME(6)` value as UTC before it enters the pure contract.
This conversion neither changes the stored clock value nor supplies a missing
timestamp; SQL `NULL` remains `MISSING` and fails closed.

## Snapshot identity and canonical serialization

Rows are uniquely sorted by symbol and serialized as canonical JSON with sorted
keys and compact separators. Every source ID and source timestamp that can
change the semantic snapshot is part of the canonical rows payload.

Rebuild-only surrogate/operational fields (`scope_status_id`,
`level_status_ids_json`, `projection_rebuilt_at_utc`) remain present for audit
but are excluded from semantic identity. Rebuilding an otherwise identical
projection therefore does not create a new snapshot merely because rebuildable
row IDs or operational rebuild time changed.

```text
content_digest = SHA-256(canonical row schema + canonical rows)
snapshot_id    = nsctx-v1-<first 24 hex chars of content_digest>
```

Operational `generated_ts_utc`, `publication_ts_utc`, paths, and publication
result do not affect semantic identity. Identical persisted inputs therefore
produce `UNCHANGED` and no new semantic snapshot directory. A changed authority
ID, timestamp, geometry, lifecycle, level state, or freshness state changes the
identity.

## Envelope and freshness summary

The manifest and bundle envelope contain:

```text
schema_version
row_schema_version
snapshot_id
content_digest
generated_ts_utc
publication_ts_utc
source_as_of_timestamps
row_count
counts {supported, fresh, stale, missing, unavailable}
overall_freshness_state
producer {name, version}
safety markers
```

`generated_ts_utc` and `publication_ts_utc` are absolute operational metadata.
They never make a source fresh. Overall freshness uses fail-closed precedence:

```text
MISSING > UNAVAILABLE > STALE > FRESH
```

This overall state is an observability summary over `SUPPORTED` rows only. A
`NOT_APPLICABLE` inventory row remains counted as `UNAVAILABLE` but does not
invalidate otherwise healthy supported rows. When no supported rows exist, the
overall state is `UNAVAILABLE`. PR B must consume and gate each symbol row; it
must not use the overall summary as permission for all symbols. A supported
`MISSING`, `STALE`, or `UNAVAILABLE` row remains individually fail-closed.

## Atomic publication protocol

The stable file is only the commit pointer:

```text
manifest_v1.json
```

It references immutable files under:

```text
snapshots/<snapshot_id>/native_short_fib_context_rows_v1.csv
snapshots/<snapshot_id>/snapshot_bundle_v1.json
```

Publication is:

1. validate the pre-existing root and every existing path before mutation;
2. build and validate all rows in memory;
3. serialize rows and bundle in memory;
4. write each immutable file through a temp file in the same directory;
5. flush and fsync the file;
6. `os.replace` it;
7. validate artifact content and digests;
8. finalize a newly created snapshot directory from `02750` to `02550`;
9. fsync its directory and the immutable snapshot parent;
10. write, flush, fsync, and atomically replace `manifest_v1.json` last;
11. fsync the manifest parent directory.

A failure before step 10 can leave an unreferenced new artifact or a new
snapshot directory at mutable staging mode `02750`, but cannot
damage or partially advance the last valid snapshot. A reader must resolve the
CSV through `manifest_v1.json`; it must not scan `snapshots/` for the newest
directory.

Publication holds a non-blocking filesystem `flock` on
`.native_short_context_snapshot_v1.publish.lock` for the complete read,
validation, immutable-write, and commit-pointer sequence. A concurrent
publisher fails closed before touching the manifest. A stale lock file is
harmless because ownership belongs to the open file descriptor and the kernel
releases it on process exit.

Before returning `UNCHANGED`, the publisher requires both immutable artifacts,
checks the CSV and bundle digests, validates the bundle/snapshot identity, and
proves that both artifacts exactly represent the current semantic build. A
self-consistent manifest cannot bless different row content. Corrupt or partial
immutable directories are rejected. The root, lock, snapshots directory,
manifest, current snapshot directory, and both artifacts must also pass their
complete filesystem contract; `UNCHANGED` performs no chmod or repair. Temp
files are removed after pre-replace failure. Snapshot and parent directories
are fsynced before the manifest is replaced.

Future consumers, including PR B, must use
`resolve_manifest_artifact_paths(...)` or equivalent validation. Absolute
paths, `..` traversal, snapshot-ID/path disagreement, and paths outside the
configured output directory are invalid; consumers must fail closed without
opening them.

## CLI

Default execution is read-only/dry-run:

```bash
python -m src.market_data.run_native_short_fib_context_snapshot_v1 --output jsonl
```

Explicit publication:

```bash
python -m src.market_data.run_native_short_fib_context_snapshot_v1 \
  --publish \
  --output summary
```

Exit `0` means `DRY_RUN`, `PUBLISHED`, or validated `UNCHANGED`; exit `1`
means load, contract, or publication failure; argument errors use argparse exit
`2`; interruption exits `130`.

## PR B dependency

PR B may consume only `manifest_v1.json`, validate its schema/digests, and pass
the referenced immutable `native_short_fib_context_rows_v1.csv` to the existing
native SHORT CSV parser. It must not rebuild native context, select a map, join
candles for geometry/lifecycle, or treat the unavailable legacy fields as
authority.

## Runtime deployment boundary

Repository merge does not install, enable, restart, or mutate any host service,
timer, cron entry, checkout, or production output. After an operator later
updates the runtime checkout, the already-existing 4h chain will invoke the
publisher automatically on its next permitted run because the producer is a
normal step in `scripts/run_chain_4h.sh`; no new owner is required.

Host rollout must preserve this order before the production owner is allowed to
run the updated chain:

1. provision the already-approved host identities/group and root ownership in
   a separate authorized host lane;
2. run
   `src.operations.run_native_short_snapshot_filesystem_preflight_v1` and
   require `PASS`, including zero same-UID consumers and zero consumer writes;
3. run the producer manually without `--publish` against configured authorities;
4. confirm supported-row freshness, authority identities, and zero DB writes;
5. run a manual publish to an acceptance/temp output directory, never the
   canonical production directory;
6. validate the manifest schema/digests and its referenced immutable CSV/bundle;
7. only then allow the selected 4h owner to use the canonical production path.

Representative acceptance command for step 3:

```bash
python -m src.market_data.run_native_short_fib_context_snapshot_v1 \
  --publish \
  --output-dir /tmp/synth-native-short-context-snapshot-v1-acceptance \
  --output jsonl
```

PR B remains blocked until this host acceptance proves one valid canonical
manifest and referenced immutable CSV. This document performs and authorizes no
host rollout.

## Safety markers

```text
broker_private_calls=0
broker_calls=0
broker_writes=0
order_submission=0
live_orders=0
account_awareness=0
decision_gate=none
execution_planner=none
executor=none
reporting_writes_market_truth=false
new_scheduler=false
```
