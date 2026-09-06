from __future__ import annotations

import argparse
import signal
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any

from src.common.db import get_connection

ENGINE_NAME = "asset_interval_quality_snapshot"
ENGINE_VERSION = "1.1"

_INTERVALS = ("1h", "4h", "1d")
_LOOKBACK_BY_INTERVAL = {
    "1h": timedelta(days=30),
    "4h": timedelta(days=90),
    "1d": timedelta(days=365),
}
_EXPECTED_ROWS_BY_INTERVAL = {"1h": 720, "4h": 540, "1d": 365}


def _utc_now_naive_seconds() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def _elapsed(started: float) -> str:
    return f"{time.monotonic() - started:.3f}s"


def _install_signal_handlers() -> dict[int, signal.Handlers]:
    previous = {
        signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)
    }

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


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def _hours_between(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds() // 3600))


def _expected_latest_open(now_utc: datetime, interval_code: str) -> datetime:
    hour = now_utc.replace(minute=0, second=0, microsecond=0)
    if interval_code == "1h":
        return hour - timedelta(hours=1)
    if interval_code == "4h":
        return hour.replace(hour=(hour.hour // 4) * 4) - timedelta(hours=4)
    return now_utc.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=1
    )


def _gap_metrics(
    open_times: list[datetime], interval_code: str
) -> tuple[int, int, int, int]:
    gap_events = 0
    missing_total = 0
    small_gap_events = 0
    large_gap_events = 0
    expected_hours = 4 if interval_code == "4h" else 1
    for previous, current in pairwise(open_times):
        diff_units = (
            (current.date() - previous.date()).days
            if interval_code == "1d"
            else _hours_between(previous, current)
        )
        if diff_units <= expected_hours:
            continue
        gap_events += 1
        missing_total += (diff_units // expected_hours) - 1
        if diff_units in ({8, 12} if interval_code == "4h" else {2, 3}):
            small_gap_events += 1
        if diff_units >= (
            24 if interval_code == "4h" else 7 if interval_code == "1d" else 6
        ):
            large_gap_events += 1
    return gap_events, missing_total, small_gap_events, large_gap_events


def _quality_score(
    *,
    interval_code: str,
    latest_open_ts_utc: datetime | None,
    large_gap_events: int,
    small_gap_events: int,
    freshness_lag_intervals: int | None,
    coverage_ratio: Decimal,
) -> Decimal:
    if latest_open_ts_utc is None:
        return Decimal("0.500000")
    score = Decimal(1)
    large_step, large_cap = {
        "1h": (Decimal("0.30"), Decimal("0.70")),
        "4h": (Decimal("0.25"), Decimal("0.60")),
        "1d": (Decimal("0.20"), Decimal("0.50")),
    }[interval_code]
    small_step, small_cap = {
        "1h": (Decimal("0.010"), Decimal("0.250")),
        "4h": (Decimal("0.008"), Decimal("0.200")),
        "1d": (Decimal("0.005"), Decimal("0.100")),
    }[interval_code]
    score -= min(Decimal(large_gap_events) * large_step, large_cap)
    score -= min(Decimal(small_gap_events) * small_step, small_cap)
    lag = freshness_lag_intervals or 0
    if interval_code == "1h" and lag >= 2:
        score -= Decimal("0.150")
    elif interval_code == "4h" and lag >= 8:
        score -= Decimal("0.120")
    elif interval_code == "1d" and lag >= 2:
        score -= Decimal("0.100")
    if interval_code == "1h" and coverage_ratio < Decimal("0.5"):
        score -= Decimal("0.250")
    elif interval_code == "4h" and coverage_ratio < Decimal("0.4"):
        score -= Decimal("0.200")
    elif interval_code == "1d" and coverage_ratio < Decimal("0.4"):
        score -= Decimal("0.150")
    elif coverage_ratio < Decimal("0.8"):
        score -= Decimal("0.080")
    return max(Decimal(0), min(Decimal(1), score)).quantize(Decimal("0.000001"))


def _quality_status(
    *,
    interval_code: str,
    latest_open_ts_utc: datetime | None,
    large_gap_events: int,
    small_gap_events: int,
    freshness_lag_intervals: int | None,
    coverage_ratio: Decimal,
    quality_score: Decimal,
) -> str:
    if latest_open_ts_utc is None:
        return "NEW"
    lag = freshness_lag_intervals if freshness_lag_intervals is not None else 999
    blocked = (
        (
            interval_code == "1h"
            and (
                large_gap_events > 0
                or lag >= 4
                or coverage_ratio < Decimal("0.50")
                or quality_score < Decimal("0.40")
            )
        )
        or (
            interval_code == "4h"
            and (
                large_gap_events > 0
                or lag >= 16
                or coverage_ratio < Decimal("0.35")
                or quality_score < Decimal("0.30")
            )
        )
        or (
            interval_code == "1d"
            and (
                large_gap_events > 0
                or lag >= 4
                or coverage_ratio < Decimal("0.20")
                or quality_score < Decimal("0.25")
            )
        )
    )
    if blocked:
        return "BLOCKED"
    degraded = (
        (
            interval_code == "1h"
            and (
                small_gap_events > 2
                or coverage_ratio < Decimal("0.85")
                or lag >= 2
                or quality_score < Decimal("0.78")
            )
        )
        or (
            interval_code == "4h"
            and (
                small_gap_events > 2
                or coverage_ratio < Decimal("0.90")
                or lag >= 2
                or quality_score < Decimal("0.82")
            )
        )
        or (
            interval_code == "1d"
            and (
                small_gap_events > 8
                or coverage_ratio < Decimal("0.90")
                or lag >= 2
                or quality_score < Decimal("0.78")
            )
        )
    )
    return "DEGRADED" if degraded else "TRUSTED"


def _build_quality_row(
    *,
    asset_id: int,
    venue: str,
    interval_code: str,
    now_utc: datetime,
    first_open_ts_utc: datetime | None,
    latest_open_ts_utc: datetime | None,
    latest_close_ts_utc: datetime | None,
    open_times: list[datetime],
) -> dict[str, Any]:
    rows_observed = len(open_times)
    expected_rows = (
        _EXPECTED_ROWS_BY_INTERVAL[interval_code] if latest_open_ts_utc else 0
    )
    coverage_ratio = (
        min(Decimal(rows_observed) / Decimal(expected_rows), Decimal(1))
        if expected_rows
        else Decimal(0)
    ).quantize(Decimal("0.000001"))
    gap_events, missing_total, small_gaps, large_gaps = _gap_metrics(
        open_times, interval_code
    )
    expected_latest = _expected_latest_open(now_utc, interval_code)
    if latest_open_ts_utc is None:
        lag_intervals = None
        lag_hours = None
        history_days = 0
    else:
        lag_hours = _hours_between(latest_open_ts_utc, now_utc)
        raw_lag = _hours_between(latest_open_ts_utc, expected_latest)
        lag_intervals = (
            raw_lag // 4
            if interval_code == "4h"
            else raw_lag // 24
            if interval_code == "1d"
            else raw_lag
        )
        history_days = (
            max(0, (latest_open_ts_utc.date() - first_open_ts_utc.date()).days)
            if first_open_ts_utc
            else 0
        )
    score = _quality_score(
        interval_code=interval_code,
        latest_open_ts_utc=latest_open_ts_utc,
        large_gap_events=large_gaps,
        small_gap_events=small_gaps,
        freshness_lag_intervals=lag_intervals,
        coverage_ratio=coverage_ratio,
    )
    status = _quality_status(
        interval_code=interval_code,
        latest_open_ts_utc=latest_open_ts_utc,
        large_gap_events=large_gaps,
        small_gap_events=small_gaps,
        freshness_lag_intervals=lag_intervals,
        coverage_ratio=coverage_ratio,
        quality_score=score,
    )
    return {
        "asset_id": asset_id,
        "venue": venue,
        "interval_code": interval_code,
        "quality_status": status,
        "quality_score": score,
        "gap_events": gap_events,
        "missing_candles_total": missing_total,
        "small_gap_events": small_gaps,
        "large_gap_events": large_gaps,
        "latest_open_ts_utc": latest_open_ts_utc,
        "latest_close_ts_utc": latest_close_ts_utc,
        "freshness_lag_hours": lag_hours,
        "rows_observed": rows_observed,
        "expected_rows": expected_rows,
        "coverage_ratio": coverage_ratio,
        "notes": (
            f"lg={large_gaps}; sg={small_gaps}; cov={coverage_ratio:.4f}; "
            f"lag_i={lag_intervals if lag_intervals is not None else -1}; "
            f"hist_d={history_days}"
        ),
    }


def fetch_quality_rows(
    conn,
    *,
    venue: str,
    now_utc: datetime | None = None,
    progress: Callable[[int, int, int, int], None] | None = None,
) -> list[dict[str, Any]]:
    """Calculate v3-compatible rows with index-bounded per-market windows.

    The legacy view repeatedly materializes the full candle table. Exact-key
    range reads preserve its per-asset latest-relative windows without the
    unbounded multi-million-row sorts.
    """
    now_utc = now_utc or _utc_now_naive_seconds()
    rows: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        cur.execute("SELECT asset_id FROM asset WHERE is_enabled = 1 ORDER BY asset_id")
        query_count = 1
        asset_ids = [int(row["asset_id"]) for row in cur.fetchall()]
        asset_total = len(asset_ids)

        def execute(sql: str, params: tuple[Any, ...]) -> None:
            nonlocal query_count
            cur.execute(sql, params)
            query_count += 1

        for asset_index, asset_id in enumerate(asset_ids, start=1):
            for interval_code in _INTERVALS:
                key_params = (asset_id, interval_code, venue)
                execute(
                    """
                    SELECT open_ts_utc, close_ts_utc
                    FROM obs_market_candle
                    FORCE INDEX (idx_omc_asset_interval_venue_open)
                    WHERE asset_id = %s AND interval_code = %s AND venue = %s
                    ORDER BY open_ts_utc ASC
                    LIMIT 1
                    """,
                    key_params,
                )
                first = cur.fetchone()
                execute(
                    """
                    SELECT open_ts_utc, close_ts_utc
                    FROM obs_market_candle
                    FORCE INDEX (idx_omc_asset_interval_venue_open)
                    WHERE asset_id = %s AND interval_code = %s AND venue = %s
                    ORDER BY open_ts_utc DESC
                    LIMIT 1
                    """,
                    key_params,
                )
                latest = cur.fetchone()
                latest_close = None
                if latest is not None:
                    execute(
                        """
                        SELECT close_ts_utc
                        FROM obs_market_candle
                        FORCE INDEX (ix_market_candle_lookup)
                        WHERE asset_id = %s AND interval_code = %s AND venue = %s
                        ORDER BY close_ts_utc DESC
                        LIMIT 1
                        """,
                        key_params,
                    )
                    latest_close = cur.fetchone()
                open_times: list[datetime] = []
                if latest is not None:
                    latest_open = latest["open_ts_utc"]
                    execute(
                        """
                        SELECT open_ts_utc
                        FROM obs_market_candle
                        FORCE INDEX (idx_omc_asset_interval_venue_open)
                        WHERE asset_id = %s AND interval_code = %s AND venue = %s
                          AND open_ts_utc > %s AND open_ts_utc <= %s
                        ORDER BY open_ts_utc
                        """,
                        (
                            *key_params,
                            latest_open - _LOOKBACK_BY_INTERVAL[interval_code],
                            latest_open,
                        ),
                    )
                    open_times = [row["open_ts_utc"] for row in cur.fetchall()]
                rows.append(
                    _build_quality_row(
                        asset_id=asset_id,
                        venue=venue,
                        interval_code=interval_code,
                        now_utc=now_utc,
                        first_open_ts_utc=None
                        if first is None
                        else first["open_ts_utc"],
                        latest_open_ts_utc=(
                            None if latest is None else latest["open_ts_utc"]
                        ),
                        latest_close_ts_utc=(
                            None
                            if latest_close is None
                            else latest_close["close_ts_utc"]
                        ),
                        open_times=open_times,
                    )
                )
            if progress is not None and (
                asset_index % 50 == 0 or asset_index == asset_total
            ):
                progress(asset_index, asset_total, len(rows), query_count)
    return rows


def write_quality_rows(
    conn,
    *,
    rows: list[dict[str, Any]],
    snapshot_ts_utc: datetime,
) -> int:
    if not rows:
        return 0

    sql = """
        INSERT INTO asset_interval_quality (
            asset_id,
            venue,
            interval_code,
            asof_ts_utc,
            quality_status,
            quality_score,
            gap_events,
            missing_candles_total,
            small_gap_events,
            large_gap_events,
            latest_open_ts_utc,
            latest_close_ts_utc,
            freshness_lag_hours,
            rows_observed,
            expected_rows,
            coverage_ratio,
            notes
        )
        VALUES (
            %(asset_id)s,
            %(venue)s,
            %(interval_code)s,
            %(asof_ts_utc)s,
            %(quality_status)s,
            %(quality_score)s,
            %(gap_events)s,
            %(missing_candles_total)s,
            %(small_gap_events)s,
            %(large_gap_events)s,
            %(latest_open_ts_utc)s,
            %(latest_close_ts_utc)s,
            %(freshness_lag_hours)s,
            %(rows_observed)s,
            %(expected_rows)s,
            %(coverage_ratio)s,
            %(notes)s
        )
        ON DUPLICATE KEY UPDATE
            quality_status = VALUES(quality_status),
            quality_score = VALUES(quality_score),
            gap_events = VALUES(gap_events),
            missing_candles_total = VALUES(missing_candles_total),
            small_gap_events = VALUES(small_gap_events),
            large_gap_events = VALUES(large_gap_events),
            latest_open_ts_utc = VALUES(latest_open_ts_utc),
            latest_close_ts_utc = VALUES(latest_close_ts_utc),
            freshness_lag_hours = VALUES(freshness_lag_hours),
            rows_observed = VALUES(rows_observed),
            expected_rows = VALUES(expected_rows),
            coverage_ratio = VALUES(coverage_ratio),
            notes = VALUES(notes)
    """

    payload = []
    for row in rows:
        payload.append(
            {
                "asset_id": row["asset_id"],
                "venue": row["venue"],
                "interval_code": row["interval_code"],
                "asof_ts_utc": snapshot_ts_utc,
                "quality_status": row["quality_status"],
                "quality_score": row["quality_score"],
                "gap_events": row["gap_events"],
                "missing_candles_total": row["missing_candles_total"],
                "small_gap_events": row["small_gap_events"],
                "large_gap_events": row["large_gap_events"],
                "latest_open_ts_utc": row["latest_open_ts_utc"],
                "latest_close_ts_utc": row["latest_close_ts_utc"],
                "freshness_lag_hours": row["freshness_lag_hours"],
                "rows_observed": row["rows_observed"],
                "expected_rows": row["expected_rows"],
                "coverage_ratio": row["coverage_ratio"],
                "notes": row["notes"],
            }
        )

    with conn.cursor() as cur:
        cur.executemany(sql, payload)

    conn.commit()
    return len(payload)


def print_table(rows: list[dict[str, Any]], *, snapshot_ts_utc: datetime) -> None:
    headers = [
        "snapshot_ts_utc",
        "asset_id",
        "venue",
        "interval",
        "status",
        "score",
        "gaps",
        "missing",
        "small",
        "large",
        "coverage",
        "latest_open",
        "lag_h",
    ]

    table_rows = []
    for row in rows:
        table_rows.append(
            [
                _fmt(snapshot_ts_utc),
                _fmt(row.get("asset_id")),
                _fmt(row.get("venue")),
                _fmt(row.get("interval_code")),
                _fmt(row.get("quality_status")),
                _fmt(row.get("quality_score")),
                _fmt(row.get("gap_events")),
                _fmt(row.get("missing_candles_total")),
                _fmt(row.get("small_gap_events")),
                _fmt(row.get("large_gap_events")),
                _fmt(row.get("coverage_ratio")),
                _fmt(row.get("latest_open_ts_utc")),
                _fmt(row.get("freshness_lag_hours")),
            ]
        )

    widths = [
        max(len(str(header)), *(len(str(row[index])) for row in table_rows))
        if table_rows
        else len(str(header))
        for index, header in enumerate(headers)
    ]

    print(
        " | ".join(
            str(header).ljust(widths[index]) for index, header in enumerate(headers)
        )
    )
    print("-+-".join("-" * width for width in widths))

    for row in table_rows:
        print(
            " | ".join(
                str(value).ljust(widths[index]) for index, value in enumerate(row)
            )
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Materialize latest asset interval quality into asset_interval_quality."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    args = parser.parse_args(argv)

    snapshot_ts_utc = _utc_now_naive_seconds()
    mode = "write" if args.write_db else "dry-run"
    started = time.monotonic()
    conn = None
    previous_handlers = _install_signal_handlers()
    print(
        f"STARTED runner={ENGINE_NAME} version={ENGINE_VERSION} "
        f"mode={mode} venue={args.venue} snapshot_ts_utc={snapshot_ts_utc.isoformat(sep=' ')}",
        flush=True,
    )
    try:
        conn = get_connection()
        phase_started = time.monotonic()
        print(
            f"PHASE_START runner={ENGINE_NAME} phase=fetch_quality_rows",
            flush=True,
        )

        def report_progress(
            assets_complete: int,
            asset_total: int,
            row_count: int,
            query_count: int,
        ) -> None:
            print(
                f"PROGRESS runner={ENGINE_NAME} phase=fetch_quality_rows "
                f"assets={assets_complete}/{asset_total} rows={row_count} "
                f"query_count={query_count} elapsed={_elapsed(phase_started)}",
                flush=True,
            )

        rows = fetch_quality_rows(
            conn,
            venue=args.venue,
            now_utc=snapshot_ts_utc,
            progress=report_progress,
        )
        print(
            f"PHASE_END runner={ENGINE_NAME} phase=fetch_quality_rows "
            f"rows={len(rows)} elapsed={_elapsed(phase_started)}",
            flush=True,
        )

        if args.output == "table":
            print_table(rows, snapshot_ts_utc=snapshot_ts_utc)

        written = 0
        if args.write_db:
            written = write_quality_rows(
                conn,
                rows=rows,
                snapshot_ts_utc=snapshot_ts_utc,
            )

        print(
            f"FINISHED runner={ENGINE_NAME} version={ENGINE_VERSION} "
            f"mode={mode} venue={args.venue} rows={len(rows)} written={written} "
            f"elapsed={_elapsed(started)}",
            flush=True,
        )
        return 0
    except KeyboardInterrupt as exc:
        print(
            f"INTERRUPTED runner={ENGINE_NAME} signal={_interruption_signal(exc)} "
            f"elapsed={_elapsed(started)}",
            flush=True,
        )
        return 130
    except Exception as exc:  # noqa: BLE001 - runner boundary must emit FAILED
        print(
            f"FAILED runner={ENGINE_NAME} error_type={type(exc).__name__} "
            f"elapsed={_elapsed(started)}",
            flush=True,
        )
        return 1
    finally:
        if conn is not None:
            conn.close()
        _restore_signal_handlers(previous_handlers)


if __name__ == "__main__":
    raise SystemExit(main())
