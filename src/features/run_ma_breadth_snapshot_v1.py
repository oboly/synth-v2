"""Manual, fail-closed canonical MA breadth snapshot runner; no timer activation."""
from __future__ import annotations

import argparse
import signal
import time
from datetime import UTC, datetime

from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.features.ma_breadth_snapshot_v1 import (
    build_snapshot,
    fetch_candles_at_or_before,
    fetch_universe_members,
    persist_snapshot,
)

RUNNER_NAME = "ma_breadth_snapshot_v1"


def _asof(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("--asof-ts must include UTC timezone")
    return parsed.astimezone(UTC)


def _elapsed(started: float) -> str:
    return f"{time.monotonic() - started:.3f}s"


def _install_signal_handlers() -> dict[int, signal.Handlers]:
    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}

    def interrupt(signum: int, _frame: object) -> None:
        raise KeyboardInterrupt(signal.Signals(signum).name)

    for signum in previous:
        signal.signal(signum, interrupt)
    return previous


def _restore_signal_handlers(previous: dict[int, signal.Handlers]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _interruption_signal(exc: KeyboardInterrupt) -> str:
    name = str(exc)
    return name if name in {"SIGINT", "SIGTERM"} else "SIGINT"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Persist canonical market-only MA50 breadth snapshot")
    parser.add_argument("--asof-ts", required=True, type=_asof, help="Exact UTC candle close timestamp; no latest fallback")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--write-db", action="store_true")
    args = parser.parse_args(argv)

    mode = "write" if args.write_db else "dry-run"
    started = time.monotonic()
    conn = None
    previous_handlers = _install_signal_handlers()
    print(
        f"STARTED runner={RUNNER_NAME} mode={mode} "
        f"scope=venue:{args.venue} worker_count=1 asof={args.asof_ts.isoformat()}",
        flush=True,
    )
    try:
        if args.write_db:
            from src.operations.writer_capability_authorization_v1 import require_capability_write_authorization

            authorization = require_capability_write_authorization("ma_breadth_snapshot", service="UNASSIGNED")
        else:
            authorization = None
        load_dotenv()
        conn = get_db_connection()

        print(f"PHASE_START runner={RUNNER_NAME} phase=fetch_universe", flush=True)
        phase_started = time.monotonic()
        members = fetch_universe_members(conn, venue=args.venue)
        print(
            f"PHASE_END runner={RUNNER_NAME} phase=fetch_universe rows={len(members)} "
            f"elapsed={_elapsed(phase_started)}",
            flush=True,
        )

        print(f"PHASE_START runner={RUNNER_NAME} phase=fetch_candles", flush=True)
        phase_started = time.monotonic()
        candles = fetch_candles_at_or_before(
            conn, members=members, venue=args.venue, asof_ts_utc=args.asof_ts
        )
        print(
            f"PHASE_END runner={RUNNER_NAME} phase=fetch_candles rows={len(candles)} "
            f"elapsed={_elapsed(phase_started)}",
            flush=True,
        )

        print(f"PHASE_START runner={RUNNER_NAME} phase=build_snapshot", flush=True)
        phase_started = time.monotonic()
        snapshot = build_snapshot(
            members=members, candles=candles, asof_ts_utc=args.asof_ts,
            venue=args.venue, interval_code="4h",
        )
        print(f"PHASE_END runner={RUNNER_NAME} phase=build_snapshot elapsed={_elapsed(phase_started)}", flush=True)
        status = persist_snapshot(conn, snapshot, authorization=authorization) if args.write_db else "DRY_RUN"
        print(
            f"FINISHED runner={RUNNER_NAME} status={status} data_status={snapshot.data_status} "
            f"eligible={snapshot.eligible_count} evaluated={snapshot.evaluated_count} "
            f"above_sma50_pct={snapshot.universe_above_sma50_pct} elapsed={_elapsed(started)}",
            flush=True,
        )
        print("broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0", flush=True)
        print("selection_engine=none decision_gate=none execution_planner=none executor=none", flush=True)
        return 0
    except KeyboardInterrupt as exc:
        print(
            f"INTERRUPTED runner={RUNNER_NAME} signal={_interruption_signal(exc)} elapsed={_elapsed(started)}",
            flush=True,
        )
        return 130
    except Exception as exc:
        print(
            f"FAILED runner={RUNNER_NAME} error_type={type(exc).__name__} elapsed={_elapsed(started)}",
            flush=True,
        )
        return 1
    finally:
        if conn is not None:
            conn.close()
        _restore_signal_handlers(previous_handlers)


if __name__ == "__main__":
    raise SystemExit(main())
