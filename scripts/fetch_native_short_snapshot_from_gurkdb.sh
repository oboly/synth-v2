#!/usr/bin/env bash
# Bounded, read-only transport step: pull gurkdb's canonical native SHORT
# snapshot manifest + immutable artifacts into a local staging directory.
#
# This script has no ownership over validation or activation. It only moves
# bytes into a staging directory; src/operations/run_native_short_context_snapshot_import_v1.py
# separately validates and atomically installs. It never writes to the
# canonical install path and never deletes anything on the remote side.
#
# Usage (run on Odroid):
#   scripts/fetch_native_short_snapshot_from_gurkdb.sh <staging_dir>
#
# Required environment:
#   SYNTH_NATIVE_SHORT_SNAPSHOT_SOURCE_HOST   ssh host/alias for gurkdb (e.g. from ~/.ssh/config)
#   SYNTH_NATIVE_SHORT_SNAPSHOT_SOURCE_PATH   defaults to the canonical publication path
set -euo pipefail

STAGING_DIR="${1:?usage: fetch_native_short_snapshot_from_gurkdb.sh <staging_dir>}"
SOURCE_HOST="${SYNTH_NATIVE_SHORT_SNAPSHOT_SOURCE_HOST:?SYNTH_NATIVE_SHORT_SNAPSHOT_SOURCE_HOST is required}"
SOURCE_PATH="${SYNTH_NATIVE_SHORT_SNAPSHOT_SOURCE_PATH:-/var/www/html/synth/_runtime/native_short_context_snapshot_v1/}"

echo "STARTED runner=fetch_native_short_snapshot_from_gurkdb source_host=${SOURCE_HOST} staging_dir=${STAGING_DIR}"

mkdir -p "${STAGING_DIR}"

# --checksum forces content verification instead of trusting mtime/size.
# No --delete: staging only ever grows; the importer decides what is used.
# Read-only on the remote side; this never writes into gurkdb's tree.
rsync \
  --archive \
  --checksum \
  --protect-args \
  --chmod=Du=rwx,Fu=rw \
  "${SOURCE_HOST}:${SOURCE_PATH}" \
  "${STAGING_DIR}/"

echo "FINISHED runner=fetch_native_short_snapshot_from_gurkdb staging_dir=${STAGING_DIR} exit_status=0"
