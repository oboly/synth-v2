#!/usr/bin/env bash
# Linked-profile runtime orchestrator v1.
#
# Owns the explicit public-price -> account-snapshot -> safe snapshot render
# sequence for all DB-linked profiles. Responsibilities stay delegated to the
# existing stage runners; this wrapper only orders, locks, records metadata, and
# fails visibly.
#
# broker_private_calls=existing_account_refresh_only broker_writes=0
# order_submission=0 live_orders=0 decision_gate=none
# execution_planner=none executor=none
set -euo pipefail

REPO_DIR="${SYNTH_REPO_DIR:-$HOME/projects/synth-v2}"
OUTPUT_ROOT="${SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT:-/var/www/html/synth}"
VENUE="${SYNTH_ACCOUNT_WALLET_VENUE:-bitvavo}"
QUOTE="${SYNTH_MARKET_PRICE_SNAPSHOT_QUOTE:-EUR}"
LOCK_FILE="${SYNTH_LINKED_PROFILE_RUNTIME_LOCK:-/tmp/synth-linked-profile-runtime-orchestrator.lock}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACCOUNT_REFRESH_SCRIPT="${SYNTH_ACCOUNT_WALLET_REFRESH_SCRIPT:-${SCRIPT_DIR}/run_account_wallet_refresh_once.sh}"
PROFILE_RENDER_SCRIPT="${SYNTH_LINKED_PROFILE_RENDER_SCRIPT:-${SCRIPT_DIR}/run_account_wallet_snapshot_dashboard_render_once.sh}"
PROFIT_PLAN_RENDER_SCRIPT="${SYNTH_ACCOUNT_PROFIT_PLAN_RENDER_SCRIPT:-${SCRIPT_DIR}/run_account_profit_plan_snapshot_render_once.sh}"
MARKET_PRICE_REFRESH_SCRIPT="${SYNTH_MARKET_PRICE_REFRESH_SCRIPT:-}"
SKIP_DISK_HEALTH="${SYNTH_LINKED_PROFILE_RUNTIME_SKIP_DISK_HEALTH:-0}"
RUN_ID="${SYNTH_LINKED_PROFILE_RUNTIME_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
RUNTIME_DIR="${SYNTH_LINKED_PROFILE_RUNTIME_DIR:-${OUTPUT_ROOT}/_runtime/linked_profile_orchestrator_v1}"
METADATA_PATH="${SYNTH_LINKED_PROFILE_RUNTIME_METADATA_PATH:-${RUNTIME_DIR}/latest_run.json}"
STAGES_TSV="$(mktemp /tmp/synth-linked-profile-orchestrator-stages.XXXXXX)"

cleanup() {
  rm -f "${STAGES_TSV}" 2>/dev/null || true
}
trap cleanup EXIT

utc_now() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

phase_start() {
  local phase="$1"
  local profile="${2:-ALL}"
  echo "PHASE_STARTED phase=${phase} profile=${profile} run_id=${RUN_ID} ts=$(utc_now)"
}

phase_finished() {
  local phase="$1"
  local profile="$2"
  local result="$3"
  local started_ts="$4"
  local started_epoch="$5"
  local finished_ts
  local elapsed
  finished_ts="$(utc_now)"
  elapsed=$(( $(date +%s) - started_epoch ))
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "${phase}" "${profile}" "${result}" "${started_ts}" "${finished_ts}" "${elapsed}" >> "${STAGES_TSV}"
  echo "PHASE_FINISHED phase=${phase} profile=${profile} result=${result} elapsed_sec=${elapsed} run_id=${RUN_ID} ts=${finished_ts}"
}

run_disk_health() {
  local started_ts
  local started_epoch
  started_ts="$(utc_now)"
  started_epoch="$(date +%s)"
  phase_start "disk_log_health"
  if [[ "${SKIP_DISK_HEALTH}" == "1" ]]; then
    echo "disk_log_health=skipped reason=SYNTH_LINKED_PROFILE_RUNTIME_SKIP_DISK_HEALTH"
    phase_finished "disk_log_health" "ALL" "skipped" "${started_ts}" "${started_epoch}"
    return 0
  fi

  local health_args=(
    -m src.operations.run_runtime_disk_log_health_v1
    --path "${SYNTH_DISK_HEALTH_PATH:-${REPO_DIR}}"
    --warn-pct "${SYNTH_DISK_HEALTH_WARN_PCT:-85}"
    --critical-pct "${SYNTH_DISK_HEALTH_CRITICAL_PCT:-95}"
    --output table
  )
  if [[ -n "${SYNTH_DISK_HEALTH_LOG_PATH:-}" ]]; then
    health_args+=(--log-path "${SYNTH_DISK_HEALTH_LOG_PATH}")
  fi
  if [[ -n "${SYNTH_DISK_HEALTH_LOG_WARN_BYTES:-}" ]]; then
    health_args+=(--log-warn-bytes "${SYNTH_DISK_HEALTH_LOG_WARN_BYTES}")
  fi
  if [[ -n "${SYNTH_DISK_HEALTH_LOG_CRITICAL_BYTES:-}" ]]; then
    health_args+=(--log-critical-bytes "${SYNTH_DISK_HEALTH_LOG_CRITICAL_BYTES}")
  fi

  if python "${health_args[@]}"; then
    phase_finished "disk_log_health" "ALL" "ok" "${started_ts}" "${started_epoch}"
    return 0
  fi
  phase_finished "disk_log_health" "ALL" "critical" "${started_ts}" "${started_epoch}"
  echo "[DISK_HEALTH][CRITICAL] aborting before public/account/render stages" >&2
  return 1
}

run_market_price_refresh() {
  local started_ts
  local started_epoch
  started_ts="$(utc_now)"
  started_epoch="$(date +%s)"
  phase_start "refresh_public_prices"

  if [[ -n "${MARKET_PRICE_REFRESH_SCRIPT}" ]]; then
    if bash "${MARKET_PRICE_REFRESH_SCRIPT}" "${VENUE}" "${QUOTE}"; then
      phase_finished "refresh_public_prices" "ALL" "ok" "${started_ts}" "${started_epoch}"
      return 0
    fi
  else
    if python -m src.market_data.run_market_price_snapshot_v1 \
      --venue "${VENUE}" \
      --quote "${QUOTE}" \
      --write-db \
      --output none; then
      phase_finished "refresh_public_prices" "ALL" "ok" "${started_ts}" "${started_epoch}"
      return 0
    fi
  fi

  echo "[WARN] public market price refresh failed; render stage must fail closed from persisted timestamp freshness."
  phase_finished "refresh_public_prices" "ALL" "failed_continuing" "${started_ts}" "${started_epoch}"
  return 1
}

discover_profiles() {
  if [[ -n "${SYNTH_LINKED_PROFILE_LIST:-}" ]]; then
    printf '%s\n' "${SYNTH_LINKED_PROFILE_LIST}" \
      | tr ',' '\n' \
      | sed 's/^[[:space:]]*//' \
      | sed 's/[[:space:]]*$//' \
      | sed '/^$/d'
    return 0
  fi

  python -m src.account.run_linked_profile_dashboard_refresh_v1 \
    --venue "${VENUE}" \
    --output profile-list
}

write_metadata() {
  local run_started_ts="$1"
  local run_finished_ts="$2"
  local overall_result="$3"
  local profile_csv="$4"
  local profile_count="$5"
  local public_price_result="$6"
  local account_success="$7"
  local account_failure="$8"
  local render_success="$9"
  local render_failure="${10}"
  local profit_plan_success="${11}"
  local profit_plan_failure="${12}"

  python - "${METADATA_PATH}" "${RUN_ID}" "${run_started_ts}" "${run_finished_ts}" \
    "${overall_result}" "${VENUE}" "${QUOTE}" "${profile_csv}" "${profile_count}" \
    "${public_price_result}" "${account_success}" "${account_failure}" \
    "${render_success}" "${render_failure}" "${profit_plan_success}" \
    "${profit_plan_failure}" "${STAGES_TSV}" <<'PY'
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

(
    output_path,
    run_id,
    started_ts,
    finished_ts,
    overall_result,
    venue,
    quote,
    profile_csv,
    profile_count,
    public_price_result,
    account_success,
    account_failure,
    render_success,
    render_failure,
    profit_plan_success,
    profit_plan_failure,
    stages_tsv,
) = sys.argv[1:]

stages = []
with Path(stages_tsv).open(encoding="utf-8") as handle:
    for line in handle:
        phase, profile, result, stage_started, stage_finished, elapsed_s = line.rstrip("\n").split("\t")
        stages.append(
            {
                "phase": phase,
                "profile": None if profile == "ALL" else profile,
                "result": result,
                "started_ts_utc": stage_started,
                "finished_ts_utc": stage_finished,
                "elapsed_s": int(elapsed_s),
            }
        )

profiles = [p for p in profile_csv.split(",") if p]
payload = {
    "schema": "linked_profile_runtime_orchestrator_v1",
    "run_id": run_id,
    "started_ts_utc": started_ts,
    "finished_ts_utc": finished_ts,
    "overall_result": overall_result,
    "venue": venue,
    "quote": quote,
    "profiles": profiles,
    "profile_count": int(profile_count),
    "public_price_result": public_price_result,
    "account_refresh": {
        "success": int(account_success),
        "failure": int(account_failure),
    },
    "snapshot_render": {
        "success": int(render_success),
        "failure": int(render_failure),
    },
    "profit_plan_render": {
        "success": int(profit_plan_success),
        "failure": int(profit_plan_failure),
    },
    "stages": stages,
    "safety": {
        "broker_writes": 0,
        "order_submission": 0,
        "live_orders": 0,
        "decision_gate": "none",
        "execution_planner": "none",
        "executor": "none",
        "renderer_private_broker_calls": 0,
        "native_short_context_build_in_render_stage": False,
    },
}

dest = Path(output_path)
dest.parent.mkdir(parents=True, exist_ok=True)
fd, tmp_name = tempfile.mkstemp(prefix=dest.name + ".", suffix=".tmp", dir=str(dest.parent))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_name, dest)
    dir_fd = os.open(dest.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
finally:
    if os.path.exists(tmp_name):
        os.unlink(tmp_name)
PY
}

echo "linked_profile_runtime_orchestrator_once starting $(utc_now)"
echo "run_id=${RUN_ID} venue=${VENUE} quote=${QUOTE} output_root=${OUTPUT_ROOT}"
echo "broker_private_calls=account_refresh_only broker_writes=0 order_submission=0 live_orders=0"
echo "decision_gate=none execution_planner=none executor=none"
echo "renderer=${PROFILE_RENDER_SCRIPT}"
echo "profit_plan_renderer=${PROFIT_PLAN_RENDER_SCRIPT}"

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
  echo "Skipped: another linked-profile runtime orchestrator is already running."
  exit 0
fi

run_started_ts="$(utc_now)"
run_disk_health

public_price_result="ok"
if ! run_market_price_refresh; then
  public_price_result="failed_continuing"
fi

phase_epoch="$(date +%s)"
phase_ts="$(utc_now)"
phase_start "discover_linked_profiles"
linked_profiles="$(discover_profiles)" || {
  phase_finished "discover_linked_profiles" "ALL" "failed" "${phase_ts}" "${phase_epoch}"
  exit 1
}
phase_finished "discover_linked_profiles" "ALL" "ok" "${phase_ts}" "${phase_epoch}"

mapfile -t profiles <<< "${linked_profiles}"
profile_count=0
account_success=0
account_failure=0
render_success=0
render_failure=0
profit_plan_success=0
profit_plan_failure=0
profile_csv=""

for profile_code in "${profiles[@]}"; do
  [[ -z "${profile_code}" ]] && continue
  profile_count=$(( profile_count + 1 ))
  if [[ -z "${profile_csv}" ]]; then
    profile_csv="${profile_code}"
  else
    profile_csv="${profile_csv},${profile_code}"
  fi

  phase_epoch="$(date +%s)"
  phase_ts="$(utc_now)"
  phase_start "refresh_account_snapshot" "${profile_code}"
  if SYNTH_REPO_DIR="${REPO_DIR}" \
     SYNTH_ACCOUNT_WALLET_VENUE="${VENUE}" \
     bash "${ACCOUNT_REFRESH_SCRIPT}" "${profile_code}"; then
    account_success=$(( account_success + 1 ))
    phase_finished "refresh_account_snapshot" "${profile_code}" "ok" "${phase_ts}" "${phase_epoch}"
  else
    account_failure=$(( account_failure + 1 ))
    phase_finished "refresh_account_snapshot" "${profile_code}" "failed_continuing" "${phase_ts}" "${phase_epoch}"
  fi

  phase_epoch="$(date +%s)"
  phase_ts="$(utc_now)"
  phase_start "render_snapshot_dashboard" "${profile_code}"
  if SYNTH_REPO_DIR="${REPO_DIR}" \
     SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT="${OUTPUT_ROOT}" \
     SYNTH_ACCOUNT_WALLET_VENUE="${VENUE}" \
     bash "${PROFILE_RENDER_SCRIPT}" "${profile_code}"; then
    render_success=$(( render_success + 1 ))
    phase_finished "render_snapshot_dashboard" "${profile_code}" "ok" "${phase_ts}" "${phase_epoch}"
  else
    render_failure=$(( render_failure + 1 ))
    phase_finished "render_snapshot_dashboard" "${profile_code}" "failed_continuing" "${phase_ts}" "${phase_epoch}"
  fi
done

# Profit Plan is a separate persisted-snapshot stage. It is deliberately
# sequenced only after every required account-refresh stage has succeeded.
for profile_code in "${profiles[@]}"; do
  [[ -z "${profile_code}" ]] && continue
  phase_epoch="$(date +%s)"
  phase_ts="$(utc_now)"
  phase_start "profit_plan_render" "${profile_code}"
  if [[ "${account_failure}" -gt 0 || "${account_success}" -ne "${profile_count}" ]]; then
    profit_plan_failure=$(( profit_plan_failure + 1 ))
    phase_finished "profit_plan_render" "${profile_code}" "skipped_account_refresh" "${phase_ts}" "${phase_epoch}"
    continue
  fi
  if SYNTH_REPO_DIR="${REPO_DIR}" \
     SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT="${OUTPUT_ROOT}" \
     SYNTH_ACCOUNT_WALLET_VENUE="${VENUE}" \
     bash "${PROFIT_PLAN_RENDER_SCRIPT}" "${profile_code}"; then
    profit_plan_success=$(( profit_plan_success + 1 ))
    phase_finished "profit_plan_render" "${profile_code}" "ok" "${phase_ts}" "${phase_epoch}"
  else
    profit_plan_failure=$(( profit_plan_failure + 1 ))
    phase_finished "profit_plan_render" "${profile_code}" "failed_continuing" "${phase_ts}" "${phase_epoch}"
  fi
done

if [[ "${profile_count}" -eq 0 ]]; then
  echo "linked_profile_count=0 nothing_to_refresh"
fi

overall_result="ok"
if [[ "${public_price_result}" != "ok" || "${account_failure}" -gt 0 || "${render_failure}" -gt 0 || "${profit_plan_failure}" -gt 0 ]]; then
  overall_result="degraded"
fi

run_finished_ts="$(utc_now)"
write_metadata "${run_started_ts}" "${run_finished_ts}" "${overall_result}" "${profile_csv}" \
  "${profile_count}" "${public_price_result}" "${account_success}" "${account_failure}" \
  "${render_success}" "${render_failure}" "${profit_plan_success}" "${profit_plan_failure}"

echo "metadata_path=${METADATA_PATH}"
echo "linked_profile_count=${profile_count} account_success=${account_success} account_failure=${account_failure} render_success=${render_success} render_failure=${render_failure} profit_plan_success=${profit_plan_success} profit_plan_failure=${profit_plan_failure}"
echo "linked_profile_runtime_orchestrator_once finished result=${overall_result} $(utc_now)"

if [[ "${overall_result}" == "ok" ]]; then
  exit 0
fi
exit 1
