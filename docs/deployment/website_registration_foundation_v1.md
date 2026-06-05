# Website Registration Foundation Deployment V1

Current deployment rule:

- existing SYNTH public pages remain reachable exactly as they are
- this foundation adds registration/login/onboarding assets and isolated auth logic only
- no auth gate or access restriction is activated in this batch

New public page outputs:

- `/synth/register.html`
- `/synth/login.html`
- `/synth/verify-result.html`
- `/synth/onboarding.html`

Required environment for later activation:

- `SYNTH_ENV`
- `SYNTH_PROOF_PROVIDER`
- provider-specific proof-of-human secret values
- SMTP host/port/user/password/from address
- `SYNTH_PUBLIC_BASE_URL`
- `SYNTH_DEFAULT_PROFILE_TIMEZONE`

Isolated HTTP service routes:

- `GET /synth/web-auth/healthz`
- `POST /synth/web-auth/register`
- `POST /synth/web-auth/resend-verification`
- `POST /synth/web-auth/verify-email`
- `POST /synth/web-auth/login`
- `POST /synth/web-auth/logout`
- `POST /synth/web-auth/onboarding-status`

Safe current posture:

- render the public registration/login/onboarding pages
- run the isolated auth service only in dev/test or a separately reviewed website layer
- do not change nginx, reverse proxy, or existing dashboard routes
- do not connect registration to `trading_account` or exchange credentials yet

Production follow-up, later:

1. apply `db/migrations/20260605_website_registration_foundation_v1.sql` through `python -m src.web.run_website_registration_db_migration_v1`
2. render `/synth/register.html`, `/synth/login.html`, `/synth/verify-result.html`, `/synth/onboarding.html`
3. deploy the isolated auth service and reverse-proxy only `/synth/web-auth/`
4. validate proof-of-human and SMTP config
5. verify registration/login/onboarding with test profiles
6. separately review any future dashboard access control change
