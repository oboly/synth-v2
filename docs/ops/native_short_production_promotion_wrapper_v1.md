# Native SHORT production promotion wrapper v1

## Status

IMPLEMENTED (repository-only). This document describes the canonical
operator procedure for native SHORT production promotion activation. It
introduces no new host mutation, DB write, or activation by itself -- see
`docs/ops/native_short_eth_bootstrap_promotion_approval_v1.md` and
`docs/ops/native_short_xrp_bootstrap_promotion_approval_v1.md` for the
already-approved decision this procedure executes against, and
`docs/todo/native_short_multi_asset_rollout_contract_v1.md` for the full
rollout contract. ETH/XRP production promotion has not been executed by this
change.

## Problem

The previous manual procedure required an operator to hand-edit
`/etc/synth/writer-capability-*-authorization-v1.json` after every merged
commit, because the production authorization file historically pinned an
*exact* `authorized_commit` that had to equal `HEAD` byte-for-byte. Every
approved fast-forward deploy moved `HEAD`, so every approved deploy required
a manual host-file edit before any write -- including cases where nothing
about host, capability, or approval had actually changed. This repeatedly
caused fail-closed activation failures for the already-approved ETH/XRP
rollout. Operators also had to hand-reconstruct actor/trigger/request-source/
timestamp/metadata/`--repository-commit` arguments for the rollout CLI on
every invocation.

## What changed

### 1. `commit_verification_mode=ANCESTOR` on the production authorization file

`src.operations.writer_capability_authorization_v1` and
`deploy/ownership/writer_capability_authorization_v1.schema.json` gained an
optional pair of fields on the production authorization file:

```json
{
  "commit_verification_mode": "ANCESTOR",
  "required_branch": "main"
}
```

- Absent (the default): unchanged legacy semantics -- `HEAD` must equal
  `authorized_commit` exactly. Every existing authorization file for every
  other capability (`public_price_snapshot`, `public_candle_freshness`,
  `market_rotation_pressure`) keeps working exactly as before; this is a
  strictly additive, opt-in change.
- `"ANCESTOR"`: `authorized_commit` becomes a fixed historical anchor.
  Authorization now requires:
  - `authorized_commit` is an ancestor of (or equal to) the deployed `HEAD`
    (`git merge-base --is-ancestor`), never equality -- the same
    non-circular ancestor model already reviewed and shipped for
    `native_short_promotion_bootstrap_evidence_v1`'s
    `approved_implementation_commit` check.
  - `required_branch` must be present and must equal the literal string
    `"main"` -- never a wildcard, never any other branch -- and the deployed
    checkout's `HEAD` must resolve to exactly that branch (a detached HEAD
    or any other branch fails closed).
  - every other existing check is unchanged: exact host match, exact
    capability/service/systemd_unit match, clean tracked working tree, no
    disallowed untracked files, no linked worktree, registry
    `production_authorization_status=AUTHORIZED` and
    `runtime_lifecycle` in `{AUTHORIZED_INACTIVE, ACTIVE}`.

A stable ANCESTOR-mode authorization file, once installed, survives every
later approved fast-forward deploy on `main` without being re-edited. It is
never rotated by an unreviewed commit -- rotating `authorized_commit` to a
newer anchor, or reverting to `EXACT` mode, is still an explicit host-file
change an operator makes deliberately, not something this repository change
performs automatically.

Regression tests: `tests/test_writer_capability_authorization_v1.py`
(`test_ancestor_mode_*`, `test_exact_mode_is_unaffected_default_when_field_absent`).

## Post-implementation runtime fixes

Two defects surfaced on the first real gurkDB dry-run of the installed
symlink and are fixed in this revision; both are covered by regression
tests.

**1. Symlink resolution in the shell wrapper.** Once installed at
`/usr/local/bin/synth-native-short-promote` (a symlink to
`scripts/synth_native_short_promote_v1.sh`), `BASH_SOURCE[0]` for a
symlinked invocation is the symlink path itself, not its target. The
original script derived `SCRIPT_DIR` directly from
`dirname "${BASH_SOURCE[0]}"`, so `SCRIPT_DIR` resolved to `/usr/local/bin`
and `REPO_DIR` to `/usr/local` -- the wrapper could never find the
repository venv. The script now resolves the physical target first:

```bash
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
```

and fails closed with an explicit message
(`could not resolve physical script path`) if that resolution ever comes
back empty (for example, `readlink` unavailable on a stripped-down `PATH`),
instead of proceeding with a wrong directory. Regression tests:
`tests/test_synth_native_short_promote_shell_wrapper_v1.py`.

**2. Missing writer runtime context.** The rollout CLI's authorization
boundary (`enforce_capability_write_authorization`) reads its execution mode
from `SYNTH_WRITER_EXECUTION_MODE` when the caller does not pass `mode`
explicitly, and defaults to `READ_ONLY` (fail closed) when that variable is
absent -- exactly like every other writer wrapper script in this repository.
The Python wrapper called the rollout CLI without ever setting
`SYNTH_WRITER_EXECUTION_MODE` or `SYNTH_WRITER_CAPABILITY_ID`, so the
rollout authorizer defaulted to `READ_ONLY` and rejected the write before
any database access. `run_native_short_production_promote_v1` now sets both
via a scoped context manager (`_writer_runtime_context`) for the exact
duration of the bounded rollout call only:

```python
os.environ[ENV_MODE] = ExecutionMode.PRODUCTION.value
os.environ[ENV_CAPABILITY] = WRITER_CAPABILITY_ID  # "native_short_4h_chain"
```

restoring whatever value -- or absence -- each variable had immediately
before, on every exit path including an exception, and never mutating
permanent host configuration. This adds no authorization logic of its own:
the real decision, including host/checkout/commit/capability verification,
remains entirely inside the unmodified `enforce_capability_write_authorization`
call, and the canonical 4h chain invoked afterward keeps setting its own
`SYNTH_WRITER_EXECUTION_MODE`/`SYNTH_WRITER_CAPABILITY_ID` exactly as it
already did, unchanged, once the scoped context has been restored.
Regression tests: `tests/test_native_short_production_promote_v1.py`
(`test_rollout_observes_production_mode_and_capability_id`,
`test_env_vars_restored_*`, `test_no_db_connection_attempted_when_authorization_denied`).

An illustrative, schema-valid, not-for-use example of the ANCESTOR-mode shape
is checked in at
`deploy/ownership/writer_capability_native_short_4h_chain_authorization_v1.example.json`.
It is not read by any code path; the real production authorization file
lives only on the authorized host, at the path named by
`authorization_guard.authorization_file` for `native_short_4h_chain` in
`deploy/ownership/writer_capability_ownership_v1.json`, and is never
committed to this repository.

### 2. `synth-native-short-promote` wrapper

A new narrow adapter centralizes execution mode, capability ID, actor,
trigger, request source, timestamp, and metadata creation for one
production promotion invocation:

```bash
sudo synth-native-short-promote ETH XRP
```

Components:

- `src/operations/run_native_short_production_promote_v1.py` -- all logic.
- `scripts/synth_native_short_promote_v1.sh` -- thin venv-activation shell
  wrapper, the intended install target for
  `/usr/local/bin/synth-native-short-promote` (a symlink; installing the
  symlink is a host action, not performed by this repository change).
- `src/operations/run_native_short_production_readiness_v1.py` /
  `scripts/synth_native_short_readiness_check_v1.sh` -- the readiness check
  this wrapper runs first; see "Readiness check and `--force`" below.

What it does, in order:

1. Validates every requested symbol is already a member of the checked-in
   `APPROVED_ROLLOUT_UNIVERSE_V1`
   (`native_short_scope_administration_rollout_v1.resolve_rollout_entries`),
   before any repository inspection or database access. An unapproved
   symbol is rejected immediately.
2. Derives `repository_commit` from the verified installed checkout's actual
   `HEAD` (`inspect_running_repository_source().head_sha`) -- never an
   operator-supplied value.
3. Derives `requested_at_utc` from that exact commit's own commit timestamp
   (`git show -s --format=%cI`) -- never wall-clock "now". This makes a
   rerun for the same checked-out commit and the same symbols fully
   deterministic: identical request digest, identical
   `OPERATION_ALREADY_COMPLETED` / idempotent-success replay behavior, with
   no separate run-state file.
4. Derives `actor_id` from `SUDO_USER` (or the current user) and fixes
   `actor_type=HUMAN_OPERATOR`, `trigger_type=MANUAL_CLI`,
   `request_source=synth-native-short-promote`, and a fixed `reason` string.
5. Runs the read-only
   `run_native_short_production_readiness_v1.evaluate_readiness` check
   in-process. By default, any hard blocker stops here -- before this step,
   before any repository-commit derivation for the rollout call, before
   `enforce_capability_write_authorization`, and before any database
   connection. `--force` skips only this stop (see "Readiness check and
   `--force`" below); it changes nothing else.
6. Calls the existing, unmodified rollout CLI
   (`run_native_short_scope_administration_rollout_v1.main`) with `--write`
   and one `--only-symbol` per requested symbol, in a single invocation, so
   the CLI's own stop-at-first-failure behavior covers every requested
   symbol. For the exact duration of this one call, a scoped context manager
   sets `SYNTH_WRITER_EXECUTION_MODE=PRODUCTION` and
   `SYNTH_WRITER_CAPABILITY_ID=native_short_4h_chain` (restoring whatever
   value, or absence, preceded them immediately afterward, on success or
   failure) -- without this, the rollout CLI's authorization boundary
   defaults to `READ_ONLY` and fails closed. This is where the real
   authorization decision happens (`enforce_capability_write_authorization`,
   called before any database connection) -- the wrapper adds no
   authorization logic of its own and no bypass.
7. Only if that call fully succeeds, runs the existing, unmodified
   `scripts/run_chain_4h.sh` (which itself re-verifies DB binding, DB grant,
   and writer-capability authorization before doing anything, and publishes
   the refreshed fib-context snapshot as one of its steps).
8. Emits exactly one final JSON result document to stdout (machine-readable)
   plus short progress lines to stderr (human-readable).

What it does **not** do:

- No symbol-specific logic -- the approved-universe check is the existing,
  unchanged rollout-CLI mechanism.
- No wildcard approval -- CLI input can only select a subset of the
  checked-in universe.
- No direct SQL, no writer, no service, no timer of its own.
- No automatic `git pull`.
- No account, wallet, broker, order, `decision_gate`, `execution_planner`,
  or `executor` coupling.

Regression tests: `tests/test_native_short_production_promote_v1.py`,
`tests/test_synth_native_short_promote_shell_wrapper_v1.py`.

## Readiness check and `--force`

`sudo synth-native-short-readiness-check` is a lightweight, entirely
read-only check: no database write, no host mutation, no systemd mutation,
no writer invocation. It orchestrates existing contracts (DB env/grant
preflight, the canonical `REQUIRED_OBJECT_PRIVILEGES` manifest, systemd unit
inspection, price/candle freshness classifiers, repository source identity)
into one verdict with exactly two severities -- no policy engine, no
approval records, no severity levels beyond these two, matching the scale of
a single-user personal trading system rather than an enterprise compliance
framework.

**Hard blocker** (`ready=false`, exit 1): a condition that makes an actual
production chain run almost certain to fail immediately.

- checkout does not resolve, or is not on `main`, or has uncontrolled dirt
- the `native_short_4h_chain` production authorization file is missing,
  unreadable, or insecurely permissioned
- the required database binding cannot be established
- any object in `synth_chain_4h_db_authority_v1.REQUIRED_OBJECT_PRIVILEGES`
  does not exist in the `synth` schema
- the actual grants do not satisfy the canonical minimum grant contract
- `synth-chain-4h.service` is not installed, or its `User`/`WorkingDirectory`/
  `ConditionHost` do not match the canonical gurkdb runtime
- a script or module the chain invokes (per the registry's
  `wrappers_invoked`/`modules_invoked` for `native_short_4h_chain`) does not
  exist

**Warning** (`ready` unaffected, never blocks): non-critical drift worth
knowing about.

- persisted public price is stale
- the expected 4h candle close is not yet persisted
- the timer is disabled/inactive (expected before the `ACTIVE` production
  cutover; not fatal on its own)
- the controlled/allowed untracked file is present
- the service's last systemd `Result` was not `success`

Exit codes: `0` ready (warnings allowed), `1` one or more hard blockers, `2`
the readiness runner itself could not evaluate safely (never treated as
ready).

`synth-native-short-promote` runs this exact check in-process before any
rollout call. Without `--force`, a hard blocker stops the command there --
before repository-commit derivation, before
`enforce_capability_write_authorization`, and before any database
connection. `sudo synth-native-short-promote --force ETH XRP` prints every
hard blocker prominently to stderr, records `force: true` in the wrapper's
own final JSON result, and continues past the readiness stop only --
everything downstream (approved-universe validation, repository-identity
derivation, `enforce_capability_write_authorization`, the rollout CLI's own
database connection) still runs completely unchanged and can still fail on
its own terms. `--force` never appears in the persisted administration
request's `--metadata`: that metadata is part of the request's immutable
digest, and an already-committed scope (the ETH/XRP promotions already
committed in production) must keep replaying as
`OPERATION_ALREADY_COMPLETED` regardless of whether a later invocation
happens to pass `--force`.

Regression tests: `tests/test_native_short_production_readiness_v1.py`
(hard-blocker/warning classification, exit codes, no-mutation safety
markers, shell-wrapper symlink smoke test) and the `--force`-specific cases
in `tests/test_native_short_production_promote_v1.py`.

## Operator procedure

Preconditions (host action, outside this repository change):

1. Install both wrappers: symlink `/usr/local/bin/synth-native-short-promote`
   to `scripts/synth_native_short_promote_v1.sh`, and
   `/usr/local/bin/synth-native-short-readiness-check` to
   `scripts/synth_native_short_readiness_check_v1.sh`, in the canonical
   checkout.
2. Ensure the `native_short_4h_chain` production authorization file
   (`/etc/synth/writer-capability-native-short-4h-chain-authorization-v1.json`,
   per `authorization_guard.authorization_file` in
   `deploy/ownership/writer_capability_ownership_v1.json`) uses
   `commit_verification_mode=ANCESTOR`, `required_branch="main"`, and an
   `authorized_commit` that is an ancestor of the exact commit approving
   this wrapper. Rotating an existing `EXACT`-mode file to `ANCESTOR` mode
   is a deliberate, explicit, reviewed host-file edit performed once, not an
   automatic side effect of this change.
3. Ensure the canonical checkout on the authorized host (`gurkdb`) is clean,
   on `main`, and at the desired approved commit.
4. If readiness reports `REQUIRED_OBJECT_MISSING` or a matching
   `GRANT_CONTRACT_MISMATCH` for the target-event tables, apply the missing
   schema and its two grants first -- see "Missing-schema recovery
   procedure" in
   `docs/ops/synth_chain_4h_database_least_privilege_contract_v1.md`.

The complete normal workflow is no more than two commands -- no manual
environment exports, no hidden MariaDB session variables, no hand-edited
authorization JSON, no direct Python module invocation:

```bash
sudo synth-native-short-readiness-check
sudo synth-native-short-promote ETH XRP
```

Stops at the first symbol whose promotion does not succeed, leaving every
later requested symbol untouched. On full success, runs the canonical 4h
chain and publishes the refreshed snapshot. Safe to re-run: an
already-completed symbol at the same commit replays as
`OPERATION_ALREADY_COMPLETED` and processing continues from the first
not-yet-attempted symbol. If readiness reports hard blockers that the
operator has independently judged safe to proceed past, use
`sudo synth-native-short-promote --force ETH XRP` -- see "Readiness check
and `--force`" above for exactly what `--force` does and does not bypass.

## Deprecated procedure

The previous procedure -- manually editing `authorized_commit` in the
production authorization file to the exact new `HEAD` after every merged
commit -- is deprecated for `native_short_4h_chain` once its authorization
file is rotated to `ANCESTOR` mode per the preconditions above. It remains
the only supported procedure for capabilities whose authorization file has
not been rotated (`EXACT` stays the default), and it is not removed from
`writer_capability_authorization_v1` -- only superseded, for this one
capability, by an explicit opt-in.
