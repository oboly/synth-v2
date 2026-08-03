# Market Candle Freshness v1

The public candle writer keeps `obs_market_candle` fresh for:

- `15m` with a 72-hour refresh window;
- `1h` with a 168-hour window;
- `4h` with a 720-hour window;
- `1d` with a 2160-hour window;
- `1w` with a 2016-hour window.

## Ownership State

```text
capability_id=public_candle_freshness
candidate_host=gurkdb
selected_host=gurkdb
acceptance_host=gurkdb
acceptance_status=ACCEPTED
production_runtime_owner=gurkdb
production_authorization_status=AUTHORIZED
runtime_lifecycle=AUTHORIZED_INACTIVE
observed_runtime_state=[]
```

Exact-head strict preflight and two controlled manual cycles passed at commit
`2e762b58ab9e311f4a8d403d8d97332e5ebb0f16`. The initial enabled-universe
mismatch was corrected by disabling only eight stale historical-import rows;
validation reports 421 enabled assets, 430 current Bitvavo EUR trading markets,
and zero mismatch. Each interval retained 421/421 asset coverage, cycle 1 added
93,457 unique rows, and cycle 2 was idempotent. The separately authorized
production owner is gurkDB in `AUTHORIZED_INACTIVE`; no timer or production
authorization has yet been installed. See
`docs/ops/public_candle_freshness_gurkdb_acceptance_20260723.md`.

The committed service and timer below are gurkDB-bound artifacts, not
host-neutral configuration:

```text
timer=deploy/systemd/synth-market-candle-freshness-writer.timer
service=deploy/systemd/synth-market-candle-freshness-writer.service
wrapper=scripts/run_market_candle_freshness_once.sh
module=src.etl.bitvavo.run_candles_etl
lock=/tmp/synth-market-candle-freshness-writer-v1.lock
ConditionHost=gurkdb
User=gurk
WorkingDirectory=/home/gurk/projects/synth-v2
authorization_file=/etc/synth/writer-capability-public-candle-freshness-authorization-v1.json
```

An installed timer may continue running operationally even after canonical
authorization is reset. Repository correction does not stop that timer.
Containment requires a separately authorized host action.

## Writer authorization: EXACT vs ANCESTOR commit verification

The production authorization file above is validated by the shared guard in
`src/operations/writer_capability_authorization_v1.py`
(`verify_writer_execution_authorization` / `verify_checkout_identity`) --
the same module and the same `commit_verification_mode` field used by every
other writer capability, including `native_short_4h_chain`. See
`docs/ops/native_short_production_promotion_wrapper_v1.md` for the full
rationale behind the `ANCESTOR` mode.

- **EXACT** (absent field, the default): `authorized_commit` must equal the
  deployed checkout's `HEAD` byte-for-byte. This is the mode `2e762b58ab9e-
  311f4a8d403d8d97332e5ebb0f16` was validated under (see the acceptance
  evidence above) and remains the default for this capability unless the
  host file is explicitly rotated.
- **ANCESTOR** (`commit_verification_mode="ANCESTOR"`,
  `required_branch="main"`): `authorized_commit` becomes a fixed historical
  anchor. Authorization instead requires `authorized_commit` to be an
  ancestor of (or equal to) the deployed `HEAD`
  (`git merge-base --is-ancestor`), the checkout to resolve to exactly the
  `main` branch (a detached HEAD or any other branch fails closed), and
  every other existing check to hold unchanged: exact host match, exact
  capability/service/systemd_unit match, clean tracked working tree, no
  disallowed untracked files, no linked worktree, and registry
  `production_authorization_status=AUTHORIZED` with `runtime_lifecycle` in
  `{AUTHORIZED_INACTIVE, ACTIVE}`. A stable ANCESTOR-mode file survives every
  later approved fast-forward deploy on `main` without a per-commit edit.
  Rotating `authorized_commit` to a newer anchor, or reverting to `EXACT`
  mode, remains a deliberate host-file edit an operator makes explicitly --
  never an automatic side effect of a repository change.

An illustrative, schema-valid, not-for-use example of the ANCESTOR-mode
shape for this capability is checked in at
`deploy/ownership/writer_capability_public_candle_freshness_authorization_v1.example.json`.
It is not read by any code path; the real production authorization file
lives only on the authorized host (`gurkdb`), at the path named by
`authorization_guard.authorization_file` for `public_candle_freshness` in
`deploy/ownership/writer_capability_ownership_v1.json`
(`/etc/synth/writer-capability-public-candle-freshness-authorization-v1.json`),
and is never committed to this repository.

Regression tests:
`tests/test_writer_capability_authorization_v1.py`
(`test_candle_freshness_exact_authorized_commit_passes`,
`test_candle_freshness_ancestor_mode_descendant_head_accepted`,
`test_candle_freshness_ancestor_mode_rejects_unrelated_commit`,
`test_candle_freshness_ancestor_mode_rejects_dirty_checkout`,
`test_candle_freshness_malformed_authorization_rejected`,
`test_candle_freshness_missing_authorization_file_blocks_production`).

### Host procedure: replacing the authorization file after merge

This procedure runs on `gurkdb` (the authorized production host for
`public_candle_freshness`) only, after this change has merged to `main`.
It performs no repository mutation and this repository change does not
perform any of these steps automatically.

1. Confirm the canonical checkout on `gurkdb` is on `main`, clean, and at
   the desired approved commit that will serve as the new
   `authorized_commit` anchor:

   ```bash
   git -C /home/gurk/projects/synth-v2 status --short
   git -C /home/gurk/projects/synth-v2 rev-parse --abbrev-ref HEAD
   git -C /home/gurk/projects/synth-v2 rev-parse HEAD
   ```

2. Build the replacement file content off-host or in a scratch path, based
   on `deploy/ownership/writer_capability_public_candle_freshness_authorization_v1.example.json`
   in this repository, with `authorized_commit` set to the exact commit
   confirmed in step 1, `commit_verification_mode="ANCESTOR"`,
   `required_branch="main"`, and every other field (`capability_id`,
   `capability_identity`, `service`, `systemd_unit`, `authorized_host`,
   `decision_evidence`) unchanged from the current file.

3. Validate the new file is well-formed JSON before installing it:

   ```bash
   python -m json.tool /path/to/new-authorization.json > /dev/null
   ```

4. Install atomically as `root` (or the existing file's owning user) so a
   concurrent writer invocation never observes a partially written file,
   then restore safe ownership and permissions -- the guard fails closed on
   a symlink, a non-regular file, unsafe ownership (must be `uid 0` or the
   invoking user), or group/world-writable bits
   (`_validate_writer_file_security` in
   `src/operations/writer_capability_authorization_v1.py`):

   ```bash
   install -m 0644 /path/to/new-authorization.json \
     /etc/synth/writer-capability-public-candle-freshness-authorization-v1.json.new
   mv -f /etc/synth/writer-capability-public-candle-freshness-authorization-v1.json.new \
     /etc/synth/writer-capability-public-candle-freshness-authorization-v1.json
   chown root:root /etc/synth/writer-capability-public-candle-freshness-authorization-v1.json
   chmod 0644 /etc/synth/writer-capability-public-candle-freshness-authorization-v1.json
   ```

5. Do not restart the timer/service or trigger a writer run as part of this
   procedure. The next regularly scheduled invocation (or an explicit,
   separately authorized manual run) exercises the new authorization file
   under its normal cadence.

The wrapper reuses the existing ETL and canonical `obs_market_candle` upserts;
it does not duplicate ETL logic. The retained
`scripts/odroid/run_market_candle_freshness_once.sh` path is a fail-closed
retirement stub and cannot invoke ETL. Reporting and account/render runners
must consume persisted candles and expose staleness rather than starting a
writer.

Safety boundary:

- public market data only;
- no account, private broker, reporting, decision, planning, or execution
  imports or calls;
- no broker writes or order submission;
- no cross-host orchestration.

Repository checks, not host activation:

```bash
bash -n scripts/run_market_candle_freshness_once.sh
python -m src.etl.bitvavo.run_candles_etl --help
systemd-analyze verify deploy/systemd/synth-market-candle-freshness-writer.service
systemd-analyze verify deploy/systemd/synth-market-candle-freshness-writer.timer
```

See `docs/ops/writer_capability_host_ownership_contract_v1.md` and
`docs/ops/public_market_data_runtime_owners_v1.md` for selection, cutover, and
rollback order.
