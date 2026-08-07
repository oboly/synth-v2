#!/usr/bin/env bash
# Held-market enrollment owner (Issue #238). Automatically enrolls any
# resolvable positive wallet holding into the account-agnostic canonical
# Fib publication cohort by flipping asset.is_portfolio (0 -> 1). Read-only
# except for that one guarded UPDATE. Never invokes the canonical Fib writer
# and never touches account_asset/venue_market rows.
#
# broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0
# decision_gate=none execution_planner=none executor=none
set -euo pipefail

REPO_DIR="${SYNTH_REPO_DIR:-$HOME/projects/synth-v2}"
VENUE="${SYNTH_ACCOUNT_WALLET_VENUE:-bitvavo}"
QUOTE_CURRENCY="${SYNTH_MARKET_PRICE_SNAPSHOT_QUOTE:-EUR}"
LOCK_FILE="${SYNTH_HELD_MARKET_ENROLLMENT_LOCK:-/tmp/synth-held-market-enrollment.lock}"
OPERATOR="${SYNTH_HELD_MARKET_ENROLLMENT_OPERATOR:-linked_profile_runtime_orchestrator}"
REASON="${SYNTH_HELD_MARKET_ENROLLMENT_REASON:-scheduled reconciliation (Issue #238)}"

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
  echo "Skipped: another held-market enrollment run is already in progress."
  exit 0
fi

python -m src.market_data.run_held_market_enrollment_v1 \
  --venue "${VENUE}" \
  --quote-currency "${QUOTE_CURRENCY}" \
  --apply \
  --operator "${OPERATOR}" \
  --reason "${REASON}" \
  --output summary
