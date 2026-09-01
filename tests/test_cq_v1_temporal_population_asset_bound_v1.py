from __future__ import annotations

from datetime import UTC, datetime

import src.research.cq_v1_temporal_population_v1 as population


class FakeCursor:
    def __init__(self) -> None:
        self.executed = []

    def execute(self, query, params):
        self.executed.append((" ".join(query.split()), tuple(params)))

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeConn:
    def __init__(self) -> None:
        self.cur = FakeCursor()

    def cursor(self):
        return self.cur


def test_selection_source_query_is_asset_bounded_when_requested() -> None:
    conn = FakeConn()
    asof = datetime(2026, 7, 18, tzinfo=UTC)
    population.fetch_selection_candidates_asof(
        conn, venue="bitvavo", asof_ts_utc=asof, asset_id=9
    )
    query, params = conn.cur.executed[0]
    assert query.count("asset_id=%s") >= 3
    assert params.count(9) == 3


def test_mrp_asset_query_is_asset_bounded_when_requested() -> None:
    conn = FakeConn()
    asof = datetime(2026, 7, 18, tzinfo=UTC)
    population.fetch_mrp_assets_asof(
        conn, venue="bitvavo", asof_ts_utc=asof, asset_id=9
    )
    query, params = conn.cur.executed[0]
    assert "o2.asset_id=%s" in query
    assert "o.asset_id=%s" in query
    assert params.count(9) == 2
