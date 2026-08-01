# Native SHORT Context Snapshot — Odroid Distribution V1

## Status

Repository lane only. Not activated. No systemd unit from this lane is
installed or enabled on any host by this change. Manual canonical activation
requires a separate, explicitly authorized host action.

## Problem

`native_short_4h_chain` publication ownership moved to `gurkdb` (#174). The
publisher writes to a host-local filesystem path only (see
`docs/architecture/native_short_fib_context_snapshot_contract_v1.md`):

```text
/var/www/html/synth/_runtime/native_short_context_snapshot_v1/
```

Odroid's Profit Plan reads that same absolute path on its own local
filesystem. Nothing copies gurkdb's published bundle to Odroid, so Odroid
keeps serving whatever it last self-published before ownership moved — no
transfer/import owner exists for this gap.

## Ownership and data flow

```text
gurkdb (sole market-truth publisher, unchanged)
  -> canonical local publication path (existing contract, untouched)

Odroid (sole importer, pull-based, consumer-side only)
  scripts/fetch_native_short_snapshot_from_gurkdb.sh
    read-only rsync/ssh pull into a local staging directory only;
    never writes the canonical path; never deletes on the remote side
  -> src/operations/run_native_short_context_snapshot_import_v1.py
    src/market_data/native_short_context_snapshot_import_v1.py
    1. validate the staged bundle (schema, snapshot_id, content_digest,
       rows_csv_digest, snapshot_bundle_digest) via the existing
       validate_published_snapshot() contract function — no duplicated
       validation logic
    2. compare against the installed canonical manifest:
       same snapshot_id            -> UNCHANGED (idempotent no-op)
       older publication_ts_utc    -> reject as STALE, no write
    3. copy the new snapshot directory into canonical/snapshots/ under a
       temp name, then atomically rename it into place
    4. re-validate the freshly installed directory in place
    5. atomically swap the canonical manifest (temp file + os.replace) —
       the only mutable pointer, and the last step
    6. re-validate the canonical path exactly as Profit Plan would read it
  -> Odroid's local canonical path (Profit Plan's existing input, unchanged)
```

Pull, not push: Odroid owns the import decision, cadence, and retry. gurkdb
stays a pure publisher with no knowledge of consumers, preserving "gurkdb is
sole market-truth publisher" without adding remote-host awareness to the
publisher itself.

Failure/rollback: the only mutable file in the canonical directory is
`manifest_v1.json`. It is swapped last, atomically, only after the new
snapshot directory has been fully copied and independently re-validated.
Any failure before that point — corrupt manifest, corrupt CSV, corrupt
bundle, partial transfer, or a crash mid-copy — leaves the canonical
manifest and every previously installed snapshot directory byte-identical
to before the import attempt. Old snapshot directories are never deleted.

## Boundaries

This lane is filesystem-only and consumer-side only. It does not:

- write to any database
- call a broker or place/monitor orders
- read balances, positions, or account state
- select maps, compute Fib geometry, or evaluate candles
- run inside `decision_gate`, `execution_planner`, `executor`, or the
  Profit Plan renderer
- run as part of `native_short_4h_chain` or any of its stages
- push from gurkdb, or give gurkdb any consumer-host knowledge

Safety markers emitted by the importer:

```text
db_writes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
account_awareness=0
decision_gate=none
execution_planner=none
executor=none
market_truth_calculated=false
```

## Files

| File | Purpose |
|---|---|
| `src/market_data/native_short_context_snapshot_import_v1.py` | validation, staleness comparison, atomic install/rollback logic |
| `src/operations/run_native_short_context_snapshot_import_v1.py` | CLI runner: `STARTED`/`FINISHED`/`FAILED`, deterministic exit codes |
| `scripts/fetch_native_short_snapshot_from_gurkdb.sh` | bounded rsync/ssh pull into a staging directory only |
| `scripts/run_native_short_snapshot_import_chain_once.sh` | locked wrapper: fetch, then import |
| `deploy/systemd/synth-native-short-snapshot-import.service` | Odroid-bound **candidate** unit, not installed |
| `deploy/systemd/synth-native-short-snapshot-import.timer` | Odroid-bound **candidate** timer, not installed |

## Exit codes (`run_native_short_context_snapshot_import_v1`)

```text
0  success (INSTALLED or UNCHANGED)
2  staged snapshot is older than the installed one (stale, rejected)
3  staged or installed bundle failed schema/digest/identity validation
4  wrong host (--expected-host did not match this host)
1  any other failure
```

## Wrong-host guard

`--expected-host` is required and compared against `socket.gethostname()`
before any filesystem write is attempted. A mismatch fails closed with exit
code 4 and touches nothing.

## What this does not authorize

- installing or enabling the candidate systemd units on Odroid or any host
- manual canonical activation
- changing gurkdb's publisher ownership or publication path
- any transport mechanism other than the bounded rsync/ssh pull described
  above

## Tests

`tests/test_native_short_context_snapshot_import_v1.py` covers: valid
import, corrupt manifest, corrupt CSV, corrupt bundle, partial transfer,
stale/older snapshot rejection, same-snapshot idempotency, rollback
preservation on a late failure, and wrong-host rejection.
