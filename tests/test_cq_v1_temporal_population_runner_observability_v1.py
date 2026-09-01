from __future__ import annotations

from pathlib import Path

import src.research.run_cq_v1_temporal_population_v1 as runner


def test_runner_declares_single_worker_and_observable_scope() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert runner.WORKER_COUNT == 1
    assert "mode={mode}" in source
    assert "scope=frozen_daily_pit_45_asofs" in source
    assert "workers={WORKER_COUNT}" in source


def test_runner_reports_asof_query_rows_and_elapsed_time() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "QUERY phase=asof_population status=started" in source
    assert "QUERY phase=asof_population status=finished" in source
    assert "rows={len(asof_rows)} elapsed_s={asof_elapsed:.3f}" in source
    assert "PHASE phase=population status=finished" in source
    assert "PHASE phase=finalize status=finished" in source


def test_terminal_logs_include_elapsed_time() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "INTERRUPTED runner={RUNNER_NAME}" in source
    assert "FAILED runner={RUNNER_NAME}" in source
    assert "FINISHED runner={RUNNER_NAME}" in source
    assert "elapsed_s={time.monotonic() - run_started:.3f}" in source
