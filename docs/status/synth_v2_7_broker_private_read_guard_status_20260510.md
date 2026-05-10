# Synth v2.7 Broker Private Read Guard Status — 2026-05-10

Status: active safety guard
Runtime impact: private broker reads fail-closed by default
DB impact: none
Broker write impact: none
Live trading: not enabled

## Purpose

The next safe broker step is private account visibility, not broker writing.

This status adds a fail-closed private-read guard before any authenticated Bitvavo account read is allowed.

## Private read guard

Private account reads require the exact environment value:

`SYNTH_BROKER_PRIVATE_READ_PERMISSION=I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA`

Without this value, private read methods raise `PermissionError` before signing or making a network request.

Currently guarded private read methods:

- `BitvavoClient.get_balance`
- `BitvavoClient.get_order`

## Broker write guard remains separate

Broker writes still require the exact environment value:

`SYNTH_BROKER_WRITE_PERMISSION=I_UNDERSTAND_THIS_PLACES_REAL_ORDERS`

Do not store the write permission in `.env`.

## Read-only balance probe

The read-only probe lives at:

`src/operations/run_broker_balance_readonly_probe_v1.py`

Default behavior:

- reports env readiness only
- redacts values
- performs no DB writes
- performs no broker writes
- performs no private API call unless `--fetch-private-balance` is passed

Even with `--fetch-private-balance`, the private read guard must be explicitly granted.

## Boundary

This is not a trading permission system.

It only allows safe account visibility when explicitly granted.

Trading still requires:

- decision_gate approval
- execution_planner plan
- executor order handling
- broker write guard
- live permission
- account and duplicate safety checks

