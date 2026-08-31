from datetime import UTC, datetime, timedelta

from src.research.run_multi_horizon_rotation_dataset_builder_v1 import fetch_candles_for_chunk


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def test_candle_fetch_uses_bounded_fetchmany_and_never_fetchall() -> None:
    rows = [
        {"asset_id": 1, "close_ts_utc": BASE, "close_price": "100", "volume_base": "2"},
        {
            "asset_id": 1,
            "close_ts_utc": BASE + timedelta(minutes=15),
            "close_price": "101",
            "volume_base": "3",
        },
        {"asset_id": 2, "close_ts_utc": BASE, "close_price": "50", "volume_base": "4"},
    ]

    class Cursor:
        def __init__(self) -> None:
            self.offset = 0
            self.fetchmany_sizes: list[int] = []
            self.executed: tuple[str, tuple[object, ...]] | None = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql: str, params: tuple[object, ...]) -> None:
            self.executed = (sql, params)

        def fetchmany(self, size: int):
            self.fetchmany_sizes.append(size)
            batch = rows[self.offset : self.offset + size]
            self.offset += len(batch)
            return batch

        def fetchall(self):
            raise AssertionError("bounded candle source fetch must not call fetchall")

    class Connection:
        def __init__(self) -> None:
            self.cursor_obj = Cursor()

        def cursor(self):
            return self.cursor_obj

    conn = Connection()
    asof = BASE + timedelta(hours=36)
    phase_end = asof + timedelta(days=1)
    candles, closes, row_count = fetch_candles_for_chunk(
        conn,
        venue="bitvavo",
        chunk_asofs=[asof],
        phase_end=phase_end,
        batch_size=2,
    )

    assert conn.cursor_obj.fetchmany_sizes == [2, 2, 2]
    assert conn.cursor_obj.executed is not None
    sql, params = conn.cursor_obj.executed
    assert "ORDER BY asset_id, close_ts_utc" in sql
    assert params[0] == "bitvavo"
    assert row_count == 3
    assert [c.close_price for c in candles[1]] == [100, 101]
    assert closes[1][BASE] == 100
    assert closes[2][BASE] == 50
