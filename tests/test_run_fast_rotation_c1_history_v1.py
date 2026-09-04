from __future__ import annotations

from datetime import UTC, datetime

from src.features import run_fast_rotation_c1_history_v1 as runner


def test_runner_safety_markers_include_live_orders_and_no_activation():
    assert "live_orders=0" in runner.SAFETY_LINE
    assert "production_activation=0" in runner.SAFETY_LINE
    assert "account_awareness=0" in runner.SAFETY_LINE
    assert "decision_gate=none" in runner.SAFETY_LINE
    assert "execution_planner=none" in runner.SAFETY_LINE
    assert "executor=none" in runner.SAFETY_LINE


def test_runner_declares_single_worker_and_heartbeat_interval():
    assert runner.WORKER_COUNT == 1
    assert runner.HEARTBEAT_INTERVAL_S > 0


def test_parse_ts_requires_15m_close_grid():
    parsed = runner.parse_ts("2026-09-04T12:15:00Z")
    assert parsed == datetime(2026, 9, 4, 12, 15, tzinfo=UTC)


def test_interruption_signal_preserves_sigterm():
    assert runner._interruption_signal(KeyboardInterrupt("SIGTERM")) == "SIGTERM"


def test_interruption_signal_defaults_to_sigint():
    assert runner._interruption_signal(KeyboardInterrupt()) == "SIGINT"
