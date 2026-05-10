# Maintenance Lock V1

Status: active runtime guard
Scope: market-only cron chains
Execution impact: none
Broker impact: none
Live trading impact: none

## Purpose

The maintenance lock prevents market cron chains from running during controlled maintenance work.

Use it for:

- new asset onboarding
- historical candle backfill
- feature bootstrap
- large schema changes
- controlled replay/bootstrap work

The lock prevents partial or inconsistent snapshots during maintenance.

## Lock path

Default lock file:

    /tmp/synth_maintenance.lock

## Enable maintenance mode

    echo "TON onboarding / candle backfill" > /tmp/synth_maintenance.lock

## Disable maintenance mode

    rm -f /tmp/synth_maintenance.lock

## Chain behavior

When the lock exists, each market chain exits cleanly with:

    [CHAIN][SKIP] maintenance lock active

No market chain work is performed.

## Boundary

This lock does not grant execution permission.

It does not enable:

- decision gate
- execution planner
- executor
- broker adapter
- live trading

It only protects market-chain determinism during maintenance.
