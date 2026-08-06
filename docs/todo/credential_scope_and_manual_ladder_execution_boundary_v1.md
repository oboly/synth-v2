# Credential scope and manual ladder execution boundary v1

> **Migration pointer.** Current execution status, priority, blockers, and
> next action for this lane are owned by GitHub Issue
> [#206 — Complete credential scope and manual execution runtime boundary](https://github.com/oboly/synth-v2/issues/206).
> This file is retained as frozen historical/design context; do not update
> status, priority, or execution order here. See
> `docs/development/github_issues_first_batch_migration_v1.md`.

Status: TODO — credential binding contract migrated to canonical docs
Owner: future execution-boundary lane
Created: 2026-07-09
Updated: 2026-07-21

## Canonical credential contract

The account-to-credential binding contract now lives in:

```text
docs/architecture/account_credential_binding_contract_v1.md
```

Do not duplicate the credential source, scope, capability, or fail-closed rules
in this TODO. Update the canonical document instead.

## Remaining purpose

This TODO tracks follow-up runtime and execution-boundary work after PR A.

PR A is schema/contract only:

```text
no runtime credential resolution change
no BitvavoClient behavior change
no private API caller change
no host mutation
no API call
no production authorization
```

## Remaining implementation tasks

1. Wire account refresh and linked-profile runtime to the canonical
   `READ_ONLY_PRIVATE` binding resolver.
2. Remove runtime dependence on repository-global `.env` credentials for private
   Bitvavo clients.
3. Add executor-only credential resolution for future `TRADE_EXECUTION`
   credentials.
4. Ensure dashboards and account refresh cannot load execution credentials.
5. Ensure executor cannot load read-only credentials for broker writes.
6. Add decision-gate checks for trade-enabled account state, credential scope,
   stale account context, risk limits, and duplicate active execution cycles.
7. Define manual ladder setup as intent/config only.
8. Define execution-planner idempotency keys and execution-cycle references for
   approved manual ladder intent.
9. Define executor audit logs for account, credential scope, decision-gate
   result, execution intent id, and permission source.
10. Document operational separation between read/account EnvironmentFile and any
    future executor-only EnvironmentFile.

## Manual ladder boundary

Manual ladder setup may define:

```text
profile/account
market
side
ladder levels
size model
expiry
invalidation
user approval state
```

Manual ladder setup must not:

- load credentials
- call Bitvavo private APIs
- create orders
- cancel orders
- submit broker writes
- bypass `decision_gate`

## Non-goals

- Do not add trade key support to the linked-profile runtime orchestrator.
- Do not enable live trading.
- Do not submit real orders.
- Do not bypass `decision_gate` for manual ladder execution.
- Do not store or use trade-capable credentials before the runtime scope
  boundary is implemented.
