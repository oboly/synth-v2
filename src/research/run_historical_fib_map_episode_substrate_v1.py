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
  from_ts, to_ts, episode_stride_candles, max_episodes) PLUS
  source_input_sha256 -- a fingerprint of the ACTUAL warmup/requested/
  forward-tail candle content the run was built from -- see
  compute_run_id() and "Source Input Fingerprint and Run Identity" below.
  This keeps two runs with different bounds/stride/limit, OR with identical
  CLI arguments but different underlying obs_market_candle content, from
  ever aliasing the same immutable path. Purely operational retrieval
  parameters that never change what candles are fetched (DB fetch chunk
  size, BUILDING progress cadence) remain deliberately excluded from
  run_id -- see "Warmup and Run Identity" below.

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
- DB fetch chunk size is a purely operational retrieval parameter (it only
  changes how many round trips fetch_candles makes, never which candles it
  returns), so compute_run_id() does not include it -- it is recorded in
  the manifest for provenance only.
- Warmup candle CONTENT is not operationally irrelevant to identity: how
  much warmup history is actually available (and its exact OHLCV values)
  can differ between two runs with identical CLI arguments, and that
  content feeds directly into feature/geometry construction for as-of
  candles near --from-ts. compute_run_id() therefore folds the actual
  fetched warmup content into source_input_sha256 -- see "Source Input
  Fingerprint and Run Identity" below. Only the fetched *count* is also
  recorded in the manifest as separate provenance (warmup_candle_count).

Forward-label tail:
- [from_ts, to_ts) is the EPISODE EMISSION window: only as-of candles in
  this range can produce an emitted episode (build_episodes'
  emit_from_ts_utc/emit_to_ts_utc).
- Pre-bound warmup (above) is FEATURE INPUT ONLY: it extends the window
  backwards so PIT trend/anchor reconstruction for an as-of candle near
  --from-ts is invariant to the requested bound. It is never itself
  eligible for emission and never contributes to outcome labels.
- The forward-label tail (fetch_forward_tail_candles) is FORWARD-LABEL
  EVIDENCE ONLY: up to `cfg.forward_max_candles` historical
  `obs_market_candle` rows starting at `open_ts_utc >= --to-ts`, fetched
  once bounded by construction (a single LIMIT query, never derived from
  wall-clock/current time). Without it, an episode emitted near --to-ts
  whose T2/invalidation resolves after --to-ts would be mislabeled
  SOURCE_DATA_EXHAUSTED purely because DB retrieval stopped at the
  requested output bound, not because the market data was actually
  exhausted. Forward-tail candles may only extend the forward-outcome scan
  for episodes already emitted from the requested window; they can never
  themselves become an as-of candle for a NEW emitted episode (same
  emit_to_ts_utc gate as warmup) and never leak into feature construction
  for an earlier as-of candle (build_episodes only ever looks backwards
  from an as-of index for feature input).
- Forward-tail candle CONTENT is, like warmup, folded into
  source_input_sha256 (see below) -- how much forward-tail history is
  actually available (and its exact OHLCV values) directly determines
  outcome labels for episodes near --to-ts, so it is not identity-irrelevant.
  Forward-tail candle *count* and the actual final fetched timestamp are
  additionally recorded in the manifest as separate provenance, like
  warmup candle count.

Source Input Fingerprint and Run Identity:
- compute_run_id() is keyed on the REQUESTED contract (builder/contract
  version, venue, symbol, timeframe, from_ts, to_ts, episode_stride_candles,
  max_episodes) PLUS source_input_sha256, a SHA-256 fingerprint
  (compute_source_input_sha256) over the exact ordered
  warmup_candles + requested_candles + forward_tail_candles sequence
  actually used to build the episodes -- the full PIT source snapshot, not
  just the CLI parameters describing what was asked for.
- This closes a real gap: two runs with byte-identical CLI arguments can
  still see different underlying obs_market_candle content (a late-arriving
  backfill, a corrected OHLC value, or simply less warmup/forward-tail
  history being available at fetch time), which would otherwise produce
  different episodes_v1.json content at the SAME immutable path -- a
  spurious write_immutable_json conflict rather than a legitimately new,
  distinguishable artifact.
- The fingerprint covers every field that can affect feature geometry or
  labels for each candle: symbol, venue, interval_code, open_ts_utc,
  close_ts_utc, open_price, high_price, low_price, close_price, volume.
  Timestamps are canonicalized to UTC ISO-8601 and Decimal values to
  format(value, "f") -- never Python repr()/hash() -- so the fingerprint is
  stable across hosts/runs for identical content and candle order.
- Two runs produce the same run_id if and only if BOTH the requested
  contract AND the actual source candle content used to satisfy it are
  identical. Purely operational retrieval settings (DB fetch chunk size,
  BUILDING progress-heartbeat cadence) never affect source_input_sha256 or
  run_id, because they never change which candles are fetched.
- source_input_sha256 is also written to the manifest, so run_id is
  mechanically recomputable from the manifest's identity fields alone.
"""

import argparse
import hashlib
import json
import os
import shutil
import signal
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.common.db import get_connection
from src.research.historical_fib_map_episode_substrate_v1 import (
    BUILDER_NAME,
    BUILDER_VERSION,
    CONTRACT_VERSION,
    BuildCancelled,
    EpisodeConfig,
    EpisodeRecord,
    EpisodeSubstrateError,
    HistoricalCandle,
    build_episodes,
    episodes_to_json,
    resolve_config,
    validate_candle_sequence,
)

DEFAULT_OUTPUT_DIR = "data/research/historical_fib_map_episode_substrate_v1"

# Bounds one DB round trip's row volume; independent of dataset identity
# (see "Warmup and Run Identity" above -- deliberately excluded from
# compute_run_id).
DEFAULT_CHUNK_CANDLES = 5000

# Cadence (in attempted as-of candle positions, not wall-clock time) at
# which BUILDING polls _SignalState and prints a heartbeat -- see
# build_episodes' `progress_interval_candles`.
DEFAULT_BUILD_PROGRESS_INTERVAL_CANDLES = 500


class ArgParseError(Exception):
    """Raised by `_Parser.error()` instead of argparse's default `SystemExit(2)`.

    argparse's default `ArgumentParser.error()` prints a usage/error message
    and calls `self.exit(2, ...)`, which raises `SystemExit` -- and it does
    so from inside `parse_args()`, before `main()` ever reaches
    `validate_args()` or any of its `FAILED`-line terminal-contract code.
    That meant a missing required flag, an invalid `--timeframe` choice, or
    a malformed `--max-episodes` int silently bypassed the
    `FAILED reason=invalid_arguments` contract every other invalid-input
    path already honors.

    `_Parser` overrides only `error()` (called for genuine parse failures)
    to raise this instead, letting `main()` catch it and emit exactly one
    `FAILED reason=invalid_arguments ...` line with exit code 2 -- the same
    contract `validate_args()` failures already produce. `--help` is
    unaffected: `argparse.Action`'s help action calls `parser.exit()`
    directly (never `error()`), so `--help` keeps normal argparse help
    semantics (print help, `SystemExit(0)`) untouched by this override.
    """


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise ArgParseError(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
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
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Raises `ArgParseError` (never `SystemExit`) for a genuine parse failure
    -- missing required flag, invalid `--timeframe` choice, malformed
    numeric argument -- so `main()` can own the single
    `FAILED reason=invalid_arguments` terminal line/exit-code contract.
    `--help` is unaffected and still raises `SystemExit(0)` after printing
    help, exactly as plain argparse does; `main()` does not catch
    `SystemExit`, so that propagates normally and is not converted to
    `FAILED`. Independently usable outside `main()` for callers that want
    the `ArgParseError` directly instead of the runner's terminal contract.
    """
    return _build_parser().parse_args(argv)


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


def format_ts_for_query(value: datetime) -> str:
    """Render a UTC-aware datetime as the canonical naive-UTC DB query bound.

    `--from-ts`/`--to-ts` accept any ISO-8601 timestamp, including one with
    an explicit UTC offset (e.g. `2026-01-01T00:00:00+02:00`). Every DB
    query bound MUST be derived from `parse_ts_arg`'s normalized UTC
    datetime (`from_ts_dt`/`to_ts_dt` in `main()`) via this function, NEVER
    from the raw CLI string directly: `obs_market_candle` timestamp columns
    are naive and stored in the UTC convention (see
    `normalize_db_datetime_to_utc`), so passing an offset-aware string
    straight through to a parameterized query would filter on the literal
    wall-clock digits the caller typed, not the UTC instant those digits
    actually name -- silently fetching a different window than the one
    `build_episodes`' `emit_from_ts_utc`/`emit_to_ts_utc` (which DOES use
    the normalized UTC datetime) uses for emission. This keeps the DB fetch
    bound and the emission bound anchored to the exact same UTC instant
    regardless of what offset notation the caller used.
    """
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


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


def fetch_forward_tail_candles(
    *,
    asset_id: int,
    symbol: str,
    venue: str,
    interval_code: str,
    to_ts: str,
    limit: int,
) -> list[HistoricalCandle]:
    """Fetch up to `limit` candles at/after `to_ts` (SELECT only).

    Forward-label evidence only -- see the module docstring's
    "Forward-label tail" section. Bounded by construction (LIMIT `limit`,
    always `cfg.forward_max_candles`), so this is a single bounded round
    trip, never an unbounded fetch. Ascending `open_ts_utc` order, starting
    at the requested output upper bound itself (`open_ts_utc >= to_ts`) so
    no gap or overlap exists between the requested-window fetch (which ends
    strictly before `to_ts`) and this tail. Derived only from the caller's
    `to_ts` argument -- never from wall-clock/current time -- and reads the
    same historical `obs_market_candle` table as every other fetch here, no
    current-state/snapshot source.
    """
    if limit <= 0:
        return []

    sql = f"""
    SELECT{_CANDLE_COLUMNS}
    FROM obs_market_candle
    WHERE asset_id = %s
      AND venue = %s
      AND interval_code = %s
      AND open_ts_utc >= %s
    ORDER BY open_ts_utc ASC
    LIMIT %s
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [asset_id, venue, interval_code, to_ts, limit])
            rows = cur.fetchall() or []
    finally:
        conn.close()

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


def _candle_fingerprint_fields(candle: HistoricalCandle) -> dict[str, str]:
    """Canonical, order-independent-within-record field mapping for one candle.

    Every field that can affect feature geometry or forward-outcome labels
    is included: identity fields (symbol/venue/interval_code), both
    timestamps, and every OHLCV value. Timestamps are serialized as UTC
    ISO-8601 (never host-timezone dependent -- candles passed here have
    already gone through `normalize_db_datetime_to_utc`); `Decimal` values
    use `format(value, "f")` (stable, locale-independent, no scientific
    notation) rather than `str()`/`repr()`, whose output can vary with a
    `Decimal`'s internal exponent for numerically-equal values. No field
    depends on Python's built-in `hash()`/`repr()` of any object.
    """
    return {
        "symbol": candle.symbol,
        "venue": candle.venue,
        "interval_code": candle.interval_code,
        "open_ts_utc": candle.open_ts_utc.astimezone(timezone.utc).isoformat(),
        "close_ts_utc": candle.close_ts_utc.astimezone(timezone.utc).isoformat(),
        "open_price": format(candle.open_price, "f"),
        "high_price": format(candle.high_price, "f"),
        "low_price": format(candle.low_price, "f"),
        "close_price": format(candle.close_price, "f"),
        "volume": format(candle.volume, "f"),
    }


def compute_source_input_sha256(candles: Sequence[HistoricalCandle]) -> str:
    """Deterministic SHA-256 fingerprint over the exact ordered source candle input.

    `candles` must be the full `warmup_candles + requested_candles +
    forward_tail_candles` sequence actually handed to `build_episodes` --
    the complete PIT source snapshot a run's feature/label output was
    computed from. Candle order is preserved as given (this substrate
    requires ascending `close_ts_utc`, enforced separately by
    `validate_candle_sequence`); this function does not sort or dedupe, so
    a caller passing an unvalidated or reordered sequence gets a
    correspondingly different fingerprint -- which is the point: identical
    source *content* in identical order always yields the identical
    fingerprint, and any difference in count, order, or any single field of
    any single candle yields a different one.

    Serialized as a single canonical (sorted-key, compact-separator) JSON
    array of `_candle_fingerprint_fields()` records, then SHA-256'd -- the
    same canonicalization discipline `compute_run_id`/`compute_episode_id`
    already use, so the result is stable across repeated runs/hosts and
    never depends on Python's `repr()`/`hash()` of any object.
    """
    canonical_text = json.dumps(
        [_candle_fingerprint_fields(c) for c in candles],
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_text(canonical_text)


def compute_run_id(
    *,
    venue: str,
    symbol: str,
    timeframe: str,
    from_ts: str,
    to_ts: str,
    episode_stride_candles: int,
    max_episodes: int | None,
    source_input_sha256: str,
) -> str:
    """Deterministic run identity over every dataset-defining parameter
    AND the actual PIT source candle content the run was built from.

    Immutable output is unsafe if it is keyed only on
    venue/symbol/timeframe/from_ts/to_ts/episode_stride_candles/
    max_episodes: those CLI/config parameters describe the REQUESTED
    contract, but the actual `obs_market_candle` content underlying it
    (warmup, requested-window, and forward-tail candles) can differ between
    two runs with identical CLI arguments -- e.g. a late-arriving backfill,
    a corrected OHLC value, or simply less warmup/forward-tail history
    being available yet -- and would otherwise produce different
    `episodes_v1.json` content at the SAME immutable path, surfacing as a
    spurious `write_immutable_json` conflict rather than a new,
    distinguishable artifact.

    `source_input_sha256` (see `compute_source_input_sha256`) closes that
    gap: it is a fingerprint of the exact ordered
    `warmup_candles + requested_candles + forward_tail_candles` sequence
    actually used to build the episodes. Folding it in here means two runs
    produce the same `run_id` if and only if BOTH the requested
    contract/config AND the actual source candle content used to satisfy
    it are identical; any difference in either produces a different
    `run_id` and therefore a different immutable path -- no legitimate
    content difference can ever collide with an existing artifact.

    Operational retrieval parameters (DB fetch chunk size, BUILDING
    progress-heartbeat cadence) are deliberately NOT included: they affect
    only how many round trips/heartbeats a run takes, never which candles
    are fetched or what content `source_input_sha256` fingerprints. See the
    module docstring's "Warmup and Run Identity" / "Forward-label tail" /
    "Source Input Fingerprint and Run Identity" sections.
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
        "source_input_sha256": source_input_sha256,
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


def _read_text_or_none(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def publish_immutable_run(
    *,
    output_dir: Path,
    episodes_text: str,
    manifest_text: str,
) -> tuple[str, str]:
    """Atomically publish a complete {episodes_v1.json, manifest_v1.json} pair.

    Structural guarantee: `output_dir` is either ABSENT or a COMPLETE,
    internally consistent immutable run directory containing BOTH files --
    never a partial directory with only one of them. This replaces the
    prior design of two independent `write_immutable_json` calls (episodes
    first, then manifest), which could leave a final run directory
    containing only `episodes_v1.json` if manifest construction or its
    write failed in between.

    Both texts are fully built in memory by the caller before this function
    is ever invoked. Both files are written into a private staging
    directory (a sibling of `output_dir`, so same filesystem/mount) and
    `fsync`'d individually, then the staging directory's entry is `fsync`'d
    too, and only then is the whole staging directory published into
    `output_dir` with a single atomic `os.rename`. A directory rename
    either fully succeeds or does not happen at all -- there is no
    filesystem-visible intermediate state with only one file present.

    If `output_dir` already exists (a repeat run, or a race with a
    concurrent identical publish):
    - both files present and content-identical to the candidate =>
      idempotent success; the staging directory is discarded and
      `output_dir` is left completely untouched
    - either file missing (a partial existing directory), or present with
      different content, => fail closed with `ValueError` (an immutable
      conflict); `output_dir` is never "repaired" or overwritten

    The staging directory never survives this function returning or
    raising: a successful rename consumes it (it *becomes* `output_dir`,
    so there is nothing left at the old path to clean up), and every other
    path (idempotent match, conflict, or any other exception) removes it in
    a `finally` block -- so no failure or interruption can ever leave an
    orphaned partial staging directory next to `output_dir`.
    """
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    def _existing_or_none() -> tuple[str, str] | None:
        if not output_dir.exists():
            return None
        existing_episodes = _read_text_or_none(output_dir / "episodes_v1.json")
        existing_manifest = _read_text_or_none(output_dir / "manifest_v1.json")
        if existing_episodes is None or existing_manifest is None:
            raise ValueError(
                f"refusing to publish immutable run {output_dir}: existing run "
                f"directory is incomplete (episodes_present="
                f"{existing_episodes is not None} manifest_present="
                f"{existing_manifest is not None})"
            )
        existing_episodes_sha256 = _sha256_text(existing_episodes)
        existing_manifest_sha256 = _sha256_text(existing_manifest)
        candidate_episodes_sha256 = _sha256_text(episodes_text)
        candidate_manifest_sha256 = _sha256_text(manifest_text)
        if (
            existing_episodes_sha256 != candidate_episodes_sha256
            or existing_manifest_sha256 != candidate_manifest_sha256
        ):
            raise ValueError(
                f"refusing to overwrite immutable run {output_dir}: "
                f"existing episodes_sha256={existing_episodes_sha256} "
                f"candidate episodes_sha256={candidate_episodes_sha256} "
                f"existing manifest_sha256={existing_manifest_sha256} "
                f"candidate manifest_sha256={candidate_manifest_sha256}"
            )
        return existing_episodes_sha256, existing_manifest_sha256

    existing = _existing_or_none()
    if existing is not None:
        return existing

    staging_dir: Path | None = Path(
        tempfile.mkdtemp(dir=output_dir.parent, prefix=f".{output_dir.name}.stage-")
    )
    try:
        for name, text in (
            ("episodes_v1.json", episodes_text),
            ("manifest_v1.json", manifest_text),
        ):
            staged_path = staging_dir / name
            with open(staged_path, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())

        dir_fd = os.open(staging_dir, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

        try:
            os.rename(staging_dir, output_dir)
        except OSError:
            # Lost a race with a concurrent identical/conflicting publish:
            # output_dir now exists where it did not a moment ago.
            # Re-check exactly as above rather than assuming success or
            # failure of our own rename attempt.
            existing = _existing_or_none()
            if existing is not None:
                return existing
            raise
        else:
            # The rename moved staging_dir to output_dir -- nothing remains
            # at the old staging path to clean up.
            staging_dir = None
            return _sha256_text(episodes_text), _sha256_text(manifest_text)
    finally:
        if staging_dir is not None and staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


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
    source_input_sha256: str = "",
    warmup_candle_count: int = 0,
    source_fetch_from_ts_utc: str | None = None,
    chunk_size_candles: int = DEFAULT_CHUNK_CANDLES,
    requested_candle_count: int = 0,
    forward_tail_candle_count: int = 0,
    forward_tail_max_candles: int = 0,
    source_fetch_final_ts_utc: str | None = None,
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
        # [source_from_ts, source_to_ts) is the requested SOURCE/OUTPUT
        # window == the episode EMISSION window. It is not a feature-input
        # bound (see warmup) and not a label-evidence bound (see the
        # forward tail fields below).
        "source_from_ts": from_ts,
        "source_to_ts": to_ts,
        "source_candle_count": candle_count,
        "episode_stride_candles": episode_stride_candles,
        "max_episodes": max_episodes,
        # Part of run_id/dataset identity (see compute_run_id and the
        # module docstring's "Source Input Fingerprint and Run Identity"
        # section): a SHA-256 fingerprint of the exact ordered
        # warmup_candles + requested_candles + forward_tail_candles content
        # this run was built from. run_id is mechanically recomputable from
        # this manifest by calling compute_run_id() with builder_version,
        # contract_version, venue, symbol, timeframe, source_from_ts,
        # source_to_ts, episode_stride_candles, max_episodes, and this
        # field.
        "source_input_sha256": source_input_sha256,
        "episode_count": episode_count,
        "episodes_sha256": episodes_sha256,
        # Provenance only -- NOT part of run_id/dataset identity (unlike
        # source_input_sha256 above, which fingerprints the same candles'
        # actual content). See compute_run_id() and the module docstring's
        # "Warmup and Run Identity" / "Forward-label tail" sections.
        "warmup_candle_count": warmup_candle_count,
        "requested_window_candle_count": requested_candle_count,
        # Forward-label evidence support only -- these candles are never
        # eligible for emission (see emit_to_ts_utc); their COUNT here is
        # provenance only, but their CONTENT is folded into
        # source_input_sha256 above.
        "forward_tail_candle_count": forward_tail_candle_count,
        "forward_tail_max_candles": forward_tail_max_candles,
        "source_fetch_from_ts_utc": source_fetch_from_ts_utc,
        "source_fetch_final_ts_utc": source_fetch_final_ts_utc,
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
    long-running phases (DB fetch, BUILDING) poll `triggered` at a bounded
    cadence via fetch_candles'/build_episodes' `should_stop` hooks.
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


# Stable machine-readable FAILED reason codes -- the exit code is only
# "non-zero"; `reason` is the contract a caller should key off of.
FAILED_REASON_ASSET_LOOKUP = "asset_lookup_failed"
FAILED_REASON_SOURCE_FETCH = "source_fetch_failed"
FAILED_REASON_SOURCE_VALIDATION = "source_validation_failed"
FAILED_REASON_BUILD = "build_failed"
FAILED_REASON_OUTPUT_WRITE = "output_write_failed"


def _print_failed(reason: str, exc: BaseException, *, exit_code: int = 1) -> int:
    """Print exactly one FAILED terminal line and return a non-zero exit code.

    Only `str(exc)` is included (no traceback, no environment/connection
    payload) to avoid leaking secrets in diagnostics. Callers must `return`
    this result immediately -- one FAILED line per run, and FINISHED must
    never follow it.
    """
    print(f"FAILED reason={reason} detail={exc}", flush=True)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except ArgParseError as exc:
        return _print_failed("invalid_arguments", exc, exit_code=2)
    try:
        validate_args(args)
    except ValueError as exc:
        return _print_failed("invalid_arguments", exc, exit_code=2)
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

    try:
        asset_id = fetch_asset_id(venue=args.venue, symbol=args.symbol)
    except Exception as exc:
        return _print_failed(FAILED_REASON_ASSET_LOOKUP, exc)
    if signal_state.triggered:
        return _interrupted_exit()

    from_ts_dt = parse_ts_arg(args.from_ts, name="--from-ts")
    to_ts_dt = parse_ts_arg(args.to_ts, name="--to-ts")

    warmup_target = cfg.lookback_candles - 1
    print(f"FETCHING phase=warmup target={warmup_target}", flush=True)
    try:
        warmup_candles = fetch_warmup_candles(
            asset_id=asset_id,
            symbol=args.symbol,
            venue=args.venue,
            interval_code=cfg.interval_code,
            before_ts=format_ts_for_query(from_ts_dt),
            limit=warmup_target,
        )
    except Exception as exc:
        return _print_failed(FAILED_REASON_SOURCE_FETCH, exc)
    print(f"FETCHING phase=warmup fetched={len(warmup_candles)}", flush=True)
    if signal_state.triggered:
        return _interrupted_exit()

    def _fetch_progress(count: int) -> None:
        print(f"FETCHING phase=requested_window fetched={count}", flush=True)

    try:
        requested_candles = fetch_candles(
            asset_id=asset_id,
            symbol=args.symbol,
            venue=args.venue,
            interval_code=cfg.interval_code,
            from_ts=format_ts_for_query(from_ts_dt),
            to_ts=format_ts_for_query(to_ts_dt),
            chunk_size=args.chunk_size_candles,
            on_progress=_fetch_progress,
            should_stop=lambda: signal_state.triggered,
        )
    except Exception as exc:
        return _print_failed(FAILED_REASON_SOURCE_FETCH, exc)
    if signal_state.triggered:
        return _interrupted_exit()

    print(f"FETCHING phase=forward_tail target={cfg.forward_max_candles}", flush=True)
    try:
        forward_tail_candles = fetch_forward_tail_candles(
            asset_id=asset_id,
            symbol=args.symbol,
            venue=args.venue,
            interval_code=cfg.interval_code,
            to_ts=format_ts_for_query(to_ts_dt),
            limit=cfg.forward_max_candles,
        )
    except Exception as exc:
        return _print_failed(FAILED_REASON_SOURCE_FETCH, exc)
    print(f"FETCHING phase=forward_tail fetched={len(forward_tail_candles)}", flush=True)
    if signal_state.triggered:
        return _interrupted_exit()

    candles = warmup_candles + requested_candles + forward_tail_candles
    print(
        f"FETCHED warmup_candles={len(warmup_candles)} "
        f"requested_candles={len(requested_candles)} "
        f"forward_tail_candles={len(forward_tail_candles)} total_candles={len(candles)}",
        flush=True,
    )

    try:
        validate_candle_sequence(candles)
    except EpisodeSubstrateError as exc:
        return _print_failed(FAILED_REASON_SOURCE_VALIDATION, exc)

    source_input_sha256 = compute_source_input_sha256(candles)
    print(f"FETCHED source_input_sha256={source_input_sha256}", flush=True)

    print(f"BUILDING candles={len(candles)}", flush=True)

    def _build_progress(processed: int, total: int) -> None:
        print(f"BUILDING progress processed={processed} total={total}", flush=True)

    try:
        records: list[EpisodeRecord] = build_episodes(
            symbol=args.symbol,
            venue=args.venue,
            candles=candles,
            cfg=cfg,
            episode_stride_candles=args.episode_stride_candles,
            max_episodes=args.max_episodes,
            emit_from_ts_utc=from_ts_dt,
            emit_to_ts_utc=to_ts_dt,
            on_progress=_build_progress,
            should_stop=lambda: signal_state.triggered,
            progress_interval_candles=DEFAULT_BUILD_PROGRESS_INTERVAL_CANDLES,
        )
    except BuildCancelled:
        return _interrupted_exit()
    except Exception as exc:
        return _print_failed(FAILED_REASON_BUILD, exc)
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
        source_input_sha256=source_input_sha256,
    )

    output_dir = Path(args.output_dir) / args.venue / args.symbol / cfg.interval_code / run_id
    episodes_path = output_dir / "episodes_v1.json"
    manifest_path = output_dir / "manifest_v1.json"

    try:
        source_fetch_from_ts_utc = candles[0].open_ts_utc.isoformat() if candles else None
        source_fetch_final_ts_utc = candles[-1].open_ts_utc.isoformat() if candles else None
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
            source_input_sha256=source_input_sha256,
            warmup_candle_count=len(warmup_candles),
            source_fetch_from_ts_utc=source_fetch_from_ts_utc,
            chunk_size_candles=args.chunk_size_candles,
            requested_candle_count=len(requested_candles),
            forward_tail_candle_count=len(forward_tail_candles),
            forward_tail_max_candles=cfg.forward_max_candles,
            source_fetch_final_ts_utc=source_fetch_final_ts_utc,
        )
        manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"

        # Both texts are fully built above -- nothing is written to
        # output_dir's filesystem location until this single atomic publish
        # call, which guarantees output_dir ends up either absent or
        # complete (both files present and mutually consistent), never a
        # partial directory with only episodes_v1.json. See
        # publish_immutable_run's docstring.
        print(f"WRITING phase=staging output_dir={output_dir}", flush=True)
        episodes_sha256, manifest_sha256 = publish_immutable_run(
            output_dir=output_dir,
            episodes_text=episodes_text,
            manifest_text=manifest_text,
        )
        print(f"WRITING phase=published output_dir={output_dir}", flush=True)
    except Exception as exc:
        return _print_failed(FAILED_REASON_OUTPUT_WRITE, exc)

    print(
        f"FINISHED episodes={len(records)} run_id={run_id} episodes_path={episodes_path} "
        f"manifest_path={manifest_path} episodes_sha256={episodes_sha256} "
        f"manifest_sha256={manifest_sha256}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
