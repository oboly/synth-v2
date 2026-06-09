# Account Provisioning TODO

Canonical status tracker for the account provisioning lane.

Canonical design doc: `docs/ops/account_provisioning_v1.md`
Branch: `feature/account-provisioning-bitvavo-v1`

---

## Batch 1 — Encrypted credential storage  ✅ DONE

Commit: `Add encrypted Bitvavo credential storage`

- [x] `cryptography` dependency added to `requirements.txt`
- [x] Migration `db/migrations/20260609_trading_account_credential_v1.sql`
- [x] `src/account_provisioning/__init__.py`
- [x] `src/account_provisioning/contracts_v1.py` — PlainBitvavoCredential, EncryptedCredentialEnvelope, StoredAccountCredential, enums
- [x] `src/account_provisioning/credential_crypto_v1.py` — AESGCM-256 encrypt/decrypt, HMAC fingerprint, master key parse/load
- [x] `src/account_provisioning/credential_repository_v1.py` — MariaDB + SQLite(test) repository
- [x] `tests/test_account_provisioning_credential_crypto_v1.py`
- [x] `tests/test_account_provisioning_credential_repository_v1.py`
- [x] Migration added to `MIGRATION_CHAIN`
- [x] `docs/ops/account_provisioning_v1.md`

Safety: broker_private_calls=0, broker_writes=0, order_submission=0, executor=none

---

## Batch 2 — Authenticated intake + mocked validation  ⬜ PENDING

Prerequisites: Batch 1 deployed.

- [ ] `POST /synth/web-auth/connect-bitvavo` HTTP endpoint in `web_auth_http_v1.py`
- [ ] Session auth: `check_access` on the POST route — profile ownership check
- [ ] Mocked Bitvavo credential validation (no live broker call in this batch)
- [ ] Atomic provisioning transaction:
  - create `trading_account` (enabled=1, live_trading_enabled=0)
  - insert `trading_account_credential` (ACTIVE, UNVALIDATED)
  - insert `app_profile_trading_account_link` (primary=1)
  - commit atomically
- [ ] Duplicate credential detection via fingerprint
- [ ] Onboarding state update: `NO_EXCHANGE_ACCOUNT_CONNECTED` → `READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED`
- [ ] CSRF / Origin protection on the POST route
- [ ] Tests: cross-profile blocked, duplicate rejected, rollback on failure

Safety: broker_private_calls=0, broker_writes=0, order_submission=0, executor=none

---

## Batch 3 — First snapshot and profile dashboards  ⬜ PENDING

Prerequisites: Batch 2 complete.

- [ ] Inline first account snapshot attempt after provisioning
- [ ] Profile redirect after successful provisioning
- [ ] Dashboard rendering for newly linked profile
- [ ] Onboarding page unlinked state: show connect form (not 401)
- [ ] Authenticated profile without account link → onboarding state, not 401

---

## Batch 4 — Real Bitvavo validation  ⬜ PARKED

Prerequisites: Batch 2 + broker read permission design reviewed.

- [ ] `_ProvisioningBitvavoClient` subclass bypassing `_require_private_read_permission`
- [ ] Live `get_balance()` call for credential validation
- [ ] Update `validation_state` → `VALID_READ_ONLY` on success
- [ ] Update `validation_state` → `INVALID_CREDENTIALS` on failure

Safety: broker_private_calls=1 (read-only), broker_writes=0, order_submission=0
