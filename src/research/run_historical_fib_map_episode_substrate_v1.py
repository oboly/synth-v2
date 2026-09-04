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
- immutable JSON episode file under
  data/research/historical_fib_map_episode_substrate_v1/<venue>/<symbol>/<timeframe>/<run_id>/
  where <run_id> is a SHA-256 of the canonical JSON of every dataset-defining
  parameter (builder_version, contract_version, venue, symbol, timeframe,
  from_ts, to_ts, episode_stride_candles, max_episodes) -- see
  compute_run_id(). This keeps two runs with different bounds/stride/limit
  from ever aliasing the same immutable path. Operational parameters that do
  not change the emitted dataset (warmup candle count, DB fetch chunk size)
  are deliberately excluded from run_id -- see "Warmup and Run Identity"
  below.

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
- bounded/chunked SELECT retrieval per symbol/timeframe (no unbounded
  fetchall over arbitrary-duration windows), local loop, no worker pool
- reuses src.market_data.fib_navigation_map_v1.build_fib_navigation_map for
  all Fib geometry; does not duplicate Fib math
- output files are written exactly once (atomic hardlink create); a repeat
  run with identical inputs is idempotent, a conflicting repeat run is
  refused; nothing is written unless the full build completes successfully

Warmup and Run Identity:
- The requested `[--from-ts, --to-ts)` window is a RESEARCH OUTPUT bound,
  not a feature-input bound. Reconstructing the canonical PIT trend/EMA and
  Fib-anchor window for an as-of candle near --from-ts requires the same
  `cfg.lookback_candles` candles of history a run with an earlier --from-ts
  would have used for that identical as-of candle -- otherwise the same
  as-of candle can silently produce a different trend/anchor outcome
  depending only on what the caller asked for, not on the market itself.
- To make as-of feature output invariant to the requested --from-ts, this
  runner fetches `cfg.lookback_candles - 1` extra candles strictly before
  --from-ts as PRE-BOUND WARMUP (fetch_warmup_candles). Warmup candles are
  feature input only: build_episodes still scans them to build up
  window/stride state, but they can never themselves produce an emitted
  episode (see build_episodes' emit_from_ts_utc/emit_to_ts_utc filter).
- No candle at/after --to-ts is ever fetched -- warmup only extends the
  window backwards, never forwards; no future data is used.
- No current-state snapshot table is read; warmup is exclusively historical
  `obs_market_candle` rows below --from-ts.
- Warmup candle count and DB fetch chunk size are operational retrieval
  parameters, not dataset-defining parameters: for fixed
  (builder_version, contract_version, venue, symbol, timeframe, from_ts,
  to_ts, episode_stride_candles, max_episodes), the emitted episode set is
  identical regardless of chunk size or of how much of the *available*
  warmup history exists. compute_run_id() therefore does not include them.
  The actual fetch window (including how much warmup was actually
  available) and the chunk size used are recorded in the manifest for
  provenance, not identity.
"""

import argparse
import hashlib
import json
import os
import signal
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

from src.common.db import get_connection
from src.research.historical_fib_map_episode_substrate_v1 import (
    BUILDER_NAME,
    BUILDER_VERSION,
    CONTRACT_VERSION,
    EpisodeConfig,
    EpisodeRecord,
    HistoricalCandle,
    build_episodes,
    episodes_to_json,
    resolve_config,
)

DEFAULT_OUTPUT_DIR = "data/research/historical_fib_map_episode_substrate_v1"

# Bounds one DB round trip's row volume; independent of dataset identity
# (see "Warmup and Run Identity" above -- deliberately excluded from
# compute_run_id).
DEFAULT_CHUNK_CANDLES = 5000


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
    parser.add_argument("--chunk-size-candles", type=int, default=DEFAULT_CHUNK_CANDLES)
    return parser.parse_args(argv)


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def normalize_db_datetime_to_utc(value: datetime) -> datetime:
    """Canonicalize a MariaDB datetime value to a UTC-aware datetime.

    obs_market_candle timestamp columns are stored naive; the driver may
    return either a naive datetime (treated as UTC, the DB storage
    convention) or, depending on connector/session settings, a
    timezone-aware one (converted to UTC). Without this normalization,
    HistoricalCandle timestamps -- and therefore episode identity via
    compute_episode_id's isoformat() serialization -- would silently depend
    on the connector/session/host timezone rather than being deterministic.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_ts_arg(text: str, *, name: str) -> datetime:
    """Parse a CLI --from-ts/--to-ts value into a UTC-aware datetime.

    Applies the same naive-means-UTC canonicalization as
    normalize_db_datetime_to_utc so requested-window comparisons
    (validate_args, build_episodes' emit_from_ts_utc/emit_to_ts_utc) use the
    identical UTC convention as the DB-sourced candle timestamps they are
    compared against.
    """
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid {name} {text!r}: expected an ISO-8601 timestamp") from exc
    return normalize_db_datetime_to_utc(parsed)


def validate_args(args: argparse.Namespace) -> None:
    """Reject invalid CLI arguments before any DB connection/query is made.

    Must be called before fetch_asset_id/fetch_warmup_candles/fetch_candles.
    """
    if args.episode_stride_candles <= 0:
        raise ValueError(
            f"--episode-stride-candles must be > 0, got {args.episode_stride_candles}"
        )
    if args.max_episodes is not None and args.max_episodes < 0:
        raise ValueError(f"--max-episodes must be omitted or >= 0, got {args.max_episodes}")
    if args.chunk_size_candles <= 0:
        raise ValueError(f"--chunk-size-candles must be > 0, got {args.chunk_size_candles}")

    from_ts_dt = parse_ts_arg(args.from_ts, name="--from-ts")
    to_ts_dt = parse_ts_arg(args.to_ts, name="--to-ts")
    if not from_ts_dt < to_ts_dt:
        raise ValueError(
            f"--from-ts ({args.from_ts}) must be strictly earlier than --to-ts ({args.to_ts})"
        )


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


def _row_to_candle(row: Mapping[str, Any], *, symbol: str) -> HistoricalCandle:
    return HistoricalCandle(
        symbol=symbol,
        venue=str(row["venue"]),
        interval_code=str(row["interval_code"]),
        open_ts_utc=normalize_db_datetime_to_utc(row["open_ts_utc"]),
        close_ts_utc=normalize_db_datetime_to_utc(row["close_ts_utc"]),
        open_price=_to_decimal(row["open_price"]),
        high_price=_to_decimal(row["high_price"]),
        low_price=_to_decimal(row["low_price"]),
        close_price=_to_decimal(row["close_price"]),
        volume=_to_decimal(row.get("volume_base")),
    )


_CANDLE_COLUMNS = """
        venue,
        interval_code,
        open_ts_utc,
        close_ts_utc,
        open_price,
        high_price,
        low_price,
        close_price,
        volume_base"""


def fetch_warmup_candles(
    *,
    asset_id: int,
    symbol: str,
    venue: str,
    interval_code: str,
    before_ts: str,
    limit: int,
) -> list[HistoricalCandle]:
    """Fetch up to `limit` candles strictly before `before_ts` (SELECT only).

    Bounded by construction (LIMIT `limit`, a small config-derived count --
    see the "Warmup and Run Identity" module docstring section), so this is
    always a single bounded round trip, never an unbounded fetchall over an
    arbitrary-duration window. Returns candles in ascending open_ts_utc
    order (the query itself runs DESC to get the `limit` candles nearest
    `before_ts`, then the result is reversed).
    """
    if limit <= 0:
        return []

    sql = f"""
    SELECT{_CANDLE_COLUMNS}
    FROM obs_market_candle
    WHERE asset_id = %s
      AND venue = %s
      AND interval_code = %s
      AND open_ts_utc < %s
    ORDER BY open_ts_utc DESC
    LIMIT %s
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [asset_id, venue, interval_code, before_ts, limit])
            rows = cur.fetchall() or []
    finally:
        conn.close()

    rows = list(reversed(rows))
    return [_row_to_candle(row, symbol=symbol) for row in rows]


def fetch_candles(
    *,
    asset_id: int,
    symbol: str,
    venue: str,
    interval_code: str,
    from_ts: str,
    to_ts: str,
    chunk_size: int = DEFAULT_CHUNK_CANDLES,
    on_progress: Callable[[int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[HistoricalCandle]:
    """Fetch every candle in `[from_ts, to_ts)` (SELECT only), in bounded chunks.

    Uses deterministic ORDER BY open_ts_utc ASC with keyset pagination
    (`open_ts_utc >= from_ts` for the first page, then strictly
    `open_ts_utc > <last row's open_ts_utc>` for every following page) so no
    single query is unbounded and no page can introduce a duplicate or
    dropped row at a page boundary -- each candle is fetched exactly once.
    `should_stop`, when given, is polled between chunks so a caller can stop
    a long-running fetch at a safe (whole-chunk) boundary, e.g. on
    SIGINT/SIGTERM.
    """
    first_page_sql = f"""
    SELECT{_CANDLE_COLUMNS}
    FROM obs_market_candle
    WHERE asset_id = %s
      AND venue = %s
      AND interval_code = %s
      AND open_ts_utc >= %s
      AND open_ts_utc < %s
    ORDER BY open_ts_utc ASC
    LIMIT %s
    """
    next_page_sql = f"""
    SELECT{_CANDLE_COLUMNS}
    FROM obs_market_candle
    WHERE asset_id = %s
      AND venue = %s
      AND interval_code = %s
      AND open_ts_utc > %s
      AND open_ts_utc < %s
    ORDER BY open_ts_utc ASC
    LIMIT %s
    """

    candles: list[HistoricalCandle] = []
    cursor: Any = from_ts
    sql = first_page_sql

    conn = get_connection()
    try:
        while True:
            if should_stop is not None and should_stop():
                break

            with conn.cursor() as cur:
                cur.execute(sql, [asset_id, venue, interval_code, cursor, to_ts, chunk_size])
                rows = cur.fetchall() or []

            if not rows:
                break

            page_candles = [_row_to_candle(row, symbol=symbol) for row in rows]
            candles.extend(page_candles)
            if on_progress is not None:
                on_progress(len(candles))

            if len(rows) < chunk_size:
                break

            cursor = page_candles[-1].open_ts_utc
            sql = next_page_sql
    finally:
        conn.close()

    return candles


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_run_id(
    *,
    venue: str,
    symbol: str,
    timeframe: str,
    from_ts: str,
    to_ts: str,
    episode_stride_candles: int,
    max_episodes: int | None,
) -> str:
    """Deterministic run identity over every dataset-defining parameter.

    Immutable output is unsafe if it is keyed only on venue/symbol/timeframe:
    different `from_ts`/`to_ts`/`episode_stride_candles`/`max_episodes` values
    produce different episode datasets. The run id folds all of them (plus
    builder/contract version) into the output path so two runs with
    different dataset-defining inputs can never alias the same immutable
    artifact, and a repeat run with identical inputs always resolves to the
    same path (idempotent).

    Operational retrieval parameters (warmup candle count, DB fetch chunk
    size) are deliberately NOT included here: they affect how the data is
    fetched, not what episode set is emitted for fixed dataset-defining
    inputs. See the module docstring's "Warmup and Run Identity" section.
    """
    run_key = {
        "builder_version": BUILDER_VERSION,
        "contract_version": CONTRACT_VERSION,
        "venue": venue,
        "symbol": symbol,
        "timeframe": timeframe,
        "from_ts": from_ts,
        "to_ts": to_ts,
        "episode_stride_candles": episode_stride_candles,
        "max_episodes": max_episodes,
    }
    canonical_text = json.dumps(run_key, sort_keys=True, separators=(",", ":"))
    return _sha256_text(canonical_text)


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
    run_id: str,
    venue: str,
    symbol: str,
    timeframe: str,
    from_ts: str,
    to_ts: str,
    episode_stride_candles: int,
    max_episodes: int | None,
    candle_count: int,
    episode_count: int,
    episodes_sha256: str,
    warmup_candle_count: int = 0,
    source_fetch_from_ts_utc: str | None = None,
    chunk_size_candles: int = DEFAULT_CHUNK_CANDLES,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
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
        "episode_stride_candles": episode_stride_candles,
        "max_episodes": max_episodes,
        "episode_count": episode_count,
        "episodes_sha256": episodes_sha256,
        # Provenance only -- NOT part of run_id/dataset identity. See
        # compute_run_id() and the module docstring's
        # "Warmup and Run Identity" section.
        "warmup_candle_count": warmup_candle_count,
        "source_fetch_from_ts_utc": source_fetch_from_ts_utc,
        "chunk_size_candles": chunk_size_candles,
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


class _SignalState:
    """Tracks the most recent SIGINT/SIGTERM so main() can stop at a safe boundary.

    Deliberately simple (a module-scoped flag, no threads/worker pool): the
    only long-running phase is DB fetch, which already polls `triggered`
    between bounded chunks via fetch_candles' `should_stop`.
    """

    def __init__(self) -> None:
        self.signum: int | None = None

    def handle(self, signum: int, frame: Any) -> None:
        self.signum = signum

    @property
    def triggered(self) -> bool:
        return self.signum is not None

    def install(self) -> None:
        signal.signal(signal.SIGINT, self.handle)
        signal.signal(signal.SIGTERM, self.handle)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_args(args)
    except ValueError as exc:
        print(f"FAILED reason=invalid_arguments detail={exc}", flush=True)
        return 2
    cfg: EpisodeConfig = resolve_config(args.timeframe)

    signal_state = _SignalState()
    signal_state.install()

    print(
        f"STARTED runner={BUILDER_NAME} mode=historical venue={args.venue} "
        f"symbol={args.symbol} timeframe={args.timeframe} workers=1 "
        f"chunk_size_candles={args.chunk_size_candles}",
        flush=True,
    )

    def _interrupted_exit() -> int:
        print(
            f"INTERRUPTED signal={signal_state.signum} "
            f"reason=stopped_at_safe_boundary_before_write",
            flush=True,
        )
        return 130 if signal_state.signum == signal.SIGINT else 143

    asset_id = fetch_asset_id(venue=args.venue, symbol=args.symbol)
    if signal_state.triggered:
        return _interrupted_exit()

    from_ts_dt = parse_ts_arg(args.from_ts, name="--from-ts")
    to_ts_dt = parse_ts_arg(args.to_ts, name="--to-ts")

    warmup_target = cfg.lookback_candles - 1
    print(f"FETCHING phase=warmup target={warmup_target}", flush=True)
    warmup_candles = fetch_warmup_candles(
        asset_id=asset_id,
        symbol=args.symbol,
        venue=args.venue,
        interval_code=cfg.interval_code,
        before_ts=args.from_ts,
        limit=warmup_target,
    )
    print(f"FETCHING phase=warmup fetched={len(warmup_candles)}", flush=True)
    if signal_state.triggered:
        return _interrupted_exit()

    def _progress(count: int) -> None:
        print(f"FETCHING phase=requested_window fetched={count}", flush=True)

    requested_candles = fetch_candles(
        asset_id=asset_id,
        symbol=args.symbol,
        venue=args.venue,
        interval_code=cfg.interval_code,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
        chunk_size=args.chunk_size_candles,
        on_progress=_progress,
        should_stop=lambda: signal_state.triggered,
    )
    if signal_state.triggered:
        return _interrupted_exit()

    candles = warmup_candles + requested_candles
    print(
        f"FETCHED warmup_candles={len(warmup_candles)} "
        f"requested_candles={len(requested_candles)} total_candles={len(candles)}",
        flush=True,
    )

    print(f"BUILDING candles={len(candles)}", flush=True)
    records: list[EpisodeRecord] = build_episodes(
        symbol=args.symbol,
        venue=args.venue,
        candles=candles,
        cfg=cfg,
        episode_stride_candles=args.episode_stride_candles,
        max_episodes=args.max_episodes,
        emit_from_ts_utc=from_ts_dt,
        emit_to_ts_utc=to_ts_dt,
    )
    print(f"BUILT episodes={len(records)}", flush=True)
    if signal_state.triggered:
        return _interrupted_exit()

    episodes_text = episodes_to_json(records)
    episodes_sha256 = _sha256_text(episodes_text)

    run_id = compute_run_id(
        venue=args.venue,
        symbol=args.symbol,
        timeframe=args.timeframe,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
        episode_stride_candles=args.episode_stride_candles,
        max_episodes=args.max_episodes,
    )

    output_dir = Path(args.output_dir) / args.venue / args.symbol / cfg.interval_code / run_id
    episodes_path = output_dir / "episodes_v1.json"
    manifest_path = output_dir / "manifest_v1.json"

    print(f"WRITING episodes_path={episodes_path}", flush=True)
    write_immutable_json(episodes_path, episodes_text)

    source_fetch_from_ts_utc = candles[0].open_ts_utc.isoformat() if candles else None
    manifest = build_manifest(
        run_id=run_id,
        venue=args.venue,
        symbol=args.symbol,
        timeframe=args.timeframe,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
        episode_stride_candles=args.episode_stride_candles,
        max_episodes=args.max_episodes,
        candle_count=len(candles),
        episode_count=len(records),
        episodes_sha256=episodes_sha256,
        warmup_candle_count=len(warmup_candles),
        source_fetch_from_ts_utc=source_fetch_from_ts_utc,
        chunk_size_candles=args.chunk_size_candles,
    )
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    print(f"WRITING manifest_path={manifest_path}", flush=True)
    write_immutable_json(manifest_path, manifest_text)

    print(
        f"FINISHED episodes={len(records)} run_id={run_id} episodes_path={episodes_path} "
        f"manifest_path={manifest_path} episodes_sha256={episodes_sha256}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
