# Native SHORT 4h Chain Ownership Preflight v1

## Decision

```text
capability=native_short_4h_chain
recommended_owner=UNASSIGNED
writer_host=UNASSIGNED
publication_host=UNASSIGNED
candidate_host=UNASSIGNED
selected_host=UNASSIGNED
production_authorization=none
activation_authorization=none
scope=BTC_ONLY
```

The repository evidence does not prove one deployable production owner.
`native_short_4h_chain` therefore remains fail-closed and `UNASSIGNED`.

PR #143 is merged as `76e6b8c`, with writer commit-time fencing at
`c20cb7c`. This closes the repository dependency only. It does not select a
host, grant writer authority, prove the installed implementation, or authorize
activation.

## Reconciliation

The canonical capability is one market-only writer chain:

```text
one timer
-> one service
-> scripts/run_chain_4h.sh
-> DB-backed Native SHORT and downstream market-state writes
-> canonical Native SHORT filesystem publication
```

Reporting and linked-profile orchestration are read-only consumers. They own no
Native SHORT DB mutation, snapshot construction, publication fallback, repair
path, or scheduler.

Repository and historical host evidence do not currently form one consistent
deployment contract:

- the only runnable committed pair is
  `deploy/systemd/synth-chain-4h.timer` and
  `deploy/systemd/synth-chain-4h.service`; it is bound to `devlap`,
  `User=gurk`, and `/home/gurk/projects/synth-v2`;
- the observed Odroid implementation used the different
  `synth-4h-market-chain.timer` and `synth-4h-market-chain.service` names,
  `User=theone`, `/home/theone/projects/synth-v2`, and an Odroid-local
  `/var/www/html/synth/_runtime/native_short_context_snapshot_v1/`
  publication root;
- the committed `docs/ops/systemd/synth-4h-market-chain.*` files are now
  non-startable retirement stubs;
- historical Odroid acceptance and a disabled/inactive installed timer do not
  authorize the current committed `synth-chain-4h` implementation;
- no current exact-commit evidence proves DB connectivity, DB writer grants,
  canonical publication-path write authority, or installed unit equivalence
  for either devlap, Odroid, or gurkDB.

The approximately seven-day-old BTC-only snapshot and
`TRANSIENT_NON_CANONICAL_CONTEXT_AVAILABLE` render state are consumer-visible
staleness evidence. They do not select a writer host and must not trigger a
reporting fallback.

## Single-Scheduler Proof

The repository topology permits exactly one scheduler:

```text
deploy/systemd/synth-chain-4h.timer
-> deploy/systemd/synth-chain-4h.service
-> scripts/run_chain_4h.sh
```

`scripts/run_chain_4h.sh` invokes
`src.market_data.run_native_short_fib_context_snapshot_v1 --publish` directly.
No publication timer is permitted. The retired
`docs/ops/systemd/synth-4h-market-chain.*` stubs are not an alternate
scheduler.

This is repository topology proof only. Production single-scheduler proof
remains blocked until a read-only inventory covers system and user systemd
units, cron, containers, and manually installed wrappers on every candidate
and historical host.

## Publication Ownership

Publication is part of the writer capability today. It cannot be split from
writer execution under the current contract because the canonical publisher
builds and atomically publishes the snapshot from DB truth inside the owning
chain.

A separate publication host would require a new, explicitly designed transport
of an immutable writer-produced bundle plus digest verification and atomic
promotion by a read-only consumer. Until that contract exists, a second host
running the publisher would duplicate canonical truth and violate the
single-scheduler invariant.

Therefore:

```text
publication_host must equal writer_host
```

for any future owner decision under this version of the contract.

## Exact Blocker Contract

All blockers below must be closed for one and the same host at one exact merged
commit before `selected_host` may change from `UNASSIGNED`:

```text
OWNER_EXACT_COMMIT_PREFLIGHT_MISSING
DB_CONNECTIVITY_PROOF_MISSING
DB_WRITER_AUTHORITY_PROOF_MISSING
PUBLICATION_PATH_OWNERSHIP_PROOF_MISSING
EXACT_INSTALLED_UNIT_EQUIVALENCE_MISSING
ALL_HOST_SCHEDULER_INVENTORY_MISSING
ROLLBACK_PROOF_MISSING
WRITER_PUBLICATION_COLOCATION_PROOF_MISSING
```

Required evidence:

1. `OWNER_EXACT_COMMIT_PREFLIGHT_MISSING`
   - candidate checkout contains merged PR #143;
   - checkout HEAD equals the reviewed expected 40-character commit;
   - repository authorization preflight passes without granting production
     authorization.
2. `DB_CONNECTIVITY_PROOF_MISSING`
   - read-only connection succeeds from the candidate service user and exact
     service environment;
   - the resolved database endpoint is recorded without secrets.
3. `DB_WRITER_AUTHORITY_PROOF_MISSING`
   - grants are inspected without mutation and prove only the exact required
     Native SHORT and market-only tables;
   - no account, broker, order, decision, planning, or execution grants are
     introduced.
4. `PUBLICATION_PATH_OWNERSHIP_PROOF_MISSING`
   - one absolute canonical publication root is selected;
   - the candidate service user owns atomic create, fsync, rename, lock, and
     rollback access;
   - reporting consumers have read-only access and no fallback publisher.
5. `EXACT_INSTALLED_UNIT_EQUIVALENCE_MISSING`
   - installed service and timer names, hashes, user, working directory,
     command, environment, lock, cadence, and `ConditionHost` equal the
     reviewed host-bound repository artifacts;
   - legacy `synth-4h-market-chain.*` units remain non-startable or absent.
6. `ALL_HOST_SCHEDULER_INVENTORY_MISSING`
   - devlap, Odroid, and gurkDB are checked for system/user timers, cron,
     containers, and direct publisher wrappers;
   - exactly zero active schedulers exist before cutover and exactly one named
     scheduler is proposed;
   - no second publisher schedule exists.
7. `ROLLBACK_PROOF_MISSING`
   - rollback disables only the proposed timer and removes its host-local
     authorization;
   - DB ledger/history is not reverted or rewritten;
   - the last digest-valid snapshot remains readable and visibly stale.
8. `WRITER_PUBLICATION_COLOCATION_PROOF_MISSING`
   - the same host and service own DB writer execution and canonical
     publication;
   - otherwise a separately reviewed immutable-bundle transport contract must
     replace this blocker before ownership selection.

Any ambiguity or failed item keeps:

```text
candidate_host=UNASSIGNED
selected_host=UNASSIGNED
production_runtime_owner=UNASSIGNED
production_authorization_status=UNASSIGNED
runtime_lifecycle=UNASSIGNED
```

## Activation Gate

This repository decision grants no production authorization. After all blocker
evidence exists, ownership selection, controlled BTC-only acceptance,
production authorization, and activation remain separate reviewed lifecycle
transitions.

Safety boundary:

```text
database_writes=0
canonical_publication=0
host_mutations=0
timer_mutations=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
multi_asset_promotion=0
reporting_fallback=0
```
