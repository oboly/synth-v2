# Multi-Horizon Rotation C1 Final Holdout Builder v1

Issue: #593
Status: research-only final-holdout dataset builder

## Purpose

Open the frozen final holdout exactly once for preregistered candidate `C1` after the canonical source-content integrity gate has been frozen and re-verified.

The pre-holdout selection is fixed:

```text
C1 -> ADVANCE_TO_FINAL_HOLDOUT
C2 -> REJECT_BEFORE_FINAL_HOLDOUT
C3 -> INSUFFICIENT_DATA
```

This runner does not reopen C2 or C3.

## Hard integrity gate

Before any final-holdout candidate replay or forward-label construction, the runner:

1. verifies the approved host and account, resolves the approved-account registry root, and canonicalizes the supplied paths;
2. loads the frozen split manifest and verifies its committed canonical SHA-256 identity;
3. loads `source_integrity_v1.json` and requires its `composite_sha256` to equal the committed approved source-integrity composite before any DB access;
4. verifies the committed semantic implementation fingerprint;
5. recomputes `multi_horizon_rotation_source_integrity_v1` against the canonical DB sources and verifies equality with the approved artifact.

Only after successful verification may holdout rows be built. On resume, these gates run again before any replay or finalization recovery.


## Canonical one-time holdout opening

There is no `--output-dir` argument. The runner takes `--split-manifest` and
`--source-integrity`, both of which must be named exactly `split_manifest_v1.json`
and `source_integrity_v1.json` and must live in the same directory. That directory
is the canonical run directory, and per-run bookkeeping artifacts
(`final_holdout_c1_rows_v1.jsonl`, `final_holdout_c1_summary_v1.json`, the
`.final_holdout_c1_rows_v1.jsonl.partial` streaming file, and the
`.final_holdout_c1_checkpoint_v1.json` checkpoint) are written there.

That per-directory checkpoint alone is **not** the security boundary: a
byte-identical copy of `split_manifest_v1.json` + `source_integrity_v1.json` in
a second directory would otherwise open a fresh checkpoint namespace. The
actual one-shot gate is a trusted, non-caller-selectable **opened-state
registry** under the approved execution account passwd home at `<approved-home>/.local/state/synth/research/multi_horizon_rotation_c1_final_holdout_registry_v1/`
(never overridable by any CLI flag or environment variable), keyed by a
SHA-256 fingerprint of:

```text
manifest_sha256, source_integrity_composite_sha256, venue, candidate_id, phase
```

Because that key is a pure function of frozen content and never of any path,
copying the manifest/integrity pair to another directory resolves to the
exact same registry entry and is denied.

Immediately after integrity verification succeeds and immediately before the
first holdout replay, the runner creates the `RUNNING` registry entry (the
authoritative marker) with a single **atomic exclusive create** -- write a
temp file, fsync it durable, then `os.link()` it into place at the fingerprint
path. `os.link()` either creates the target or raises `FileExistsError`
atomically at the filesystem level, so there is no check-then-write window: of
any number of fresh runners racing on the same fingerprint (a concurrent
invocation, or two runners started against a copied manifest/integrity pair),
exactly one call ever creates the entry. Every other caller gets told it lost
and creates or mutates nothing at all -- no local checkpoint, no partial file,
no replay. Only the winner goes on to create the matching local `RUNNING`
checkpoint and begin replay. This is the same exclusive-create idiom already
used by `persist_or_reuse_manifest` for the frozen split manifest.

Once a registry entry exists, a fresh (non-`--resume`) invocation always fails
closed for **any** registry state -- `RUNNING`, `INTERRUPTED`, `FAILED`, or
`FINISHED` -- including from a different directory holding a copy of the same
manifest and integrity artifact. The local checkpoint schema binds:

```text
runner, runner_version, venue, candidate_id, manifest_sha256,
source_integrity_composite_sha256, implementation_fingerprint_sha256,
phase, phase_start, phase_end, last_completed_asof, asofs_completed,
row_count, partial_bytes, source_query_count, source_rows_read,
terminal_state, updated_ts_utc
```

The registry entry binds the same identity fields plus `terminal_state` and
`updated_ts_utc` (its state is the authority; the local checkpoint carries the
per-as-of replay progress).

## Approved execution host

Current #593 topology has no shared cross-host authoritative state store, and
`database_writes` must remain `0` for this research-only runner, so no
DB-backed cross-host lock exists. The authoritative opened-state registry
above is deliberately **host-local**: a different host has its own,
independent registry and could otherwise "open" the identical frozen
manifest/integrity content a second time.

To close that gap without inventing a new DB mutation layer, the runner
additionally enforces a single **approved execution host**,
`gurkdb` (`APPROVED_EXECUTION_HOST`, matching the existing canonical-host
convention already used by `src/operations/verify_agent_worktree_v1.py`).
Exactly-once ownership of the holdout is the **conjunction** of two
independent controls, neither sufficient alone:

```text
approved-host-only + trusted host-local registry
```

Before any registry entry is created and before any holdout replay, the
runner compares `socket.gethostname()` (the trusted `gethostname(2)`
syscall answer, never a caller-controlled environment variable such as
`HOSTNAME`) against the fixed `APPROVED_EXECUTION_HOST` constant and fails
closed on any mismatch. There is no CLI/env override for the approved host.
A non-approved host cannot open, resume, or replay this holdout at all,
regardless of whether it holds a byte-identical copy of the frozen
manifest/integrity pair.

## Frozen C1 implementation fingerprint

Before any final-holdout candidate replay, and before any registry entry is
created (fresh run) or continued (resume), the runner recomputes a
deterministic SHA-256 **implementation fingerprint** and verifies it against
a pre-registered, committed expected value at
`docs/research/multi_horizon_rotation_c1_final_holdout_implementation_fingerprint_v1.json`.
There is no CLI/env override and no refreeze/update mechanism in the
runner -- a mismatch always fails closed.

The fingerprint binds the canonical C1 spec and exact source-byte SHA-256 values for the minimal direct semantic owners: `multi_horizon_rotation_replay_v1` (C1 scoring), `multi_horizon_rotation_dataset_builder_v1` (PIT and forward-label primitives), `run_multi_horizon_rotation_dataset_builder_v1` (candle reconstruction and validation rows), and `run_multi_horizon_rotation_source_integrity_v1` (source-integrity construction and verification). DB, CLI, logging, and path helpers are deliberately excluded. The committed record stores this deterministic canonical envelope and its overall SHA-256.

The verified fingerprint is bound into both the local checkpoint and the
authoritative registry entry (`implementation_fingerprint_sha256`), so a
later `--resume` re-validates it against the checkpoint's own recorded
value and fails closed -- permanently locking the run `FAILED` -- if the
frozen C1 spec or replay implementation has drifted since the run was
opened, even if the module-level gate were somehow bypassed.

## Interruption, failure, and resume

`SIGINT` and `SIGTERM` are handled explicitly: the runner flushes and fsyncs
the last fully committed as-of, marks both the local checkpoint and the
registry entry `INTERRUPTED`, prints exactly one `INTERRUPTED` line with no
traceback, restores the previous signal handlers, and exits `130` (SIGINT) or
`143` (SIGTERM). No partially processed as-of is ever committed.

Before the rows rename, ordinary failures retain `FAILED` semantics. Immediately before the rename, both records transition to `FINALIZING`. Once rows are published, ordinary failures leave that recoverable state (or a deterministic mixed `FINISHED`/`FINALIZING` pair); a later `--resume` must reacquire the same lease, performs zero replay, never rewrites rows, and completes only summary, terminal records, and lease handling. `FAILED` remains permanently non-resumable; `FINALIZING` is resumeable only with a published rows artifact and no partial artifact. A failure that happens *before* the holdout
was opened (for example the initial integrity verification itself) creates no
registry entry at all.

`--resume` normally requires the canonical local checkpoint and partial artifact with terminal state `RUNNING` or `INTERRUPTED`. The only exception is artifact-backed `FINALIZING` recovery (including a mixed `FINISHED`/`FINALIZING` pair): it requires no partial artifact and completes no replay. The matching registry entry is located by the checkpoint's own recorded fingerprint.


### Exclusive resume lease

An opened holdout can be resumed by more than one process (a retried job, an
operator error, two schedulers racing). To make `--resume` itself exclusive,
the runner then acquires a **resume lease** at
`<registry_key>.resume_lease.json` in the same trusted `REGISTRY_ROOT` --
deterministic from the registry key alone, so it is path-independent and not
caller-selectable. Acquisition uses the identical atomic exclusive-create
primitive as registry creation (temp file, fsync, `os.link()` into place): at
most one concurrent `--resume` of the same opened fingerprint can ever hold
the lease. A second resume that loses the race gets `False` back immediately
and performs **zero** partial reconciliation, replay, or output mutation --
the checkpoint, registry entry, and partial artifact are all left completely
untouched, and the existing lease is never overwritten.

The lease is acquired right after the registry entry is confirmed resumable
and *before* anything else -- before source integrity is re-verified, before
checkpoint/registry identity is validated, before the partial artifact is
reconciled, and before any replay. It is released:

- on successful completion, right after the checkpoint and registry are
  marked `FINISHED`;
- on `SIGINT`/`SIGTERM`, right after both are marked `INTERRUPTED` (a further
  explicit `--resume` is then allowed to reacquire it);
- on any ordinary post-open failure, right after both are marked `FAILED`
  (permanently non-resumable, so the lease is simply gone with them).

There is deliberately **no automatic staleness/timeout recovery** for the
lease. A lease left behind by a process that was hard-killed (e.g. `SIGKILL`,
which bypasses the `SIGINT`/`SIGTERM` handling above) stays forever and
permanently blocks further `--resume` until a human clears it -- an automatic
timeout could let two live resumes run concurrently, which is exactly what
the lease exists to prevent.

Once the lease is held, `--resume` re-verifies source integrity, validates
every checkpoint identity field against the freshly recomputed manifest and
integrity fingerprints, truncates the partial artifact back to the
checkpoint's committed byte offset, reconciles the row count, confirms
`last_completed_asof` belongs to the frozen holdout grid, and only then
continues strictly after that as-of.

## Candidate scope

Exactly one frozen spec is allowed:

```text
candidate_id = C1
effective_horizon = VERY_SHORT
target operator timescale ~= 15m
```

No sign flip, recalibration, threshold change, candidate substitution, or formula change is permitted after discovery/validation inspection.

## Data and labels

The builder reuses the canonical #593 replay and row-building owners from the discovery/validation implementation:

- point-in-time observed asset universe;
- C1 replay implementation;
- B0 Rotation Pressure V1 PIT lookup;
- B1 comparable 15m return;
- B2 unavailable status;
- exact-boundary forward responses at 15m, 1h, 4h, 24h;
- phase-end purge so no outcome endpoint at/after the frozen source end is used.

Output:

```text
final_holdout_c1_rows_v1.jsonl
final_holdout_c1_summary_v1.json
```

The runner is one-shot and refuses to overwrite an existing final-holdout artifact, summary, checkpoint, or partial artifact unless `--resume` is given for a `RUNNING`/`INTERRUPTED` checkpoint. See "Canonical one-time holdout opening" and "Interruption and resume" above.

## Isolation

The existing discovery/validation builder remains unchanged and continues to deny final-holdout access.

This separate runner exists specifically so holdout access cannot be obtained by adding a third phase to the ordinary builder CLI.

C2/C3 are never evaluated by this runner.

## Safety

```text
research_only=1
market_only=1
database_reads=1
database_writes=0
account_awareness=0
decision_gate=none
execution_planner=none
executor=none
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
```

## Next step

The resulting `final_holdout_c1_rows_v1.jsonl` must be evaluated by a separate C1-only holdout evaluator that reuses the frozen validation metric semantics. No model change is allowed between dataset creation and evaluation.
