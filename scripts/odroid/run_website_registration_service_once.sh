#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${SYNTH_REPO_DIR:-$HOME/projects/synth-v2}"
HOST="${SYNTH_WEB_AUTH_HOST:-127.0.0.1}"
PORT="${SYNTH_WEB_AUTH_PORT:-8786}"
DATABASE="${SYNTH_WEB_AUTH_DATABASE:-mariadb}"
SQLITE_PATH="${SYNTH_WEB_AUTH_SQLITE_PATH:-/tmp/synth_website_registration_v1.sqlite3}"

echo "website_registration_service_once starting $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0"
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

exec python -m src.web.run_web_auth_service_v1 \
  --host "${HOST}" \
  --port "${PORT}" \
  --database "${DATABASE}" \
  --sqlite-path "${SQLITE_PATH}"
