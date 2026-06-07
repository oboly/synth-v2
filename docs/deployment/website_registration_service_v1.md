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

## systemd ExecStart Fix (status=203/EXEC)

**Root cause:** `scripts/odroid/run_website_registration_service_once.sh` has git mode `100644`
(intentionally not executable). systemd invokes `ExecStart=` directly via `execve(2)`.
Without the executable bit set, `execve` returns `EACCES` and systemd reports `status=203/EXEC`.

**Canonical fix:** invoke bash explicitly so the file mode is irrelevant:

```ini
ExecStart=/usr/bin/bash /home/theone/projects/synth-v2/scripts/odroid/run_website_registration_service_once.sh
```

This is the canonical unit in `scripts/odroid/systemd/synth-website-registration.service`.
Do not change the wrapper script's git mode — the explicit bash invocation is sufficient.

**Removing the temporary drop-in** (if one was applied via `systemctl edit`):

```bash
# Remove override
sudo rm -rf /etc/systemd/system/synth-website-registration.service.d/   # system unit
# or for user unit:
rm -rf ~/.config/systemd/user/synth-website-registration.service.d/

# Deploy canonical unit
install -m 0644 scripts/odroid/systemd/synth-website-registration.service \
    ~/.config/systemd/user/

# Reload and restart
systemctl --user daemon-reload
systemctl --user restart synth-website-registration.service

# Verify
systemctl --user status synth-website-registration.service
curl -fsS http://127.0.0.1:8786/synth/web-auth/healthz
```

Expected after fix: `active (running)`, healthz returns `{"ok": true}`, port 8786 listening.

## Migration Chain

Migrations must be applied in order. All are idempotent (safe to re-run):

1. `db/migrations/20260605_website_registration_foundation_v1.sql`
2. `db/migrations/20260607_profile_session_authorization_v1.sql`
3. `db/migrations/20260607_app_profile_trading_account_link_v1.sql`

The canonical runner applies all migrations automatically:

```bash
python -m src.web.run_website_registration_db_migration_v1 --output summary
```

## Explicit Profile/Account Linkage

Profile-to-trading-account mapping is stored in `app_profile_trading_account_link`.
No credentials are stored there. No broker calls. DB link write only.

**Link Joost to his read-only Bitvavo account:**

```bash
python -m src.account.run_app_profile_trading_account_link_v1 \
    --profile joost \
    --venue bitvavo \
    --account-code bitvavo_joost_read \
    --set-primary \
    --output summary
```

This is idempotent — safe to re-run.

**Hugo remains unlinked** until a future account provisioning step. Hugo's login lands on `/synth/onboarding.html` with `account_connection_state=NO_EXCHANGE_ACCOUNT_CONNECTED`.

## Login Landing Contract

After login, the server returns `landing_path` and `account_connection_state`:

| Profile state | landing_path | account_connection_state |
|---|---|---|
| No active primary link | `/synth/onboarding.html` | `NO_EXCHANGE_ACCOUNT_CONNECTED` |
| Active primary link | `/synth/accounts/<profile>/` | `READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED` |
| Ambiguous links | `/synth/onboarding.html` | `NO_EXCHANGE_ACCOUNT_CONNECTED` |

The browser validates `landing_path.startsWith("/synth/")` before navigation. Never constructs the account URL from profile_code alone.

## Profile Home Page

Generate Joost's account home after linking:

```bash
python -m src.reporting.account_dashboard_profile_access_v1  # (no runner yet — use wallet runner which resolves linkage)
```

Or via the wallet dashboard runner (which also writes `index.html` indirectly via the full render pipeline):

The profile home (`/var/www/html/synth/accounts/joost/index.html`) is generated by `src/reporting/account_profile_home_v1.py`. Wire this into the Joost account render pipeline so timers keep it current.

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

Use the canonical fail-closed installer. It is idempotent and rolls back automatically on any error.

**Activate (always-tests only):**

```bash
bash scripts/odroid/activate_nginx_transition_dual_auth_v1.sh
```

**Activate with authenticated acceptance tests:**

```bash
bash scripts/odroid/activate_nginx_transition_dual_auth_v1.sh --basic-user theone
```

The script:
1. Guards: refuses to run unless `hostname=odroid` and `user=theone`
2. Pre-flight: checks web-auth health, active site file, enabled symlink, htpasswd, TLS certs
3. Generates the full nginx config via single-quoted heredoc (no bash variable expansion into nginx)
4. Creates a timestamped backup: `${ACTIVE_SITE}.backup.${TIMESTAMP}`
5. Installs candidate, runs `sudo nginx -t`, reloads
6. On any error: trap restores backup and reloads nginx before exit
7. Runs `verify_nginx_transition_dual_auth_v1.sh` for acceptance

**sudo usage in pre-flight:** `/etc/nginx/.synth_htpasswd` and Let's Encrypt live/archive dirs
(`/etc/letsencrypt/live/…`) are not traversable or readable by user `theone`. nginx reads them
as root. The installer uses `sudo test -f` to check existence only — no certificate or key
contents are printed, hashed, or logged.

**Verify only (read-only, safe to run at any time):**

```bash
# Always tests (no credentials required)
bash scripts/odroid/verify_nginx_transition_dual_auth_v1.sh

# With authenticated acceptance tests
bash scripts/odroid/verify_nginx_transition_dual_auth_v1.sh --basic-user theone
```

**Rollback** (if acceptance fails after activation):

```bash
# Restore from timestamped backup printed by activation script:
sudo cp /etc/nginx/sites-available/synth.backup.<TIMESTAMP> /etc/nginx/sites-available/synth
sudo nginx -t && sudo nginx -s reload
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
