# Public Candle Freshness gurkDB Acceptance — 2026-07-23

## Outcome

Strict read-only preflight passed. Controlled acceptance initially stopped
before the first writer invocation because the configured enabled universe did
not match the current Bitvavo EUR trading universe. The bounded canonical
metadata correction completed on 2026-07-24 and the enabled-universe validator
now reports zero mismatch. Acceptance remains pending a fresh exact-head
preflight.

```text
capability=public_candle_freshness
host=gurkdb
preflight_commit=6031a94a2f6e9a0576dd73b0d3babe5d6e228bb6
preflight_required_pass=19
preflight_required_warn=0
preflight_required_fail=0
preflight_required_unverified=0
acceptance_status=PENDING
production_runtime_owner=UNASSIGNED
runtime_lifecycle=PREFLIGHT_PASSED
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

## Deferred Acceptance and Activation

```text
manual_cycle_1=NOT_RUN
manual_cycle_2=NOT_RUN
accepted_candle_writes=0
lock_test=NOT_RUN
timer_installed=false
timer_enabled=false
scheduled_cycles_observed=0
production_authorization_created=false
```

An administrator-capable installation path is also required for the eventual
system unit and capability-specific production authorization file; the
available SSH account has no non-interactive sudo delegation. This was not
bypassed.

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

Repeat exact-commit strict preflight on the final candidate, then run two
controlled acceptance cycles and verify persisted coverage and lock behavior.
Only after successful acceptance may production authorization and canonical
gurkDB timer installation be considered.
