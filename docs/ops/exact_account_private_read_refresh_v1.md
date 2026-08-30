# Exact-account private-read account-state refresh (Issue #614)

Status: repository code only. No production migration, no timer, no LIVE
authorization is created by this change. `broker_private_calls<=2` per run,
`broker_writes=0`, `order_submission=0`, `live_orders=0`,
`live_authority_grant=0`, `kill_switch_mutation=0`, `service_mutation=0`.

## Files

```text
src/account/run_exact_account_state_refresh_v1.py   runner / CLI
src/account/account_snapshot_models_v1.py           + ExactAccountStateRefreshResult
```

No new persistence module was added. This seam reuses, unmodified:

```text
src/account/private_read_credential_resolver_v1.py   identity + credential resolution
src/account/run_account_wallet_refresh_v1.py          normalize_*, discover_account_assets,
                                                       write_aligned_account_state_snapshot
src/account/account_state_snapshot_alignment_v1.py    COMPLETE bundle contract
```

## Why this is a separate seam from `run_account_wallet_refresh_v1`

`run_account_wallet_refresh_v1.py` resolves identity through
`linked_account_resolver_v1.resolve_primary_linked_account(profile_code, venue)`.
That resolver is the profile-primary **dashboard** refresh path and fails
closed with `LIVE_TRADING_ENABLED` whenever the linked account has
`live_trading_enabled != 0` — i.e. it permanently refuses `account_mode='live'`
accounts. This is correct for that path and is unchanged by this issue.

A LIVE-capable trading account (e.g. `trading_account_id=5`,
`account_code='bitvavo_joost_live'`, `account_mode='live'`) still needs
bounded, private-read-only account-state evidence (balances, open orders,
derived positions) for operator review, independent of any dashboard
profile link. `run_exact_account_state_refresh_v1.py` is that seam: it
resolves identity by **exact `trading_account_id` + `venue` only**, via
`private_read_credential_resolver_v1.resolve_private_read_credential`
(`trading_account_id=...`), which already has no `account_mode` /
`live_trading_enabled` restriction — it never imports
`linked_account_resolver_v1` and does not change or weaken its
`LIVE_TRADING_ENABLED` fail-closed behavior in any way.

## Account isolation rule

Every persisted row (balance snapshot, open-order snapshot, derived
position, `account_state_snapshot_run_v1` header) is scoped by the caller's
exact `trading_account_id` + `venue`, using the same canonical write
functions as the profile-based wallet refresh. Credential resolution is
independently scoped to the same exact `trading_account_id` + `venue`
(`CREDENTIAL_ENVELOPE_ACCOUNT_MISMATCH` / `CREDENTIAL_ENVELOPE_VENUE_MISMATCH`
fail closed on any envelope/account mismatch). No account's evidence is ever
copied, derived from, or projected onto another account's rows — e.g.
account 3 (`bitvavo_joost_read`, `live_readonly`) evidence is never used to
produce or substitute for account 5 (`bitvavo_joost_live`) evidence; each
resolves its own credential and produces its own COMPLETE bundle
independently.

## Contract

- `--trading-account-id` (required, exact `int`) + `--venue` (required,
  exact match) — no profile, no account-code, no fallback identity path.
- Account must exist, be `enabled=1`, and match the exact requested venue;
  otherwise fails closed (`ACCOUNT_NOT_FOUND` / `ACCOUNT_DISABLED` /
  `VENUE_MISMATCH`).
- `account_mode` is not gated by this seam — `live`, `live_readonly`, and
  `paper` are all accepted, because this is exact-identity private-read
  ingestion, not profile-primary dashboard refresh.
- Credential: exactly one `ACTIVE`, validated `READ_ONLY_PRIVATE` binding
  for the same `trading_account_id` + `venue`, with `allowed_private_read=1`
  and `allowed_order_write=0`, is required
  (`NO_CREDENTIAL_BINDING` / `MISSING_REQUIRED_PRIVATE_READ_SCOPE` fail
  closed otherwise). No permission is inferred from any other field.
- Broker calls: `client.get_balance()` and `client.get_open_orders()` only.
  No write/order method is imported or reachable from this module.
- Persistence (`--write-db`) reuses
  `run_account_wallet_refresh_v1.write_aligned_account_state_snapshot` and
  `discover_account_assets` verbatim, inside the caller's existing
  single-transaction, all-or-nothing COMPLETE-bundle contract
  (`docs/ops/multi_account_wallet_refresh_v1.md`). Without `--write-db` the
  run is a dry-run: no DB write occurs.

## CLI

Dry-run:

```bash
SYNTH_BROKER_PRIVATE_READ_PERMISSION=I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA \
python -m src.account.run_exact_account_state_refresh_v1 \
  --trading-account-id 5 \
  --venue bitvavo \
  --output summary
```

Write mode:

```bash
SYNTH_BROKER_PRIVATE_READ_PERMISSION=I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA \
python -m src.account.run_exact_account_state_refresh_v1 \
  --trading-account-id 5 \
  --venue bitvavo \
  --write-db \
  --output summary
```

Example summary output:

```
runner=exact_account_state_refresh_v1 version=0.1
trading_account_id=5 account_code=bitvavo_joost_live
venue=bitvavo account_mode=live
credential_source=db_encrypted
credential_profile_id=<id>
permission_scope=READ_ONLY_PRIVATE
validation_state=VALID_PRIVATE_READ
[INFO] private read-only; no broker writes; no order submission
snapshot_ts_utc=2026-08-30 12:00:00
balance_count=<n>
order_count=<n>
position_count=<n>
account_asset_inserted=<n>
account_asset_existing=<n>
account_state_snapshot_run_id=<id>
broker_private_calls=2
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

No secret (API key, API secret, encrypted envelope, master key,
fingerprint) is ever printed.

## Bounded manual acceptance target (account 5)

The production acceptance target for this issue is a single bounded manual
run against:

```text
trading_account_id=5
account_code=bitvavo_joost_live
venue=bitvavo
```

This requires that `trading_account_id=5` already exists with an ACTIVE,
validated `READ_ONLY_PRIVATE` credential binding
(`docs/ops/live_execution_trading_account_provisioning_v1.md`,
`docs/ops/private_read_account_credential_enforcement_v1.md`). Provisioning
that row/credential, if not already done, is out of scope for this issue.

## Explicitly out of scope for this issue

- No systemd timer or scheduled job is added for this runner.
- No LIVE trading authorization, decision_gate permission, or kill-switch
  change is made or implied.
- No change to `linked_account_resolver_v1`,
  `app_profile_trading_account_link` rows, or any existing app-profile
  primary link.
- No `decision_gate`, `execution_planner`, or `executor` code path is
  touched or called.

## Safety

```text
broker_private_calls<=2 per bounded run
broker_writes=0
order_submission=0
live_orders=0
live_authority_grant=0
kill_switch_mutation=0
service_mutation=0
decision_gate=none
execution_planner=none
executor=none
```
