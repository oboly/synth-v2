from __future__ import annotations

"""Regressions for #488: the normal recurring writer must be idempotent for
an immediate rerun of the same as-of publication identity.

Root cause on prior main: the recurring writer read prior continuity through
the unbounded ``fetch_latest_production_rows`` (the "current latest" view),
so an immediate rerun for the same asof read the identity's own
just-published cohort as its own prior continuity, changing the semantic
content digest for an unchanged public input state and tripping the
publish() collision guard.

The fix: the recurring writer (``load_publication_inputs`` in
``run_canonical_fib_zone_map_v1``) derives the candidate ``asof_ts_utc``
directly from fetched candles first, then reads prior continuity via
``fetch_production_rows_before(before_asof_ts_utc=candidate)`` -- the same
bounded read the historical/operator repair path already used.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from src.market_data.canonical_fib_zone_map_v1 import (
    CanonicalFibMapError,
    PublicationBuild,
    build_historical_publication,
    build_publication,
    fetch_production_rows_before,
    publish,
)
from src.market_data import run_canonical_fib_zone_map_v1 as runner
from src.operations.writer_capability_authorization_v1 import (
    ExecutionMode,
    _mint_authorization,
)


VENUE = "bitvavo"
QUOTE = "EUR"
INTERVAL = "4h"
SYMBOL = "BTC"

T = datetime(2026, 8, 23, 16, 0, tzinfo=UTC)
T_PRIOR = T - timedelta(hours=4)


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


def _bullish_candle_rows(*, latest: datetime) -> list[dict[str, Any]]:
    lows = ("100", "98", "95", "90", "94", "99", "104", "108", "106", "109", "111", "112")
    highs = ("105", "103", "100", "95", "100", "106", "112", "120", "116", "119", "121", "122")
    start = latest - timedelta(hours=4 * (len(lows) - 1))
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
    assert rows[-1]["close_ts_utc"] == _naive(latest)
    return rows


def _trend_row(*, latest: datetime) -> dict[str, Any]:
    return {
        "symbol": SYMBOL,
        "close_ts_utc": _naive(latest),
        "price_vs_ema20": Decimal("0.03"),
        "price_vs_ema50": Decimal("0.04"),
        "ema_spread_pct": Decimal("0.02"),
    }


def _count_in_placeholders(sql: str) -> int:
    import re

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
        elif "canonical_fib_zone_map_publication_v1 p" in sql and "canonical_fib_zone_map_v1 mm" in sql:
            self._exec_prior_before(params)
        elif s.startswith("SELECT DISTINCT a.symbol"):
            self._result = [{"symbol": SYMBOL}]
        elif "FOR UPDATE" in sql:
            self._exec_publication_lookup(params)
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
        elif s.startswith("INSERT INTO canonical_fib_zone_map_v1"):
            self._script["map_rows"].append(dict(params))
        else:
            raise AssertionError(f"unexpected SQL in fake cursor: {sql[:160]}")

    def _exec_candles(self, sql: str, params: Any) -> None:
        n = _count_in_placeholders(sql)
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

    def _exec_publication_lookup(self, params: Any) -> None:
        venue, quote, interval, asof = params
        match = None
        for row in self._script["publications"].values():
            if (
                row["venue"] == venue
                and row["quote_currency"] == quote
                and row["interval_code"] == interval
                and row["asof_ts_utc"] == asof
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

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.script)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _fixed_symbol_universe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "fetch_tracked_symbols", lambda *args, **kwargs: [SYMBOL])


def _empty_script(*, latest: datetime = T) -> dict:
    return {
        "candles": _bullish_candle_rows(latest=latest),
        "trend": [_trend_row(latest=latest)],
        "publications": {},
        "map_rows": [],
    }


def _load_and_build(conn: _FakeConn) -> PublicationBuild:
    symbols, candles, prior_rows, trend_rows, _metrics = runner.load_publication_inputs(
        conn,
        venue=VENUE,
        quote=QUOTE,
        interval=INTERVAL,
        lookback_candles=180,
    )
    return build_publication(
        venue=VENUE,
        quote_currency=QUOTE,
        interval_code=INTERVAL,
        symbols=symbols,
        candles_by_symbol=candles,
        trend_rows_by_symbol=trend_rows,
        now_utc=T + timedelta(minutes=5),
        prior_rows_by_symbol=prior_rows,
    )


# ---------------------------------------------------------------------------
# A. publish T -> rebuild T: identical digest, second publish UNCHANGED
# ---------------------------------------------------------------------------


def test_immediate_rebuild_of_same_asof_produces_identical_digest_and_unchanged() -> None:
    conn = _FakeConn(_empty_script())

    build_1 = _load_and_build(conn)
    assert build_1.asof_ts_utc == T
    result_1 = publish(conn, build_1, authorization=_authorization())
    assert result_1.status == "PUBLISHED"

    # Immediate rerun for the same asof, same public input state.
    build_2 = _load_and_build(conn)
    assert build_2.asof_ts_utc == T
    assert build_2.content_digest == build_1.content_digest

    result_2 = publish(conn, build_2, authorization=_authorization())
    assert result_2.status == "UNCHANGED"
    assert result_2.publication_id == result_1.publication_id
    assert result_2.content_digest == build_1.content_digest


# ---------------------------------------------------------------------------
# B. prior continuity used by the builder for candidate T stays strictly < T
# ---------------------------------------------------------------------------


def test_prior_continuity_stays_strictly_before_candidate_even_after_t_is_published() -> None:
    conn = _FakeConn(_empty_script())

    # Seed a real prior cohort at T-4h.
    prior_script = _empty_script(latest=T_PRIOR)
    prior_conn = _FakeConn(prior_script)
    prior_build = _load_and_build(prior_conn)
    assert prior_build.asof_ts_utc == T_PRIOR
    publish(prior_conn, prior_build, authorization=_authorization())
    conn.script["publications"] = prior_script["publications"]
    conn.script["map_rows"] = prior_script["map_rows"]

    prior_before_publish = fetch_production_rows_before(
        conn, venue=VENUE, quote_currency=QUOTE, interval_code=INTERVAL, before_asof_ts_utc=T,
    )
    assert prior_before_publish[SYMBOL]["asof_ts_utc"] == _naive(T_PRIOR)

    build_at_t = _load_and_build(conn)
    assert build_at_t.asof_ts_utc == T
    publish(conn, build_at_t, authorization=_authorization())

    # T is now published too. Prior continuity for a rebuild of T must still
    # resolve to T-4h, never to T itself.
    prior_after_publish = fetch_production_rows_before(
        conn, venue=VENUE, quote_currency=QUOTE, interval_code=INTERVAL, before_asof_ts_utc=T,
    )
    assert prior_after_publish[SYMBOL]["asof_ts_utc"] == _naive(T_PRIOR)

    build_at_t_again = _load_and_build(conn)
    assert build_at_t_again.content_digest == build_at_t.content_digest


# ---------------------------------------------------------------------------
# C. a later publication must never leak into an earlier identity's prior
#    continuity (shared bound with the historical/operator repair path)
# ---------------------------------------------------------------------------


def test_future_publication_never_leaks_into_earlier_prior_continuity() -> None:
    script = _empty_script(latest=T_PRIOR)
    conn = _FakeConn(script)
    build_prior = _load_and_build(conn)
    publish(conn, build_prior, authorization=_authorization())

    # A later cohort exists at T, strictly after the identity under test.
    later_row = dict(script["map_rows"][0])
    later_row["asof_ts_utc"] = _naive(T)
    later_row["publication_id"] = "fibnav-future"
    script["map_rows"].append(later_row)
    script["publications"]["fibnav-future"] = {
        "publication_id": "fibnav-future",
        "venue": VENUE,
        "quote_currency": QUOTE,
        "interval_code": INTERVAL,
        "asof_ts_utc": _naive(T),
        "map_version": "canonical_fib_zone_map_v1",
        "content_digest": "f" * 64,
        "row_count": 1,
        "available_count": 1,
    }

    rebuilt_prior = fetch_production_rows_before(
        conn, venue=VENUE, quote_currency=QUOTE, interval_code=INTERVAL, before_asof_ts_utc=T_PRIOR,
    )
    assert rebuilt_prior == {}

    historical_rebuild = build_historical_publication(
        conn,
        venue=VENUE,
        quote_currency=QUOTE,
        interval_code=INTERVAL,
        symbols=[SYMBOL],
        requested_asof_ts_utc=T_PRIOR,
        now_utc=T_PRIOR + timedelta(minutes=5),
    )
    assert historical_rebuild.content_digest == build_prior.content_digest


# ---------------------------------------------------------------------------
# D. genuine same-identity content mismatch still raises
# ---------------------------------------------------------------------------


def test_genuine_content_mismatch_for_same_identity_still_raises() -> None:
    conn = _FakeConn(_empty_script())
    build_1 = _load_and_build(conn)
    publish(conn, build_1, authorization=_authorization())

    mismatched = PublicationBuild(
        venue=build_1.venue,
        quote_currency=build_1.quote_currency,
        interval_code=build_1.interval_code,
        asof_ts_utc=build_1.asof_ts_utc,
        rows=build_1.rows,
        content_digest="0" * 64,
        available_count=build_1.available_count,
    )
    with pytest.raises(CanonicalFibMapError, match="collision"):
        publish(conn, mismatched, authorization=_authorization())


# ---------------------------------------------------------------------------
# E. empty/no prior cohort: first publication is unaffected
# ---------------------------------------------------------------------------


def test_first_publication_with_no_prior_cohort_is_unaffected() -> None:
    conn = _FakeConn(_empty_script())
    symbols, candles, prior_rows, trend_rows, metrics = runner.load_publication_inputs(
        conn, venue=VENUE, quote=QUOTE, interval=INTERVAL, lookback_candles=180,
    )
    assert prior_rows == {}
    assert metrics["prior_rows"] == 0
    build = _load_and_build(conn)
    result = publish(conn, build, authorization=_authorization())
    assert result.status == "PUBLISHED"


# ---------------------------------------------------------------------------
# F. recurring writer and historical/operator repair path share the same
#    prior-continuity primitive
# ---------------------------------------------------------------------------


def test_recurring_writer_and_repair_path_share_fetch_production_rows_before() -> None:
    assert runner.fetch_production_rows_before is fetch_production_rows_before
    import inspect

    assert "fetch_production_rows_before" in inspect.getsource(build_historical_publication)
    assert "fetch_production_rows_before" in inspect.getsource(runner.load_publication_inputs)
    assert "fetch_latest_production_rows" not in inspect.getsource(runner.load_publication_inputs)
