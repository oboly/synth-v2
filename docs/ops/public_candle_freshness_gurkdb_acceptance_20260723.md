# Public Candle Freshness gurkDB Acceptance — 2026-07-23

## Outcome

Strict read-only preflight and controlled acceptance passed on gurkDB. The
configured enabled-universe mismatch was corrected before any writer
invocation, then exact-head validation reported zero mismatch. Two authorized
manual cycles completed for the full enabled universe with the host-local lock
and duplicate-writer boundaries intact.

```text
capability=public_candle_freshness
host=gurkdb
preflight_commit=6031a94a2f6e9a0576dd73b0d3babe5d6e228bb6
preflight_required_pass=19
preflight_required_warn=0
preflight_required_fail=0
preflight_required_unverified=0
acceptance_commit=2e762b58ab9e311f4a8d403d8d97332e5ebb0f16
acceptance_status=ACCEPTED
production_runtime_owner=gurkdb
production_authorization_status=AUTHORIZED
runtime_lifecycle=AUTHORIZED_INACTIVE
production_authorization_file_present=false
timer_enabled=false
timer_active=false
```

## Host and Legacy Containment

```text
gurkdb canonical candle units=not installed
gurkdb candle writer processes=0
devlap legacy enablement links=0
devlap candle writer processes=0
odroid legacy user service=masked/inactive
odroid legacy user timer=masked/inactive
odroid canonical writer units=not found
odroid candle writer processes=0
authorized_active_candle_owner_count=0
duplicate_candle_writer_count=0
```

The gurkDB acceptance checkout was a full canonical clone at the exact clean
commit. It used the existing gurkDB virtual environment and runtime
configuration without changing the active public-price checkout or
authorization.

## Strict Preflight

Fresh external evidence was observed at `2026-07-23T16:39:43Z`. All 12 required
local checks and seven required external checks passed. The public writer does
not require private exchange credentials, so that non-required check remained
`UNVERIFIED` by design.

The probes used one read-only MariaDB transaction, one public Bitvavo candle
request, DNS resolution, NTP state, journald/logrotate state, and safe runtime
configuration metadata. They made no database write or systemd mutation.

### Exact-Head Evidence Boundary

The strict preflight above is initial evidence for commit
`6031a94a2f6e9a0576dd73b0d3babe5d6e228bb6` only. Registry lifecycle state and
the systemd candidate description changed afterward, producing candidate head
`032eac5d2025271060f25af4d57532c50ab80264`. The initial preflight must not be
presented as exact-head evidence for that later artifact state.

Commit `23d9f309c439fcaf31c47bf655f077cd8f0334b5` subsequently passed complete
exact-head strict preflight, recorded in PR #139 comment `5064126224`. The
metadata correction and validation artifacts were added afterward, so the
final candidate commit containing this record requires another complete
exact-head strict preflight before controlled acceptance resumes.

## Resolved Universe Mismatch

The writer loads every row where `asset.is_enabled=1`. The bounded comparison
found:

```text
enabled_assets=429
current_bitvavo_eur_trading_markets=421
missing_market_count=8
missing_markets=CARDS,COS,D,IP,MBOX,NFP,QTUM,XION
```

The task failed closed at that point before creating an acceptance permit or
invoking the writer.

One live Bitvavo `/markets` verification on 2026-07-24 confirmed that none of
the eight symbols was a current trading EUR market. Migration
`db/migrations/20260724_disable_stale_bitvavo_asset_import_v1.sql` then changed
only `asset.is_enabled` for those exact rows:

```text
enabled_assets_before=429
enabled_assets_after=421
target_rows_changed=8
target_historical_candle_rows_before=18660
target_historical_candle_rows_after=18660
target_history_first_close=2021-01-11T00:00:00Z
target_history_last_close=2026-07-20T04:00:00Z
current_bitvavo_eur_trading_markets=430
remaining_enabled_universe_mismatch=0
```

No asset or candle row was deleted. No alias, writer exclusion, calculation
change, writer invocation, runtime change, or timer change occurred.

## Controlled Acceptance

```text
manual_cycle_1=PASS
manual_cycle_1_started=2026-07-23T23:02:13Z
manual_cycle_1_finished=2026-07-23T23:06:31Z
manual_cycle_1_accepted_input_rows=219630
manual_cycle_2=PASS
manual_cycle_2_started=2026-07-23T23:06:42Z
manual_cycle_2_finished=2026-07-23T23:10:13Z
manual_cycle_2_accepted_input_rows=219630
lock_test=PASS
lock_test_exit_status=75
lock_test_etl_invocations=0
enabled_asset_coverage_per_interval=421/421
bitvavo_rows_before=3506001
bitvavo_rows_after_cycle_1=3599458
bitvavo_rows_after_cycle_2=3599458
latest_15m_close=2026-07-23T23:00:00Z
latest_1h_close=2026-07-23T23:00:00Z
latest_4h_close=2026-07-23T20:00:00Z
latest_1d_close=2026-07-23T00:00:00Z
latest_1w_close=2026-07-20T00:00:00Z
source_venue=bitvavo
unavailable_market_errors=0
duplicate_writer_processes=0
disabled_target_history_rows=18660
timer_installed=false
timer_enabled=false
scheduled_cycles_observed=0
production_authorization_created=false
```

Cycle 1 added 93,457 previously missing unique candle rows. Cycle 2 repeated
the same bounded inputs without increasing the row count, proving idempotent
operation. The acceptance permit was exact-commit, host-bound, and
acceptance-only; the prior permit file was restored byte-for-byte afterward.
No production authorization was created.

An administrator-capable installation path is required for the eventual
system unit and capability-specific production authorization file. The
available SSH account has no non-interactive sudo delegation, so cutover was
not attempted or bypassed.

## Production Cutover Authorization

The user explicitly authorized the `public_candle_freshness` production
cutover to gurkDB on 2026-07-24, separately from the controlled acceptance
permit. The authorization covers the repository ownership transition to
`AUTHORIZED_INACTIVE`, creation of the capability-specific production
authorization bound to the exact merged commit, installation of the canonical
candle service and timer, one production service run, and timer activation
after its required checks pass.

```text
candidate_host=gurkdb
selected_host=gurkdb
acceptance_host=gurkdb
acceptance_status=ACCEPTED
production_runtime_owner=gurkdb
production_authorization_status=AUTHORIZED
runtime_lifecycle=AUTHORIZED_INACTIVE
accepted_merge=9bafa64607542818e2ae639aeb1bcae0816ebd56
```

`AUTHORIZED_INACTIVE` does not permit execution by itself. The runtime remains
fail-closed until this authorization change is reviewed and merged and a
schema-valid production authorization file binds the exact merged commit,
host, capability, service, and this decision evidence.

## Safety

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
Rotation Pressure changes=0
dashboard changes=0
Native SHORT changes=0
account changes=0
decision_gate changes=0
execution_planner changes=0
executor changes=0
```

## Next Gate

Review and merge the authorization change. Then update the clean canonical
gurkDB checkout to the exact merge commit, install the capability-specific
production authorization and canonical units, run the service once, verify
fresh persisted Bitvavo candles and zero duplicate writers, and enable/start
the timer. One post-cutover service run is sufficient; do not repeat acceptance.
