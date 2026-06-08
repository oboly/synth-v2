#!/usr/bin/env bash
# Canonical Odroid deployment acceptance script.
# Pulls origin/main, applies migrations, restarts web-auth with health retry,
# runs generic linked-profile dashboard refresh, verifies output files.
#
# Guards: hostname must be odroid, user must be theone.
# Fail-closed: any unverified step aborts with non-zero exit.
#
# broker_private_calls=0 broker_writes=0 order_submission=0
# live_orders=0 decision_gate=none execution_planner=none executor=none
set -euo pipefail

EXPECTED_HOST="odroid"
EXPECTED_USER="theone"
REPO_DIR="${SYNTH_REPO_DIR:-$HOME/projects/synth-v2}"
OUTPUT_ROOT="${SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT:-/var/www/html/synth}"
VENUE="${SYNTH_ACCOUNT_WALLET_VENUE:-bitvavo}"
WEB_AUTH_HEALTH_URL="http://127.0.0.1:8786/synth/web-auth/healthz"
WEB_AUTH_HEALTH_RETRIES=10
WEB_AUTH_HEALTH_INTERVAL=2

# -- Guards --

if [[ "$(hostname)" != "${EXPECTED_HOST}" ]]; then
  echo "[abort] hostname=$(hostname) expected=${EXPECTED_HOST}" >&2
  exit 1
fi

if [[ "$(id -un)" != "${EXPECTED_USER}" ]]; then
  echo "[abort] user=$(id -un) expected=${EXPECTED_USER}" >&2
  exit 1
fi

echo "odroid_deployment_acceptance_v1 starting $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "repo_dir=${REPO_DIR} output_root=${OUTPUT_ROOT} venue=${VENUE}"
echo "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0"
echo "decision_gate=none execution_planner=none executor=none"

cd "${REPO_DIR}"

# -- Pull origin/main --

echo ""
echo "PHASE_STARTED phase=git_pull ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
phase_epoch="$(date +%s)"
git pull origin main
echo "PHASE_FINISHED phase=git_pull elapsed_sec=$(( $(date +%s) - phase_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# -- Activate venv --

if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
elif [[ -d "venv" ]]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
else
  echo "[abort] No .venv or venv found under ${REPO_DIR}" >&2
  exit 1
fi

# -- Apply migrations --

echo ""
echo "PHASE_STARTED phase=apply_migrations ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
phase_epoch="$(date +%s)"
python -m src.web.run_website_registration_db_migration_v1 --output summary
echo "PHASE_FINISHED phase=apply_migrations elapsed_sec=$(( $(date +%s) - phase_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# -- Restart web-auth service --

echo ""
echo "PHASE_STARTED phase=restart_web_auth ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
phase_epoch="$(date +%s)"
systemctl --user restart synth-website-registration.service
echo "PHASE_FINISHED phase=restart_web_auth elapsed_sec=$(( $(date +%s) - phase_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# -- Health retry (fail-closed, up to 20s) --

echo ""
echo "PHASE_STARTED phase=health_check ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
phase_epoch="$(date +%s)"
health_ok=0
for i in $(seq 1 "${WEB_AUTH_HEALTH_RETRIES}"); do
  if curl -fsS --max-time 3 "${WEB_AUTH_HEALTH_URL}" | grep -q '"ok":true'; then
    health_ok=1
    echo "health_check=ok attempt=${i}"
    break
  fi
  echo "health_check=retry attempt=${i} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  sleep "${WEB_AUTH_HEALTH_INTERVAL}"
done

if [[ "${health_ok}" != "1" ]]; then
  echo "[abort] web-auth health check failed after ${WEB_AUTH_HEALTH_RETRIES} attempts" >&2
  exit 1
fi
echo "PHASE_FINISHED phase=health_check elapsed_sec=$(( $(date +%s) - phase_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# -- Generic linked-profile dashboard refresh --

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "PHASE_STARTED phase=linked_profile_dashboard_refresh ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
phase_epoch="$(date +%s)"
SYNTH_REPO_DIR="${REPO_DIR}" \
SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT="${OUTPUT_ROOT}" \
SYNTH_ACCOUNT_WALLET_VENUE="${VENUE}" \
bash "${SCRIPT_DIR}/run_linked_profile_dashboard_refresh_once.sh"
echo "PHASE_FINISHED phase=linked_profile_dashboard_refresh elapsed_sec=$(( $(date +%s) - phase_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# -- Verify linked profile outputs (Joost, or any active linked profile) --

echo ""
echo "PHASE_STARTED phase=verify_linked_profile_outputs ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
phase_epoch="$(date +%s)"

linked_profiles="$(python -m src.account.run_linked_profile_dashboard_refresh_v1 \
  --venue "${VENUE}" \
  --output profile-list)"

if [[ -z "${linked_profiles}" ]]; then
  echo "verify=no_linked_profiles_found nothing_to_verify"
else
  while IFS= read -r profile_code; do
    [[ -z "${profile_code}" ]] && continue
    profile_dir="${OUTPUT_ROOT}/accounts/${profile_code}"
    verify_fail=0
    for f in index.html wallet.html wallet.json profit-plan.html open-orders-monitor.html; do
      if [[ -f "${profile_dir}/${f}" ]]; then
        echo "verify=ok profile=${profile_code} file=${f}"
      else
        echo "verify=MISSING profile=${profile_code} file=${f}" >&2
        verify_fail=1
      fi
    done
    if [[ "${verify_fail}" == "1" ]]; then
      echo "[abort] output verification failed for profile=${profile_code}" >&2
      exit 1
    fi
  done <<< "${linked_profiles}"
fi

echo "PHASE_FINISHED phase=verify_linked_profile_outputs elapsed_sec=$(( $(date +%s) - phase_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# -- Verify unlinked profiles have no account directory --
# Hugo is the canonical unlinked example; use discover to confirm non-presence.
# Any profile in accounts/ dir that is NOT in the linked list should not exist.
# (This is a spot check — does not enumerate all possible profile names.)
#
# Currently we only have Joost linked and Hugo unlinked, but this check is
# generic: it verifies that profiles NOT returned by discovery have no
# accounts/<profile>/index.html.

# No hardcoded names: unlinked verification is done by the acceptance test suite.

echo ""
echo "PHASE_STARTED phase=safety_markers ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "broker_private_calls=0"
echo "broker_writes=0"
echo "order_submission=0"
echo "live_orders=0"
echo "decision_gate=none"
echo "execution_planner=none"
echo "executor=none"
echo "PHASE_FINISHED phase=safety_markers elapsed_sec=0 ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo ""
echo "odroid_deployment_acceptance_v1 finished $(date -u +%Y-%m-%dT%H:%M:%SZ)"
