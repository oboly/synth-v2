from __future__ import annotations

"""
ENGINE: run_historical_fib_map_episode_substrate_v1
MODE: historical (research-only)

Builds the canonical reusable historical PIT Fib/map episode substrate for
issue #555, for one symbol and one timeframe configuration (1h or 4h) per
invocation.

INPUT:
- obs_market_candle (SELECT only)
- asset (SELECT only)

OUTPUT:
- immutable JSON episode file under data/research/historical_fib_map_episode_substrate_v1/

CLI:
python -m src.research.run_historical_fib_map_episode_substrate_v1 \
  --venue bitvavo \
  --symbol BTC \
  --timeframe 4h \
  --from-ts "2026-01-01 00:00:00" \
  --to-ts "2026-06-01 00:00:00"

HISTORICAL:
- supported (this runner is historical-only)

SAFETY MARKERS:
research_only=1 market_only=1 account_awareness=0 decision_permission=0
execution_intent=0 broker_calls=0 broker_writes=0 orders=0 db_writes=0
production_profile_writes=0 runtime_activation=0

NOTES:
- read-only DB access; no writes of any kind to the database
- bulk fetch per symbol/timeframe, local loop (no per-candle DB queries)
- reuses src.market_data.fib_navigation_map_v1.build_fib_navigation_map for
  all Fib geometry; does not duplicate Fib math
- output files are written exactly once (atomic hardlink create); a repeat
  run with identical inputs is idempotent, a conflicting repeat run is
  refused
"""

import argparse
import hashlib
import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.research.historical_fib_map_episode_substrate_v1 import (
    BUILDER_NAME,
    BUILDER_VERSION,
    CONTRACT_VERSION,
    EpisodeRecord,
    HistoricalCandle,
    build_episodes,
    episodes_to_json,
    resolve_config,
)

DEFAULT_OUTPUT_DIR = "data/research/historical_fib_map_episode_substrate_v1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the historical PIT Fib/map episode substrate for one symbol/timeframe (#555)."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", required=True, choices=["1h", "4h"])
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--episode-stride-candles", type=int, default=1)
    parser.add_argument("--max-episodes", type=int, default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def fetch_asset_id(*, venue: str, symbol: str) -> int:
    sql = """
    SELECT asset_id
    FROM asset
    WHERE symbol = %s
    LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [symbol])
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"no asset found for symbol={symbol!r}")
    return int(row["asset_id"])


def fetch_candles(
    *,
    asset_id: int,
    symbol: str,
    venue: str,
    interval_code: str,
    from_ts: str,
    to_ts: str,
) -> list[HistoricalCandle]:
    sql = """
    SELECT
        venue,
        interval_code,
        open_ts_utc,
        close_ts_utc,
        open_price,
        high_price,
        low_price,
        close_price,
        volume_base
    FROM obs_market_candle
    WHERE asset_id = %s
      AND venue = %s
      AND interval_code = %s
      AND open_ts_utc >= %s
      AND open_ts_utc < %s
    ORDER BY open_ts_utc ASC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [asset_id, venue, interval_code, from_ts, to_ts])
            rows = cur.fetchall() or []
    finally:
        conn.close()

    return [
        HistoricalCandle(
            symbol=symbol,
            venue=str(row["venue"]),
            interval_code=str(row["interval_code"]),
            open_ts_utc=row["open_ts_utc"],
            close_ts_utc=row["close_ts_utc"],
            open_price=_to_decimal(row["open_price"]),
            high_price=_to_decimal(row["high_price"]),
            low_price=_to_decimal(row["low_price"]),
            close_price=_to_decimal(row["close_price"]),
            volume=_to_decimal(row.get("volume_base")),
        )
        for row in rows
    ]


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_immutable_json(path: Path, text: str) -> str:
    """Write `text` to `path` exactly once via atomic hardlink create.

    Idempotent for identical content on repeat runs; refuses (raises) when
    an existing file at `path` has different content.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate_sha256 = _sha256_text(text)

    if path.exists():
        existing_sha256 = _sha256_text(path.read_text(encoding="utf-8"))
        if existing_sha256 != candidate_sha256:
            raise ValueError(
                f"refusing to overwrite immutable output {path}: "
                f"existing sha256={existing_sha256} candidate sha256={candidate_sha256}"
            )
        return existing_sha256

    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as handle:
            temp_name = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        temp_path = Path(temp_name)
        try:
            os.link(temp_path, path)
        except FileExistsError:
            existing_sha256 = _sha256_text(path.read_text(encoding="utf-8"))
            if existing_sha256 != candidate_sha256:
                raise ValueError(
                    f"refusing to overwrite immutable output {path}: "
                    f"existing sha256={existing_sha256} candidate sha256={candidate_sha256}"
                ) from None
            return existing_sha256
        return candidate_sha256
    finally:
        if temp_name is not None:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass


def build_manifest(
    *,
    venue: str,
    symbol: str,
    timeframe: str,
    from_ts: str,
    to_ts: str,
    candle_count: int,
    episode_count: int,
    episodes_sha256: str,
) -> dict[str, Any]:
    return {
        "builder_name": BUILDER_NAME,
        "builder_version": BUILDER_VERSION,
        "contract_version": CONTRACT_VERSION,
        "venue": venue,
        "symbol": symbol,
        "timeframe": timeframe,
        "source_table": "obs_market_candle",
        "source_from_ts": from_ts,
        "source_to_ts": to_ts,
        "source_candle_count": candle_count,
        "episode_count": episode_count,
        "episodes_sha256": episodes_sha256,
        "safety_markers": {
            "research_only": 1,
            "market_only": 1,
            "account_awareness": 0,
            "decision_permission": 0,
            "execution_intent": 0,
            "broker_calls": 0,
            "broker_writes": 0,
            "orders": 0,
            "db_writes": 0,
            "production_profile_writes": 0,
            "runtime_activation": 0,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = resolve_config(args.timeframe)

    print(
        f"STARTED runner={BUILDER_NAME} mode=historical venue={args.venue} "
        f"symbol={args.symbol} timeframe={args.timeframe} workers=1",
        flush=True,
    )

    asset_id = fetch_asset_id(venue=args.venue, symbol=args.symbol)
    candles = fetch_candles(
        asset_id=asset_id,
        symbol=args.symbol,
        venue=args.venue,
        interval_code=cfg.interval_code,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
    )
    print(f"FETCHED source_candles={len(candles)}", flush=True)

    records: list[EpisodeRecord] = build_episodes(
        symbol=args.symbol,
        venue=args.venue,
        candles=candles,
        cfg=cfg,
        episode_stride_candles=args.episode_stride_candles,
        max_episodes=args.max_episodes,
    )
    print(f"BUILT episodes={len(records)}", flush=True)

    episodes_text = episodes_to_json(records)
    episodes_sha256 = _sha256_text(episodes_text)

    output_dir = Path(args.output_dir) / args.venue / args.symbol / cfg.interval_code
    episodes_path = output_dir / "episodes_v1.json"
    manifest_path = output_dir / "manifest_v1.json"

    write_immutable_json(episodes_path, episodes_text)

    manifest = build_manifest(
        venue=args.venue,
        symbol=args.symbol,
        timeframe=args.timeframe,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
        candle_count=len(candles),
        episode_count=len(records),
        episodes_sha256=episodes_sha256,
    )
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    write_immutable_json(manifest_path, manifest_text)

    print(
        f"FINISHED episodes={len(records)} episodes_path={episodes_path} "
        f"manifest_path={manifest_path} episodes_sha256={episodes_sha256}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
