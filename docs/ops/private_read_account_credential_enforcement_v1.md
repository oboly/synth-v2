# Private-read account credential enforcement v1

Status: PR B1 implemented in code; production migration and binding remain
operational gates.

Reference contract:

```text
docs/architecture/account_credential_binding_contract_v1.md
```

PR A schema/contract is merged. PR B1 enforces that private read-only account
runtimes resolve credentials only through:

```text
trading_account_id + venue + READ_ONLY_PRIVATE
-> exactly one ACTIVE validated db_encrypted credential
```

Legacy global private-read fallback is removed from runtime behavior. Private
read clients no longer consume repository-global `BITVAVO_API_KEY` or
`BITVAVO_API_SECRET`; `BitvavoClient()` is public/unbound by default.

Allowed private-read secret input:

```text
SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY
```

That value must be supplied by a host-local EnvironmentFile outside git.

Out of scope for PR B1:

```text
trade-execution credential enforcement
live execution permission production
decision-gate permission production
broker order submission or cancellation
authenticated trade monitoring
atomic execution claims, idempotency, or reconciliation
production credential migration
host .env edits
systemd installation/enabling
exchange calls during validation
```

PR #129's executor boundary remains authoritative: LIVE execution fails closed,
PAPER uses its dedicated unauthenticated public market-data client, and executor
credentials do not authorize execution. PR B1 does not modify the executor or
execution-planner contract.

## Bitvavo caller inventory

```text
PUBLIC
- market sync and ETL callers use unauthenticated public HTTP only
- PAPER worker uses BitvavoPublicMarketDataClient only

PRIVATE_READ runtime
- wallet refresh
- balance snapshot writer
- order snapshot writer
- balance read-only probe
- open-orders read-only probe
  -> canonical account-bound private-read resolver

PRIVATE_READ provisioning
- credential validator
  -> explicit request credential before the canonical binding is created;
     no global fallback and no broker-write capability
- first account snapshot after provisioning
  -> canonical resolver after the binding transaction commits

TRADE_EXECUTION
- executor worker has no private Bitvavo client and no broker-write path
- limit-ladder helpers accept an injected client but do not resolve credentials
  or bypass execution permission

UNKNOWN
- none
```

The Odroid account-refresh timer remains contained and must not be reactivated
as part of this change. Production rollout still requires migrated credential
bindings and the host-local master-key EnvironmentFile.

## Post-merge deployment gate

Deployment is explicitly authorized only after this PR passes independent
review and is merged. Deployment was not performed in the implementation
refresh session. A separate host-acceptance procedure must deploy the exact
eventual merge SHA.

Required production prerequisites must be verified on the target host; this
document does not claim they currently exist:

```text
db/migrations/20260609_trading_account_credential_v1.sql applied
db/migrations/20260609_trading_account_credential_add_valid_private_read.sql applied
db/migrations/20260721_account_credential_binding_contract_v1.sql applied
enabled trading_account rows with exact account_code and venue
exactly one ACTIVE validated db_encrypted READ_ONLY_PRIVATE row per account+venue
allowed_private_read=1, allowed_order_write=0, allowed_withdrawal=0
encrypted-envelope account, venue, algorithm, schema, and key-version metadata valid
required app_profile and primary ACTIVE account links present
host-local SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY EnvironmentFile present and readable only by the service identity
account/profile runner mappings explicit
account-refresh timer contained until host acceptance passes
```

Rollback requires stopping or keeping contained all affected timers, restoring
the previous known-good application SHA, and confirming no private-read runner
remains active. Credential rows and encrypted envelopes must not be deleted or
decrypted as a rollback shortcut; any binding correction or revocation requires
explicit operator review. Remove the master-key EnvironmentFile from a service
only after confirming no deployed process consumes it.
