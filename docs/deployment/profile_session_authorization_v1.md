# Profile Session Authorization v1

Canonical documentation for SYNTH profile-scoped website session authorization.

## Route Matrix

### Public (no auth required)

`/synth/index.html` and `/synth/about.html` are strictly account-agnostic.
They contain no `/synth/accounts/<profile>/` hrefs and are rendered without
any linked-profile or account discovery. See `docs/ops/synth_mvp_readonly_cockpit_v1.md`.

| Route | Handler |
|---|---|
| `GET /synth/` | Static (Hugo) |
| `GET /synth/about.html` | Static |
| `GET /synth/register.html` | Static |
| `GET /synth/login.html` | Static |
| `GET /synth/verify-result.html` | Static |
| `GET /synth/assets/*` | Static |
| `POST /synth/web-auth/register` | Auth service |
| `POST /synth/web-auth/verify-email` | Auth service |
| `POST /synth/web-auth/resend-verification` | Auth service |
| `POST /synth/web-auth/login` | Auth service |
| `POST /synth/web-auth/logout` | Auth service |
| `GET /synth/web-auth/healthz` | Auth service |

### Protected (session required)

| Route | Profile check |
|---|---|
| `GET /synth/onboarding.html` | Any valid session (profile resolved server-side from session) |
| `GET /synth/api-account-connect.html` | Any valid session (future milestone) |
| `GET /synth/accounts/<profile>/` | Session owner must match `<profile>` |
| `GET /synth/accounts/<profile>/wallet.html` | Session owner must match `<profile>` |
| `GET /synth/accounts/<profile>/profit-plan.html` | Session owner must match `<profile>` |
| `GET /synth/accounts/<profile>/open-orders-monitor.html` | Session owner must match `<profile>` |

### Internal (nginx auth_request only)

| Route | Description |
|---|---|
| `GET /synth/web-auth/check-access` | nginx auth subrequest — not accessible from public |

## Session Lifecycle

```
login
  → invalidate all existing sessions for user (session rotation)
  → create new session
      session_hash = SHA-256(random 32-byte token)
      expires_ts_utc = now + 14 days (absolute expiry)
      idle_expires_ts_utc = now + 7 days (idle expiry)
  → set cookie:
      name=synth_web_session
      value=<raw token>
      Path=/synth
      HttpOnly; Secure; SameSite=Lax
      Max-Age=<session_ttl seconds>

protected request
  → nginx matches route
  → nginx auth_request → /synth/web-auth/check-access (internal)
      validate session hash
      check invalidated_ts_utc IS NULL
      check expires_ts_utc > now (absolute expiry)
      check idle_expires_ts_utc > now (idle expiry)
      check user.status = ACTIVE
      check profile ownership (when profile slug in URI)
      update last_seen_ts_utc
      extend idle_expires_ts_utc = now + 7 days
  → 200: nginx serves static file
  → 401: redirect to /synth/login.html?reason=unauthorized
  → 403: redirect to /synth/login.html?reason=forbidden

logout
  → POST /synth/web-auth/logout
  → invalidated_ts_utc = now set on session
  → clear cookie (Max-Age=0)
```

## Onboarding Status Endpoint

`POST /synth/web-auth/onboarding-status` is session-owned:

- **Empty `requested_profile_code`** (or omitted): success using the session row's `profile_code`. The frontend sends an empty body — no URL parameter or storage lookup required.
- **Explicit matching `requested_profile_code`**: success (backward-compatible with existing callers).
- **Explicit mismatched `requested_profile_code`**: `403 FORBIDDEN`.
- **Invalid or missing session**: `401 UNAUTHORIZED`.

The frontend must not read a `?profile=` query parameter or localStorage to populate `requested_profile_code`. The server returns `profile_code` in the success response; the frontend uses that value for display only.

## Ownership Model

```
app_user (email, password_hash, status)
  └─ app_user_profile_access (access_role=OWNER)
       └─ app_profile (profile_code, onboarding_state)
```

- One email → one `app_user`.
- One profile code → one `app_profile`.
- Ownership is stored in `app_user_profile_access`.
- A session is bound to both `app_user_id` and `app_profile_id`.
- Authorization: `session.profile_code == requested_profile_code`.
- Authorization is never derived from URL alone, Basic Auth username, display name, or client-provided header.

## nginx auth_request Flow

```
nginx receives GET /synth/accounts/joost/wallet.html
  set $synth_profile_slug = "joost"   (from regex capture — not from client)
  auth_request @synth_check_access
    → internal subrequest to auth service
    → proxy_set_header X-Synth-Requested-Profile "joost"   (overwritten by nginx)
    → auth service reads session cookie, validates ownership
    → returns 200 / 401 / 403
  200 → nginx serves /var/www/html/synth/accounts/joost/wallet.html
  401 → redirect to /synth/login.html?reason=unauthorized
  403 → redirect to /synth/login.html?reason=forbidden
```

## Login Rate Limiting

- Tracked per source IP (stored as SHA-256 hash — raw IPs not persisted).
- Window: 15 minutes, max 10 failed attempts.
- After limit: `LOGIN_RATE_LIMITED` error (same HTTP 401, no account enumeration).

## CSRF Protection

- **Origin header validation**: when `allowed_origins` is configured on the WSGI app, all state-changing POST routes require a matching `Origin` header. Missing or unknown origin → `403 ORIGIN_NOT_ALLOWED`.
- **SameSite=Lax cookie**: prevents cross-origin cookie transmission for non-navigation requests.
- **JSON Content-Type**: browsers require preflight for cross-origin JSON POSTs; no CORS headers are returned, so cross-origin requests are blocked by browsers.
- **Request size limit**: 64 KiB maximum body.

## Session Rotation

- On each successful login, all existing active sessions for the user are invalidated before a new session is created. This prevents session fixation and limits concurrent session abuse.

## Security Assumptions

- TLS is terminated at nginx. The cookie is marked `Secure`.
- The `check-access` endpoint is marked `internal` in nginx; external access is denied.
- `X-Synth-Requested-Profile` is set by nginx from a regex capture group — not forwarded from the client.
- The raw session token is only in the cookie and never in HTML, JSON, URLs, logs, or localStorage.
- Only the SHA-256 hash of the session token is stored in the database.
- Passwords are stored as scrypt hashes (n=2^14, r=8, p=1, dklen=64).
- Login errors are generic (`INVALID_LOGIN`) — no account enumeration.

## Basic Auth Transition Plan

The current production nginx configuration uses HTTP Basic Auth. The transition sequence is:

1. Apply migration `20260607_profile_session_authorization_v1.sql`.
2. Restart `synth-website-registration` systemd service.
3. Verify health endpoint: `GET /synth/web-auth/healthz` → `{"ok": true}`.
4. Run acceptance tests (see below).
5. Only after all acceptance tests pass: update nginx to add `auth_request` for protected routes.
6. Run smoke tests on protected routes with application auth.
7. Only after smoke tests pass: remove Basic Auth from nginx config and reload.

Do not remove Basic Auth in any step before step 7.

## Deployment Acceptance Steps

Before removing Basic Auth:

- [ ] Registration flow works end-to-end (register → email → verify → login → dashboard).
- [ ] Correct profile is shown after login (no cross-profile access possible).
- [ ] Session expires correctly (absolute and idle).
- [ ] Logout invalidates session (subsequent request gets 401).
- [ ] Login rate limiting fires at 10 failures within 15 minutes.
- [ ] nginx auth_request returns 200 for own profile, 403 for other profile.
- [ ] nginx serves correct static file after successful auth_request.
- [ ] Error pages redirect correctly to `/synth/login.html?reason=...`.

## Rollback Plan

If application auth fails in production:

1. Revert nginx config to Basic Auth only (remove `auth_request` blocks).
2. Reload nginx: `sudo nginx -s reload`.
3. No data loss: registration data, sessions, and profiles are preserved.
4. Investigate auth service logs before re-enabling.

To undo the migration:
```sql
ALTER TABLE web_session DROP COLUMN idle_expires_ts_utc;
DROP TABLE IF EXISTS login_attempt;
```
(Session and profile data are unaffected.)

## API-Account Connection (Future Milestone)

Exchange API credential linking is a separate future milestone. When implemented:

- Allowed: read balance, read positions, read open orders.
- Not allowed: trading, order creation or modification, withdrawals, transfers, address management.
- Credentials will be encrypted server-side.
- Never stored in HTML, JSON, URLs, logs, or browser storage.
- Separate migration and service lane. No credential fields are present in this release.

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
