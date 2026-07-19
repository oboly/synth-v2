# Public Market-Data Runtime Owners v1

## Status

Repository implementation only. No host deployment, timer activation, writer
invocation, database mutation, or operational acceptance is claimed here.

## Ownership-contract correction (superseding note)

This document historically named `devlap` the *sole public market-data database
writer host* as the target for every writer capability. That was derived from an
acceptance/development placement, not from a separate infrastructure decision,
and is corrected. Production ownership is now an explicit, per-capability,
separately evidenced decision. The authoritative contract and machine-readable
registry are:

```text
docs/ops/writer_capability_host_ownership_contract_v1.md
deploy/ownership/writer_capability_ownership_v1.json
```

Under the corrected model `production_runtime_owner` is `UNASSIGNED` for the
public price snapshot, candle freshness, and Native SHORT 4h chain capabilities;
only `market_rotation_pressure` carries a recorded separate host-acceptance
decision (devlap, PR #100/#101). Where the graphs below still read "devlap: sole
public market-data database writer host," treat that as the retired claim: devlap
is at most a *candidate/acceptance* host, and gurkDB is a *preferred candidate,
not a proven owner*. The wrapper and unit contracts below remain valid as the
capability definitions; only the implicit permanent host assignment is removed.

## Domain boundary

Public market-data database writes are distinct from other persistence:

- public market data: public price snapshots, candle ETL, Native SHORT market
  state, and rotation-pressure market state;
- account snapshots: authenticated read-only exchange observations persisted by
  account-owned runners;
- website registration: identity/application persistence;
- publication: HTML/JSON or static-file output from persisted state.

Only the first category belongs to the public market-data writer capabilities
(neutral, host-independent owner identities; `production_runtime_owner` assigned
by explicit host selection). Account snapshot persistence may remain on Odroid
and does not make Odroid a public market-data owner.

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
public market-data writer capabilities (production_runtime_owner UNASSIGNED;
candidate/acceptance host only — NOT a canonical sole-host assignment)
  synth-market-price-snapshot-writer.timer
    -> scripts/run_market_price_snapshot_once.sh
    -> run_market_price_snapshot_v1 --write-db
  synth-market-candle-freshness-writer.timer
    -> scripts/run_market_candle_freshness_once.sh
    -> run_candles_etl for 15m/1h/4h/1d/1w
  synth-chain-4h.timer
    -> SELECT-only persisted public-price freshness validation
    -> SELECT-only persisted 4h candle boundary validation
    -> canonical Native SHORT scope/map publication
    -> canonical Native SHORT context snapshot publication
    -> later 4h market-only chain stages
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

There is no SSH orchestration, remote systemd dependency, dashboard render, or
reporting-triggered repair path in any devlap writer or the 4h chain. Reporting
transport is a downstream, separately owned persisted-state consumer.

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

The price and candle timers are the only canonical ingestion owners. The 4h
chain invokes the canonical SELECT-only public-price validator first and the
expected 4h candle-boundary validator second. Either failure stops the chain
before all Native SHORT work. The chain does not attempt writer repair. Its
repository timer fires at minute 12 after each 4h close, after the
multi-interval writer's minute-02 cycle.

The 4h chain is the sole canonical Native SHORT runtime publisher owner. It
publishes scope/map state and the persisted context snapshot through one
timer-owned invocation path. Linked-profile and reporting owners consume that
persisted snapshot and must not reconstruct or publish Native SHORT state.

Both wrappers are market-only and account-agnostic. They use public exchange
endpoints, name a neutral host-independent capability identity as owner
(`public-price-snapshot-writer` / `public-candle-freshness-writer`, overridable
via `SYNTH_MARKET_PRICE_WRITER_OWNER` / `SYNTH_MARKET_CANDLE_WRITER_OWNER`),
record repository commit identity, and contain no reporting, broker, account,
decision, planning, execution, SSH, or remote-host invocation. The
`/var/lib/synth-runtime-backups/devlap-public-market-data-v1/` backup path
referenced below is a historical devlap acceptance-host artifact path, not a
canonical production-owner assignment.

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

This batch-level check is a writer-liveness and timestamp-freshness gate only.
It does not prove that every account asset exists in the newest persisted
batch. Wallet and Profit Plan consumers must retain their independent
per-asset `MISSING_CURRENT_PRICE` and `STALE_CURRENT_PRICE` fail-closed checks.
Top-level batch freshness must never replace per-asset coverage validation, and
account-specific coverage policy does not belong in this market-data validator.

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

1. Merge the accepted 4h boundary correction.
2. Deploy its exact accepted commit without enabling the 4h timer.
3. Confirm the separately owned devlap public-price writer is active and fresh.
4. Confirm the separately owned devlap candle writer is active and fresh.
5. Prove persisted price and candle freshness from SELECT-only evidence, then
   install the updated 4h-chain service and timer definitions without manually
   invoking the chain.
6. Confirm downstream reporting and linked-profile paths remain consumers.
7. Only after an explicit activation authorization, enable the 4h timer.
8. Observe a natural scheduled cycle and repeat Native SHORT runtime acceptance.

Timer activation remains blocked during repository review and until the
post-merge host preflight passes.

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
