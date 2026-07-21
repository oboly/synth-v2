# Linked-Profile Runtime Orchestrator v1

## Status

Repository contract updated for Odroid persisted-state consumption. Host
deployment and acceptance remain separate.

## Ownership

```text
public market-data writer capabilities
  -> public_price_snapshot owner=gurkdb, lifecycle=AUTHORIZED_INACTIVE
  -> other writer capabilities retain their registry-specific state

Odroid linked-profile orchestrator candidate/consumer role
  -> validate persisted public-price freshness (SELECT-only)
  -> discover linked profiles
  -> authenticated read-only account refresh and account-snapshot persistence
  -> wallet/open-order persisted-snapshot render
  -> Profit Plan persisted-snapshot render
```

The orchestrator is account/render ownership, not public market-data ownership.
Account snapshot persistence remains allowed and does not grant public market
writer authority. An installed timer may continue running operationally even
after canonical authorization is reset; repository correction does not stop that
timer. Containment requires a separately authorized host action.

## Hard boundaries

- no public exchange request;
- no public market-price write;
- no candle ETL;
- no Native SHORT or rotation-pressure writer;
- no arbitrary validation/writer command override;
- no broker write, order submission, decision-gate mutation, planning, or
  execution;
- no SSH or cross-host systemd dependency;
- reporting never repairs stale persisted state.

## Stage order

`scripts/odroid/run_linked_profile_runtime_orchestrator_once.sh` owns one
locked account/render cycle:

1. disk/log health check;
2. fixed SELECT-only persisted public-price validation;
3. linked-profile discovery;
4. authenticated read-only account refresh per profile;
5. wallet/open-order persisted-snapshot render per profile;
6. Profit Plan persisted-snapshot render after all required account refreshes
   succeed.

The validation stage calls only:

```text
python -m src.operations.run_persisted_market_price_freshness_v1
```

Defaults are a 900-second maximum age and 30-second maximum future skew. A
missing, malformed, future-dated, unavailable, or stale latest price batch
produces `BLOCKED`. The orchestrator records metadata and exits before profile
discovery or any account/render stage. It never invokes a writer as fallback.

## Metadata contract

Every completed or freshness-blocked cycle atomically writes
`/var/www/html/synth/_runtime/linked_profile_orchestrator_v1/latest_run.json`
unless `SYNTH_LINKED_PROFILE_RUNTIME_METADATA_PATH` overrides the output path.

The metadata payload schema is `linked_profile_runtime_orchestrator_v2`. The
version reflects the incompatible replacement of the former refresh-result
field with persisted public-price validation, freshness, age, and row-count
fields. No repository consumer depends on the retired v1 payload shape.

Freshness fields are truthful validation fields, not refresh claims:

```json
{
  "public_price_validation_result": "PASS|BLOCKED",
  "persisted_public_price_as_of_utc": "2026-07-18T12:00:00+00:00|null",
  "persisted_public_price_age_seconds": 60.0,
  "freshness_classification": "FRESH|STALE|MISSING|UNAVAILABLE",
  "public_price_validation_reason": "WITHIN_THRESHOLD|EXCEEDS_THRESHOLD|FUTURE_TIMESTAMP|...",
  "persisted_public_price_snapshot_row_count": 42,
  "safety": {
    "public_market_data_writes": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "native_short_context_build_in_render_stage": false
  }
}
```

`overall_result=blocked_public_price_validation` means no profile, account, or
render stage ran. `overall_result=degraded` remains reserved for later-stage
account/render failures after public-price validation passed.

## Render paths

The scheduled orchestrator continues to use:

- `scripts/odroid/run_account_wallet_refresh_once.sh` for authenticated
  read-only account refresh plus account-snapshot persistence;
- `scripts/odroid/run_account_wallet_snapshot_dashboard_render_once.sh` for
  wallet/open-order persisted-snapshot rendering;
- `scripts/odroid/run_account_profit_plan_snapshot_render_once.sh` for the
  persisted-snapshot-only Profit Plan owner.

Profile discovery and those later responsibilities are unchanged.

Legacy/manual wrappers now validate persisted public prices and contain no
public market writer invocation. `run_mvp_dashboard_render_once.sh` remains
entry-candidate/about publication only.

## Account-owner boundary

The installed `synth-linked-profile-runtime-refresh.timer`, if present on a
host, remains an account/render runtime fact only. It is not evidence of
public-writer authorization and must not invoke public market-data writers.
`synth-mvp-account-refresh.timer` is a separate duplicate-account-owner
retirement task. This public market-data ownership change does not modify or
disable either account unit and does not touch website registration.

## Systemd templates

```text
docs/ops/systemd/synth-linked-profile-runtime-refresh.service
docs/ops/systemd/synth-linked-profile-runtime-refresh.timer
```

The templates contain no public writer command or test injection. Deploy only
after required persisted public data is fresh from separately authorized writer
capabilities. See `docs/ops/public_market_data_runtime_owners_v1.md` for
sequencing and rollback.

## Acceptance checklist

- [ ] Exact repository commit deployed on selected hosts.
- [ ] Public-price and candle writers are separately authorized and fresh.
- [ ] Persisted public prices classify `FRESH` within the 900-second contract.
- [ ] Odroid metadata records validation fields above.
- [ ] Stale/missing/future/malformed fixtures stop before account refresh.
- [ ] Current data permits account refresh, wallet/open-order render, and
      persisted-snapshot Profit Plan render in order.
- [ ] Odroid public market-data writer count is zero.
- [ ] No account duplicate is retired as an implicit side effect.
- [ ] Native SHORT provenance acceptance is repeated only afterward.

## Non-goals

- no decision, planning, execution, broker-write, or order change;
- no account-owner cleanup;
- no website registration change;
- no host activation in this repository change;
- no Native SHORT scope expansion or blocker clearance.
