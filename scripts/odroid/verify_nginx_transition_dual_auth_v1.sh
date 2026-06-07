#!/usr/bin/env bash
# verify_nginx_transition_dual_auth_v1.sh
# Read-only acceptance verification for SYNTH transitional nginx dual-auth.
# No config writes. No nginx reloads. Safe to run at any time.
#
# Usage:
#   bash scripts/odroid/verify_nginx_transition_dual_auth_v1.sh
#   bash scripts/odroid/verify_nginx_transition_dual_auth_v1.sh --basic-user USER
#
# Always tests (no credentials required):
#   - web-auth backend health 200
#   - /synth/ without credentials returns 401
#   - WWW-Authenticate realm is "Synth cockpit"
#   - nginx config syntax valid
#   - /synth/_internal/check-access returns non-200 (not publicly serving)
#
# Optional tests (--basic-user USER, password read securely):
#   - /synth/ = 200
#   - /synth/register.html = 200
#   - /synth/login.html = 200
#   - /synth/web-auth/healthz = 200
#   - /synth/onboarding.html without app cookie = 302 to login (unauthorized)
#   - /synth/accounts/joost/ without app cookie = 302 to login (unauthorized)
#   - /synth/web-auth/check-access = 403 (deny all)
#   - /synth/_internal/check-access with credentials = 404 (internal block)
#
# Safety:
#   broker_private_calls=0 broker_writes=0 order_submission=0
#   live_orders=0 decision_gate=none execution_planner=none executor=none

set -euo pipefail

# ── Constants ─────────────────────────────────────────────────────────────────
DOMAIN="gurk11.duckdns.org"
BASE_URL="https://${DOMAIN}"
WEB_AUTH_LOCAL="http://127.0.0.1:8786"
HEALTHZ_LOCAL="${WEB_AUTH_LOCAL}/synth/web-auth/healthz"
EXPECTED_REALM="Synth cockpit"

BASIC_USER=""
PASS_FAILURES=0

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

echo "STARTED verify_nginx_transition_dual_auth_v1 domain=${DOMAIN}"
echo "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0"
echo "decision_gate=none execution_planner=none executor=none"

# ── Helper ────────────────────────────────────────────────────────────────────
check_http() {
    local label="$1"
    local expected="$2"
    local actual="$3"
    if [[ "${actual}" == "${expected}" ]]; then
        echo "PASS ${label} expected=${expected} actual=${actual}"
    else
        echo "FAIL ${label} expected=${expected} actual=${actual}" >&2
        PASS_FAILURES=$(( PASS_FAILURES + 1 ))
    fi
}

# ── Always tests ──────────────────────────────────────────────────────────────
echo ""
echo "phase=always_tests"

# 1. Backend health
echo "check web-auth backend health..."
HEALTH_CODE="$(curl -s -o /dev/null -w '%{http_code}' \
    --connect-timeout 5 --max-time 10 "${HEALTHZ_LOCAL}")"
check_http "web-auth-health" "200" "${HEALTH_CODE}"

# 2. /synth/ without credentials → 401
NO_CRED_CODE="$(curl -s -o /dev/null -w '%{http_code}' \
    --connect-timeout 5 --max-time 10 \
    "${BASE_URL}/synth/")"
check_http "synth-no-cred-returns-401" "401" "${NO_CRED_CODE}"

# 3. WWW-Authenticate realm
WWW_AUTH="$(curl -s -o /dev/null -D - \
    --connect-timeout 5 --max-time 10 \
    "${BASE_URL}/synth/" 2>/dev/null \
    | grep -i '^WWW-Authenticate:' | head -1 | tr -d '\r')"
if echo "${WWW_AUTH}" | grep -qF "\"${EXPECTED_REALM}\""; then
    echo "PASS www-auth-realm realm found in: ${WWW_AUTH}"
else
    echo "FAIL www-auth-realm expected realm '${EXPECTED_REALM}' not found in: ${WWW_AUTH}" >&2
    PASS_FAILURES=$(( PASS_FAILURES + 1 ))
fi

# 4. nginx syntax valid
if sudo nginx -t 2>&1 | grep -q "syntax is ok"; then
    echo "PASS nginx-syntax-valid"
else
    echo "FAIL nginx-syntax-valid" >&2
    PASS_FAILURES=$(( PASS_FAILURES + 1 ))
fi

# 5. /synth/_internal/check-access is not publicly serving (returns non-200)
INTERNAL_CODE="$(curl -s -o /dev/null -w '%{http_code}' \
    --connect-timeout 5 --max-time 10 \
    "${BASE_URL}/synth/_internal/check-access")"
if [[ "${INTERNAL_CODE}" != "200" ]]; then
    echo "PASS internal-check-access-not-exposed status=${INTERNAL_CODE}"
else
    echo "FAIL internal-check-access-not-exposed returned 200 (must not be publicly accessible)" >&2
    PASS_FAILURES=$(( PASS_FAILURES + 1 ))
fi

echo "phase=always_tests status=done"

# ── Optional authenticated tests ──────────────────────────────────────────────
if [[ -z "${BASIC_USER}" ]]; then
    echo ""
    echo "phase=optional_tests status=skipped (pass --basic-user USER to enable)"
    echo ""
    if [[ "${PASS_FAILURES}" -gt 0 ]]; then
        echo "RESULT failures=${PASS_FAILURES}" >&2
        exit 1
    fi
    echo "RESULT all_always_tests=passed"
    exit 0
fi

# Read password securely — never echoed or stored in logs
if [[ ! -t 0 ]]; then
    echo "ERROR --basic-user requires an interactive terminal for password input" >&2
    exit 1
fi
read -r -s -p "Basic Auth password for ${BASIC_USER}: " BASIC_PASS
echo ""

# Temporary netrc — mode 0600, deleted on exit
NETRC="$(mktemp -t synth-verify-netrc.XXXXXX)"
chmod 0600 "${NETRC}"
# shellcheck disable=SC2064
trap "rm -f '${NETRC}'" EXIT

# BASIC_PASS written to netrc file only — never echoed or logged
printf 'machine %s\nlogin %s\npassword %s\n' \
    "${DOMAIN}" "${BASIC_USER}" "${BASIC_PASS}" > "${NETRC}"

# Helper for authenticated curl
auth_code() {
    local url="$1"
    shift
    curl -s -o /dev/null -w '%{http_code}' \
        --netrc-file "${NETRC}" \
        --connect-timeout 5 --max-time 10 \
        "$@" "${url}"
}

# Helper for redirect-following: returns final status
auth_code_follow() {
    local url="$1"
    shift
    curl -s -o /dev/null -w '%{http_code}' -L \
        --netrc-file "${NETRC}" \
        --connect-timeout 5 --max-time 10 \
        "$@" "${url}"
}

# Helper for checking redirect location
auth_redirect_location() {
    local url="$1"
    curl -s -o /dev/null -D - \
        --netrc-file "${NETRC}" \
        --connect-timeout 5 --max-time 10 \
        "${url}" 2>/dev/null \
        | grep -i '^[Ll]ocation:' | head -1 | tr -d '\r'
}

echo ""
echo "phase=optional_tests user=${BASIC_USER}"

# /synth/ → 200
CODE="$(auth_code "${BASE_URL}/synth/")"
check_http "synth-root-with-auth" "200" "${CODE}"

# /synth/register.html → 200
CODE="$(auth_code "${BASE_URL}/synth/register.html")"
check_http "synth-register-with-auth" "200" "${CODE}"

# /synth/login.html → 200
CODE="$(auth_code "${BASE_URL}/synth/login.html")"
check_http "synth-login-with-auth" "200" "${CODE}"

# /synth/web-auth/healthz → 200
CODE="$(auth_code "${BASE_URL}/synth/web-auth/healthz")"
check_http "synth-healthz-with-auth" "200" "${CODE}"

# /synth/onboarding.html without app cookie → 302 to login?reason=unauthorized
# (nginx auth_request returns 401 → error_page 401 = @synth_login_required → 302)
ONBOARD_LOC="$(auth_redirect_location "${BASE_URL}/synth/onboarding.html")"
if echo "${ONBOARD_LOC}" | grep -q "reason=unauthorized"; then
    echo "PASS onboarding-no-cookie-redirects-to-login: ${ONBOARD_LOC}"
else
    echo "FAIL onboarding-no-cookie-redirects-to-login expected reason=unauthorized, got: ${ONBOARD_LOC}" >&2
    PASS_FAILURES=$(( PASS_FAILURES + 1 ))
fi

# /synth/accounts/joost/ without app cookie → 302 to login?reason=unauthorized
JOOST_LOC="$(auth_redirect_location "${BASE_URL}/synth/accounts/joost/")"
if echo "${JOOST_LOC}" | grep -q "reason=unauthorized"; then
    echo "PASS joost-no-cookie-redirects-to-login: ${JOOST_LOC}"
else
    echo "FAIL joost-no-cookie-redirects-to-login expected reason=unauthorized, got: ${JOOST_LOC}" >&2
    PASS_FAILURES=$(( PASS_FAILURES + 1 ))
fi

# /synth/web-auth/check-access → 403 (deny all)
CODE="$(auth_code "${BASE_URL}/synth/web-auth/check-access")"
check_http "web-auth-check-access-denied" "403" "${CODE}"

# /synth/_internal/check-access with credentials → 404 (internal block not external)
CODE="$(auth_code "${BASE_URL}/synth/_internal/check-access")"
check_http "internal-check-access-with-auth-404" "404" "${CODE}"

echo "phase=optional_tests status=done"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
if [[ "${PASS_FAILURES}" -gt 0 ]]; then
    echo "RESULT failures=${PASS_FAILURES}" >&2
    exit 1
fi
echo "RESULT all_tests=passed"
echo "broker_private_calls=0"
echo "broker_writes=0"
echo "order_submission=0"
echo "live_orders=0"
echo "decision_gate=none"
echo "execution_planner=none"
echo "executor=none"
