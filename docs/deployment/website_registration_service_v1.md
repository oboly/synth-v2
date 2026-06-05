# Website Registration Service V1

Purpose:

- activate the isolated SYNTH website registration service on Odroid
- keep existing dashboard URLs public and unchanged
- keep registration/profile onboarding separate from `trading_account`

Service boundary:

- service routes only under `/synth/web-auth/`
- static public pages remain rendered under `/var/www/html/synth/`
- no auth gate is added around `/synth/accounts/<profile>/...` in this batch

Odroid service files:

- runner: `scripts/odroid/run_website_registration_service_once.sh`
- migration runner: `scripts/odroid/run_website_registration_db_migration_once.sh`
- systemd unit template: `scripts/odroid/systemd/synth-website-registration.service`

Required environment:

- `SYNTH_ENV=production`
- `SYNTH_PUBLIC_BASE_URL=https://<your public host>`
- `SYNTH_DEFAULT_PROFILE_TIMEZONE=Europe/Amsterdam`
- `SYNTH_PROOF_PROVIDER=turnstile`
- `SYNTH_TURNSTILE_SECRET=<provider secret>`
- `SYNTH_SMTP_HOST=<smtp host>`
- `SYNTH_SMTP_PORT=587`
- `SYNTH_SMTP_USER=<smtp username>`
- `SYNTH_SMTP_PASSWORD=<smtp password>`
- `SYNTH_SMTP_FROM=<from address>`
- optional: `SYNTH_WEB_AUTH_HOST=127.0.0.1`
- optional: `SYNTH_WEB_AUTH_PORT=8786`
- optional: `SYNTH_WEB_AUTH_DATABASE=mariadb`

Fail-closed rules:

- production refuses the mock proof-of-human provider
- production refuses missing SMTP configuration
- health endpoint exposes no secrets, token values, or user data
- no broker or `trading_account` access is used

Reverse-proxy template:

```nginx
location /synth/web-auth/ {
    proxy_pass http://127.0.0.1:8786;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Safe production activation order:

1. Render the public auth pages:
   `python -m src.web.run_website_registration_pages_v1 --output-root /var/www/html/synth --output summary`
2. Review production env file outside the repository.
3. Apply the registration migration:
   `python -m src.web.run_website_registration_db_migration_v1 --output summary`
4. Install the user service:
   `install -m 0644 scripts/odroid/systemd/synth-website-registration.service ~/.config/systemd/user/`
5. Reload the user daemon:
   `systemctl --user daemon-reload`
6. Start the service:
   `systemctl --user start synth-website-registration.service`
7. Verify health:
   `curl -fsS http://127.0.0.1:8786/synth/web-auth/healthz`
8. Add the reverse-proxy route for `/synth/web-auth/` only.
9. Validate test registration and onboarding without touching `trading_account` data.

Explicit non-goals:

- no change to dashboard public accessibility
- no exchange credential onboarding
- no `trading_account` creation
- no broker calls or writes
