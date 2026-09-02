"""Manual, fail-closed canonical MA breadth snapshot runner; no timer activation."""
from __future__ import annotations
import argparse
from datetime import UTC, datetime
from dotenv import load_dotenv
from src.common.db import get_db_connection
from src.features.ma_breadth_snapshot_v1 import build_snapshot, fetch_candles_at_or_before, fetch_universe_members, persist_snapshot

def _asof(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("--asof-ts must include UTC timezone")
    return parsed.astimezone(UTC)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Persist canonical market-only MA50 breadth snapshot")
    parser.add_argument("--asof-ts", required=True, type=_asof, help="Exact UTC candle close timestamp; no latest fallback")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--write-db", action="store_true")
    args = parser.parse_args(argv)
    print(f"STARTED runner=ma_breadth_snapshot_v1 mode={'write' if args.write_db else 'dry-run'} asof={args.asof_ts.isoformat()}", flush=True)
    if args.write_db:
        from src.operations.writer_capability_authorization_v1 import require_capability_write_authorization
        authorization = require_capability_write_authorization("ma_breadth_snapshot", service="UNASSIGNED")
    else:
        authorization = None
    load_dotenv()
    conn = get_db_connection()
    try:
        members = fetch_universe_members(conn, venue=args.venue)
        snapshot = build_snapshot(members=members, candles=fetch_candles_at_or_before(conn, members=members, venue=args.venue, asof_ts_utc=args.asof_ts), asof_ts_utc=args.asof_ts, venue=args.venue, interval_code="4h")
        status = persist_snapshot(conn, snapshot, authorization=authorization) if args.write_db else "DRY_RUN"
        print(f"FINISHED status={status} data_status={snapshot.data_status} eligible={snapshot.eligible_count} evaluated={snapshot.evaluated_count} above_sma50_pct={snapshot.universe_above_sma50_pct}")
        print("broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0")
        print("selection_engine=none decision_gate=none execution_planner=none executor=none")
        return 0
    finally:
        conn.close()

if __name__ == "__main__":
    raise SystemExit(main())
