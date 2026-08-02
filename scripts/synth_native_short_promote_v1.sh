#!/usr/bin/env bash

# Canonical native SHORT production activation entrypoint.
#
# Intended install target: /usr/local/bin/synth-native-short-promote (a
# symlink to this repository-owned script; see
# docs/ops/native_short_production_promotion_wrapper_v1.md for the exact
# install procedure). Usage:
#
#   sudo synth-native-short-promote ETH XRP
#
# This is a thin process wrapper only: venv activation, then delegation to
# src.operations.run_native_short_production_promote_v1, which derives all
# request identity from the verified installed checkout and calls the
# existing, unmodified rollout CLI and canonical 4h chain. No writer-capable
# code lives in this file, and it performs no git pull.

if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_DIR}" || exit 1

activate_runtime_venv() {
    for candidate in venv .venv; do
        if [ -f "${candidate}/bin/activate" ]; then
            # shellcheck disable=SC1090
            . "${candidate}/bin/activate"

            if python -c 'import requests, pymysql, pandas, yaml, dotenv' >/dev/null 2>&1; then
                echo "[PROMOTE] venv=${candidate}" >&2
                return 0
            fi

            deactivate >/dev/null 2>&1 || true
        fi
    done

    echo "[PROMOTE][FAIL] no usable venv found; missing one of: requests pymysql pandas yaml dotenv" >&2
    exit 1
}

activate_runtime_venv

exec python -m src.operations.run_native_short_production_promote_v1 "$@"
