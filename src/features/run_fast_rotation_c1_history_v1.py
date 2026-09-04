"""Manual C1 fast Rotation history materializer for Issue #733.

Implementation only. No timer/service/runtime activation is introduced here.
Dry-run is the default. Database mutation additionally requires the separate
writer-capability authorization owned by operations.
"""

from __future__ import annotations

import argparse
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
LOOKBACK = timedelta(minutes=135)
CANDLE_FETCH_BATCH_SIZE = 5000


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


def fetch_market_identities(conn: Any, *, venue: str) -> dict[int, str]:
    """Resolve exactly one canonical tradeable venue market per asset.

    Ambiguity fails closed; a C1 row may never be persisted against an
    arbitrary market label.
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
    return market_by_asset


def fetch_candles(
    conn: Any,
    *,
    venue: str,
    asset_ids: tuple[int, ...],
    asof_ts: datetime,
    batch_size: int = CANDLE_FETCH_BATCH_SIZE,
) -> dict[int, list[Candle]]:
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    if not asset_ids:
        return {}

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
    with conn.cursor() as cur:
        cur.execute(sql, params)
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            for row in rows:
                asset_id = int(row["asset_id"])
                candles[asset_id].append(
                    Candle(
                        close_ts_utc=ensure_utc(row["close_ts_utc"]),
                        close_price=Decimal(str(row["close_price"])),
                        volume_base=Decimal(str(row["volume_base"])),
                    )
                )
    return candles


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

    print(
        f"STARTED runner={RUNNER_NAME} mode={mode} venue={args.venue} asof={args.asof_ts.isoformat()} ",
        "candidate=C1 account_awareness=0 selection_engine=none decision_gate=none ",
        "execution_planner=none executor=none broker_private_calls=0 broker_writes=0 order_submission=0",
        sep="",
        flush=True,
    )

    try:
        replay_sha = verify_frozen_replay_source()

        if args.write_db:
            from src.operations.writer_capability_authorization_v1 import require_capability_write_authorization

            authorization = require_capability_write_authorization(
                "fast_rotation_c1_history", service="UNASSIGNED"
            )
        else:
            authorization = None

        load_dotenv(dotenv_path=".env", override=False)
        conn = get_db_connection()
        market_by_asset = fetch_market_identities(conn, venue=args.venue)
        asset_ids = tuple(sorted(market_by_asset))
        candles_by_asset = fetch_candles(
            conn,
            venue=args.venue,
            asset_ids=asset_ids,
            asof_ts=args.asof_ts,
        )
        results = evaluate_candidate(
            candles_by_asset=candles_by_asset,
            asof_ts=args.asof_ts,
            spec=c1_spec(),
            venue=args.venue,
        )
        observations = materialize_observations(results, market_by_asset=market_by_asset)

        complete = sum(row.data_quality == "COMPLETE" for row in observations)
        insufficient = len(observations) - complete
        if args.write_db:
            created, existing = persist_observations(
                conn,
                observations,
                authorization=authorization,
            )
            persist_state = f"created={created} existing={existing}"
        else:
            persist_state = "created=0 existing=0"

        print(
            f"FINISHED runner={RUNNER_NAME} mode={mode} rows={len(observations)} complete={complete} "
            f"insufficient={insufficient} {persist_state} frozen_replay_sha256={replay_sha} "
            f"elapsed_s={time.monotonic() - started:.3f}",
            flush=True,
        )
        return 0
    except Exception as exc:
        print(
            f"FAILED runner={RUNNER_NAME} error_type={type(exc).__name__} "
            f"elapsed_s={time.monotonic() - started:.3f}",
            flush=True,
        )
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
