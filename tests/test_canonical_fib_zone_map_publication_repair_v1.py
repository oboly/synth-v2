from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from src.market_data.canonical_fib_zone_map_v1 import (
    CanonicalFibMapError,
    PublicationBuild,
    build_publication,
    publish,
)
from src.market_data.fib_navigation_map_v1 import FibNavCandle
from src.operations.canonical_fib_zone_map_publication_repair_v1 import (
    RepairResult,
    repair_publication_identity,
)
from src.operations.writer_capability_authorization_v1 import (
    ExecutionMode,
    _mint_authorization,
)


NOW = datetime(2026, 8, 5, 16, 30, tzinfo=UTC)
ASOF = NOW - timedelta(minutes=30)


def bullish_candles() -> list[FibNavCandle]:
    lows = ("100", "98", "95", "90", "94", "99", "104", "108", "106", "109", "111", "112")
    highs = ("105", "103", "100", "95", "100", "106", "112", "120", "116", "119", "121", "122")
    start = ASOF - timedelta(hours=4 * (len(lows) - 1))
    return [
        FibNavCandle(
            close_ts_utc=start + timedelta(hours=4 * index),
            open_price=(Decimal(low) + Decimal(high)) / 2,
            high_price=Decimal(high),
            low_price=Decimal(low),
            close_price=(Decimal(low) + Decimal(high)) / 2,
            volume=Decimal("1000"),
        )
        for index, (low, high) in enumerate(zip(lows, highs, strict=True))
    ]


def bearish_candles() -> list[FibNavCandle]:
    lows = ("110", "112", "115", "120", "116", "110", "104", "98", "100", "96", "94", "92")
    highs = ("115", "117", "120", "125", "122", "116", "110", "104", "108", "102", "100", "98")
    start = ASOF - timedelta(hours=4 * (len(lows) - 1))
    return [
        FibNavCandle(
            close_ts_utc=start + timedelta(hours=4 * index),
            open_price=(Decimal(low) + Decimal(high)) / 2,
            high_price=Decimal(high),
            low_price=Decimal(low),
            close_price=(Decimal(low) + Decimal(high)) / 2,
            volume=Decimal("1000"),
        )
        for index, (low, high) in enumerate(zip(lows, highs, strict=True))
    ]


def trend_row(source_candles: list[FibNavCandle], *, state: str) -> dict[str, object]:
    values = {
        "UP": (Decimal("0.03"), Decimal("0.04"), Decimal("0.02")),
        "DOWN": (Decimal("-0.03"), Decimal("-0.04"), Decimal("-0.02")),
    }[state]
    return {
        "close_ts_utc": source_candles[-1].close_ts_utc,
        "price_vs_ema20": values[0],
        "price_vs_ema50": values[1],
        "ema_spread_pct": values[2],
    }


def bad_build() -> PublicationBuild:
    """Simulates the pre-PR#192 publication: same asof identity, wrong content."""
    source = bearish_candles()
    return build_publication(
        venue="bitvavo",
        quote_currency="EUR",
        interval_code="4h",
        symbols=["BTC"],
        candles_by_symbol={"BTC": source},
        trend_rows_by_symbol={"BTC": trend_row(source, state="DOWN")},
        now_utc=NOW,
    )


def good_build() -> PublicationBuild:
    """Simulates the corrected post-PR#192 recomputation for the same asof identity."""
    source = bullish_candles()
    return build_publication(
        venue="bitvavo",
        quote_currency="EUR",
        interval_code="4h",
        symbols=["BTC"],
        candles_by_symbol={"BTC": source},
        trend_rows_by_symbol={"BTC": trend_row(source, state="UP")},
        now_utc=NOW,
    )


def other_asof_build() -> PublicationBuild:
    other_now = NOW + timedelta(hours=4)
    other_asof = other_now - timedelta(minutes=30)
    source = [
        FibNavCandle(
            close_ts_utc=candle.close_ts_utc + timedelta(hours=4),
            open_price=candle.open_price,
            high_price=candle.high_price,
            low_price=candle.low_price,
            close_price=candle.close_price,
            volume=candle.volume,
        )
        for candle in bullish_candles()
    ]
    assert source[-1].close_ts_utc == other_asof
    return build_publication(
        venue="bitvavo",
        quote_currency="EUR",
        interval_code="4h",
        symbols=["BTC"],
        candles_by_symbol={"BTC": source},
        trend_rows_by_symbol={"BTC": trend_row(source, state="UP")},
        now_utc=other_now,
    )


class _FakeCursor:
    def __init__(self, script: dict) -> None:
        self._script = script
        self._result: Any = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: Any = ()) -> None:
        stripped = sql.strip()
        if stripped.startswith("SELECT") and "canonical_fib_zone_map_publication_v1" in sql:
            venue, quote, interval, asof = params[0], params[1], params[2], params[3]
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
        elif stripped.startswith("DELETE FROM canonical_fib_zone_map_v1"):
            publication_id = params[0]
            self._script["map_rows"] = [
                row for row in self._script["map_rows"] if row["publication_id"] != publication_id
            ]
        elif stripped.startswith("DELETE FROM canonical_fib_zone_map_publication_v1"):
            publication_id = params[0]
            self._script["publications"].pop(publication_id, None)
        elif stripped.startswith("INSERT INTO canonical_fib_zone_map_publication_v1"):
            (
                publication_id,
                venue,
                quote,
                interval,
                asof,
                map_version,
                digest,
                row_count,
                available_count,
                producer_name,
                producer_version,
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
        elif stripped.startswith("INSERT INTO canonical_fib_zone_map_v1"):
            self._script["map_rows"].append(dict(params))
        elif stripped.startswith("INSERT INTO canonical_fib_zone_map_publication_repair_v1"):
            (
                venue,
                quote,
                interval,
                asof,
                map_version,
                old_publication_id,
                old_content_digest,
                new_publication_id,
                new_content_digest,
                operator,
                reason,
            ) = params
            self._script["repair_audit"].append(
                {
                    "venue": venue,
                    "quote_currency": quote,
                    "interval_code": interval,
                    "asof_ts_utc": asof,
                    "map_version": map_version,
                    "old_publication_id": old_publication_id,
                    "old_content_digest": old_content_digest,
                    "new_publication_id": new_publication_id,
                    "new_content_digest": new_content_digest,
                    "operator": operator,
                    "reason": reason,
                }
            )
        else:
            raise AssertionError(f"unexpected SQL in fake cursor: {sql[:120]}")

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._result or []


class _FakeConn:
    def __init__(self, script: dict | None = None) -> None:
        self.script = script or {"publications": {}, "map_rows": [], "repair_audit": []}
        self.committed = 0
        self.rolled_back = 0

    def cursor(self):
        return _FakeCursor(self.script)

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1


def _authorization() -> Any:
    return _mint_authorization(
        capability_id="native_short_4h_chain",
        execution_mode=ExecutionMode.PRODUCTION,
        validated_host="test-host",
        validated_commit="0" * 40,
        authorization_or_permit_id="test-authorization",
    )


def _seed_bad_publication(conn: _FakeConn) -> PublicationBuild:
    build = bad_build()
    publish(conn, build, authorization=_authorization())
    return build


def test_normal_publish_still_fails_closed_on_different_content_same_identity() -> None:
    conn = _FakeConn()
    _seed_bad_publication(conn)
    with pytest.raises(CanonicalFibMapError, match="publication identity collision"):
        publish(conn, good_build(), authorization=_authorization())
    assert len(conn.script["publications"]) == 1
    assert len(conn.script["map_rows"]) == 1


def test_repair_requires_exact_expected_old_digest_wrong_digest_fails_closed() -> None:
    conn = _FakeConn()
    old_build = _seed_bad_publication(conn)
    new_build = good_build()
    assert old_build.content_digest != new_build.content_digest

    with pytest.raises(CanonicalFibMapError, match="expected_old_digest"):
        repair_publication_identity(
            conn,
            venue="bitvavo",
            quote_currency="EUR",
            interval_code="4h",
            asof_ts_utc=ASOF,
            expected_old_digest="0" * 64,
            new_build=new_build,
            operator="joost",
            reason="confirmed feat_candle alignment defect fixed in PR #192",
        )
    # No mutation on a digest mismatch.
    assert len(conn.script["publications"]) == 1
    only = next(iter(conn.script["publications"].values()))
    assert only["content_digest"] == old_build.content_digest
    assert conn.script["repair_audit"] == []


def test_repair_requires_matching_scope_fails_closed() -> None:
    conn = _FakeConn()
    old_build = _seed_bad_publication(conn)
    mismatched = good_build()
    # Force an interval mismatch against the exact repair scope.
    mismatched_wrong_interval = PublicationBuild(
        venue=mismatched.venue,
        quote_currency=mismatched.quote_currency,
        interval_code="1h",
        asof_ts_utc=mismatched.asof_ts_utc,
        rows=mismatched.rows,
        content_digest=mismatched.content_digest,
        available_count=mismatched.available_count,
    )

    with pytest.raises(CanonicalFibMapError, match="does not match the exact repair scope"):
        repair_publication_identity(
            conn,
            venue="bitvavo",
            quote_currency="EUR",
            interval_code="4h",
            asof_ts_utc=ASOF,
            expected_old_digest=old_build.content_digest,
            new_build=mismatched_wrong_interval,
            operator="joost",
            reason="scope mismatch test",
        )
    assert len(conn.script["publications"]) == 1
    assert conn.script["repair_audit"] == []


def test_repair_requires_operator_and_reason() -> None:
    conn = _FakeConn()
    old_build = _seed_bad_publication(conn)
    new_build = good_build()
    with pytest.raises(CanonicalFibMapError, match="operator"):
        repair_publication_identity(
            conn,
            venue="bitvavo",
            quote_currency="EUR",
            interval_code="4h",
            asof_ts_utc=ASOF,
            expected_old_digest=old_build.content_digest,
            new_build=new_build,
            operator="",
            reason="confirmed defect",
        )
    with pytest.raises(CanonicalFibMapError, match="reason"):
        repair_publication_identity(
            conn,
            venue="bitvavo",
            quote_currency="EUR",
            interval_code="4h",
            asof_ts_utc=ASOF,
            expected_old_digest=old_build.content_digest,
            new_build=new_build,
            operator="joost",
            reason="   ",
        )
    assert len(conn.script["publications"]) == 1
    assert conn.script["repair_audit"] == []


def test_repair_with_no_existing_publication_fails_closed() -> None:
    conn = _FakeConn()
    new_build = good_build()
    with pytest.raises(CanonicalFibMapError, match="no existing publication"):
        repair_publication_identity(
            conn,
            venue="bitvavo",
            quote_currency="EUR",
            interval_code="4h",
            asof_ts_utc=ASOF,
            expected_old_digest="0" * 64,
            new_build=new_build,
            operator="joost",
            reason="confirmed defect",
        )
    assert conn.script["publications"] == {}
    assert conn.script["repair_audit"] == []


def test_repair_replaces_publication_transactionally_and_records_audit_evidence() -> None:
    conn = _FakeConn()
    old_build = _seed_bad_publication(conn)
    new_build = good_build()

    result = repair_publication_identity(
        conn,
        venue="bitvavo",
        quote_currency="EUR",
        interval_code="4h",
        asof_ts_utc=ASOF,
        expected_old_digest=old_build.content_digest,
        new_build=new_build,
        operator="joost",
        reason="confirmed feat_candle alignment defect fixed in PR #192",
    )

    assert isinstance(result, RepairResult)
    assert result.status == "REPAIRED"
    assert result.old_content_digest == old_build.content_digest
    assert result.new_content_digest == new_build.content_digest
    assert result.old_publication_id != result.new_publication_id

    # Old publication_id is fully gone; exactly one publication remains at this identity.
    assert result.old_publication_id not in conn.script["publications"]
    assert len(conn.script["publications"]) == 1
    remaining = next(iter(conn.script["publications"].values()))
    assert remaining["content_digest"] == new_build.content_digest
    assert remaining["publication_id"] == result.new_publication_id

    # Child rows now belong only to the new publication_id.
    assert all(row["publication_id"] == result.new_publication_id for row in conn.script["map_rows"])
    assert len(conn.script["map_rows"]) == len(new_build.rows)

    # Provenance/audit evidence recorded.
    assert len(conn.script["repair_audit"]) == 1
    audit = conn.script["repair_audit"][0]
    assert audit["old_content_digest"] == old_build.content_digest
    assert audit["new_content_digest"] == new_build.content_digest
    assert audit["operator"] == "joost"
    assert "PR #192" in audit["reason"]


def test_unrelated_publications_remain_untouched_by_repair() -> None:
    conn = _FakeConn()
    old_build = _seed_bad_publication(conn)
    other_build = other_asof_build()
    publish(conn, other_build, authorization=_authorization())
    assert len(conn.script["publications"]) == 2

    new_build = good_build()
    repair_publication_identity(
        conn,
        venue="bitvavo",
        quote_currency="EUR",
        interval_code="4h",
        asof_ts_utc=ASOF,
        expected_old_digest=old_build.content_digest,
        new_build=new_build,
        operator="joost",
        reason="confirmed feat_candle alignment defect fixed in PR #192",
    )

    assert len(conn.script["publications"]) == 2
    digests = {row["content_digest"] for row in conn.script["publications"].values()}
    assert digests == {new_build.content_digest, other_build.content_digest}
    other_rows = [
        row
        for row in conn.script["map_rows"]
        if row["asof_ts_utc"] == conn.script["publications"][
            next(pid for pid, row in conn.script["publications"].items() if row["content_digest"] == other_build.content_digest)
        ]["asof_ts_utc"]
    ]
    assert len(other_rows) == len(other_build.rows)


def test_rerunning_normal_publish_after_repair_returns_unchanged() -> None:
    conn = _FakeConn()
    old_build = _seed_bad_publication(conn)
    new_build = good_build()
    repair_publication_identity(
        conn,
        venue="bitvavo",
        quote_currency="EUR",
        interval_code="4h",
        asof_ts_utc=ASOF,
        expected_old_digest=old_build.content_digest,
        new_build=new_build,
        operator="joost",
        reason="confirmed feat_candle alignment defect fixed in PR #192",
    )

    result = publish(conn, new_build, authorization=_authorization())
    assert result.status == "UNCHANGED"
    assert result.content_digest == new_build.content_digest
    # Rerunning the normal writer performs no further mutation.
    assert len(conn.script["publications"]) == 1
    assert len(conn.script["map_rows"]) == len(new_build.rows)
