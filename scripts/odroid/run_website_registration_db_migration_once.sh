#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${SYNTH_REPO_DIR:-$HOME/projects/synth-v2}"

echo "website_registration_db_migration_once starting $(date -u +%Y-%m-%dT%H:%M:%SZ)"
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

exec python -m src.web.run_website_registration_db_migration_v1 --output summary
