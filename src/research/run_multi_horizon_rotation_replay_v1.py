from __future__ import annotations

"""Bounded read-only replay runner for Issue #593 multi-horizon Rotation research."""

import argparse
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.research.multi_horizon_rotation_replay_v1 import (
    CANDIDATE_SPECS,
    Candle,
    evaluate_candidate,
)


RUNNER_NAME = "run_multi_horizon_rotation_replay_v1"
RUNNER_VERSION = "0.1"
MAX_LOOKBACK = timedelta(hours=36)


def emit(message: str) -> None:
    print(message, flush=True)


def parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raise TypeError(type(value).__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only #593 C1/C2/C3 replay at one historical as-of")
    parser.add_argument("--asof", required=True, help="UTC ISO timestamp on exact 15m close grid")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--candidate", action="append", choices=[spec.candidate_id for spec in CANDIDATE_SPECS])
    return parser.parse_args(argv)


def fetch_candles(conn: Any, *, venue: str, asof_ts: datetime) -> dict[int, list[Candle]]:
    start_ts = asof_ts - MAX_LOOKBACK
    sql = """
    SELECT asset_id, close_ts_utc, close_price, volume_base
    FROM obs_market_candle
    WHERE venue = %s
      AND interval_code = '15m'
      AND close_ts_utc >= %s
      AND close_ts_utc <= %s
    ORDER BY asset_id, close_ts_utc
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, start_ts.replace(tzinfo=None), asof_ts.replace(tzinfo=None)))
        rows = cur.fetchall()

    out: dict[int, list[Candle]] = {}
    for row in rows:
        asset_id = int(row["asset_id"])
        ts = row["close_ts_utc"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        else:
            ts = ts.astimezone(UTC)
        out.setdefault(asset_id, []).append(
            Candle(
                close_ts_utc=ts,
                close_price=Decimal(str(row["close_price"])),
                volume_base=Decimal(str(row["volume_base"])),
            )
        )
    return out


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(dotenv_path=".env", override=False)
    started = time.perf_counter()
    asof = parse_ts(args.asof)
    requested = set(args.candidate or [spec.candidate_id for spec in CANDIDATE_SPECS])
    specs = [spec for spec in CANDIDATE_SPECS if spec.candidate_id in requested]

    emit(
        f"STARTED runner={RUNNER_NAME} version={RUNNER_VERSION} mode=read_only "
        f"venue={args.venue} asof={asof.isoformat()} candidates={','.join(spec.candidate_id for spec in specs)}"
    )

    conn = None
    try:
        emit("PHASE_STARTED name=fetch_canonical_15m_candles")
        conn = get_db_connection()
        candles_by_asset = fetch_candles(conn, venue=args.venue, asof_ts=asof)
        emit(
            f"PHASE_FINISHED name=fetch_canonical_15m_candles asset_count={len(candles_by_asset)} "
            f"elapsed_s={time.perf_counter() - started:.3f}"
        )

        total_rows = 0
        complete_rows = 0
        for spec in specs:
            emit(f"PHASE_STARTED name=evaluate_candidate candidate={spec.candidate_id}")
            results = evaluate_candidate(candles_by_asset=candles_by_asset, asof_ts=asof, spec=spec)
            for result in results:
                emit(json.dumps(asdict(result), sort_keys=True, default=json_default))
            complete = sum(result.data_quality == "COMPLETE" for result in results)
            total_rows += len(results)
            complete_rows += complete
            emit(
                f"PHASE_FINISHED name=evaluate_candidate candidate={spec.candidate_id} "
                f"rows={len(results)} complete={complete}"
            )

        emit(
            f"FINISHED runner={RUNNER_NAME} result=PASS rows={total_rows} complete={complete_rows} "
            f"database_writes=0 account_awareness=0 broker_private_calls=0 broker_writes=0 "
            f"order_submission=0 elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 0
    except KeyboardInterrupt:
        emit(
            f"INTERRUPTED runner={RUNNER_NAME} database_writes=0 account_awareness=0 "
            f"broker_private_calls=0 broker_writes=0 order_submission=0 "
            f"elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 130
    except Exception as exc:
        emit(
            f"FAILED runner={RUNNER_NAME} error={exc.__class__.__name__}:{exc} "
            f"database_writes=0 account_awareness=0 broker_private_calls=0 broker_writes=0 "
            f"order_submission=0 elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
