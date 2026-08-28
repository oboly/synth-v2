from decimal import Decimal
from types import SimpleNamespace

import pytest

import src.research.run_entry_quality_shadow_v1 as runner
from src.research.entry_quality_shadow_v1 import (
    EntryQualityInput,
    compute_entry_quality_shadow,
    compute_entry_strength,
)


def test_entry_quality_uses_trade_quality_as_independent_baseline() -> None:
    result = compute_entry_quality_shadow(
        EntryQualityInput(
            trade_quality_score=Decimal("0.68"),
            timing_refinement_score=Decimal("0.03"),
            quality_penalty=Decimal("0.05"),
            quality_status_1d="TRUSTED",
            quality_status_4h="TRUSTED",
            quality_status_1h="TRUSTED",
        )
    )

    assert result.entry_quality_score == Decimal("0.680000")
    assert result.entry_quality_state == "GOOD"
    assert "BASELINE_FROM_TRADE_QUALITY_SCORE" in result.reasons
    assert "TIMING_REFINEMENT_OBSERVED_NOT_APPLIED" in result.reasons
    assert "QUALITY_PENALTY_OBSERVED_NOT_APPLIED" in result.reasons
    assert result.blockers == ()


def test_entry_quality_blocks_on_required_quality() -> None:
    result = compute_entry_quality_shadow(
        EntryQualityInput(
            trade_quality_score=Decimal("0.90"),
            timing_refinement_score=Decimal("0.03"),
            quality_penalty=Decimal("0"),
            quality_status_1d="TRUSTED",
            quality_status_4h="BLOCKED",
            quality_status_1h="TRUSTED",
        )
    )

    assert result.entry_quality_score is None
    assert result.entry_quality_state == "BLOCKED"
    assert result.blockers == ("BLOCKED_4H_QUALITY",)


def test_blocked_1h_does_not_block_higher_timeframe_cq() -> None:
    result = compute_entry_quality_shadow(
        EntryQualityInput(
            trade_quality_score=Decimal("0.50"),
            timing_refinement_score=Decimal("0"),
            quality_penalty=Decimal("0"),
            quality_status_1d="TRUSTED",
            quality_status_4h="TRUSTED",
            quality_status_1h="BLOCKED",
        )
    )

    assert result.entry_quality_score == Decimal("0.500000")
    assert result.entry_quality_state == "WATCH"
    assert "1H_REFINEMENT_UNAVAILABLE" in result.reasons


def test_entry_strength_multiplies_ppp_percentage_points_by_cq() -> None:
    assert compute_entry_strength(
        ppp_pct=Decimal("20.00"),
        entry_quality_score=Decimal("0.75"),
    ) == Decimal("15.000000")


def test_entry_strength_fails_closed_on_missing_ppp_or_cq() -> None:
    assert compute_entry_strength(
        ppp_pct=None,
        entry_quality_score=Decimal("0.75"),
    ) is None
    assert compute_entry_strength(
        ppp_pct=Decimal("20"),
        entry_quality_score=None,
    ) is None


def test_entry_strength_rejects_invalid_ranges() -> None:
    assert compute_entry_strength(
        ppp_pct=Decimal("-1"),
        entry_quality_score=Decimal("0.75"),
    ) is None
    assert compute_entry_strength(
        ppp_pct=Decimal("20"),
        entry_quality_score=Decimal("1.01"),
    ) is None


def test_source_asof_uses_evidence_timestamp_not_runner_time() -> None:
    row = SimpleNamespace(symbol="AAVE", asof_ts_utc="2026-08-28 04:00:00")
    assert runner._source_asof(row) == "2026-08-28 04:00:00"


def test_source_asof_fails_closed_when_missing() -> None:
    row = SimpleNamespace(symbol="AAVE", asof_ts_utc=None)
    with pytest.raises(ValueError, match="Missing canonical source as-of"):
        runner._source_asof(row)


def test_ppp_csv_rejects_mixed_planning_and_actionable(tmp_path) -> None:
    path = tmp_path / "ppp.csv"
    path.write_text(
        "symbol,ppp_pct,ppp_kind,ppp_source_ref\n"
        "AAVE,20,ACTIONABLE_PPP,action:aave\n"
        "ETH,10,PLANNING_PPP,planning:eth\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must contain exactly one PPP kind"):
        runner._load_ppp_csv(str(path))


def test_ppp_csv_rejects_unknown_kind(tmp_path) -> None:
    path = tmp_path / "ppp.csv"
    path.write_text(
        "symbol,ppp_pct,ppp_kind,ppp_source_ref\n"
        "AAVE,20,SURPRISE_PPP,source:aave\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported ppp_kind"):
        runner._load_ppp_csv(str(path))


def test_parse_args_has_deterministic_default_csv() -> None:
    args = runner.parse_args([])
    assert args.out_csv == runner.DEFAULT_OUTPUT_CSV


class _FakeConnection:
    def __init__(self) -> None:
        self.closed = False
        self.rolled_back = False

    def close(self) -> None:
        self.closed = True

    def rollback(self) -> None:
        self.rolled_back = True


def _runner_args() -> SimpleNamespace:
    return SimpleNamespace(
        config="unused.yaml",
        venue="bitvavo",
        limit=1,
        asset_id=None,
        ppp_csv=None,
        out_csv=runner.DEFAULT_OUTPUT_CSV,
        write_db=False,
    )


def test_runner_success_emits_lifecycle_and_default_csv(monkeypatch, capsys) -> None:
    conn = _FakeConnection()
    csv_calls: list[tuple[str, list[dict]]] = []
    monkeypatch.setattr(runner, "get_db_connection", lambda: conn)
    monkeypatch.setattr(runner, "load_selection_config", lambda _path: {})
    monkeypatch.setattr(runner, "fetch_selection_candidates", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(runner, "rank_candidates", lambda _rows, _config: [])
    monkeypatch.setattr(runner, "_load_ppp_csv", lambda _path: {})
    monkeypatch.setattr(runner, "write_csv", lambda path, rows: csv_calls.append((path, rows)))

    result = runner.run(_runner_args())
    output = capsys.readouterr().out

    assert result == 0
    assert output.count("STARTED runner=entry_quality_shadow_v1") == 1
    assert "PHASE_START name=fetch_selection_candidates" in output
    assert "PHASE_END name=fetch_selection_candidates" in output
    assert "PHASE_START name=build_shadow" in output
    assert "PHASE_END name=build_shadow" in output
    assert "PHASE_START name=write_csv" in output
    assert "PHASE_END name=write_csv" in output
    assert output.count("FINISHED runner=entry_quality_shadow_v1") == 1
    assert "FAILED runner=entry_quality_shadow_v1" not in output
    assert csv_calls == [(runner.DEFAULT_OUTPUT_CSV, [])]
    assert conn.closed is True


def test_runner_failure_emits_single_failed_terminal(monkeypatch, capsys) -> None:
    def _fail_connection():
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "get_db_connection", _fail_connection)

    result = runner.run(_runner_args())
    output = capsys.readouterr().out

    assert result == 1
    assert output.count("STARTED runner=entry_quality_shadow_v1") == 1
    assert output.count("FAILED runner=entry_quality_shadow_v1") == 1
    assert "reason=RuntimeError:boom" in output
    assert "FINISHED runner=entry_quality_shadow_v1" not in output
