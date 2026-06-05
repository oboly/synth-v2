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

Safe current posture:

- render the public registration/login/onboarding pages
- run the isolated auth service only in dev/test or a separately reviewed website layer
- do not change nginx, reverse proxy, or existing dashboard routes
- do not connect registration to `trading_account` or exchange credentials yet

Production follow-up, later:

1. deploy the isolated auth service
2. validate proof-of-human and SMTP config
3. verify registration/login/onboarding with test profiles
4. separately review any future dashboard access control change
