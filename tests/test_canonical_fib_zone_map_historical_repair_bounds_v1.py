from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from src.market_data.canonical_fib_zone_map_v1 import (
    CanonicalFibMapError,
    build_historical_publication,
    build_publication,
    fetch_latest_trend_rows,
    fetch_production_rows_before,
    fetch_publication_at_identity,
    fetch_recent_candles,
    insert_publication_cohort,
    publish,
)
from src.operations import run_canonical_fib_zone_map_publication_repair_v1 as runner
from src.operations.canonical_fib_zone_map_publication_repair_v1 import (
    repair_publication_identity,
)
from src.operations.writer_capability_authorization_v1 import (
    ExecutionMode,
    _mint_authorization,
)


VENUE = "bitvavo"
QUOTE = "EUR"
INTERVAL = "4h"
SYMBOL = "BTC"

ASOF_12 = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
ASOF_16 = datetime(2026, 8, 5, 16, 0, tzinfo=UTC)
ASOF_20 = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)


def _naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _authorization() -> Any:
    return _mint_authorization(
        capability_id="native_short_4h_chain",
        execution_mode=ExecutionMode.PRODUCTION,
        validated_host="test-host",
        validated_commit="0" * 40,
        authorization_or_permit_id="test-authorization",
    )


# ---------------------------------------------------------------------------
# Fake candle/feature history: a valid bullish 12-candle structure ending
# exactly at 16:00Z (the identity under repair), plus one further candle and
# feature row at 20:00Z (the next live asof). Both timestamps exist in the
# same fake database at once, exactly like production after PR #192 unblocked
# the chain at 20:00Z while 16:00Z stayed unrepaired.
# ---------------------------------------------------------------------------


def _candle_rows() -> list[dict[str, Any]]:
    lows = ("100", "98", "95", "90", "94", "99", "104", "108", "106", "109", "111", "112")
    highs = ("105", "103", "100", "95", "100", "106", "112", "120", "116", "119", "121", "122")
    start = ASOF_16 - timedelta(hours=4 * (len(lows) - 1))
    rows = [
        {
            "symbol": SYMBOL,
            "close_ts_utc": _naive(start + timedelta(hours=4 * index)),
            "open_price": (Decimal(low) + Decimal(high)) / 2,
            "high_price": Decimal(high),
            "low_price": Decimal(low),
            "close_price": (Decimal(low) + Decimal(high)) / 2,
            "volume": Decimal("1000"),
        }
        for index, (low, high) in enumerate(zip(lows, highs, strict=True))
    ]
    assert rows[-1]["close_ts_utc"] == _naive(ASOF_16)
    # One further candle at 20:00Z -- present in the database, must never
    # affect a build requested for 16:00Z.
    rows.append(
        {
            "symbol": SYMBOL,
            "close_ts_utc": _naive(ASOF_20),
            "open_price": Decimal("122"),
            "high_price": Decimal("130"),
            "low_price": Decimal("121"),
            "close_price": Decimal("129"),
            "volume": Decimal("1000"),
        }
    )
    return rows


def _trend_rows() -> list[dict[str, Any]]:
    up = (Decimal("0.03"), Decimal("0.04"), Decimal("0.02"))
    return [
        {
            "symbol": SYMBOL,
            "close_ts_utc": _naive(ASOF_16),
            "price_vs_ema20": up[0],
            "price_vs_ema50": up[1],
            "ema_spread_pct": up[2],
        },
        {
            "symbol": SYMBOL,
            "close_ts_utc": _naive(ASOF_20),
            "price_vs_ema20": up[0],
            "price_vs_ema50": up[1],
            "ema_spread_pct": up[2],
        },
    ]


def _bearish_candle_rows_up_to_16() -> list[dict[str, Any]]:
    lows = ("110", "112", "115", "120", "116", "110", "104", "98", "100", "96", "94", "92")
    highs = ("115", "117", "120", "125", "122", "116", "110", "104", "108", "102", "100", "98")
    start = ASOF_16 - timedelta(hours=4 * (len(lows) - 1))
    rows = [
        {
            "symbol": SYMBOL,
            "close_ts_utc": _naive(start + timedelta(hours=4 * index)),
            "open_price": (Decimal(low) + Decimal(high)) / 2,
            "high_price": Decimal(high),
            "low_price": Decimal(low),
            "close_price": (Decimal(low) + Decimal(high)) / 2,
            "volume": Decimal("1000"),
        }
        for index, (low, high) in enumerate(zip(lows, highs, strict=True))
    ]
    assert rows[-1]["close_ts_utc"] == _naive(ASOF_16)
    return rows


def _prior_map_row(*, asof: datetime, publication_id: str) -> dict[str, Any]:
    return {
        "publication_id": publication_id,
        "symbol": SYMBOL,
        "asof_ts_utc": _naive(asof),
        "map_status": "FRESH",
        "current_leg": "UP",
        "anchor_low_price": Decimal("90"),
        "anchor_high_price": Decimal("122"),
        "target_extension": Decimal("200"),
        "input_latest_candle_ts_utc": _naive(asof),
    }


def _count_in_placeholders(sql: str) -> int:
    match = re.search(r"IN \(([%s,]+)\)", sql)
    return match.group(1).count("%s") if match else 0


class _FakeCursor:
    def __init__(self, script: dict) -> None:
        self._script = script
        self._result: Any = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: Any = ()) -> None:
        s = sql.strip()
        if "FROM obs_market_candle" in sql:
            self._exec_candles(sql, params)
        elif "FROM feat_candle" in sql:
            self._exec_trend(sql, params)
        elif s.startswith("SELECT DISTINCT symbol FROM canonical_fib_zone_map_v1"):
            publication_id = params[0]
            self._result = [
                {"symbol": row["symbol"]}
                for row in sorted(self._script["map_rows"], key=lambda r: r["symbol"])
                if row["publication_id"] == publication_id
            ]
        elif "canonical_fib_zone_map_publication_v1 p" in sql and "canonical_fib_zone_map_v1 mm" in sql:
            self._exec_prior_before(params)
        elif s.startswith("SELECT publication_id, content_digest"):
            self._exec_publication_lookup(sql, params)
        elif s.startswith("DELETE FROM canonical_fib_zone_map_v1"):
            publication_id = params[0]
            self._script["map_rows"] = [
                row for row in self._script["map_rows"] if row["publication_id"] != publication_id
            ]
        elif s.startswith("DELETE FROM canonical_fib_zone_map_publication_v1"):
            self._script["publications"].pop(params[0], None)
        elif s.startswith("INSERT INTO canonical_fib_zone_map_publication_v1"):
            (
                publication_id, venue, quote, interval, asof, map_version,
                digest, row_count, available_count, producer_name, producer_version,
            ) = params
            self._script["publications"][publication_id] = {
                "publication_id": publication_id,
                "venue": venue,
                "quote_currency": quote,
                "interval_code": interval,
                "asof_ts_utc": asof,
                "map_version": map_version,
                "content_digest": digest,
                "row_count": row_count,
                "available_count": available_count,
            }
            self._script["mutations"] += 1
        elif s.startswith("INSERT INTO canonical_fib_zone_map_v1"):
            self._script["map_rows"].append(dict(params))
            self._script["mutations"] += 1
        elif s.startswith("INSERT INTO canonical_fib_zone_map_publication_repair_v1"):
            (
                venue, quote, interval, asof, map_version, old_publication_id,
                old_content_digest, new_publication_id, new_content_digest,
                operator, reason,
            ) = params
            self._script["repair_audit"].append(
                {
                    "old_publication_id": old_publication_id,
                    "old_content_digest": old_content_digest,
                    "new_publication_id": new_publication_id,
                    "new_content_digest": new_content_digest,
                    "operator": operator,
                    "reason": reason,
                }
            )
            self._script["mutations"] += 1
        else:
            raise AssertionError(f"unexpected SQL in fake cursor: {sql[:160]}")

    def _exec_candles(self, sql: str, params: Any) -> None:
        n = _count_in_placeholders(sql)
        venue, interval = params[0], params[1]
        symbols = params[2 : 2 + n]
        idx = 2 + n
        cutoff = None
        if "c.close_ts_utc <= %s" in sql:
            cutoff = params[idx]
            idx += 1
        lookback = params[idx]
        rows = [
            row
            for row in self._script["candles"]
            if row["symbol"] in symbols and (cutoff is None or row["close_ts_utc"] <= cutoff)
        ]
        by_symbol: dict[str, list[dict]] = {}
        for row in rows:
            by_symbol.setdefault(row["symbol"], []).append(row)
        result: list[dict] = []
        for symbol in symbols:
            ranked = sorted(by_symbol.get(symbol, []), key=lambda r: r["close_ts_utc"], reverse=True)[:lookback]
            result.extend(sorted(ranked, key=lambda r: r["close_ts_utc"]))
        self._result = result

    def _exec_trend(self, sql: str, params: Any) -> None:
        n = _count_in_placeholders(sql)
        symbols = params[2 : 2 + n]
        idx = 2 + n
        cutoff = params[idx] if "fc.close_ts_utc <= %s" in sql else None
        rows = [
            row
            for row in self._script["trend"]
            if row["symbol"] in symbols and (cutoff is None or row["close_ts_utc"] <= cutoff)
        ]
        by_symbol: dict[str, list[dict]] = {}
        for row in rows:
            by_symbol.setdefault(row["symbol"], []).append(row)
        result = []
        for symbol in symbols:
            ranked = sorted(by_symbol.get(symbol, []), key=lambda r: r["close_ts_utc"], reverse=True)
            if ranked:
                result.append(ranked[0])
        self._result = result

    def _exec_prior_before(self, params: Any) -> None:
        venue, quote, interval, before_asof = params
        candidates = [
            row
            for row in self._script["map_rows"]
            if row["asof_ts_utc"] < before_asof
            and self._script["publications"].get(row["publication_id"], {}).get("venue") == venue
            and self._script["publications"].get(row["publication_id"], {}).get("quote_currency") == quote
            and self._script["publications"].get(row["publication_id"], {}).get("interval_code") == interval
        ]
        by_symbol: dict[str, dict] = {}
        for row in candidates:
            existing = by_symbol.get(row["symbol"])
            if existing is None or row["asof_ts_utc"] > existing["asof_ts_utc"]:
                by_symbol[row["symbol"]] = row
        self._result = [by_symbol[symbol] for symbol in sorted(by_symbol)]

    def _exec_publication_lookup(self, sql: str, params: Any) -> None:
        has_row_count = "row_count" in sql
        if has_row_count:
            venue, quote, interval, asof = params
            map_version = None
        else:
            venue, quote, interval, asof, map_version = params
        match = None
        for row in self._script["publications"].values():
            if (
                row["venue"] == venue
                and row["quote_currency"] == quote
                and row["interval_code"] == interval
                and row["asof_ts_utc"] == asof
                and (map_version is None or row["map_version"] == map_version)
            ):
                match = row
                break
        self._result = match

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._result or []


class _FakeConn:
    def __init__(self, script: dict) -> None:
        self.script = script
        self.committed = 0
        self.rolled_back = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.script)

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def close(self) -> None:
        pass


def _empty_script() -> dict:
    return {
        "candles": _candle_rows(),
        "trend": _trend_rows(),
        "publications": {},
        "map_rows": [],
        "repair_audit": [],
        "mutations": 0,
    }


def _seed_bad_16_publication(conn: _FakeConn) -> Any:
    """Simulates the pre-PR#192 16:00Z publication: same exact identity, but
    built from different (bearish/DOWN) content than the bullish/UP data that
    actually sits in obs_market_candle/feat_candle for this asof in the fake
    database (see ``_candle_rows``/``_trend_rows``). This is what makes a
    correct historical rebuild for the same identity produce a different
    digest -- exactly the collision the repair path exists to resolve."""
    from src.market_data.fib_navigation_map_v1 import FibNavCandle

    source = [
        FibNavCandle(
            close_ts_utc=row["close_ts_utc"].replace(tzinfo=UTC),
            open_price=row["open_price"],
            high_price=row["high_price"],
            low_price=row["low_price"],
            close_price=row["close_price"],
            volume=row["volume"],
        )
        for row in _bearish_candle_rows_up_to_16()
    ]
    trend = {
        SYMBOL: {
            "close_ts_utc": ASOF_16,
            "price_vs_ema20": Decimal("-0.03"),
            "price_vs_ema50": Decimal("-0.04"),
            "ema_spread_pct": Decimal("-0.02"),
        }
    }
    build = build_publication(
        venue=VENUE,
        quote_currency=QUOTE,
        interval_code=INTERVAL,
        symbols=[SYMBOL],
        candles_by_symbol={SYMBOL: source},
        trend_rows_by_symbol=trend,
        now_utc=ASOF_16 + timedelta(minutes=30),
    )
    publish(conn, build, authorization=_authorization())
    return build


# ---------------------------------------------------------------------------
# Bounded-fetch behavior
# ---------------------------------------------------------------------------


def test_fixture_contains_both_16_and_20_candles_and_features() -> None:
    script = _empty_script()
    assert any(row["close_ts_utc"] == _naive(ASOF_16) for row in script["candles"])
    assert any(row["close_ts_utc"] == _naive(ASOF_20) for row in script["candles"])
    assert {row["close_ts_utc"] for row in script["trend"]} == {_naive(ASOF_16), _naive(ASOF_20)}


def test_normal_live_fetch_selects_20_not_16() -> None:
    conn = _FakeConn(_empty_script())
    candles = fetch_recent_candles(conn, venue=VENUE, interval_code=INTERVAL, symbols=[SYMBOL], lookback_candles=180)
    trend = fetch_latest_trend_rows(conn, venue=VENUE, interval_code=INTERVAL, symbols=[SYMBOL])
    assert candles[SYMBOL][-1].close_ts_utc == ASOF_20
    assert trend[SYMBOL]["close_ts_utc"] == ASOF_20

    build = build_publication(
        venue=VENUE,
        quote_currency=QUOTE,
        interval_code=INTERVAL,
        symbols=[SYMBOL],
        candles_by_symbol=candles,
        trend_rows_by_symbol=trend,
        now_utc=ASOF_20 + timedelta(minutes=30),
    )
    assert build.asof_ts_utc == ASOF_20


def test_historical_fetch_bounded_to_16_never_sees_20() -> None:
    conn = _FakeConn(_empty_script())
    candles = fetch_recent_candles(
        conn, venue=VENUE, interval_code=INTERVAL, symbols=[SYMBOL], lookback_candles=180,
        asof_cutoff_ts_utc=ASOF_16,
    )
    trend = fetch_latest_trend_rows(
        conn, venue=VENUE, interval_code=INTERVAL, symbols=[SYMBOL], asof_cutoff_ts_utc=ASOF_16
    )
    assert candles[SYMBOL][-1].close_ts_utc == ASOF_16
    assert all(candle.close_ts_utc <= ASOF_16 for candle in candles[SYMBOL])
    assert trend[SYMBOL]["close_ts_utc"] == ASOF_16


def test_build_historical_publication_rebuilds_16_never_20() -> None:
    conn = _FakeConn(_empty_script())
    build = build_historical_publication(
        conn,
        venue=VENUE,
        quote_currency=QUOTE,
        interval_code=INTERVAL,
        symbols=[SYMBOL],
        requested_asof_ts_utc=ASOF_16,
        now_utc=ASOF_16 + timedelta(minutes=30),
    )
    assert build.asof_ts_utc == ASOF_16


def test_rows_after_16_cannot_affect_the_digest() -> None:
    conn_without_future = _FakeConn(_empty_script())
    conn_without_future.script["candles"] = [
        row for row in conn_without_future.script["candles"] if row["close_ts_utc"] <= _naive(ASOF_16)
    ]
    conn_without_future.script["trend"] = [
        row for row in conn_without_future.script["trend"] if row["close_ts_utc"] <= _naive(ASOF_16)
    ]
    build_without_future = build_historical_publication(
        conn_without_future,
        venue=VENUE, quote_currency=QUOTE, interval_code=INTERVAL, symbols=[SYMBOL],
        requested_asof_ts_utc=ASOF_16, now_utc=ASOF_16 + timedelta(minutes=30),
    )

    conn_with_future = _FakeConn(_empty_script())
    build_with_future = build_historical_publication(
        conn_with_future,
        venue=VENUE, quote_currency=QUOTE, interval_code=INTERVAL, symbols=[SYMBOL],
        requested_asof_ts_utc=ASOF_16, now_utc=ASOF_16 + timedelta(minutes=30),
    )

    assert build_without_future.content_digest == build_with_future.content_digest


def test_historical_build_fails_closed_when_asof_cannot_be_reproduced() -> None:
    conn = _FakeConn(_empty_script())
    with pytest.raises(CanonicalFibMapError, match="could not reproduce exactly"):
        build_historical_publication(
            conn,
            venue=VENUE, quote_currency=QUOTE, interval_code=INTERVAL, symbols=[SYMBOL],
            requested_asof_ts_utc=ASOF_16 + timedelta(hours=1),
            now_utc=ASOF_20,
        )


# ---------------------------------------------------------------------------
# Prior continuity
# ---------------------------------------------------------------------------


def test_prior_continuity_excludes_publications_at_and_after_requested_asof() -> None:
    script = _empty_script()
    script["publications"] = {
        "fibnav-prior12": {
            "publication_id": "fibnav-prior12", "venue": VENUE, "quote_currency": QUOTE,
            "interval_code": INTERVAL, "asof_ts_utc": _naive(ASOF_12), "map_version": "canonical_fib_zone_map_v1",
            "content_digest": "1" * 64, "row_count": 1, "available_count": 1,
        },
        "fibnav-at16": {
            "publication_id": "fibnav-at16", "venue": VENUE, "quote_currency": QUOTE,
            "interval_code": INTERVAL, "asof_ts_utc": _naive(ASOF_16), "map_version": "canonical_fib_zone_map_v1",
            "content_digest": "2" * 64, "row_count": 1, "available_count": 1,
        },
        "fibnav-at20": {
            "publication_id": "fibnav-at20", "venue": VENUE, "quote_currency": QUOTE,
            "interval_code": INTERVAL, "asof_ts_utc": _naive(ASOF_20), "map_version": "canonical_fib_zone_map_v1",
            "content_digest": "3" * 64, "row_count": 1, "available_count": 1,
        },
    }
    script["map_rows"] = [
        _prior_map_row(asof=ASOF_12, publication_id="fibnav-prior12"),
        _prior_map_row(asof=ASOF_16, publication_id="fibnav-at16"),
        _prior_map_row(asof=ASOF_20, publication_id="fibnav-at20"),
    ]
    conn = _FakeConn(script)

    prior = fetch_production_rows_before(
        conn, venue=VENUE, quote_currency=QUOTE, interval_code=INTERVAL, before_asof_ts_utc=ASOF_16
    )
    assert set(prior) == {SYMBOL}
    assert prior[SYMBOL]["asof_ts_utc"] == _naive(ASOF_12)

    prior_strictly_after_16 = fetch_production_rows_before(
        conn, venue=VENUE, quote_currency=QUOTE, interval_code=INTERVAL, before_asof_ts_utc=ASOF_20
    )
    # Bounded to before 20:00Z: the 16:00Z row is a legitimate prior for a
    # 20:00Z build, but 20:00Z itself must never be its own prior.
    assert prior_strictly_after_16[SYMBOL]["asof_ts_utc"] == _naive(ASOF_16)


# ---------------------------------------------------------------------------
# End-to-end repair planning (fetch_publication_at_identity + historical build)
# ---------------------------------------------------------------------------


def test_repair_planning_derives_historical_symbols_from_existing_publication_and_rebuilds_16() -> None:
    conn = _FakeConn(_empty_script())
    old_build = _seed_bad_16_publication(conn)

    existing = fetch_publication_at_identity(
        conn, venue=VENUE, quote_currency=QUOTE, interval_code=INTERVAL, asof_ts_utc=ASOF_16
    )
    assert existing is not None
    assert existing["symbols"] == (SYMBOL,)
    assert existing["content_digest"] == old_build.content_digest

    rebuilt = build_historical_publication(
        conn,
        venue=VENUE, quote_currency=QUOTE, interval_code=INTERVAL,
        symbols=existing["symbols"], requested_asof_ts_utc=ASOF_16,
        now_utc=ASOF_16 + timedelta(minutes=30),
    )
    assert rebuilt.asof_ts_utc == ASOF_16
    # The bearish seed above simulates the pre-fix wrong content; the bounded
    # historical rebuild reads the real (bullish) candle/feature rows from the
    # fake database, so it reproduces different, correct content for the same
    # identity -- this is the exact collision the repair path resolves.
    assert rebuilt.content_digest != old_build.content_digest

    rebuilt_again = build_historical_publication(
        conn,
        venue=VENUE, quote_currency=QUOTE, interval_code=INTERVAL,
        symbols=existing["symbols"], requested_asof_ts_utc=ASOF_16,
        now_utc=ASOF_16 + timedelta(minutes=30),
    )
    assert rebuilt_again.content_digest == rebuilt.content_digest


# ---------------------------------------------------------------------------
# Runner: dry-run performs zero writes; collision protection unchanged
# ---------------------------------------------------------------------------


def test_runner_dry_run_performs_zero_writes(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    conn = _FakeConn(_empty_script())
    old_build = _seed_bad_16_publication(conn)
    monkeypatch.setattr(runner, "get_connection", lambda: conn)

    mutations_after_seed = conn.script["mutations"]

    exit_code = runner.main(["--asof", "2026-08-05T16:00:00Z", "--output", "json"])
    assert exit_code == 0
    assert conn.script["mutations"] == mutations_after_seed  # none from the dry run
    assert conn.committed == 0

    import json

    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    finished = [line for line in lines if line["event"] == "FINISHED"][0]
    assert finished["result"] == "DRY_RUN"
    assert finished["old_content_digest"] == old_build.content_digest
    assert finished["recomputed_content_digest"] != old_build.content_digest
    assert finished["recomputed_asof_ts_utc"] == "2026-08-05T16:00:00+00:00"
    assert finished["database_writes"] == 0


def test_runner_repair_end_to_end_replaces_16_only(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn(_empty_script())
    old_build = _seed_bad_16_publication(conn)
    monkeypatch.setattr(runner, "get_connection", lambda: conn)

    exit_code = runner.main(
        [
            "--asof", "2026-08-05T16:00:00Z",
            "--confirm-old-digest", old_build.content_digest,
            "--operator", "joost",
            "--reason", "confirmed feat_candle alignment defect fixed in PR #192",
            "--repair",
        ]
    )
    assert exit_code == 0
    assert conn.committed == 1
    assert len(conn.script["publications"]) == 1
    remaining = next(iter(conn.script["publications"].values()))
    assert remaining["asof_ts_utc"] == _naive(ASOF_16)
    assert all(
        row["publication_id"] == remaining["publication_id"] for row in conn.script["map_rows"]
    )
    assert all(
        row["input_latest_candle_ts_utc"].replace(tzinfo=None) == _naive(ASOF_16)
        for row in conn.script["map_rows"]
    )


def test_normal_collision_protection_remains_unchanged() -> None:
    from src.market_data.fib_navigation_map_v1 import FibNavCandle

    conn = _FakeConn(_empty_script())
    _seed_bad_16_publication(conn)
    # The bullish content that actually matches the fake obs_market_candle /
    # feat_candle rows for this asof -- different from the bearish seed above.
    different = build_publication(
        venue=VENUE,
        quote_currency=QUOTE,
        interval_code=INTERVAL,
        symbols=[SYMBOL],
        candles_by_symbol={
            SYMBOL: [
                FibNavCandle(
                    close_ts_utc=row["close_ts_utc"].replace(tzinfo=UTC),
                    open_price=row["open_price"],
                    high_price=row["high_price"],
                    low_price=row["low_price"],
                    close_price=row["close_price"],
                    volume=row["volume"],
                )
                for row in _candle_rows()
                if row["close_ts_utc"] <= _naive(ASOF_16)
            ]
        },
        trend_rows_by_symbol={
            SYMBOL: {
                "close_ts_utc": ASOF_16,
                "price_vs_ema20": Decimal("0.03"),
                "price_vs_ema50": Decimal("0.04"),
                "ema_spread_pct": Decimal("0.02"),
            }
        },
        now_utc=ASOF_16 + timedelta(minutes=30),
    )
    with pytest.raises(CanonicalFibMapError, match="publication identity collision"):
        publish(conn, different, authorization=_authorization())
    assert len(conn.script["publications"]) == 1
