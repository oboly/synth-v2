# TODO — Authenticated Account Provisioning

## Status

Active P0 product lane, parallel to:

```text
docs/todo/profit_plan_live_ladder.md
```

Immediate goal:

```text
authenticated Hugo session
-> enter Bitvavo API key + secret once
-> validate read-only access server-side
-> reject trade permission
-> reject withdrawal permission
-> encrypt credentials server-side
-> create trading_account
-> create app_profile_trading_account_link
-> refresh first account snapshot
-> render Hugo wallet / Profit Plan pages
```

This lane unblocks Hugo’s own account-backed cockpit.

It must not block Joost’s first live-ladder canary when Joost’s account and credentials are already provisioned.

## Sources

Canonical areas to inspect before implementation:

```text
src/web/
src/account/
src/execution/bitvavo_client.py
src/reporting/account_dashboard_profile_access_v1.py
scripts/odroid/run_account_wallet_dashboard_render_once.sh
db/migrations/20260605_website_registration_foundation_v1.sql
db/migrations/20260607_profile_session_authorization_v1.sql
docs/ops/
```

Additional source:

```text
Recent chat handoff: Hugo can register and log in, but has no authenticated credential intake or account provisioning path.
```

## Current state / facts

- Website registration owns user, session, profile, verification, login, and authorization concerns.
- `app_profile_trading_account_link` contains linkage only and must never contain API credentials.
- Wallet-management UI preparation and profile/account linkage are foundations, not credential provisioning.
- The onboarding page currently describes exchange connection as future functionality and intentionally contains no credential fields.
- Hugo currently has no safe place to submit a Bitvavo API key and secret.
- Hugo remains without a linked trading account until provisioning exists.
- Existing per-profile dashboards correctly fail closed when no active primary trading-account link exists.

## Architecture decision

Create a separate account-aware provisioning layer.

Preferred ownership:

```text
existing authenticated web service
-> account_provisioning HTTP controller
-> account_provisioning application service
-> encrypted credential repository
-> Bitvavo validation adapter
-> account repository
-> account snapshot refresh
-> linked-profile dashboard render trigger
```

Separation of concerns:

```text
website_registration = identity, verification, login, session
account_provisioning = credential intake, validation, encrypted storage, account creation/linking
account layer = trading-account ownership and account snapshots
reporting = read-only dashboard rendering
executor = order handling only
```

Forbidden shortcuts:

```text
website_registration stores exchange credentials
app_profile stores exchange credentials
app_profile_trading_account_link stores exchange credentials
dashboard renderer receives or persists credentials
browser stores credentials in localStorage/sessionStorage
credentials are passed through URL/query string
credentials are placed in command-line arguments
credentials are written to logs
```

## Product split

### Initial provisioning: READ-ONLY ONLY

The initial Hugo provisioning flow accepts only a Bitvavo key that can perform required private reads.

It must reject credentials with:

```text
trade permission
withdrawal permission
```

Initial account state must remain:

```text
live_trading_enabled = false
broker_write_permission = NOT_GRANTED
order_submission = disabled
```

This is sufficient for:

- balances
- positions
- open-order visibility, when read permission supports it
- wallet dashboard
- Profit Plan account context
- later dry-run decision validation

### Later trade activation: separate controlled lane

Read-only provisioning does **not** enable Hugo’s live `Fix selected ladder` execution.

A later explicit account credential activation/rotation lane may accept a credential with trading permission, but only after:

- live execution architecture is complete
- decision_gate and executor canary are proven
- authenticated operator confirmation exists
- account and market allowlists exist
- broker-write permission is granted server-side
- withdrawal permission is still rejected

Never silently upgrade a read-only account into a trading account.

## Secret-storage contract

### Encryption at rest

Store API key and secret only as authenticated encrypted ciphertext.

Required properties:

- modern AEAD encryption
- random nonce per encrypted value or envelope
- authentication tag verification
- key version
- credential fingerprint for deduplication without exposing plaintext
- master encryption key stored outside the database and repository
- production master key loaded from a restricted server secret/environment file
- key rotation path
- credential revocation/status fields

Do not invent custom cryptography.

Use an established cryptographic library already present in the repository, or add one explicitly and document the operational dependency.

### Proposed storage shape

Adapt names to canonical repository conventions after inspection.

A dedicated credential table should contain equivalents of:

```text
trading_account_credential_id
venue
credential_kind
api_key_ciphertext
api_secret_ciphertext
nonce / envelope metadata
key_version
credential_fingerprint
validation_state
capabilities_json
credential_status
validated_ts_utc
created_ts_utc
rotated_ts_utc
revoked_ts_utc
```

The table must not contain recoverable plaintext outside the encrypted envelope.

`trading_account` stores account identity and operating flags, not secret material.

`app_profile_trading_account_link` stores authorization linkage only.

### Secret handling

Credential values must:

- arrive only through HTTPS POST
- be accepted only for an authenticated session
- be scoped to the authenticated profile server-side
- never be echoed in HTML or JSON
- never appear in exception strings
- never appear in access/application logs
- never be committed to Git
- never be written to preview files
- never be persisted after failed validation
- be removed from references as early as practical after use

Responses may expose only masked metadata such as a short fingerprint suffix.

## Permission validation

Provisioning must verify the credential using private read operations only.

Required result states:

```text
VALID_READ_ONLY
REJECTED_INVALID_CREDENTIALS
REJECTED_TRADE_PERMISSION
REJECTED_WITHDRAWAL_PERMISSION
REJECTED_UNVERIFIABLE_PERMISSIONS
REJECTED_ACCOUNT_ALREADY_LINKED
REJECTED_DUPLICATE_CREDENTIAL
REJECTED_PROFILE_MISMATCH
VALIDATION_UNAVAILABLE
```

Rules:

- Do not validate trading permission by placing or cancelling an order.
- Do not validate withdrawal permission by attempting a withdrawal.
- Use canonical exchange capability metadata when available.
- When permission scope cannot be proven safely, fail closed as `REJECTED_UNVERIFIABLE_PERMISSIONS`.
- A successful balance/open-order read does not by itself prove that trade or withdrawal permission is absent.
- Document the exact Bitvavo permission-verification mechanism before production activation.

## Authenticated intake UX

Add a profile-scoped account connection page, using the existing authenticated web service and route protection.

Suggested public route:

```text
/synth/accounts/<profile>/connect-exchange.html
```

Suggested server action route, adapted to current web-service conventions:

```text
POST /synth/web-auth/account-provisioning/bitvavo
```

The requested profile must be derived and verified server-side from the authenticated session/authorized route.

The browser must not authoritatively supply:

```text
user_id
profile owner
trading_account_id
account mode
permission flags
credential status
live_trading_enabled
broker_write_permission
```

Minimum page fields:

- venue fixed to Bitvavo for v1
- API key
- API secret
- clear statement that v1 accepts read-only credentials only
- explicit checkbox confirming trade and withdrawal permissions are disabled
- `Connect read-only account` button

Do not retain the fields after navigation or failure.

Do not add a generic multi-exchange abstraction before the Bitvavo path works.

## Request flow

Shortest safe v1 flow:

```text
1. Authenticate session.
2. Resolve the profile from server-owned session/route context.
3. Enforce Origin/CSRF and rate limits.
4. Reject if an active primary account link already exists, unless using a separate rotation flow.
5. Accept key + secret in memory.
6. Validate credentials through read-only Bitvavo calls.
7. Verify trade permission is absent.
8. Verify withdrawal permission is absent.
9. Encrypt credentials.
10. In one database transaction:
    - create credential record
    - create trading_account in read-only/non-live state
    - create active primary app_profile_trading_account_link
    - create provisioning audit record
11. Commit.
12. Trigger first private account snapshot refresh.
13. Trigger linked-profile wallet/Profit Plan render.
14. Return success without credentials.
```

If validation fails:

```text
no credential row
no trading_account
no profile/account link
no secret persistence
```

If the post-commit first snapshot or render fails:

- keep the valid provisioned account/link
- mark provisioning as `PROVISIONED_REFRESH_PENDING`
- expose a safe retry action
- do not ask the user to resubmit credentials

## Transaction and idempotency

Provisioning must be idempotent and concurrency-safe.

Required controls:

- unique active-primary link per profile/venue
- unique active credential fingerprint per venue where appropriate
- server-generated request/idempotency identifier
- transaction around credential/account/link creation
- rollback on any pre-commit failure
- safe retry after network timeout
- no duplicate trading accounts after double-click

Do not infer success solely from the browser response. Persist a provisioning state machine.

Suggested states:

```text
RECEIVED
VALIDATING
REJECTED
PROVISIONED
PROVISIONED_REFRESH_PENDING
READY
REVOKED
ROTATION_REQUIRED
```

Avoid persisting `RECEIVED`/`VALIDATING` rows containing secret material. Audit metadata only.

## First snapshot and dashboard activation

After successful provisioning:

1. Run the canonical account balance/open-order snapshot path for the new account.
2. Store only normal account snapshots, never credential plaintext.
3. Confirm profile/account linkage resolves through the account layer.
4. Render Hugo’s account dashboard pages through the existing linked-profile rendering pipeline.
5. Show onboarding status as connected/ready.

Provisioning must not directly render HTML itself. It triggers or queues the canonical render path.

For v1, a synchronous bounded refresh may be used if that matches existing infrastructure. Otherwise persist `PROVISIONED_REFRESH_PENDING` and invoke the existing safe refresh runner.

## Audit requirements

Persist non-secret audit events for:

- provisioning requested
- authentication/profile authorization result
- credential validation result
- capability result
- account created
- profile/account link created
- first snapshot result
- first dashboard render result
- credential revoked/rotated

Never store:

- API key plaintext
- API secret plaintext
- full encrypted payload in general-purpose logs
- request body

## P0 implementation batches

### Batch 1 — infrastructure audit and contracts

No broker calls.

- inspect existing web-auth controller/router
- inspect session/profile ownership
- inspect CSRF/Origin handling
- inspect existing Bitvavo private client
- inspect credential handling, if any
- inspect trading-account creation contracts
- inspect profile/account linkage writer
- inspect account snapshot refresh
- inspect linked-profile dashboard render trigger
- define immutable provisioning contracts
- define migration and encryption-key operational contract
- document exact files and blockers

Safety:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
executor=none
```

### Batch 2 — encrypted storage and repository

No broker calls.

- add migration for credential envelope and provisioning audit/state
- add encryption/decryption service
- add credential repository
- add fingerprint/deduplication
- add rotation/revocation primitives
- tests proving plaintext never enters DB payloads or logs

### Batch 3 — mocked authenticated intake

No real broker calls.

- profile-scoped connection page
- authenticated POST handler
- Origin/CSRF enforcement
- payload limits and rate limits
- server-derived profile identity
- mocked validator
- atomic account/link creation tests
- no production activation

### Batch 4 — real Bitvavo read-only validation

Private broker reads allowed; writes forbidden.

- validate credentials using canonical private-read adapter
- verify capability scope safely
- reject trade permission
- reject withdrawal permission
- no create/cancel order probes
- no order submission

Expected safety:

```text
broker_private_calls>0 only for explicit validation/snapshot
broker_writes=0
order_submission=0
executor=none
```

### Batch 5 — Hugo canary

- Hugo submits a newly created read-only Bitvavo API key
- credential validates
- encrypted credential record created
- read-only trading account created
- active primary profile/account link created
- first snapshot succeeds
- Hugo wallet and Profit Plan render
- Joost/Hugo isolation remains correct
- no trade or withdrawal permission

## Required tests

### Security

- unauthenticated request rejected
- cross-profile request rejected
- invalid Origin/CSRF rejected
- oversized payload rejected
- secrets absent from response
- secrets absent from logs
- secrets absent from exception messages
- secrets absent from `app_profile`
- secrets absent from `app_profile_trading_account_link`
- secrets absent from `trading_account`
- database ciphertext differs from plaintext
- wrong master key fails closed
- tampered ciphertext fails authentication
- key version required
- duplicate fingerprint rejected

### Permission validation

- invalid key rejected
- invalid secret rejected
- read-only key accepted
- trade-enabled key rejected
- withdrawal-enabled key rejected
- unverifiable permissions rejected
- no order create/cancel method called during validation

### Provisioning

- server derives profile and user identity
- account code generated server-side
- double submission creates one account/link
- transaction rollback leaves no partial account/link
- existing active primary link rejects normal provisioning
- successful provisioning creates credential/account/link atomically
- account starts non-live and broker-write-disabled
- failed initial render does not lose valid provisioning
- refresh retry does not require credentials again

### Multi-user

- Hugo can provision only Hugo’s profile
- Joost cannot submit credentials for Hugo through payload manipulation
- Hugo cannot view Joost credential metadata
- neither user can retrieve encrypted or plaintext credentials
- linked-profile discovery includes Hugo only after successful provisioning

## Boundaries

Allowed:

- authenticated credential intake
- private read-only broker validation
- encrypted server-side secret storage
- account and profile-link creation
- private account snapshot refresh
- dashboard render triggering

Forbidden:

- order creation
- order cancellation
- order replacement
- withdrawal
- live trading enablement
- broker-write permission grants
- executor coupling
- credentials in website-registration tables
- credentials in dashboard/reporting models
- credentials in browser storage

## Dependencies with live ladder lane

```text
Joost live canary:
  may continue independently when Joost already has a valid provisioned trading account.

Hugo read-only cockpit:
  blocked on this account_provisioning lane.

Hugo live Fix selected ladder:
  blocked on account_provisioning
  + later explicit trade-credential activation
  + proven live ladder executor path.
```

## Immediate next implementation batch

```text
1. Audit existing auth, account, broker-client, snapshot, and render-trigger infrastructure.
2. Define account_provisioning immutable contracts.
3. Design the encrypted credential migration and external master-key contract.
4. Add tests for server-derived identity and forbidden secret destinations.
5. Stop before any real broker call.
```
