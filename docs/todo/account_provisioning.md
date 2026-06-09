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

## Batch 2 — Authenticated intake + mocked validation  ✅ DONE

Commit: `Add authenticated Bitvavo account provisioning`

- [x] `POST /synth/web-auth/connect-bitvavo` HTTP endpoint in `web_auth_http_v1.py`
- [x] Session identity resolution via `WebsiteRegistrationService.resolve_session_identity`
- [x] `AuthenticatedProfileIdentity` — server-derived, never client-supplied
- [x] Browser-supplied ownership fields silently ignored (profile_code, app_user_id, etc.)
- [x] Mocked Bitvavo credential validation (`MockBitvavoCredentialValidator`)
- [x] `BitvavoCredentialValidator` protocol for future real validator
- [x] Atomic provisioning via `AccountProvisioningService.provision_bitvavo_account`
  - create `trading_account` (paper, enabled=1, live_trading_enabled=0)
  - encrypt + insert `trading_account_credential` (ACTIVE, UNVALIDATED)
  - insert `app_profile_trading_account_link` (primary=1)
  - update `app_profile.onboarding_state` → READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED
  - caller commits / rolls back atomically
- [x] `ACCOUNT_ALREADY_CONNECTED` returns 409 + landing_path, no new rows
- [x] `INVALID_CREDENTIALS` returns 400, no rows created
- [x] `VALIDATION_UNAVAILABLE` returns 503, no rows created
- [x] Origin protection on POST route (inherited from build_wsgi_app)
- [x] Onboarding page updated with Bitvavo connect form
- [x] `SqliteAccountRepository` for test isolation
- [x] `SqliteWebsiteRegistrationRepository.lookup_primary_account_link` updated to query real table
- [x] Tests: `test_account_provisioning_http_v1.py`, `test_account_provisioning_service_v1.py`

Note: `refresh_pending=true` in success response — snapshot/render activation is Batch 4.

Safety: broker_private_calls=0, broker_writes=0, order_submission=0, executor=none

---

## Batch 3 — First snapshot and profile dashboards  ⬜ PENDING

Prerequisites: Batch 2 deployed.

- [ ] Inline first account snapshot attempt after provisioning
- [ ] Profile redirect after successful provisioning (`refresh_pending=true` resolved)
- [ ] Dashboard rendering for newly linked profile
- [ ] Onboarding page unlinked state: show connect form (not 401)
- [ ] Authenticated profile without account link → onboarding state, not 401

---

## Batch 4 — Real Bitvavo private-read validation  ⬜ PARKED

Prerequisites: Batch 2 + broker read permission design reviewed.

- [ ] `_ProvisioningBitvavoClient` subclass bypassing `_require_private_read_permission`
- [ ] Live `get_balance()` call for credential validation
- [ ] Update `validation_state` → `VALID_READ_ONLY` on success
- [ ] Update `validation_state` → `INVALID_CREDENTIALS` on failure

Safety: broker_private_calls=1 (read-only), broker_writes=0, order_submission=0
