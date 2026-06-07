# Website Registration Service V1

Purpose:

- activate the isolated SYNTH website registration service on Odroid
- keep existing dashboard URLs public and unchanged
- keep registration/profile onboarding separate from `trading_account`

## Current Test Phase

**Phase: Basic Auth + Application Auth**

- All `/synth/*` routes require HTTP Basic Auth (unchanged from production).
- `/synth/accounts/<profile>/` and `/synth/onboarding.html` additionally require a valid application session.
- Home, Register, Login, and Verify pages are **not** public yet — Basic Auth still required.
- Removing Basic Auth is a future step, only after full acceptance test sign-off.

## Service Boundary

- service routes only under `/synth/web-auth/`
- static public pages remain rendered under `/var/www/html/synth/`
- profile-scoped dashboard pages under `/synth/accounts/<profile>/`

## Odroid Service Files

- runner: `scripts/odroid/run_website_registration_service_once.sh`
- migration runner: `scripts/odroid/run_website_registration_db_migration_once.sh`
- systemd unit template: `scripts/odroid/systemd/synth-website-registration.service`

## Required Environment

Production env file: `/home/theone/.config/synth/web-auth.env` (not in git)

```
SYNTH_ENV=production
SYNTH_PUBLIC_BASE_URL=https://gurk11.duckdns.org
SYNTH_DEFAULT_PROFILE_TIMEZONE=Europe/Amsterdam
SYNTH_PROOF_PROVIDER=turnstile
SYNTH_TURNSTILE_SECRET=<private server key — never in HTML/logs/URLs>
SYNTH_SMTP_HOST=<smtp host>
SYNTH_SMTP_PORT=587
SYNTH_SMTP_USER=<smtp username>
SYNTH_SMTP_PASSWORD=<smtp password>
SYNTH_SMTP_FROM=<from address>
SYNTH_IP_HASH_PEPPER=<random string, minimum 32 characters>
```

Optional overrides (default values shown):

```
SYNTH_WEB_AUTH_HOST=127.0.0.1
SYNTH_WEB_AUTH_PORT=8786
SYNTH_WEB_AUTH_DATABASE=mariadb
```

## Turnstile Key Separation

| Key | Variable | Where used | Security |
|---|---|---|---|
| Site key | `SYNTH_TURNSTILE_SITE_KEY` | Browser HTML (`data-sitekey`) | **Public** — safe to embed in HTML |
| Secret key | `SYNTH_TURNSTILE_SECRET` | Server-side token verification only | **Private** — never in HTML, JSON, URL, log, or browser storage |

The Cloudflare Turnstile widget sends a `cf-turnstile-response` token to the browser.
The JS reads it via the `synthTurnstileSuccess` callback and passes it as `proof_response` in the JSON POST body.
The server validates `proof_response` against the Turnstile verify API using `SYNTH_TURNSTILE_SECRET`.
`SYNTH_TURNSTILE_SECRET` is never sent to or rendered in the browser.

**Hostname note:** Turnstile site keys are bound to a hostname. `gurk11.duckdns.org` must be registered
in the Cloudflare Turnstile dashboard as the allowed hostname.

**Key rotation:** To rotate the site key, update `SYNTH_TURNSTILE_SITE_KEY` and re-render the registration
page. To rotate the secret key, update `SYNTH_TURNSTILE_SECRET` and restart the auth service.
Both can be rotated independently without data loss.

## Production Pepper Requirement

`SYNTH_IP_HASH_PEPPER` is required in production. Minimum 32 characters.
Used for HMAC-SHA256 IP hashing in login rate limiting. Never logged or returned in responses.

## Fail-Closed Rules

- production refuses the mock proof-of-human provider
- production refuses missing SMTP configuration
- production requires a valid `SYNTH_PUBLIC_BASE_URL` (must be HTTPS, no path/query/fragment/userinfo)
- production requires `SYNTH_IP_HASH_PEPPER` of minimum 32 chars
- production page render fails if `SYNTH_TURNSTILE_SITE_KEY` is not set
- CSRF: production enforces `Origin` header matching `SYNTH_PUBLIC_BASE_URL` for all POST routes
- health endpoint exposes no secrets, token values, or user data
- no broker or `trading_account` access is used

## Migration Chain

Migrations must be applied in order. Both are idempotent (safe to re-run):

1. `db/migrations/20260605_website_registration_foundation_v1.sql`
2. `db/migrations/20260607_profile_session_authorization_v1.sql`

The canonical runner applies both automatically:

```bash
python -m src.web.run_website_registration_db_migration_v1 --output summary
```

## Registration Page Render Command

Render the static auth pages with the public site key. The secret key must not appear in this command.

```bash
SYNTH_TURNSTILE_SITE_KEY="$(grep SYNTH_TURNSTILE_SITE_KEY /home/theone/.config/synth/web-auth.env | cut -d= -f2-)" \
  python -m src.web.run_website_registration_pages_v1 \
    --output-root /var/www/html/synth \
    --turnstile-site-key "$SYNTH_TURNSTILE_SITE_KEY" \
    --output summary
```

Or pass the site key directly (it is public):

```bash
python -m src.web.run_website_registration_pages_v1 \
  --output-root /var/www/html/synth \
  --turnstile-site-key 0x4AAAAAAA... \
  --output summary
```

**Secret leakage check** (run after render):

```bash
grep -i "turnstile_secret\|SYNTH_TURNSTILE_SECRET" /var/www/html/synth/register.html && echo "LEAK DETECTED" || echo "ok"
```

The normal dashboard render timers (`run_mvp_dashboard_render_once.sh` etc.) do not touch
`register.html` — they write account and market pages under `/var/www/html/synth/accounts/`.

## systemd Install / Start / Health

```bash
# Install the user service unit
install -m 0644 scripts/odroid/systemd/synth-website-registration.service \
    ~/.config/systemd/user/

# Reload user daemon
systemctl --user daemon-reload

# Start service
systemctl --user start synth-website-registration.service

# Enable at login
systemctl --user enable synth-website-registration.service

# Verify health
curl -fsS http://127.0.0.1:8786/synth/web-auth/healthz
```

## nginx Activation (Transitional Phase)

```bash
# Test new config
nginx -t

# Reload without downtime
nginx -s reload
```

**Rollback** (if application auth fails):

```bash
# Revert nginx to previous config, then:
sudo nginx -s reload
# No data loss: registration, sessions, profiles preserved.
```

## Joost/Hugo Cross-Profile Acceptance Matrix

Test phase must verify all cells before removing Basic Auth:

| Session | Route | Expected |
|---|---|---|
| No app cookie | `/synth/` (home) | 200 (Basic Auth only) |
| No app cookie | `/synth/login.html` | 200 (Basic Auth only) |
| No app cookie | `/synth/register.html` | 200 (Basic Auth only) |
| No app cookie | `/synth/onboarding.html` | 401 (no app session) |
| No app cookie | `/synth/accounts/joost/` | 401 (no app session) |
| No app cookie | `/synth/accounts/hugo/` | 401 (no app session) |
| Joost session | `/synth/accounts/joost/` | 200 |
| Joost session | `/synth/accounts/hugo/` | 403 (forbidden) |
| Hugo session | `/synth/accounts/hugo/` | 200 |
| Hugo session | `/synth/accounts/joost/` | 403 (forbidden) |
| Expired session | `/synth/accounts/joost/` | 401 (session expired) |
| Logged out | `/synth/accounts/joost/` | 401 (session revoked) |

## Security: No Credentials in Transit

- Session token: cookie only (`HttpOnly; Secure; SameSite=Lax; Path=/synth`)
- No credentials in HTML, JSON response, URL, log, or browser storage
- `check-access` endpoint: internal nginx only, never publicly callable
- `X-Synth-Requested-Profile` set by nginx from URI regex capture, never from client

## Safety Markers

```
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```
