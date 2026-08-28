from datetime import UTC, datetime, timedelta
from decimal import Decimal

import src.research.run_entry_quality_forward_validation_v1 as runner
from src.research.entry_quality_forward_validation_v1 import HorizonSpec, evaluate_horizon


def ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 28, hour, minute, tzinfo=UTC)


class _CursorSequence:
    def __init__(self, responses):
        self._responses = iter(responses)
        self._current = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, _sql, _params):
        self._current = next(self._responses)

    def fetchone(self):
        if isinstance(self._current, list):
            return self._current[0] if self._current else None
        return self._current

    def fetchall(self):
        return list(self._current or [])


class _Connection:
    def __init__(self, responses):
        self._responses = responses

    def cursor(self):
        return _CursorSequence(self._responses)


def test_runner_fetches_post_max_horizon_coverage_candle_for_nonaligned_asof() -> None:
    conn = _Connection(
        [
            {
                "close_ts_utc": ts(10, 0),
                "close_price": "100",
                "high_price": "101",
                "low_price": "99",
            },
            [
                {
                    "close_ts_utc": ts(10, 15),
                    "close_price": "101",
                    "high_price": "102",
                    "low_price": "100",
                },
                {
                    "close_ts_utc": ts(11, 0),
                    "close_price": "103",
                    "high_price": "104",
                    "low_price": "101",
                },
            ],
            {
                "close_ts_utc": ts(11, 15),
                "close_price": "999",
                "high_price": "1000",
                "low_price": "998",
            },
        ]
    )

    candles = runner.fetch_candles_for_observation(
        conn,
        asset_id=1,
        venue="bitvavo",
        observation_asof=ts(10, 7),
        max_horizon=timedelta(hours=1),
    )
    result = evaluate_horizon(
        observation_asof=ts(10, 7),
        candles=candles,
        horizon=HorizonSpec("1h", timedelta(hours=1)),
    )

    assert result.status == "COMPLETE"
    assert result.future_close_price == Decimal("103")
    assert result.forward_return_pct == Decimal("3.000000")
    assert result.mfe_pct == Decimal("4.000000")
    assert result.mae_pct == Decimal("0.000000")
