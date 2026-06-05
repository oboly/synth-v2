# Website Registration Foundation V1

Purpose:

- create a minimal isolated website-profile registration foundation
- keep trading/runtime/dashboard architecture unchanged
- prepare later exchange-account onboarding without creating trading accounts

Canonical separation:

```text
app user/profile != trading_account
credential != trading_account
registration != exchange onboarding
reporting/dashboards read DB snapshots only
```

Current scope:

- public registration and login pages can exist
- existing public dashboard URLs remain unchanged
- no nginx or reverse-proxy auth changes
- no gating of `/synth/accounts/<profile>/...` in this batch
- isolated POST routes live under `/synth/web-auth/`
- public HTML shells remain static pages rendered under `/var/www/html/synth/`

Registration flow:

1. submit `email`, `alias/profile code`, `password`, `proof-of-human response`
2. validate proof-of-human through an isolated provider adapter
3. reserve unique normalized email and profile code
4. hash password with `scrypt`
5. create `app_user`, `app_profile`, `app_user_profile_access`
6. create a single-use hashed email verification token
7. send verification link through a mailer adapter
8. activate the profile only after verification
9. login creates a hashed server-side session
10. onboarding shows `NO_EXCHANGE_ACCOUNT_CONNECTED`
11. resend verification is rate-limited and must not leak whether an email/profile exists

Data model:

- `app_user`
- `app_profile`
- `app_user_profile_access`
- `email_verification_token`
- `web_session`

Security rules:

- password hashes only; no plaintext password storage
- verification/session tokens are stored only as hashes
- token values must not be logged
- proof-of-human fails closed when production config is absent
- SMTP/proof-provider secrets come from environment only
- production must not run the mock proof-of-human provider
- health endpoints must expose no secrets, tokens, or user data

Explicit non-goals in this batch:

- no `trading_account` creation
- no exchange credential upload or storage
- no broker calls or writes
- no decision/execution changes
- no public dashboard URL changes
