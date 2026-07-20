# Account Provisioning v1

Canonical documentation for the `src/account_provisioning/` package.

## Scope

Encrypted Bitvavo credential storage, authenticated account provisioning, and
non-secret account-to-credential binding metadata.

Canonical binding contract:

```text
docs/architecture/account_credential_binding_contract_v1.md
```

PR A boundary: schema/contract only. It does not change private API runtime
behavior or production credential resolution.

## Safety boundary

```
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

No live trading. No broker calls. No order logic.

## Package structure

```
src/account_provisioning/
    __init__.py
    contracts_v1.py                  — immutable contracts and enums
    credential_crypto_v1.py          — AES-256-GCM encryption, fingerprinting
    credential_repository_v1.py      — MariaDB + SQLite(test) encrypted credential repo
    credential_binding_contract_v1.py — pure non-secret binding validators
    credential_validator_v1.py       — BitvavoCredentialValidator protocol + MockBitvavoCredentialValidator
    account_repository_v1.py         — trading_account + profile link repo (MariaDB + SQLite)
    account_provisioning_service_v1.py — orchestration: validate → create account → store credential → link
```

## Database schema

Table: `trading_account_credential`

Base migration: `db/migrations/20260609_trading_account_credential_v1.sql`

Binding metadata migration:
`db/migrations/20260721_account_credential_binding_contract_v1.sql`

Key columns:

| Column | Type | Notes |
|---|---|---|
| `trading_account_credential_id` | BIGINT UNSIGNED PK | |
| `trading_account_id` | BIGINT UNSIGNED FK | FK to `trading_account` |
| `venue` | VARCHAR(32) | e.g. `bitvavo` |
| `credential_kind` | VARCHAR(32) | `API_KEY_SECRET` |
| `encrypted_envelope` | MEDIUMTEXT | JSON — no plaintext credentials |
| `encryption_algorithm` | VARCHAR(32) | `AESGCM-256` |
| `key_version` | VARCHAR(16) | e.g. `v1` |
| `credential_fingerprint` | CHAR(64) | HMAC-SHA256 hex — no plaintext |
| `credential_status` | VARCHAR(16) | `ACTIVE` / `REVOKED` / `ROTATED` / `INVALID` |
| `credential_source` | VARCHAR(32) | `db_encrypted` / `legacy_profile_env_deprecated` |
| `permission_scope` | VARCHAR(32) | `READ_ONLY_PRIVATE` / `TRADE_EXECUTION` |
| `allowed_private_read` | TINYINT(1) | non-secret capability metadata |
| `allowed_order_write` | TINYINT(1) | false for `READ_ONLY_PRIVATE` |
| `allowed_withdrawal` | TINYINT(1) | must remain false |
| `validation_state` | VARCHAR(32) | `UNVALIDATED` / `VALID_READ_ONLY` / `VALID_PRIVATE_READ` / `INVALID_CREDENTIALS` |
| `created_ts_utc` | DATETIME | |
| `validated_ts_utc` | DATETIME NULL | |
| `last_validation_error_code` | VARCHAR(64) NULL | safe non-secret error code |
| `rotated_ts_utc` | DATETIME NULL | |
| `revoked_ts_utc` | DATETIME NULL | |

No plaintext `api_key` or `api_secret` columns exist in the schema.

The active binding invariant is:

```text
trading_account_id + venue + permission_scope
-> exactly one ACTIVE credential profile
```

Historical `REVOKED`, `ROTATED`, and `INVALID` rows are retained.

## Encrypted envelope format

One AES-256-GCM authenticated envelope per credential row containing:

```json
{
  "alg": "AESGCM-256",
  "kv":  "v1",
  "sv":  "1",
  "venue": "bitvavo",
  "tid": 42,
  "nonce": "<base64url-12-bytes>",
  "ct":    "<base64url-ciphertext+auth-tag>"
}
```

The ciphertext decrypts to:

```json
{"api_key": "...", "api_secret": "..."}
```

Authenticated additional data (AAD) binds the ciphertext to:

```
synth-credential-aad-v1\n{venue}\n{trading_account_id}
```

Changing `trading_account_id` or `venue` makes decryption fail.

## Master key setup

Environment variable: `SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY`

Format: `v1:<base64url-encoded-32-byte-key>`

Example generator for an operator to run once and store in a host-local
EnvironmentFile outside the repository:

```python
import os, base64
print("v1:" + base64.urlsafe_b64encode(os.urandom(32)).decode())
```

Rules:

- exactly 32 decoded bytes for AES-256-GCM
- missing or malformed value raises `ValueError` (fail closed)
- no generated fallback in production
- never logged, never committed to git

## Fingerprint

Stored in `credential_fingerprint` (CHAR(64) hex).

Algorithm: HMAC-SHA256 under a domain-separated key derived from the master key.

```
fingerprint_key = HMAC-SHA256(master_key_bytes, b"synth-fingerprint-key-v1")
fingerprint     = HMAC-SHA256(fingerprint_key, f"{venue}\n{api_key}".encode())
```

- deterministic: same venue + api_key → same fingerprint
- does not include the api_secret
- cannot be reversed without the master key
- used for deduplication before provisioning

## Ownership model

```
trading_account (enabled, non-live by default)
  └─ trading_account_credential (ACTIVE, scoped, non-secret metadata)
       ↑ FK to trading_account
       └─ provisioning service creates atomically with profile link
```

The provisioning flow (next batch) creates `trading_account` first,
then inserts `trading_account_credential` + `app_profile_trading_account_link`
in one transaction. No orphan credentials.

## Transaction model

`CredentialRepository` and `SqliteCredentialRepository` take a caller-owned
connection. Repository methods do not commit or rollback. The provisioning
service is responsible for transaction boundaries.

This allows the full provisioning sequence (trading_account + credential +
profile link) to commit or rollback atomically.

## Credential status lifecycle

```
ACTIVE      → REVOKED  (explicit revocation)
ACTIVE      → ROTATED  (replaced by a newer credential)
ACTIVE      → INVALID  (validation failure on existing credential)
```

Unique active credential per `(trading_account_id, venue, permission_scope)` is
the canonical invariant. The binding metadata migration adds a generated active
scope column and unique index for this invariant. Repository validators also
fail closed on missing or ambiguous active bindings.

## Rotation / revocation

- `mark_revoked(trading_account_credential_id, now_utc)` — sets `REVOKED` + timestamp
- `mark_rotated(trading_account_credential_id, now_utc)` — sets `ROTATED` + timestamp

After revocation: call `insert_active_credential` to add the replacement.

Old rows are retained for audit history. `find_by_fingerprint` checks all
statuses — allows detecting a re-submitted duplicate key before inserting.

## Migration deployment

Migration chain includes the base credential migrations and the binding metadata
migration. Run only from an authorized environment:

```bash
python -m src.web.run_website_registration_db_migration_v1
```

Migration is idempotent (safe to re-run).

Precondition: before binding metadata exists, each `(trading_account_id, venue)`
must have at most one `ACTIVE` credential. If duplicate active credentials exist,
the migration aborts before adding or defaulting binding columns with:

```text
ACCOUNT_CREDENTIAL_BINDING_DUPLICATE_ACTIVE_PRECONDITION_FAILED
```

Duplicate active credentials require explicit operator review. The migration
does not choose one credential, revoke credentials, change statuses, assign
different scopes, or delete rows automatically.

## HTTP endpoint (Batch 2)

```
POST /synth/web-auth/connect-bitvavo
```

Request body:
```json
{"api_key": "...", "api_secret": "...", "withdrawal_disabled_confirmed": true}
```

Server derives identity from session cookie. Browser-supplied ownership fields are ignored.

Success response:
```json
{
  "ok": true,
  "profile_code": "hugo",
  "account_connection_state": "READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED",
  "landing_path": "/synth/accounts/hugo/profit-plan.html",
  "refresh_pending": true
}
```

`refresh_pending=true` is expected in Batches 2 and 3 until snapshot/render activation is wired.

## Session identity contract

`WebsiteRegistrationService.resolve_session_identity(session_token)` returns
`{app_user_id, app_profile_id, profile_code}` server-side. The HTTP handler converts
this to `AuthenticatedProfileIdentity`. Provisioning service receives only this identity —
never raw browser-supplied profile or user IDs.

## Provisioning flow

```
POST /synth/web-auth/connect-bitvavo
  → resolve_session_identity → AuthenticatedProfileIdentity
  → AccountProvisioningService.provision_bitvavo_account
      1. check existing primary link
      2. MockBitvavoCredentialValidator.validate (Batch 2)
      3. create trading_account (paper, enabled, not live)
      4. encrypt + store credential
      5. create primary profile link
      6. update onboarding state
  → HTTP handler commits on ok=True, rolls back on ok=False
```

## Batch 3 (complete)

### Transaction ownership

`AccountProvisioningService` owns the full transaction boundary:
- Takes `conn_factory`, `account_repo_factory`, `cred_repo_factory`
- Commits on success, rolls back on failure or exception
- HTTP handler and runner never call commit/rollback

### Real Bitvavo validator

`RealBitvavoCredentialValidator` in `bitvavo_credential_validator_v1.py`:
- Calls `get_balance()` then `get_open_orders()` — both required
- Uses `BitvavoClient(api_key=..., api_secret=...)` — explicit credentials only
- Never falls back to global env vars (`BITVAVO_API_KEY`, `BITVAVO_API_SECRET`)
- Requires `SYNTH_BROKER_PRIVATE_READ_PERMISSION=I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA`
- balance 401/403 → `INVALID_CREDENTIALS_OR_READ_PERMISSION`
- balance ok, open-orders 401/403 → `TRADE_PERMISSION_REQUIRED`
- network/server failure → `VALIDATION_UNAVAILABLE`
- both succeed → `VALID_PRIVATE_READ`, capabilities `["read_balance", "read_orders"]`

Required Bitvavo API key permissions: Read ON · Trade ON · Withdraw OFF.
Trade permission on the key does not enable trading in Synth.
Synth live_trading_enabled and broker_write_permission remain disabled separately.

### Account credential loader

`account_credential_loader_v1.load_account_credential(conn, trading_account_id, venue, master_key_bytes, cred_repo_factory)`:
- Returns `PlainBitvavoCredential` for the given account
- Raises `ValueError(NO_ACTIVE_CREDENTIAL)` if none found
- Never falls back to global env vars — Hugo always uses Hugo's stored credential

### Account credential binding contract

`credential_binding_contract_v1.validate_credential_binding(...)`:
- validates non-secret rows only
- requires exact `trading_account_id + venue + required_permission_scope`
- rejects missing, ambiguous, disabled, unvalidated, or scope-mismatched bindings
- rejects withdrawal capability and read-only credentials with order-write capability
- rejects global/repository `.env` fallback requirements
- exposes only non-secret report fields

### Account snapshot service

`account_snapshot_service_v1.take_first_snapshot(conn, trading_account_id, venue, bitvavo_client, now_utc)`:
- Calls `get_balance()` then `get_open_orders()` — both required
- Writes to both `trading_account_balance_snapshot` and `broker_order_snapshot`
- Failure of either fetch returns `ok=False` without writing any rows
- Returns `SnapshotResult(ok, error_code, balance_row_count, order_row_count)`

### Production runner wiring (complete)

`src/account_provisioning/connect_bitvavo_v1.build_connect_bitvavo(...)` builds the callable:
- Provision account (transaction) → load stored credential → take snapshot → render wallet
- `refresh_pending=False` only when all three activation steps succeed
- On post-commit failure: `refresh_pending=True` + `refresh_error_code`
- Safe retry: `ACCOUNT_ALREADY_CONNECTED` retries snapshot + render without resubmitting credentials

Wired in `run_web_auth_service_v1.py` (`--database mariadb` mode only):
- `RealBitvavoCredentialValidator` — never the mock
- Dependencies constructed once at startup
- `--output-root` controls where rendered dashboards are written
