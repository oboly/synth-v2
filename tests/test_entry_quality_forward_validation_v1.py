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
            candle(11, 30, "999", "1000", "998"),
        ],
        horizon=HorizonSpec("1h", timedelta(hours=1)),
    )
    assert result.status == "COMPLETE"
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
    assert result.status == "COMPLETE"
    assert result.future_candle_count == 2
    assert result.future_close_price == Decimal("103")
    assert result.mfe_pct == Decimal("5.000000")
    assert result.mae_pct == Decimal("-3.000000")


def test_truncated_horizon_fails_closed_even_with_some_future_candles() -> None:
    result = evaluate_horizon(
        observation_asof=ts(10, 0),
        candles=[
            candle(10, 0, "100", "101", "99"),
            candle(10, 15, "101", "102", "100"),
            candle(10, 30, "103", "104", "101"),
        ],
        horizon=HorizonSpec("1h", timedelta(hours=1)),
    )
    assert result.status == "INSUFFICIENT_HORIZON_COVERAGE"
    assert result.base_price == Decimal("100")
    assert result.future_candle_count == 2
    assert result.future_close_price is None
    assert result.forward_return_pct is None
    assert result.mfe_pct is None
    assert result.mae_pct is None


def test_post_horizon_candle_proves_coverage_without_leaking_its_values() -> None:
    result = evaluate_horizon(
        observation_asof=ts(10, 0),
        candles=[
            candle(10, 0, "100", "101", "99"),
            candle(10, 30, "102", "103", "98"),
            candle(11, 15, "999", "1000", "998"),
        ],
        horizon=HorizonSpec("1h", timedelta(hours=1)),
    )
    assert result.status == "COMPLETE"
    assert result.future_candle_count == 1
    assert result.future_close_price == Decimal("102")
    assert result.forward_return_pct == Decimal("2.000000")
    assert result.mfe_pct == Decimal("3.000000")
    assert result.mae_pct == Decimal("-2.000000")


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


def test_missing_future_candles_fails_closed_after_horizon_is_covered() -> None:
    result = evaluate_horizon(
        observation_asof=ts(10, 0),
        candles=[
            candle(10, 0, "100", "101", "99"),
            candle(11, 15, "150", "151", "149"),
        ],
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


def _args(tmp_path, *, resume: bool = False, venue: str = "bitvavo", asset_id: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        registry="unused.yaml",
        venue=venue,
        asset_id=asset_id,
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


def _outcome_row(shadow_id: int, horizon: str = "1h") -> dict:
    return {"shadow_id": shadow_id, "horizon": horizon, "status": "COMPLETE"}


def _registry() -> dict:
    return {
        "registry_name": "entry_quality_forward_validation_v1",
        "registry_version": "1.0.0",
    }


def _write_checkpoint(tmp_path, *, last_shadow_id: int | None, observations: int, rows: int, venue: str = "bitvavo", asset_id: int | None = None) -> None:
    runner.write_checkpoint(
        tmp_path,
        registry=_registry(),
        venue=venue,
        asset_id=asset_id,
        last_shadow_id=last_shadow_id,
        observations_completed=observations,
        rows_written=rows,
        terminal_state="INTERRUPTED",
    )


def test_checkpoint_roundtrip_includes_scope(tmp_path) -> None:
    _write_checkpoint(tmp_path, last_shadow_id=42, observations=7, rows=21, asset_id=12)
    loaded = runner.load_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded["venue"] == "bitvavo"
    assert loaded["asset_id"] == 12
    assert loaded["last_shadow_id"] == 42
    assert loaded["observations_completed"] == 7
    assert loaded["rows_written"] == 21
    assert loaded["terminal_state"] == "INTERRUPTED"


def test_reconcile_truncates_append_before_checkpoint_crash_window(tmp_path) -> None:
    checkpoint = {
        "last_shadow_id": 10,
        "rows_written": 3,
    }
    rows_path = tmp_path / runner.OUTPUT_ROWS
    rows_path.write_text(
        "".join(
            runner.json.dumps(_outcome_row(shadow_id), sort_keys=True) + "\n"
            for shadow_id in (10, 10, 10, 11, 11, 11)
        ),
        encoding="utf-8",
    )
    rows = runner.reconcile_output_to_checkpoint(rows_path, checkpoint)
    assert len(rows) == 3
    persisted = runner._read_existing_rows(rows_path)
    assert len(persisted) == 3
    assert all(int(row["shadow_id"]) == 10 for row in persisted)


def test_reconcile_fails_closed_when_jsonl_is_shorter_than_checkpoint(tmp_path) -> None:
    rows_path = tmp_path / runner.OUTPUT_ROWS
    rows_path.write_text(runner.json.dumps(_outcome_row(10)) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Checkpoint/output mismatch"):
        runner.reconcile_output_to_checkpoint(rows_path, {"last_shadow_id": 10, "rows_written": 3})


def test_resume_appends_only_new_observations_and_preserves_cumulative_totals(monkeypatch, tmp_path) -> None:
    registry = _registry()
    horizons = [HorizonSpec("1h", timedelta(hours=1))]
    conn = _FakeConnection()
    seen_after: list[int | None] = []

    _write_checkpoint(tmp_path, last_shadow_id=10, observations=7, rows=21)
    existing_rows = "".join(
        runner.json.dumps(_outcome_row(shadow_id, horizon), sort_keys=True) + "\n"
        for shadow_id in range(4, 11)
        for horizon in ("1h", "4h", "24h")
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
            _outcome_row(int(observation["shadow_id"]), "1h"),
            _outcome_row(int(observation["shadow_id"]), "4h"),
            _outcome_row(int(observation["shadow_id"]), "24h"),
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
    assert len(runner._read_existing_rows(tmp_path / runner.OUTPUT_ROWS)) == 24
    assert conn.closed is True


def test_resume_rejects_scope_mismatch_before_db_connect(monkeypatch, tmp_path, capsys) -> None:
    _write_checkpoint(tmp_path, last_shadow_id=10, observations=1, rows=1, asset_id=1)
    (tmp_path / runner.OUTPUT_ROWS).write_text(runner.json.dumps(_outcome_row(10)) + "\n", encoding="utf-8")
    monkeypatch.setattr(runner, "_install_signal_handlers", lambda: {})
    monkeypatch.setattr(runner, "_restore_signal_handlers", lambda _previous: None)
    monkeypatch.setattr(runner, "load_registry", lambda _path: (_registry(), [HorizonSpec("1h", timedelta(hours=1))]))
    monkeypatch.setattr(runner, "get_db_connection", lambda: (_ for _ in ()).throw(AssertionError("DB must not connect")))

    assert runner.run(_args(tmp_path, resume=True, asset_id=2)) == 1
    assert "Checkpoint asset_id mismatch" in capsys.readouterr().out


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


def test_safety_line_emits_required_markers(monkeypatch, tmp_path, capsys) -> None:
    registry = _registry()
    conn = _FakeConnection()
    monkeypatch.setattr(runner, "_install_signal_handlers", lambda: {})
    monkeypatch.setattr(runner, "_restore_signal_handlers", lambda _previous: None)
    monkeypatch.setattr(runner, "load_registry", lambda _path: (registry, [HorizonSpec("1h", timedelta(hours=1))]))
    monkeypatch.setattr(runner, "get_db_connection", lambda: conn)
    monkeypatch.setattr(runner, "fetch_shadow_observations", lambda *_args, **_kwargs: [])

    assert runner.run(_args(tmp_path)) == 0
    output = capsys.readouterr().out
    assert "broker_private_calls=0" in output
    assert "order_submission=0" in output
    assert "live_orders=0" in output
