"""Manual C1 fast Rotation history materializer for Issue #733.

Implementation only. No timer/service/runtime activation is introduced here.
Dry-run is the default. Database mutation additionally requires the separate
writer-capability authorization owned by operations.
"""

from __future__ import annotations

import argparse
import signal
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.features.fast_rotation_c1_history_v1 import (
    CANDIDATE_ID,
    materialize_observations,
    persist_observations,
    verify_frozen_replay_source,
)
from src.research.multi_horizon_rotation_replay_v1 import (
    CANDIDATE_SPECS,
    Candle,
    evaluate_candidate,
    ensure_utc,
    is_on_15m_close_grid,
)

RUNNER_NAME = "fast_rotation_c1_history_v1"
VENUE = "bitvavo"
WORKER_COUNT = 1
LOOKBACK = timedelta(minutes=135)
CANDLE_FETCH_BATCH_SIZE = 5000
HEARTBEAT_INTERVAL_S = 15.0
SAFETY_LINE = (
    "market_only=1 account_awareness=0 selection_engine=none decision_gate=none "
    "execution_planner=none executor=none broker_private_calls=0 broker_writes=0 "
    "order_submission=0 live_orders=0 production_activation=0"
)


def emit(message: str) -> None:
    print(message, flush=True)


def parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include UTC timezone")
    parsed = parsed.astimezone(UTC)
    if not is_on_15m_close_grid(parsed):
        raise argparse.ArgumentTypeError("timestamp must be on the canonical 15m close grid")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize one canonical #733 C1 Rotation history as-of; dry-run by default"
    )
    parser.add_argument("--asof-ts", required=True, type=parse_ts)
    parser.add_argument("--venue", default=VENUE, choices=(VENUE,))
    parser.add_argument("--write-db", action="store_true")
    return parser.parse_args(argv)


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


def _phase_start(name: str, *, query_count: int, rows_read: int) -> float:
    emit(
        f"PHASE_START runner={RUNNER_NAME} phase={name} query_count={query_count} "
        f"rows_read={rows_read}"
    )
    return time.monotonic()


def _phase_end(
    name: str,
    phase_started: float,
    *,
    query_count: int,
    rows_read: int,
    extra: str = "",
) -> None:
    suffix = f" {extra}" if extra else ""
    emit(
        f"PHASE_END runner={RUNNER_NAME} phase={name} elapsed_s={time.monotonic() - phase_started:.3f} "
        f"query_count={query_count} rows_read={rows_read}{suffix}"
    )


def _heartbeat(
    *,
    phase: str,
    started: float,
    query_count: int,
    rows_read: int,
    force: bool = True,
) -> float:
    now = time.monotonic()
    if force:
        emit(
            f"HEARTBEAT runner={RUNNER_NAME} phase={phase} elapsed_s={now - started:.3f} "
            f"worker_count={WORKER_COUNT} query_count={query_count} rows_read={rows_read}"
        )
    return now


def fetch_market_identities(conn: Any, *, venue: str) -> tuple[dict[int, str], int]:
    """Resolve exactly one canonical tradeable venue market per asset.

    Ambiguity fails closed; a C1 row may never be persisted against an
    arbitrary market label. Returns `(market_by_asset, source_rows_read)`.
    """
    sql = """
    SELECT vm.base_asset_id AS asset_id, vm.market AS market
    FROM venue_market vm
    JOIN asset a ON a.asset_id = vm.base_asset_id
    WHERE vm.venue = %s
      AND vm.is_tradeable = 1
      AND a.is_enabled = 1
      AND COALESCE(a.is_tradeable, 0) = 1
    ORDER BY vm.base_asset_id, vm.market
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue,))
        rows = cur.fetchall()

    market_by_asset: dict[int, str] = {}
    for row in rows:
        asset_id = int(row["asset_id"])
        market = str(row["market"])
        previous = market_by_asset.get(asset_id)
        if previous is not None and previous != market:
            raise ValueError(
                f"ambiguous canonical venue_market for asset_id={asset_id}: {previous!r}, {market!r}"
            )
        market_by_asset[asset_id] = market
    if not market_by_asset:
        raise ValueError(f"no canonical tradeable venue markets for venue={venue!r}")
    return market_by_asset, len(rows)


def fetch_candles(
    conn: Any,
    *,
    venue: str,
    asset_ids: tuple[int, ...],
    asof_ts: datetime,
    runner_started: float,
    query_count: int,
    rows_read_before: int,
    batch_size: int = CANDLE_FETCH_BATCH_SIZE,
) -> tuple[dict[int, list[Candle]], int]:
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    if not asset_ids:
        return {}, 0

    start = ensure_utc(asof_ts) - LOOKBACK
    end = ensure_utc(asof_ts)
    placeholders = ",".join(["%s"] * len(asset_ids))
    sql = f"""
    SELECT asset_id, close_ts_utc, close_price, volume_base
    FROM obs_market_candle
    WHERE venue = %s
      AND interval_code = '15m'
      AND asset_id IN ({placeholders})
      AND close_ts_utc >= %s
      AND close_ts_utc <= %s
    ORDER BY asset_id, close_ts_utc
    """
    params: tuple[Any, ...] = (
        venue,
        *asset_ids,
        start.replace(tzinfo=None),
        end.replace(tzinfo=None),
    )

    candles: dict[int, list[Candle]] = {asset_id: [] for asset_id in asset_ids}
    source_rows_read = 0
    last_heartbeat = time.monotonic()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            source_rows_read += len(rows)
            for row in rows:
                asset_id = int(row["asset_id"])
                candles[asset_id].append(
                    Candle(
                        close_ts_utc=ensure_utc(row["close_ts_utc"]),
                        close_price=Decimal(str(row["close_price"])),
                        volume_base=Decimal(str(row["volume_base"])),
                    )
                )
            now = time.monotonic()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
                last_heartbeat = _heartbeat(
                    phase="fetch_candles",
                    started=runner_started,
                    query_count=query_count,
                    rows_read=rows_read_before + source_rows_read,
                )
    return candles, source_rows_read


def c1_spec() -> Any:
    matches = [spec for spec in CANDIDATE_SPECS if spec.candidate_id == CANDIDATE_ID]
    if len(matches) != 1:
        raise RuntimeError("frozen C1 candidate spec is missing or ambiguous")
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = "write" if args.write_db else "dry-run"
    started = time.monotonic()
    conn = None
    query_count = 0
    rows_read = 0
    previous_handlers = _install_signal_handlers()

    emit(
        f"STARTED runner={RUNNER_NAME} mode={mode} venue={args.venue} asof={args.asof_ts.isoformat()} "
        f"candidate=C1 worker_count={WORKER_COUNT}"
    )
    emit(f"SAFETY runner={RUNNER_NAME} {SAFETY_LINE}")

    try:
        phase_started = _phase_start("verify_frozen_replay_source", query_count=query_count, rows_read=rows_read)
        replay_sha = verify_frozen_replay_source()
        _phase_end(
            "verify_frozen_replay_source",
            phase_started,
            query_count=query_count,
            rows_read=rows_read,
            extra=f"replay_sha256={replay_sha}",
        )
        _heartbeat(
            phase="verify_frozen_replay_source",
            started=started,
            query_count=query_count,
            rows_read=rows_read,
        )

        phase_started = _phase_start("authorize", query_count=query_count, rows_read=rows_read)
        if args.write_db:
            from src.operations.writer_capability_authorization_v1 import require_capability_write_authorization

            authorization = require_capability_write_authorization(
                "fast_rotation_c1_history", service="UNASSIGNED"
            )
        else:
            authorization = None
        _phase_end("authorize", phase_started, query_count=query_count, rows_read=rows_read)

        phase_started = _phase_start("connect_db", query_count=query_count, rows_read=rows_read)
        load_dotenv(dotenv_path=".env", override=False)
        conn = get_db_connection()
        _phase_end("connect_db", phase_started, query_count=query_count, rows_read=rows_read)

        phase_started = _phase_start("resolve_markets", query_count=query_count, rows_read=rows_read)
        market_by_asset, market_rows = fetch_market_identities(conn, venue=args.venue)
        query_count += 1
        rows_read += market_rows
        asset_ids = tuple(sorted(market_by_asset))
        evaluated_universe_size = len(asset_ids)
        _phase_end(
            "resolve_markets",
            phase_started,
            query_count=query_count,
            rows_read=rows_read,
            extra=f"evaluated_universe_size={evaluated_universe_size}",
        )
        _heartbeat(
            phase="resolve_markets",
            started=started,
            query_count=query_count,
            rows_read=rows_read,
        )

        phase_started = _phase_start("fetch_candles", query_count=query_count, rows_read=rows_read)
        next_query_count = query_count + 1
        candles_by_asset, candle_rows = fetch_candles(
            conn,
            venue=args.venue,
            asset_ids=asset_ids,
            asof_ts=args.asof_ts,
            runner_started=started,
            query_count=next_query_count,
            rows_read_before=rows_read,
        )
        query_count = next_query_count
        rows_read += candle_rows
        _phase_end(
            "fetch_candles",
            phase_started,
            query_count=query_count,
            rows_read=rows_read,
            extra=f"candle_rows={candle_rows}",
        )
        _heartbeat(
            phase="fetch_candles",
            started=started,
            query_count=query_count,
            rows_read=rows_read,
        )

        phase_started = _phase_start("evaluate_c1", query_count=query_count, rows_read=rows_read)
        results = evaluate_candidate(
            candles_by_asset=candles_by_asset,
            asof_ts=args.asof_ts,
            spec=c1_spec(),
            venue=args.venue,
        )
        _phase_end(
            "evaluate_c1",
            phase_started,
            query_count=query_count,
            rows_read=rows_read,
            extra=f"result_count={len(results)}",
        )

        phase_started = _phase_start("materialize", query_count=query_count, rows_read=rows_read)
        observations = materialize_observations(
            results,
            market_by_asset=market_by_asset,
            evaluated_universe_size=evaluated_universe_size,
        )
        complete = sum(row.data_quality == "COMPLETE" for row in observations)
        insufficient = len(observations) - complete
        coverage_ratio = observations[0].coverage_ratio if observations else Decimal("0")
        _phase_end(
            "materialize",
            phase_started,
            query_count=query_count,
            rows_read=rows_read,
            extra=(
                f"rows={len(observations)} complete={complete} insufficient={insufficient} "
                f"coverage_ratio={coverage_ratio}"
            ),
        )
        _heartbeat(
            phase="materialize",
            started=started,
            query_count=query_count,
            rows_read=rows_read,
        )

        if args.write_db:
            phase_started = _phase_start("persist", query_count=query_count, rows_read=rows_read)
            created, existing = persist_observations(
                conn,
                observations,
                authorization=authorization,
            )
            _phase_end(
                "persist",
                phase_started,
                query_count=query_count,
                rows_read=rows_read,
                extra=f"created={created} existing={existing}",
            )
            persist_state = f"created={created} existing={existing}"
        else:
            persist_state = "created=0 existing=0"

        emit(
            f"FINISHED runner={RUNNER_NAME} mode={mode} rows={len(observations)} complete={complete} "
            f"insufficient={insufficient} evaluated_universe_size={evaluated_universe_size} "
            f"coverage_ratio={coverage_ratio} {persist_state} query_count={query_count} rows_read={rows_read} "
            f"worker_count={WORKER_COUNT} frozen_replay_sha256={replay_sha} "
            f"elapsed_s={time.monotonic() - started:.3f}"
        )
        return 0
    except KeyboardInterrupt as exc:
        emit(
            f"INTERRUPTED runner={RUNNER_NAME} signal={_interruption_signal(exc)} query_count={query_count} "
            f"rows_read={rows_read} worker_count={WORKER_COUNT} elapsed_s={time.monotonic() - started:.3f}"
        )
        return 130
    except Exception as exc:
        emit(
            f"FAILED runner={RUNNER_NAME} error_type={type(exc).__name__} query_count={query_count} "
            f"rows_read={rows_read} worker_count={WORKER_COUNT} elapsed_s={time.monotonic() - started:.3f}"
        )
        return 1
    finally:
        if conn is not None:
            conn.close()
        _restore_signal_handlers(previous_handlers)


if __name__ == "__main__":
    raise SystemExit(main())
