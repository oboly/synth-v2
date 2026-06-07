#!/usr/bin/env bash
# activate_nginx_transition_dual_auth_v1.sh
# Fail-closed Odroid installer for SYNTH transitional nginx dual-auth.
#
# Deploys Basic Auth + application session auth config atomically.
# Rolls back automatically on any error.
#
# Usage:
#   bash scripts/odroid/activate_nginx_transition_dual_auth_v1.sh
#   bash scripts/odroid/activate_nginx_transition_dual_auth_v1.sh --basic-user USER
#
# Safety:
#   broker_private_calls=0 broker_writes=0 order_submission=0
#   live_orders=0 decision_gate=none execution_planner=none executor=none

set -euo pipefail

# ── Constants ─────────────────────────────────────────────────────────────────
DOMAIN="gurk11.duckdns.org"
ACTIVE_SITE="/etc/nginx/sites-available/synth"
ENABLED_LINK="/etc/nginx/sites-enabled/synth"
HTPASSWD="/etc/nginx/.synth_htpasswd"
TLS_CERT="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
TLS_KEY="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"
WEB_AUTH_BACKEND="http://127.0.0.1:8786"
HEALTHZ_URL="${WEB_AUTH_BACKEND}/synth/web-auth/healthz"
REQUIRED_HOSTNAME="odroid"
REQUIRED_USER="theone"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASIC_USER=""

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --basic-user)
            BASIC_USER="$2"
            shift 2
            ;;
        *)
            echo "ERROR unknown argument: $1" >&2
            echo "Usage: bash $0 [--basic-user USER]" >&2
            exit 1
            ;;
    esac
done

# ── Guards ────────────────────────────────────────────────────────────────────
ACTUAL_HOST="$(hostname)"
if [[ "${ACTUAL_HOST}" != "${REQUIRED_HOSTNAME}" ]]; then
    echo "FAIL host_guard host=${ACTUAL_HOST} expected=${REQUIRED_HOSTNAME}" >&2
    exit 1
fi

ACTUAL_USER="$(id -un)"
if [[ "${ACTUAL_USER}" != "${REQUIRED_USER}" ]]; then
    echo "FAIL user_guard user=${ACTUAL_USER} expected=${REQUIRED_USER}" >&2
    exit 1
fi

echo "STARTED activate_nginx_transition_dual_auth_v1 host=${ACTUAL_HOST} user=${ACTUAL_USER}"
echo "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0"
echo "decision_gate=none execution_planner=none executor=none"

# ── Pre-flight checks ─────────────────────────────────────────────────────────
echo "phase=preflight"

echo "check web-auth health..."
HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' \
    --connect-timeout 5 --max-time 10 "${HEALTHZ_URL}")"
if [[ "${HTTP_CODE}" != "200" ]]; then
    echo "FAIL web-auth healthz returned ${HTTP_CODE} (expected 200)" >&2
    echo "Is synth-website-registration.service running?" >&2
    exit 1
fi
echo "check web-auth health ok status=${HTTP_CODE}"

if [[ ! -f "${ACTIVE_SITE}" ]]; then
    echo "FAIL active site not found: ${ACTIVE_SITE}" >&2
    exit 1
fi
echo "check active site ok: ${ACTIVE_SITE}"

if [[ ! -L "${ENABLED_LINK}" ]]; then
    echo "FAIL enabled symlink not found: ${ENABLED_LINK}" >&2
    exit 1
fi
echo "check enabled symlink ok: ${ENABLED_LINK}"

if [[ ! -f "${HTPASSWD}" ]]; then
    echo "FAIL htpasswd not found: ${HTPASSWD}" >&2
    exit 1
fi
echo "check htpasswd ok"

if [[ ! -f "${TLS_CERT}" ]]; then
    echo "FAIL TLS cert not found: ${TLS_CERT}" >&2
    exit 1
fi
if [[ ! -f "${TLS_KEY}" ]]; then
    echo "FAIL TLS key not found: ${TLS_KEY}" >&2
    exit 1
fi
echo "check TLS files ok"

echo "phase=preflight status=passed"

# ── Generate candidate config ─────────────────────────────────────────────────
CANDIDATE="$(mktemp /tmp/synth-nginx-candidate.XXXXXX.conf)"

cleanup_candidate() { rm -f "${CANDIDATE}"; }
trap cleanup_candidate EXIT

# Single-quoted heredoc: bash performs no expansion inside.
# nginx variables ($host, $remote_addr, etc.) are preserved as-is.
cat > "${CANDIDATE}" << 'ENDOFCONFIG'
# synth transitional dual-auth nginx config
# Phase: Basic Auth + application session authorization
# Managed by: activate_nginx_transition_dual_auth_v1.sh
# Do NOT edit by hand — re-run the activation script to regenerate.

# ── Port 80: ACME challenge + HTTP-to-HTTPS redirect ─────────────────────────
server {
    listen 80;
    server_name gurk11.duckdns.org;

    # ACME challenge must remain public
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

# ── Port 443: HTTPS with Basic Auth + application session authorization ───────
server {
    listen 443 ssl;
    server_name gurk11.duckdns.org;

    ssl_certificate     /etc/letsencrypt/live/gurk11.duckdns.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/gurk11.duckdns.org/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

    root  /var/www/html;
    index index.html;

    # Security headers
    add_header X-Frame-Options        DENY                            always;
    add_header X-Content-Type-Options nosniff                         always;
    add_header Referrer-Policy        strict-origin-when-cross-origin always;
    add_header Cache-Control          no-store                        always;

    # Basic Auth — required for all routes in this transitional phase
    auth_basic           "Synth cockpit";
    auth_basic_user_file /etc/nginx/.synth_htpasswd;

    # Root redirect
    location = / {
        return 302 /synth/;
    }

    # Web-auth service: registration, login, logout, healthz
    # Basic Auth satisfied first (from global block above), then proxied
    location /synth/web-auth/ {
        # Block direct external access to the internal check-access endpoint
        location = /synth/web-auth/check-access {
            deny all;
        }

        proxy_pass         http://127.0.0.1:8786;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 10s;
    }

    # Internal auth-check subrequest location.
    # internal: only reachable via auth_request, never from the public internet.
    # auth_basic off: subrequest must not re-challenge (outer block already authenticated).
    # X-Synth-Requested-Profile set from nginx URI regex capture only — never from client.
    location = /synth/_internal/check-access {
        internal;
        auth_basic off;
        proxy_pass             http://127.0.0.1:8786/synth/web-auth/check-access;
        proxy_pass_request_body off;
        proxy_set_header       Content-Length            "";
        proxy_set_header       Cookie                    $http_cookie;
        proxy_set_header       X-Synth-Requested-Profile $synth_profile_slug;
    }

    # Auth failure handlers
    # /synth/login.html requires only Basic Auth — not an app-session auth loop.
    location @synth_login_required {
        return 302 /synth/login.html?reason=unauthorized;
    }

    location @synth_forbidden {
        return 302 /synth/login.html?reason=forbidden;
    }

    # Static /synth routes — Basic Auth required, no application session required
    location = /synth/                   { try_files $uri $uri/index.html =404; }
    location = /synth/about.html         { try_files $uri =404; }
    location = /synth/register.html      { try_files $uri =404; }
    location = /synth/login.html         { try_files $uri =404; }
    location = /synth/verify-result.html { try_files $uri =404; }
    location /synth/assets/              { try_files $uri =404; }

    # Protected: onboarding — any valid application session required
    location = /synth/onboarding.html {
        set $synth_profile_slug "";
        auth_request /synth/_internal/check-access;
        error_page 401 = @synth_login_required;
        error_page 403 = @synth_forbidden;
        try_files $uri =404;
    }

    # Protected: account pages — session owner must match profile slug from URI.
    # Profile slug extracted from URI by nginx (never from client-supplied header).
    location ~ "^/synth/accounts/([a-z0-9][a-z0-9_-]{0,62})(/.*)?" {
        set $synth_profile_slug $1;

        auth_request /synth/_internal/check-access;
        error_page 401 = @synth_login_required;
        error_page 403 = @synth_forbidden;

        if ($request_uri ~ "\.\./") {
            return 400;
        }

        try_files $uri $uri/index.html =404;
    }

    # Defense-in-depth: block direct check-access from any unmatched path
    location = /synth/web-auth/check-access {
        deny all;
    }
}
ENDOFCONFIG

echo "phase=config_generated candidate=${CANDIDATE}"

# ── Backup + atomic install ───────────────────────────────────────────────────
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="${ACTIVE_SITE}.backup.${TIMESTAMP}"

echo "creating backup: ${BACKUP}"
sudo cp "${ACTIVE_SITE}" "${BACKUP}"

rollback() {
    local exit_code=$?
    echo "ROLLBACK restoring backup=${BACKUP}" >&2
    sudo cp "${BACKUP}" "${ACTIVE_SITE}"
    sudo nginx -s reload || echo "WARN nginx reload failed during rollback" >&2
    echo "ROLLBACK complete" >&2
    exit "${exit_code}"
}
trap rollback ERR

echo "installing candidate..."
sudo cp "${CANDIDATE}" "${ACTIVE_SITE}"

echo "nginx syntax check..."
sudo nginx -t

echo "reloading nginx..."
sudo nginx -s reload

# ── Success: clear rollback trap ──────────────────────────────────────────────
trap cleanup_candidate EXIT

echo "phase=deploy status=done"
echo "backup=${BACKUP}"

# ── Acceptance tests ──────────────────────────────────────────────────────────
VERIFY_ARGS=()
if [[ -n "${BASIC_USER}" ]]; then
    VERIFY_ARGS+=(--basic-user "${BASIC_USER}")
fi

echo ""
echo "phase=acceptance"
bash "${SCRIPT_DIR}/verify_nginx_transition_dual_auth_v1.sh" "${VERIFY_ARGS[@]}"

echo ""
echo "FINISHED activate_nginx_transition_dual_auth_v1"
echo "broker_private_calls=0"
echo "broker_writes=0"
echo "order_submission=0"
echo "live_orders=0"
echo "decision_gate=none"
echo "execution_planner=none"
echo "executor=none"
