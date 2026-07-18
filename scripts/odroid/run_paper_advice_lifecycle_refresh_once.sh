#!/usr/bin/env bash
set -euo pipefail

echo "FAILED runner=run_paper_advice_lifecycle_refresh_once reason=ODROID_CANDLE_ETL_OWNERSHIP_RETIRED" >&2
echo "reporting paths consume persisted public market data and must not repair freshness" >&2
echo "owner=devlap-public-market-data database_writes=0 writer_invocations=0 broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0" >&2
exit 2
