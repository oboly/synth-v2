from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

import src.research.run_entry_quality_forward_validation_v1 as runner
from src.research.entry_quality_forward_validation_v1 import (
    Candle,
    HorizonSpec,
    evaluate_horizon,
    pct_change,
    validate_candles,
)


def ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 28, hour, minute, tzinfo=UTC)


def candle(hour: int, minute: int, close: str, high: str, low: str) -> Candle:
    return Candle(
        close_ts_utc=ts(hour, minute),
        close_price=Decimal(close),
        high_price=Decimal(high),
        low_price=Decimal(low),
    )


def test_forward_outcome_uses_last_close_at_or_before_asof_and_strict_future() -> None:
    result = evaluate_horizon(
        observation_asof=ts(10, 7),
        candles=[
            candle(10, 0, "100", "101", "99"),
            candle(10, 15, "102", "103", "100"),
            candle(10, 30, "104", "105", "101"),
            candle(11, 0, "108", "110", "103"),
            candle(11, 15, "200", "205", "190"),
        ],
        horizon=HorizonSpec("1h", timedelta(hours=1)),
    )
    assert result.status == "COMPLETE"
    assert result.base_price == Decimal("100")
    assert result.future_close_price == Decimal("108")
    assert result.future_candle_count == 3
    assert result.forward_return_pct == Decimal("8.000000")
    assert result.mfe_pct == Decimal("10.000000")
    assert result.mae_pct == Decimal("0.000000")


def test_candle_exactly_at_observation_asof_is_base_not_future_label() -> None:
    result = evaluate_horizon(
        observation_asof=ts(10, 15),
        candles=[
            candle(10, 0, "100", "101", "99"),
            candle(10, 15, "101", "102", "100"),
            candle(10, 30, "103", "104", "101"),
        ],
        horizon=HorizonSpec("1h", timedelta(hours=1)),
    )
    assert result.base_price == Decimal("101")
    assert result.future_candle_count == 1
    assert result.future_close_price == Decimal("103")


def test_horizon_end_is_inclusive_but_candles_after_horizon_are_excluded() -> None:
    result = evaluate_horizon(
        observation_asof=ts(10, 0),
        candles=[
            candle(10, 0, "100", "101", "99"),
            candle(10, 30, "101", "102", "98"),
            candle(11, 0, "103", "105", "97"),
            candle(11, 15, "150", "160", "140"),
        ],
        horizon=HorizonSpec("1h", timedelta(hours=1)),
    )
    assert result.future_candle_count == 2
    assert result.future_close_price == Decimal("103")
    assert result.mfe_pct == Decimal("5.000000")
    assert result.mae_pct == Decimal("-3.000000")


def test_missing_base_price_fails_closed() -> None:
    result = evaluate_horizon(
        observation_asof=ts(10, 0),
        candles=[candle(10, 15, "101", "102", "100")],
        horizon=HorizonSpec("1h", timedelta(hours=1)),
    )
    assert result.status == "INSUFFICIENT_BASE_PRICE"
    assert result.forward_return_pct is None
    assert result.mfe_pct is None
    assert result.mae_pct is None


def test_missing_future_candles_fails_closed() -> None:
    result = evaluate_horizon(
        observation_asof=ts(10, 0),
        candles=[candle(10, 0, "100", "101", "99")],
        horizon=HorizonSpec("1h", timedelta(hours=1)),
    )
    assert result.status == "INSUFFICIENT_FUTURE_CANDLES"
    assert result.base_price == Decimal("100")
    assert result.future_close_price is None


def test_validate_candles_rejects_duplicate_timestamps() -> None:
    rows = [
        candle(10, 0, "100", "101", "99"),
        candle(10, 0, "100", "101", "99"),
    ]
    with pytest.raises(ValueError, match="strictly increasing and unique"):
        validate_candles(rows)


def test_pct_change_is_deterministic_decimal_math() -> None:
    assert pct_change(Decimal("100"), Decimal("101.25")) == Decimal("1.250000")


class _FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _args(tmp_path, *, resume: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        registry="unused.yaml",
        venue="bitvavo",
        asset_id=None,
        limit=100,
        output_dir=str(tmp_path),
        resume=resume,
    )


def _observation(shadow_id: int) -> dict:
    return {
        "shadow_id": shadow_id,
        "asset_id": 1,
        "symbol": "AAVE",
        "venue": "bitvavo",
        "asof_ts_utc": "2026-08-28T10:00:00+00:00",
        "evidence_key": f"evidence-{shadow_id}",
        "cq_model_version": "cq_shadow_v1",
        "trade_quality_score": Decimal("0.60"),
        "selection_score": Decimal("0.62"),
        "entry_quality_score": Decimal("0.60"),
        "entry_quality_state": "GOOD",
        "ppp_pct": Decimal("20"),
        "ppp_kind": "ACTIONABLE_PPP",
        "ppp_source_ref": "test",
        "entry_strength": Decimal("12"),
    }


def _outcome_row(shadow_id: int) -> dict:
    return {"shadow_id": shadow_id, "horizon": "1h", "status": "COMPLETE"}


def _registry() -> dict:
    return {
        "registry_name": "entry_quality_forward_validation_v1",
        "registry_version": "1.0.0",
    }


def test_checkpoint_roundtrip_and_resume_starts_after_last_shadow_id(tmp_path) -> None:
    runner.write_checkpoint(
        tmp_path,
        registry=_registry(),
        last_shadow_id=42,
        observations_completed=7,
        rows_written=21,
        terminal_state="INTERRUPTED",
    )
    loaded = runner.load_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded["last_shadow_id"] == 42
    assert loaded["observations_completed"] == 7
    assert loaded["rows_written"] == 21
    assert loaded["terminal_state"] == "INTERRUPTED"


def test_resume_appends_only_new_observations_and_preserves_cumulative_totals(monkeypatch, tmp_path) -> None:
    registry = _registry()
    horizons = [HorizonSpec("1h", timedelta(hours=1))]
    conn = _FakeConnection()
    seen_after: list[int | None] = []

    runner.write_checkpoint(
        tmp_path,
        registry=registry,
        last_shadow_id=10,
        observations_completed=7,
        rows_written=21,
        terminal_state="INTERRUPTED",
    )
    existing_rows = "".join(
        f'{{"shadow_id": {shadow_id}, "horizon": "1h", "status": "COMPLETE"}}\n'
        for shadow_id in range(4, 11)
        for _ in range(3)
    )
    (tmp_path / runner.OUTPUT_ROWS).write_text(existing_rows, encoding="utf-8")

    monkeypatch.setattr(runner, "_install_signal_handlers", lambda: {})
    monkeypatch.setattr(runner, "_restore_signal_handlers", lambda _previous: None)
    monkeypatch.setattr(runner, "load_registry", lambda _path: (registry, horizons))
    monkeypatch.setattr(runner, "get_db_connection", lambda: conn)

    def _fetch(_conn, **kwargs):
        seen_after.append(kwargs.get("after_shadow_id"))
        return [_observation(11)]

    monkeypatch.setattr(runner, "fetch_shadow_observations", _fetch)
    monkeypatch.setattr(
        runner,
        "build_rows_for_observation",
        lambda *_args, observation, **_kwargs: [
            _outcome_row(int(observation["shadow_id"])),
            {**_outcome_row(int(observation["shadow_id"])), "horizon": "4h"},
            {**_outcome_row(int(observation["shadow_id"])), "horizon": "24h"},
        ],
    )

    assert runner.run(_args(tmp_path, resume=True)) == 0
    assert seen_after == [10]
    checkpoint = runner.load_checkpoint(tmp_path)
    assert checkpoint is not None
    assert checkpoint["last_shadow_id"] == 11
    assert checkpoint["observations_completed"] == 8
    assert checkpoint["rows_written"] == 24
    assert checkpoint["terminal_state"] == "FINISHED"
    rows = [
        line
        for line in (tmp_path / runner.OUTPUT_ROWS).read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(rows) == 24
    assert '"shadow_id": 11' in rows[-1]
    assert conn.closed is True


def test_interruption_writes_terminal_checkpoint(monkeypatch, tmp_path, capsys) -> None:
    registry = _registry()
    horizons = [HorizonSpec("1h", timedelta(hours=1))]
    conn = _FakeConnection()

    monkeypatch.setattr(runner, "_install_signal_handlers", lambda: {})
    monkeypatch.setattr(runner, "_restore_signal_handlers", lambda _previous: None)
    monkeypatch.setattr(runner, "load_registry", lambda _path: (registry, horizons))
    monkeypatch.setattr(runner, "get_db_connection", lambda: conn)
    monkeypatch.setattr(
        runner,
        "fetch_shadow_observations",
        lambda *_args, **_kwargs: [_observation(1), _observation(2)],
    )

    def _build(*_args, observation, **_kwargs):
        rows = [_outcome_row(int(observation["shadow_id"]))]
        if int(observation["shadow_id"]) == 1:
            runner._STOP_REQUESTED = True
            runner._STOP_SIGNAL = "SIGTERM"
        return rows

    monkeypatch.setattr(runner, "build_rows_for_observation", _build)

    result = runner.run(_args(tmp_path))
    output = capsys.readouterr().out
    checkpoint = runner.load_checkpoint(tmp_path)
    assert result == 130
    assert "INTERRUPTED runner=entry_quality_forward_validation_v1 signal=SIGTERM" in output
    assert checkpoint is not None
    assert checkpoint["last_shadow_id"] == 1
    assert checkpoint["observations_completed"] == 1
    assert checkpoint["rows_written"] == 1
    assert checkpoint["terminal_state"] == "INTERRUPTED"
