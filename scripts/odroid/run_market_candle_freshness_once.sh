#!/usr/bin/env bash
set -euo pipefail

echo "FAILED runner=run_market_candle_freshness_once reason=ODROID_PUBLIC_MARKET_WRITER_RETIRED" >&2
echo "owner=public-candle-freshness-writer canonical_runner=scripts/run_market_candle_freshness_once.sh" >&2
echo "database_writes=0 writer_invocations=0 broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0" >&2
exit 2
