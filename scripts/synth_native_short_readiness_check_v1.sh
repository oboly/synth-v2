#!/usr/bin/env bash

# Lightweight native SHORT production readiness check.
#
# Intended install target: /usr/local/bin/synth-native-short-readiness-check
# (a symlink to this repository-owned script). Usage:
#
#   sudo synth-native-short-readiness-check
#
# This is a thin process wrapper only: venv activation, then delegation to
# src.operations.run_native_short_production_readiness_v1, which is entirely
# read-only (no host mutation, no DB write, no systemd mutation, no writer
# invocation). No writer-capable code lives in this file.

if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

set -u

# Resolve the physical script file first: this script is invoked through a
# symlink at /usr/local/bin/synth-native-short-readiness-check, and
# BASH_SOURCE[0] for a symlinked invocation is the symlink path itself, not
# its target. See scripts/synth_native_short_promote_v1.sh for the identical,
# previously-fixed reasoning.
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
if [ -z "${SCRIPT_PATH}" ] || [ ! -f "${SCRIPT_PATH}" ]; then
    echo "[READINESS][FAIL] could not resolve physical script path from ${BASH_SOURCE[0]}" >&2
    exit 2
fi
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_DIR}" || exit 2

activate_runtime_venv() {
    for candidate in venv .venv; do
        if [ -f "${candidate}/bin/activate" ]; then
            # shellcheck disable=SC1090
            . "${candidate}/bin/activate"

            if python -c 'import requests, pymysql, pandas, yaml, dotenv' >/dev/null 2>&1; then
                echo "[READINESS] venv=${candidate}" >&2
                return 0
            fi

            deactivate >/dev/null 2>&1 || true
        fi
    done

    echo "[READINESS][FAIL] no usable venv found; missing one of: requests pymysql pandas yaml dotenv" >&2
    exit 2
}

activate_runtime_venv

exec python -m src.operations.run_native_short_production_readiness_v1 "$@"
