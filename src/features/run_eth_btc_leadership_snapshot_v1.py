"""Manual, fail-closed canonical ETH/BTC leadership snapshot runner (#721);
no timer/service activation."""
from __future__ import annotations

import argparse
import signal
import time
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.features.eth_btc_leadership_snapshot_v1 import (
    INPUT_INTERVAL,
    BTC_SYMBOL,
    ETH_SYMBOL,
    build_snapshot,
    fetch_asset_boundary,
    fetch_btc_eth_markets,
    persist_snapshot,
)

RUNNER_NAME = "eth_btc_leadership_snapshot_v1"
LOOKBACK_DELTA = timedelta(hours=24)


def _asof(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include UTC timezone")
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
    parser = argparse.ArgumentParser(
        description="Persist canonical market-only ETH/BTC leadership snapshot (#721, under #305)"
    )
    parser.add_argument("--asof-ts", required=True, type=_asof, help="Exact UTC candle close timestamp; no latest fallback")
    parser.add_argument(
        "--evaluated-at",
        type=_asof,
        default=None,
        help="Replay evaluation instant; omit only for a live run (defaults to current UTC time)",
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--write-db", action="store_true")
    args = parser.parse_args(argv)

    evaluated_at = args.evaluated_at if args.evaluated_at is not None else datetime.now(UTC)
    mode = "write" if args.write_db else "dry-run"
    started = time.monotonic()
    conn = None
    previous_handlers = _install_signal_handlers()
    print(
        f"STARTED runner={RUNNER_NAME} mode={mode} scope=venue:{args.venue} "
        f"worker_count=1 asof={args.asof_ts.isoformat()} evaluated_at={evaluated_at.isoformat()}",
        flush=True,
    )
    try:
        if args.write_db:
            from src.operations.writer_capability_authorization_v1 import require_capability_write_authorization

            authorization = require_capability_write_authorization(
                "eth_btc_leadership_snapshot", service="UNASSIGNED"
            )
        else:
            authorization = None
        load_dotenv()
        conn = get_db_connection()

        print(f"PHASE_START runner={RUNNER_NAME} phase=resolve_markets", flush=True)
        phase_started = time.monotonic()
        markets = fetch_btc_eth_markets(conn, venue=args.venue)
        btc_asset_id = int(markets[BTC_SYMBOL]["asset_id"])
        eth_asset_id = int(markets[ETH_SYMBOL]["asset_id"])
        btc_market = str(markets[BTC_SYMBOL]["market"])
        eth_market = str(markets[ETH_SYMBOL]["market"])
        print(
            f"PHASE_END runner={RUNNER_NAME} phase=resolve_markets "
            f"btc_market={btc_market} eth_market={eth_market} elapsed={_elapsed(phase_started)}",
            flush=True,
        )

        lookback_ts = args.asof_ts - LOOKBACK_DELTA
        print(f"PHASE_START runner={RUNNER_NAME} phase=fetch_candle_boundaries", flush=True)
        phase_started = time.monotonic()
        btc_asof_row = fetch_asset_boundary(
            conn, venue=args.venue, interval_code=INPUT_INTERVAL, asset_id=btc_asset_id, expected_close_ts_utc=args.asof_ts
        )
        eth_asof_row = fetch_asset_boundary(
            conn, venue=args.venue, interval_code=INPUT_INTERVAL, asset_id=eth_asset_id, expected_close_ts_utc=args.asof_ts
        )
        btc_lookback_row = fetch_asset_boundary(
            conn, venue=args.venue, interval_code=INPUT_INTERVAL, asset_id=btc_asset_id, expected_close_ts_utc=lookback_ts
        )
        eth_lookback_row = fetch_asset_boundary(
            conn, venue=args.venue, interval_code=INPUT_INTERVAL, asset_id=eth_asset_id, expected_close_ts_utc=lookback_ts
        )
        print(f"PHASE_END runner={RUNNER_NAME} phase=fetch_candle_boundaries elapsed={_elapsed(phase_started)}", flush=True)

        print(f"PHASE_START runner={RUNNER_NAME} phase=build_snapshot", flush=True)
        phase_started = time.monotonic()
        snapshot = build_snapshot(
            btc_asof_row=btc_asof_row,
            eth_asof_row=eth_asof_row,
            btc_lookback_row=btc_lookback_row,
            eth_lookback_row=eth_lookback_row,
            asof_ts_utc=args.asof_ts,
            lookback_ts_utc=lookback_ts,
            evaluated_at=evaluated_at,
            venue=args.venue,
            interval_code=INPUT_INTERVAL,
            btc_market=btc_market,
            eth_market=eth_market,
        )
        print(f"PHASE_END runner={RUNNER_NAME} phase=build_snapshot elapsed={_elapsed(phase_started)}", flush=True)

        status = persist_snapshot(conn, snapshot, authorization=authorization) if args.write_db else "DRY_RUN"
        print(
            f"FINISHED runner={RUNNER_NAME} status={status} freshness={snapshot.freshness} "
            f"data_status={snapshot.data_status} eth_minus_btc_return_pct={snapshot.eth_minus_btc_return_pct} "
            f"reason_codes={list(snapshot.reason_codes)} elapsed={_elapsed(started)}",
            flush=True,
        )
        print("broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0", flush=True)
        print("selection_engine=none decision_gate=none execution_planner=none executor=none", flush=True)
        return 0
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 1
        print(
            f"FAILED runner={RUNNER_NAME} error_type=SystemExit exit_code={exit_code} elapsed={_elapsed(started)}",
            flush=True,
        )
        return exit_code
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
