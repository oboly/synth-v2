# Public Market-Data Runtime Owners v1

## Status

Repository implementation only. No host deployment, timer activation, writer
invocation, database mutation, or operational acceptance is claimed here.

## Domain boundary

Public market-data database writes are distinct from other persistence:

- public market data: public price snapshots, candle ETL, Native SHORT market
  state, and rotation-pressure market state;
- account snapshots: authenticated read-only exchange observations persisted by
  account-owned runners;
- website registration: identity/application persistence;
- publication: HTML/JSON or static-file output from persisted state.

Only the first category belongs to the devlap public market-data writer owner.
Account snapshot persistence may remain on Odroid and does not make Odroid a
public market-data owner.

## Ownership graph before this repository change

```text
devlap
  synth-chain-4h.timer
    -> scripts/run_chain_4h.sh
    -> 4h candle ETL
    -> Native SHORT market-data writers
  synth-market-rotation-pressure-writer.timer
    -> scripts/run_market_rotation_pressure_once.sh --write-db

Odroid
  synth-linked-profile-runtime-refresh.timer
    -> scripts/odroid/run_linked_profile_runtime_orchestrator_once.sh
    -> run_market_price_snapshot_v1 --write-db       [violation]
    -> authenticated account snapshot refresh
    -> wallet/open-order and Profit Plan renders
  synth-market-candle-freshness.timer
    -> scripts/odroid/run_market_candle_freshness_once.sh
    -> run_candles_etl for 15m/1h/4h/1d/1w          [violation]
  legacy/manual Odroid wrappers
    -> public-price writes, candle ETL, or optional 4h chain [capability violation]
  synth-market-rotation-pressure-publisher.timer
    -> read-only persisted-state publication
```

The live Odroid 4h and candle-freshness timers were contained separately. This
document records repository ownership only; it does not repeat or supersede
that host evidence.

## Target ownership graph

```text
devlap: sole public market-data database writer host
  synth-market-price-snapshot-writer.timer
    -> scripts/run_market_price_snapshot_once.sh
    -> run_market_price_snapshot_v1 --write-db
  synth-market-candle-freshness-writer.timer
    -> scripts/run_market_candle_freshness_once.sh
    -> run_candles_etl for 15m/1h/4h/1d/1w
  synth-chain-4h.timer
    -> SELECT-only persisted 4h candle boundary validation
    -> existing Native SHORT and later 4h market chain stages
  synth-market-rotation-pressure-writer.timer
    -> existing rotation history/pressure writer

Odroid: persisted-state consumer and publisher
  synth-linked-profile-runtime-refresh.timer
    -> SELECT-only persisted public-price validation
    -> authenticated account snapshot refresh
    -> wallet/open-order persisted-snapshot render
    -> Profit Plan persisted-snapshot render
  synth-market-rotation-pressure-publisher.timer
    -> read-only persisted pressure publication
  static/public dashboard services
    -> persisted-state publication only
```

There is no SSH orchestration, remote systemd dependency, or reporting-triggered
repair path in either new writer contract.

## Devlap writer contracts

Public prices:

```text
scripts/run_market_price_snapshot_once.sh
deploy/systemd/synth-market-price-snapshot-writer.service
deploy/systemd/synth-market-price-snapshot-writer.timer
lock=/tmp/synth-market-price-snapshot-writer-v1.lock
cadence=every 5 minutes, up to 30 seconds randomized delay
```

Candles:

```text
scripts/run_market_candle_freshness_once.sh
deploy/systemd/synth-market-candle-freshness-writer.service
deploy/systemd/synth-market-candle-freshness-writer.timer
lock=/tmp/synth-market-candle-freshness-writer-v1.lock
cadence=minutes 02,17,32,47 UTC, up to 30 seconds randomized delay
intervals=15m,1h,4h,1d,1w
```

The candle timer is the only scheduled caller of canonical candle ETL. The 4h
chain no longer refreshes candles; it fails closed unless the expected 4h close
is already persisted, then continues with Native SHORT and later market-only
stages. Its repository timer fires at minute 12 after each 4h close, after the
multi-interval writer's minute-02 cycle.

Both wrappers are market-only and account-agnostic. They use public exchange
endpoints, name `devlap-public-market-data` as owner, record repository commit
identity, and contain no reporting, broker, account, decision, planning,
execution, SSH, or remote-host invocation.

## Odroid freshness contract

`src.operations.run_persisted_market_price_freshness_v1` performs one read-only
transaction and a SELECT over the latest persisted price batch. The linked
profile orchestrator uses the fixed module directly; no production command or
writer override exists.

The default contract is:

```text
max_age_seconds=900
max_future_skew_seconds=30
PASS only when classification=FRESH and snapshot_row_count>0
BLOCKED for STALE, MISSING, UNAVAILABLE, malformed, future-dated, or query failure
```

A blocked validation writes truthful run metadata but stops before profile
discovery, account refresh, wallet/open-order render, or Profit Plan render. It
never attempts to repair persisted state.

## Separate account-domain work

These remain account-domain questions and are not folded into this change:

- `synth-linked-profile-runtime-refresh.timer` remains the intended linked
  profile account-refresh and render owner after its public-price write is
  removed;
- `synth-mvp-account-refresh.timer` is a separate duplicate-account-owner
  retirement task;
- website registration ownership is unchanged.

## Required host rollout order

No command in this section was executed by the repository change.

1. Deploy the accepted repository commit without enabling new units.
2. Install and manually validate the devlap public-price writer.
3. Install and manually validate the devlap candle writer.
4. Prove persisted price and candle freshness from SELECT-only evidence, then
   install the updated minute-12 4h-chain timer definition without manually
   invoking the chain.
5. Deploy the Odroid linked-profile SELECT-only validation path.
6. Verify account refresh and all persisted-snapshot render stages.
7. Confirm the Odroid public market-data writer count is zero.
8. Only then repeat Native SHORT writer-provenance operational acceptance.
9. Amend or replace PR #118 evidence after the successful repeat acceptance.

Repository-backed installation candidates, to be executed only in a separately
authorized host rollout:

```bash
sudo install -D -m 0644 /etc/systemd/system/synth-chain-4h.timer \
  /var/lib/synth-runtime-backups/devlap-public-market-data-v1/synth-chain-4h.timer
sudo cp deploy/systemd/synth-market-price-snapshot-writer.service /etc/systemd/system/
sudo cp deploy/systemd/synth-market-price-snapshot-writer.timer /etc/systemd/system/
sudo cp deploy/systemd/synth-market-candle-freshness-writer.service /etc/systemd/system/
sudo cp deploy/systemd/synth-market-candle-freshness-writer.timer /etc/systemd/system/
sudo cp deploy/systemd/synth-chain-4h.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

Activation remains separately authorized:

```bash
sudo systemctl enable --now synth-market-price-snapshot-writer.timer
sudo systemctl enable --now synth-market-candle-freshness-writer.timer
```

## Rollback sequencing

Never restore an Odroid writer while its devlap replacement remains active.

Public-price rollback candidate:

```bash
sudo systemctl disable --now synth-market-price-snapshot-writer.timer
sudo systemctl is-active synth-market-price-snapshot-writer.timer
sudo systemctl is-enabled synth-market-price-snapshot-writer.timer
```

This deliberately creates a fail-closed public-price freshness outage. It does
not restore an Odroid writer implicitly.

Candle rollback candidate:

```bash
sudo systemctl disable --now synth-market-candle-freshness-writer.timer
sudo systemctl is-active synth-market-candle-freshness-writer.timer
sudo systemctl is-enabled synth-market-candle-freshness-writer.timer
sudo cp /var/lib/synth-runtime-backups/devlap-public-market-data-v1/synth-chain-4h.timer \
  /etc/systemd/system/synth-chain-4h.timer
sudo systemctl daemon-reload
```

This deliberately creates a fail-closed candle freshness outage. Restoring the
retired Odroid timer is a separate incident decision requiring an exact
pre-cutover Odroid commit and proof that the devlap writer remains disabled; it
is not part of this ownership contract.

Rollback must record exact commits, timer states, database freshness, and the
absence of overlapping owners. The retired repository Odroid candle wrapper is
a fail-closed stub and cannot be used as a writer.
