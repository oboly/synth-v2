# Account Provisioning v1

Canonical documentation for the `src/account_provisioning/` package.

## Scope

Encrypted storage of exchange API credentials, linked to a `trading_account` row.

This batch covers:

- encrypted credential storage (contracts, crypto, repository)
- MariaDB migration for `trading_account_credential`

Not yet in scope:

- HTTP endpoint for credential intake
- Bitvavo API validation (no broker calls)
- `trading_account` creation
- `app_profile_trading_account_link` creation
- account snapshot refresh
- dashboard rendering

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
    contracts_v1.py          — immutable contracts and enums
    credential_crypto_v1.py  — AES-256-GCM encryption, fingerprinting
    credential_repository_v1.py — MariaDB + SQLite(test) repository
```

## Database schema

Table: `trading_account_credential`

Migration: `db/migrations/20260609_trading_account_credential_v1.sql`

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
| `validation_state` | VARCHAR(32) | `UNVALIDATED` / `VALID_READ_ONLY` / `INVALID_CREDENTIALS` |
| `created_ts_utc` | DATETIME | |
| `validated_ts_utc` | DATETIME NULL | |
| `rotated_ts_utc` | DATETIME NULL | |
| `revoked_ts_utc` | DATETIME NULL | |

No plaintext `api_key` or `api_secret` columns exist in the schema.

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

Example (generate once, store in `.env`, never commit):

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
trading_account (disabled/non-live)
  └─ trading_account_credential (ACTIVE, UNVALIDATED)
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

Unique active credential per `(trading_account_id, venue)` is enforced at
application level in `insert_active_credential`. After revocation or
rotation, a new ACTIVE credential may be inserted for the same account+venue.

## Rotation / revocation

- `mark_revoked(trading_account_credential_id, now_utc)` — sets `REVOKED` + timestamp
- `mark_rotated(trading_account_credential_id, now_utc)` — sets `ROTATED` + timestamp

After revocation: call `insert_active_credential` to add the replacement.

Old rows are retained for audit history. `find_by_fingerprint` checks all
statuses — allows detecting a re-submitted duplicate key before inserting.

## Migration deployment

Add to `MIGRATION_CHAIN` in `run_website_registration_db_migration_v1.py`
(already done). Run:

```bash
python -m src.web.run_website_registration_db_migration_v1
```

Migration is idempotent (safe to re-run).

## Next batch

- `POST /synth/web-auth/connect-bitvavo` HTTP endpoint
- Mocked Bitvavo credential validation (no live broker call)
- Atomic `trading_account` + credential + profile link creation
- Onboarding state update to `READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED`
- First account snapshot trigger
- Profile dashboard rendering for linked accounts
