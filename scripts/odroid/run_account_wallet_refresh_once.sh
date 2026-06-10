#!/usr/bin/env bash
set -euo pipefail

PROFILE="${1:-}"
if [[ -z "${PROFILE}" ]]; then
  echo "Usage: $0 <profile>" >&2
  exit 1
fi

REPO_DIR="${SYNTH_REPO_DIR:-$HOME/projects/synth-v2}"
LOCK_FILE="${SYNTH_ACCOUNT_WALLET_REFRESH_LOCK:-/tmp/synth-account-wallet-refresh-${PROFILE}.lock}"
VENUE="${SYNTH_ACCOUNT_WALLET_VENUE:-bitvavo}"
# Credential source: 'db' for encrypted DB credentials (default for provisioned accounts).
# Set to 'profile-env' via a systemd drop-in for accounts still using legacy .env files.
CREDENTIAL_SOURCE="${SYNTH_WALLET_CREDENTIAL_SOURCE:-db}"

echo "account_wallet_refresh_once starting $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "profile=${PROFILE}"
echo "broker_private_calls=2 broker_writes=0 order_submission=0 live_orders=0"
echo "decision_gate=none execution_planner=none executor=none"

cd "${REPO_DIR}"

if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
elif [[ -d "venv" ]]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
else
  echo "No .venv or venv found under ${REPO_DIR}" >&2
  exit 1
fi

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "Skipped: another wallet refresh is already running for ${PROFILE}."
  exit 0
fi

export SYNTH_BROKER_PRIVATE_READ_PERMISSION="${SYNTH_BROKER_PRIVATE_READ_PERMISSION:-I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA}"

# CREDENTIAL_SOURCE is set from SYNTH_WALLET_CREDENTIAL_SOURCE env var (default: db).
# Provisioned accounts use 'db'. Legacy accounts still using a .env file must set
# SYNTH_WALLET_CREDENTIAL_SOURCE=profile-env via a systemd drop-in.
python -m src.account.run_account_wallet_refresh_v1 \
  --account-profile "${PROFILE}" \
  --credential-source "${CREDENTIAL_SOURCE}" \
  --venue "${VENUE}" \
  --write-db \
  --output summary

echo "account_wallet_refresh_once finished $(date -u +%Y-%m-%dT%H:%M:%SZ)"
