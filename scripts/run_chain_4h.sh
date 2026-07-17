#!/usr/bin/env bash

# Re-exec with bash when invoked through sh.
# This prevents POSIX sh from breaking bash-compatible runtime behavior.
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

# Prevent overlapping 4h chain runs.
# This protects DB writes and avoids duplicate/competing pipeline snapshots.
if [ "${SYNTH_CHAIN_4H_LOCKED:-0}" != "1" ]; then
    exec env SYNTH_CHAIN_4H_LOCKED=1 flock -n /tmp/synth_chain_4h.lock bash "$0" "$@"
fi

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${SYNTH_REPO_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"

cd "${REPO_DIR}" || exit 1
source scripts/synth_maintenance_guard.sh

activate_runtime_venv() {
    for candidate in venv .venv; do
        if [ -f "${candidate}/bin/activate" ]; then
            # shellcheck disable=SC1090
            . "${candidate}/bin/activate"

            if python -c 'import requests, pymysql, pandas, yaml, dotenv' >/dev/null 2>&1; then
                echo "[CHAIN][4h] venv=${candidate}"
                return 0
            fi

            deactivate >/dev/null 2>&1 || true
        fi
    done

    echo "[CHAIN][4h][FAIL] no usable venv found; missing one of: requests pymysql pandas yaml dotenv"
    exit 1
}

activate_runtime_venv

run_step() {
    echo "[CHAIN][4h][STEP] $*"
    "$@"
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "[CHAIN][4h][FAIL] rc=$rc step=$*"
        exit "$rc"
    fi
}

NATIVE_SHORT_REPOSITORY_COMMIT="$(git rev-parse --verify HEAD)" || exit 2
run_step python -m src.market_data.native_short_repository_source_identity_v1 \
    --repository-commit "${NATIVE_SHORT_REPOSITORY_COMMIT}"

CHAIN_4H_END_TS="$(
    python -c 'from datetime import datetime, timezone; n=datetime.now(timezone.utc); h=(n.hour//4)*4; print(n.replace(hour=h, minute=0, second=0, microsecond=0).isoformat())'
)"

CHAIN_4H_ETL_START_TS="$(
    python -c 'from datetime import datetime, timezone, timedelta; n=datetime.now(timezone.utc); h=(n.hour//4)*4; e=n.replace(hour=h, minute=0, second=0, microsecond=0); print((e - timedelta(days=21)).isoformat())'
)"

echo "[CHAIN][4h] START $(date -u +%F' '%T) UTC"
echo "[CHAIN][4h] ETL window start=${CHAIN_4H_ETL_START_TS} end=${CHAIN_4H_END_TS}"
echo "[CHAIN][4h] feature window lookback_hours=720 warmup_bars=300"

run_step python -m src.etl.bitvavo.run_candles_etl \
    --interval 4h \
    --start "$CHAIN_4H_ETL_START_TS" \
    --end "$CHAIN_4H_END_TS"

run_step env \
    SYNTH_NATIVE_SHORT_REPOSITORY_COMMIT="${NATIVE_SHORT_REPOSITORY_COMMIT}" \
    SYNTH_NATIVE_SHORT_WRITER_ENTRYPOINT="scripts/run_chain_4h.sh" \
    SYNTH_NATIVE_SHORT_TRIGGER_REF="scripts/run_chain_4h.sh" \
    bash scripts/run_native_short_scope_status_chain_once.sh

run_step python -m src.market_data.run_native_short_fib_context_snapshot_v1 \
    --publish \
    --output summary

run_step python -m src.features.run_feat_candle \
    --interval 4h \
    --end "$CHAIN_4H_END_TS" \
    --lookback-hours 720 \
    --warmup-bars 300

run_step python -m src.signal_engine.run_signal_state_etl --venue bitvavo --interval 4h
run_step python -m src.advice.run_advice_engine --interval 4h
run_step python -m src.ranking.run_ranking_engine --venue bitvavo --interval 4h
run_step python -m src.measurement.run_asset_interval_quality_snapshot --venue bitvavo --write-db --output none
run_step python -m src.selection.run_selection_engine_v2 --venue bitvavo --write-db

run_step python -m src.zone.run_zone_engine_v1 \
    --venue bitvavo \
    --interval 4h \
    --lookback-candles 120 \
    --swing-window 5 \
    --write-db \
    --output table

run_step python -m src.trade_setup_filter.run_trade_setup_filter_v1 \
    --venue bitvavo \
    --limit 40 \
    --asset-suitability-mode candidate_weak_set \
    --write-db \
    --output table

run_step python -m src.research.run_trade_setup_filter_policy_preview_v1 \
    --venue bitvavo \
    --target-horizon 24H \
    --write-db \
    --output table

run_step python -m src.advice.run_paper_advice_policy_v1 \
  --venue bitvavo \
  --interval 4h \
  --write-db \
  --output table

if [[ -n "${SYNTH_PAPER_ADVICE_DASHBOARD_HTML:-}" ]]; then
    DASHBOARD_LIFECYCLE_INTERVAL="${SYNTH_PAPER_ADVICE_LIFECYCLE_INTERVAL:-15m}"

    run_step python -m src.reporting.run_paper_advice_static_dashboard_v1 \
      --venue bitvavo \
      --interval 4h \
      --lifecycle-candle-interval "${DASHBOARD_LIFECYCLE_INTERVAL}" \
      --output-html "$SYNTH_PAPER_ADVICE_DASHBOARD_HTML" \
      --output table
fi

run_step python -m src.strategy_runtime.run_strategy_runtime_snapshot \
    --interval 4h \
    --chain-name run_chain_4h \
    --notes "successful market-only chain run; decision/execution disabled"


if [[ -n "${SYNTH_PAPER_ADVICE_DASHBOARD_REMOTE_HOST:-}" ]]; then
    run_step scripts/publish_paper_advice_dashboard_to_odroid.sh
fi

echo "[CHAIN][4h] DONE  $(date -u +%F' '%T) UTC"
