#!/usr/bin/env bash

# Synth maintenance/onboarding guard.
#
# Purpose:
# - Keep cron/runtime chains deterministic during large backfills,
#   new asset onboarding, schema maintenance, or controlled bootstrap work.
# - If the lock exists, market chains exit cleanly before doing work.
#
# This lock only skips market-chain work.

SYNTH_MAINTENANCE_LOCK="${SYNTH_MAINTENANCE_LOCK:-/tmp/synth_maintenance.lock}"

if [[ -f "$SYNTH_MAINTENANCE_LOCK" ]]; then
    echo "[CHAIN][SKIP] maintenance lock active: $SYNTH_MAINTENANCE_LOCK"
    echo "[CHAIN][SKIP] reason: $(cat "$SYNTH_MAINTENANCE_LOCK" 2>/dev/null || true)"
    exit 0
fi
