"""Manual, fail-closed canonical MOMENTUM evidence runner (#741); no timer activation."""
from __future__ import annotations

import argparse
import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.features.momentum_evidence_snapshot_v1 import (
    build_momentum_evidence,
    fetch_candles_for_asof,
    persist_snapshot,
)

RUNNER_NAME = "momentum_evidence_snapshot_v1"


@dataclass(frozen=True)
class ResolvedMarketIdentity:
    venue: str
    market: str
    asset_id: int


def resolve_market_identity(
    conn: Any,
    *,
    venue: str,
    market: str,
    expected_asset_id: int,
) -> ResolvedMarketIdentity:
    """Resolve one canonical venue_market identity and fail closed on mismatch."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT venue, market, base_asset_id
            FROM venue_market
            WHERE venue = %s AND market = %s
            LIMIT 2
            """,
            (venue, market),
        )
        rows = cur.fetchall()

    if not rows:
        raise ValueError("CANONICAL_MARKET_NOT_FOUND")
    if len(rows) != 1:
        raise RuntimeError("CANONICAL_MARKET_AMBIGUOUS")

    row = rows[0]
    resolved = ResolvedMarketIdentity(
        venue=str(row["venue"]),
        market=str(row["market"]),
        asset_id=int(row["base_asset_id"]),
    )
    if resolved.asset_id != expected_asset_id:
        raise ValueError("CANONICAL_MARKET_ASSET_MISMATCH")
    return resolved


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
    parser = argparse.ArgumentParser(description="Compute (and optionally persist) canonical market-only MOMENTUM evidence")
    parser.add_argument("--asof-ts", required=True, type=_asof, help="Exact UTC candle close timestamp; no latest fallback")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--asset-id", required=True, type=int)
    parser.add_argument("--market", required=True, help="e.g. BTC-EUR")
    parser.add_argument("--write-db", action="store_true")
    args = parser.parse_args(argv)

    mode = "write" if args.write_db else "dry-run"
    started = time.monotonic()
    evaluated_at = datetime.now(UTC)
    conn = None
    previous_handlers = _install_signal_handlers()
    print(
        f"STARTED runner={RUNNER_NAME} mode={mode} "
        f"scope=venue:{args.venue}/asset:{args.asset_id}/market:{args.market} "
        f"worker_count=1 asof={args.asof_ts.isoformat()}",
        flush=True,
    )
    try:
        if args.write_db:
            from src.operations.writer_capability_authorization_v1 import require_capability_write_authorization

            authorization = require_capability_write_authorization("momentum_evidence_snapshot", service="UNASSIGNED")
        else:
            authorization = None
        load_dotenv()
        conn = get_db_connection()

        print(f"PHASE_START runner={RUNNER_NAME} phase=resolve_market_identity", flush=True)
        phase_started = time.monotonic()
        identity = resolve_market_identity(
            conn,
            venue=args.venue,
            market=args.market,
            expected_asset_id=args.asset_id,
        )
        print(
            f"PHASE_END runner={RUNNER_NAME} phase=resolve_market_identity "
            f"venue={identity.venue} market={identity.market} asset_id={identity.asset_id} "
            f"elapsed={_elapsed(phase_started)}",
            flush=True,
        )

        print(f"PHASE_START runner={RUNNER_NAME} phase=fetch_candles", flush=True)
        phase_started = time.monotonic()
        candles = fetch_candles_for_asof(
            conn,
            asset_id=identity.asset_id,
            venue=identity.venue,
            asof_ts_utc=args.asof_ts,
        )
        print(
            f"PHASE_END runner={RUNNER_NAME} phase=fetch_candles rows={len(candles)} "
            f"elapsed={_elapsed(phase_started)}",
            flush=True,
        )

        print(f"PHASE_START runner={RUNNER_NAME} phase=build_evidence", flush=True)
        phase_started = time.monotonic()
        snapshot = build_momentum_evidence(
            candles=candles,
            asof_ts_utc=args.asof_ts,
            evaluated_at=evaluated_at,
            venue=identity.venue,
            asset_id=identity.asset_id,
            market=identity.market,
            interval_code="4h",
        )
        print(f"PHASE_END runner={RUNNER_NAME} phase=build_evidence elapsed={_elapsed(phase_started)}", flush=True)
        write_status = persist_snapshot(conn, snapshot, authorization=authorization) if args.write_db else "DRY_RUN"
        print(
            f"FINISHED runner={RUNNER_NAME} status={write_status} data_quality={snapshot.data_quality} "
            f"evidence_status={snapshot.status} macd_value={snapshot.macd_value} "
            f"histogram_delta={snapshot.histogram_delta} elapsed={_elapsed(started)}",
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
