from __future__ import annotations

from datetime import UTC, datetime

from src.research.measure_rotation_pressure_freshness_sla_v1 import (
    ASOF_RE,
    FINISHED_RE,
    STARTED_RE,
    _parse_ts,
    _pctile,
    parse_publisher_journal_export,
    source_completion_for_asof,
    summarize,
)


def test_parse_ts_handles_z_and_utc_suffix_and_naive() -> None:
    assert _parse_ts("2026-09-01T14:20:32Z") == datetime(2026, 9, 1, 14, 20, 32, tzinfo=UTC)
    assert _parse_ts("2026-08-08 12:00:00 UTC") == datetime(2026, 8, 8, 12, 0, 0, tzinfo=UTC)
    assert _parse_ts("2026-08-08T12:00:00+00:00") == datetime(2026, 8, 8, 12, 0, 0, tzinfo=UTC)


def test_writer_log_regexes_match_real_lines() -> None:
    started = "STARTED runner=run_market_rotation_pressure_once mode=market_data_write ts=2026-09-01T14:20:26Z"
    finished = "FINISHED runner=run_market_rotation_pressure_once exit_status=0 elapsed_sec=5 ts=2026-09-01T14:20:32Z"
    asof_line = "MARKET ROTATION as_of=2026-09-01T14:00:00Z venue=bitvavo direction=ROTATION_IN score=+21.15 lights=4/5"

    m = STARTED_RE.search(started)
    assert m is not None
    assert m.group("ts") == "2026-09-01T14:20:26Z"

    m = FINISHED_RE.search(finished)
    assert m is not None
    assert m.group("code") == "0"
    assert m.group("elapsed") == "5"
    assert m.group("ts") == "2026-09-01T14:20:32Z"

    m = ASOF_RE.search(asof_line)
    assert m is not None
    assert m.group("asof") == "2026-09-01T14:00:00Z"


def test_pctile_and_summarize_basic() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _pctile(values, 0.0) == 1.0
    assert _pctile(values, 1.0) == 5.0
    assert _pctile(values, 0.5) == 3.0

    summary = summarize("x", values)
    assert summary["count"] == 5
    assert summary["min_sec"] == 1.0
    assert summary["max_sec"] == 5.0
    assert summary["p50_sec"] == 3.0


def test_summarize_empty() -> None:
    assert summarize("x", []) == {"label": "x", "count": 0}


def test_source_completion_for_asof_picks_first_completion_at_or_after() -> None:
    asof = datetime(2026, 9, 1, 14, 0, 0, tzinfo=UTC)
    completions = [
        datetime(2026, 9, 1, 13, 48, 23, tzinfo=UTC),
        datetime(2026, 9, 1, 14, 4, 12, tzinfo=UTC),
        datetime(2026, 9, 1, 14, 18, 37, tzinfo=UTC),
    ]
    result = source_completion_for_asof(asof, completions)
    assert result == datetime(2026, 9, 1, 14, 4, 12, tzinfo=UTC)


def test_source_completion_for_asof_none_when_no_later_completion() -> None:
    asof = datetime(2026, 9, 1, 14, 0, 0, tzinfo=UTC)
    completions = [datetime(2026, 9, 1, 13, 0, 0, tzinfo=UTC)]
    assert source_completion_for_asof(asof, completions) is None


def test_parse_publisher_journal_export_pairs_started_finished() -> None:
    text = "\n".join(
        [
            "2026-09-01T14:36:49+00:00 odroid synth-market-rotation-pressure-publisher[1]: STARTED runner=run_market_rotation_pressure_dashboard_render_once mode=read_only ts=2026-09-01T14:36:49Z",
            "2026-09-01T14:36:49+00:00 odroid synth-market-rotation-pressure-publisher[2]: PUBLISHED html=/x.html json=/x.json status=AVAILABLE freshness=FRESH direction=ROTATION_IN score=+1.00 lights=1/5 eligible=100",
            "2026-09-01T14:36:50+00:00 odroid synth-market-rotation-pressure-publisher[1]: FINISHED runner=run_market_rotation_pressure_dashboard_render_once exit_status=0 elapsed_sec=1 ts=2026-09-01T14:36:50Z",
        ]
    )
    successes, failures, boots = parse_publisher_journal_export(text)
    assert len(successes) == 1
    assert len(failures) == 0
    assert len(boots) == 0
    assert successes[0].start_ts == datetime(2026, 9, 1, 14, 36, 49, tzinfo=UTC)
    assert successes[0].finish_ts == datetime(2026, 9, 1, 14, 36, 50, tzinfo=UTC)
    assert successes[0].published_ts == datetime(2026, 9, 1, 14, 36, 49, tzinfo=UTC)
    assert successes[0].elapsed_sec == 1
    assert successes[0].exit_status == 0


def test_parse_publisher_journal_export_detects_network_outage_failure() -> None:
    text = "\n".join(
        [
            "2026-09-01T07:47:38+00:00 odroid synth-market-rotation-pressure-publisher[588]: STARTED runner=run_market_rotation_pressure_dashboard_render_once mode=read_only ts=2026-09-01T07:47:38Z",
            "2026-09-01T07:47:42+00:00 odroid synth-market-rotation-pressure-publisher[636]: Traceback (most recent call last):",
            "2026-09-01T07:47:42+00:00 odroid synth-market-rotation-pressure-publisher[636]: OSError: [Errno 101] Network is unreachable",
            "2026-09-01T07:47:42+00:00 odroid synth-market-rotation-pressure-publisher[636]: pymysql.err.OperationalError: (2003, \"Can't connect\")",
            "-- Boot dd9fd0eb376243618809cf8a1f2f3df1 --",
            "2026-09-01T08:17:01+00:00 odroid synth-market-rotation-pressure-publisher[567]: STARTED runner=run_market_rotation_pressure_dashboard_render_once mode=read_only ts=2026-09-01T08:17:01Z",
            "2026-09-01T08:17:05+00:00 odroid synth-market-rotation-pressure-publisher[605]: Traceback (most recent call last):",
            "2026-09-01T08:17:05+00:00 odroid synth-market-rotation-pressure-publisher[605]: OSError: [Errno 101] Network is unreachable",
        ]
    )
    successes, failures, boots = parse_publisher_journal_export(text)
    assert len(successes) == 0
    assert len(failures) == 2
    assert len(boots) == 1
    assert all(f.error_reason for f in failures)
    assert failures[0].start_ts == datetime(2026, 9, 1, 7, 47, 38, tzinfo=UTC)
