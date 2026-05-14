#!/usr/bin/env bash

set -u

cd "$(dirname "$0")/.." || exit 1

if [[ -d "venv" ]]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
elif [[ -d ".venv" ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

export SYNTH_EXECUTION_MODE="${SYNTH_EXECUTION_MODE:-paper}"
export SYNTH_LIVE_EXECUTION_PERMISSION="${SYNTH_LIVE_EXECUTION_PERMISSION:-NOT_GRANTED}"
export SYNTH_BROKER_WRITE_PERMISSION="${SYNTH_BROKER_WRITE_PERMISSION:-NOT_GRANTED}"

REMOTE_HOST="${SYNTH_PAPER_ADVICE_DASHBOARD_REMOTE_HOST:-odroid}"
REMOTE_PATH="${SYNTH_PAPER_ADVICE_DASHBOARD_REMOTE_PATH:-/var/www/html/synth/paper-advice.html}"
LOCAL_HTML="${SYNTH_PAPER_ADVICE_DASHBOARD_LOCAL_HTML:-/tmp/synth-paper-advice.html}"
TMP_REMOTE="/tmp/synth-paper-advice.html"

echo "[PUBLISH][paper-advice] render local html=${LOCAL_HTML}"

python -m src.reporting.run_paper_advice_static_dashboard_v1 \
  --venue bitvavo \
  --interval 4h \
  --output-html "${LOCAL_HTML}" \
  --output table
RC=$?
if [[ "$RC" -ne 0 ]]; then
    echo "[PUBLISH][paper-advice][FAIL] render failed rc=${RC}"
    exit "$RC"
fi

if ! grep -q "Synth Paper Advice" "${LOCAL_HTML}"; then
    echo "[PUBLISH][paper-advice][FAIL] missing title marker"
    exit 1
fi

if ! grep -q "broker_calls=0" "${LOCAL_HTML}"; then
    echo "[PUBLISH][paper-advice][FAIL] missing safety marker"
    exit 1
fi

LOCAL_SHA="$(sha256sum "${LOCAL_HTML}" | awk '{print $1}')"

echo "[PUBLISH][paper-advice] copy to ${REMOTE_HOST}:${REMOTE_PATH}"

scp "${LOCAL_HTML}" "${REMOTE_HOST}:${TMP_REMOTE}"
RC=$?
if [[ "$RC" -ne 0 ]]; then
    echo "[PUBLISH][paper-advice][FAIL] scp failed rc=${RC}"
    exit "$RC"
fi

ssh "${REMOTE_HOST}" "
  mkdir -p \"\$(dirname '${REMOTE_PATH}')\" &&
  mv '${TMP_REMOTE}' '${REMOTE_PATH}' &&
  chmod 644 '${REMOTE_PATH}' &&
  test -s '${REMOTE_PATH}' &&
  grep -q 'Synth Paper Advice' '${REMOTE_PATH}' &&
  grep -q 'broker_calls=0' '${REMOTE_PATH}'
"
RC=$?
if [[ "$RC" -ne 0 ]]; then
    echo "[PUBLISH][paper-advice][FAIL] remote install/marker check failed rc=${RC}"
    exit "$RC"
fi

REMOTE_SHA="$(ssh "${REMOTE_HOST}" "sha256sum '${REMOTE_PATH}' | awk '{print \$1}'")"
if [[ "${LOCAL_SHA}" != "${REMOTE_SHA}" ]]; then
    echo "[PUBLISH][paper-advice][FAIL] checksum mismatch local=${LOCAL_SHA} remote=${REMOTE_SHA}"
    exit 1
fi

ssh "${REMOTE_HOST}" "
  curl -s http://127.0.0.1:5002/synth/paper-advice.html |
  grep -E 'Synth Paper Advice|broker_calls=0' |
  head
"
RC=$?
if [[ "$RC" -ne 0 ]]; then
    echo "[PUBLISH][paper-advice][FAIL] remote HTTP marker check failed rc=${RC}"
    exit "$RC"
fi

echo "[PUBLISH][paper-advice][DONE] broker_calls=0 broker_writes=0 order_submission=0 live_orders=0"
