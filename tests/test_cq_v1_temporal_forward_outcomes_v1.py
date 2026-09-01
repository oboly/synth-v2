from __future__ import annotations

import argparse
import json
import signal
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.research.entry_quality_forward_validation_v1 import Candle
from src.research import run_cq_v1_temporal_forward_outcomes_v1 as mod


def _observation(asset_id: int, asof: str, observation_id: str) -> dict:
    return {
        "observation_id": observation_id,
        "asset_id": asset_id,
        "symbol": f"A{asset_id}",
        "venue": "bitvavo",
        "asof_ts_utc": asof,
        "split": "discovery",
        "evidence_key": f"e{asset_id}",
        "cq_model_version": "cq_shadow_v1",
        "model_family_version": "1.0.0",
        "trade_quality_score": "0.5",
        "selection_score": "0.4",
        "cq_v0": "0.45",
    }


def _args(**overrides) -> argparse.Namespace:
    values = {
        "population": "frozen.jsonl",
        "contract": mod.DEFAULT_CONTRACT,
        "venue": "bitvavo",
        "output_dir": "unused",
        "asof_index": None,
        "asset_id": None,
        "limit_observations": None,
        "horizon": None,
        "resume": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _outcome_row(observation: dict, horizon: str = "1h") -> dict:
    return {
        "outcome_id": f"{observation['observation_id']}:{horizon}",
        "observation_id": observation["observation_id"],
        "asset_id": observation["asset_id"],
        "symbol": observation["symbol"],
        "venue": observation["venue"],
        "observation_asof_ts_utc": observation["asof_ts_utc"],
        "split": observation["split"],
        "horizon": horizon,
        "status": "COMPLETE",
        "forward_return_pct": "1.0",
        "mfe_pct": "2.0",
        "mae_pct": "-1.0",
    }


def test_frozen_contract_loads_exact_horizons() -> None:
    contract, horizons = mod.load_contract()
    assert contract["frozen_population"]["population_sha256"] == mod.PINNED_POPULATION_SHA256
    assert [(item.label, int(item.delta.total_seconds() // 60)) for item in horizons] == [
        ("1h", 60),
        ("4h", 240),
        ("24h", 1440),
    ]


def test_load_population_fails_closed_on_hash_mismatch(tmp_path) -> None:
    path = tmp_path / "population.jsonl"
    path.write_text(json.dumps(_observation(1, "2026-07-18T00:00:00+00:00", "x")) + "\n")
    contract, _ = mod.load_contract()
    with pytest.raises(ValueError, match="population SHA256 mismatch"):
        mod.load_population(path, contract)


def test_select_population_rows_applies_asof_asset_and_limit() -> None:
    rows = [
        _observation(2, "2026-07-19T00:00:00+00:00", "b"),
        _observation(1, "2026-07-18T00:00:00+00:00", "a"),
        _observation(2, "2026-07-18T00:00:00+00:00", "c"),
    ]
    selected = mod.select_population_rows(rows, _args(asof_index=1, asset_id=2, limit_observations=1))
    assert [row["observation_id"] for row in selected] == ["c"]


def test_build_outcomes_batches_single_asof_and_is_deterministic(monkeypatch) -> None:
    asof = "2026-07-18T00:00:00+00:00"
    observations = [_observation(1, asof, "obs-1"), _observation(2, asof, "obs-2")]
    calls: list[tuple[list[int], datetime]] = []

    def fake_fetch(conn, *, asset_ids, venue, observation_asof, max_horizon):
        calls.append((list(asset_ids), observation_asof))
        out = {}
        for asset_id in asset_ids:
            base = Decimal("100") + Decimal(asset_id)
            out[asset_id] = [
                Candle(datetime(2026, 7, 18, 0, 0, tzinfo=UTC), base, base, base),
                Candle(datetime(2026, 7, 18, 1, 0, tzinfo=UTC), base + 1, base + 2, base - 1),
                Candle(datetime(2026, 7, 18, 4, 0, tzinfo=UTC), base + 2, base + 3, base - 2),
                Candle(datetime(2026, 7, 19, 0, 0, tzinfo=UTC), base + 4, base + 5, base - 3),
            ]
        return out

    monkeypatch.setattr(mod, "fetch_candles_for_asof_assets", fake_fetch)
    _, horizons = mod.load_contract()
    rows1 = mod.build_outcome_rows(object(), observations=observations, venue="bitvavo", horizons=horizons)
    rows2 = mod.build_outcome_rows(object(), observations=observations, venue="bitvavo", horizons=horizons)

    assert len(calls) == 2
    assert calls[0][0] == [1, 2]
    assert len(rows1) == 6
    assert [row["outcome_id"] for row in rows1] == [row["outcome_id"] for row in rows2]
    assert len({row["outcome_id"] for row in rows1}) == 6
    assert {row["status"] for row in rows1} == {"COMPLETE"}


def test_build_outcomes_rejects_multiple_asofs() -> None:
    observations = [
        _observation(1, "2026-07-18T00:00:00+00:00", "a"),
        _observation(1, "2026-07-19T00:00:00+00:00", "b"),
    ]
    _, horizons = mod.load_contract()
    with pytest.raises(ValueError, match="exactly one as-of batch"):
        mod.build_outcome_rows(object(), observations=observations, venue="bitvavo", horizons=horizons)


def test_population_venue_mismatch_fails_closed() -> None:
    observation = _observation(1, "2026-07-18T00:00:00+00:00", "obs-1")
    observation["venue"] = "other"
    _, horizons = mod.load_contract()
    with pytest.raises(ValueError, match="population venue mismatch"):
        mod.build_outcome_rows(object(), observations=[observation], venue="bitvavo", horizons=horizons)


def test_single_horizon_remains_one_label_per_observation(monkeypatch) -> None:
    observation = _observation(1, "2026-07-18T00:00:00+00:00", "obs-1")

    def fake_fetch(conn, *, asset_ids, venue, observation_asof, max_horizon):
        return {
            1: [
                Candle(datetime(2026, 7, 18, 0, 0, tzinfo=UTC), Decimal("100"), Decimal("100"), Decimal("100")),
                Candle(datetime(2026, 7, 18, 1, 0, tzinfo=UTC), Decimal("101"), Decimal("102"), Decimal("99")),
            ]
        }

    monkeypatch.setattr(mod, "fetch_candles_for_asof_assets", fake_fetch)
    _, horizons = mod.load_contract()
    rows = mod.build_outcome_rows(
        object(), observations=[observation], venue="bitvavo", horizons=[item for item in horizons if item.label == "1h"]
    )
    assert len(rows) == 1
    assert rows[0]["horizon"] == "1h"
    assert rows[0]["status"] == "COMPLETE"
    assert rows[0]["forward_return_pct"] == Decimal("1.000000")


def test_fresh_output_requires_new_directory(tmp_path) -> None:
    output_dir = tmp_path / "existing"
    output_dir.mkdir()
    with pytest.raises(ValueError, match="immutable outcome output directory already exists"):
        mod._prepare_output(output_dir, args=_args(), asof_total=1)


def test_checkpoint_reconcile_discards_uncheckpointed_tail(tmp_path) -> None:
    rows_path = tmp_path / mod.OUTPUT_ROWS
    rows_path.write_bytes(
        mod._row_line({"outcome_id": "kept", "horizon": "1h", "status": "COMPLETE"})
        + b'{"partial":'
    )
    rows = mod._load_checkpointed_rows(rows_path, 1)
    assert [row["outcome_id"] for row in rows] == ["kept"]
    assert len(rows_path.read_text().splitlines()) == 1


def test_preflight_signal_interrupt_does_not_create_output_or_connect(monkeypatch, tmp_path, capsys) -> None:
    output_dir = tmp_path / "not-created"
    _, horizons = mod.load_contract()
    previous_sigint_handler = signal.getsignal(signal.SIGINT)
    monkeypatch.setattr(mod, "load_contract", lambda path=mod.DEFAULT_CONTRACT: ({}, horizons))

    def interrupt_population(path, contract):
        handler = signal.getsignal(signal.SIGINT)
        handler(signal.SIGINT, None)
        raise AssertionError("installed SIGINT handler did not interrupt population loading")

    monkeypatch.setattr(mod, "load_population", interrupt_population)
    monkeypatch.setattr(mod, "get_db_connection", lambda: pytest.fail("DB connection attempted during preflight"))

    assert mod.run(_args(output_dir=str(output_dir))) == 130
    output = capsys.readouterr().out
    assert output.count("INTERRUPTED runner=") == 1
    assert "resumable=0" in output
    assert "asofs_completed=0" in output
    assert "outcome_rows=0" in output
    assert "db_writes=0" in output
    assert not output_dir.exists()
    assert signal.getsignal(signal.SIGINT) is previous_sigint_handler


def test_interrupt_then_resume_finishes_same_output(monkeypatch, tmp_path, capsys) -> None:
    observations = [
        _observation(1, "2026-07-18T00:00:00+00:00", "obs-1"),
        _observation(1, "2026-07-19T00:00:00+00:00", "obs-2"),
    ]
    _, horizons = mod.load_contract()
    monkeypatch.setattr(mod, "load_contract", lambda path=mod.DEFAULT_CONTRACT: ({}, horizons))
    monkeypatch.setattr(mod, "load_population", lambda path, contract: observations)

    class Conn:
        def rollback(self):
            pass
        def close(self):
            pass

    monkeypatch.setattr(mod, "get_db_connection", lambda: Conn())
    calls = {"n": 0}

    def interrupt_second(conn, *, observations, venue, horizons):
        calls["n"] += 1
        if calls["n"] == 2:
            handler = signal.getsignal(signal.SIGINT)
            handler(signal.SIGINT, None)
        return [_outcome_row(observations[0])]

    monkeypatch.setattr(mod, "build_outcome_rows", interrupt_second)
    output_dir = tmp_path / "run"
    fresh = _args(output_dir=str(output_dir))
    assert mod.run(fresh) == 130
    checkpoint = json.loads((output_dir / mod.OUTPUT_CHECKPOINT).read_text())
    assert checkpoint["terminal_state"] == "INTERRUPTED"
    assert checkpoint["asofs_completed"] == 1
    assert checkpoint["outcome_rows_written"] == 1
    first_output = capsys.readouterr().out
    assert first_output.count("INTERRUPTED runner=") == 1
    assert "resumable=1" in first_output
    assert "db_writes=0" in first_output
    assert "FINISHED runner=" not in first_output

    monkeypatch.setattr(
        mod,
        "build_outcome_rows",
        lambda conn, *, observations, venue, horizons: [_outcome_row(observations[0])],
    )
    resumed = _args(output_dir=str(output_dir), resume=True)
    assert mod.run(resumed) == 0
    checkpoint = json.loads((output_dir / mod.OUTPUT_CHECKPOINT).read_text())
    summary = json.loads((output_dir / mod.OUTPUT_SUMMARY).read_text())
    assert checkpoint["terminal_state"] == "FINISHED"
    assert checkpoint["asofs_completed"] == 2
    assert checkpoint["outcome_rows_written"] == 2
    assert summary["outcome_row_count"] == 2
    outcome_rows = [json.loads(line) for line in (output_dir / mod.OUTPUT_ROWS).read_text().splitlines()]
    assert len(outcome_rows) == 2
    assert [row["outcome_id"] for row in outcome_rows] == ["obs-1:1h", "obs-2:1h"]
    assert len({row["outcome_id"] for row in outcome_rows}) == 2
    second_output = capsys.readouterr().out
    assert second_output.count("FINISHED runner=") == 1
    assert "FAILED runner=" not in second_output

    assert mod.run(resumed) == 0
    noop_output = capsys.readouterr().out
    assert noop_output.count("FINISHED runner=") == 1
    assert "resume_noop=1" in noop_output


def test_finalize_summary_is_technical_only(tmp_path) -> None:
    output_dir = tmp_path / "run"
    args = _args(output_dir=str(output_dir))
    identity = mod._scope_identity(args, asof_total=1)
    mod._prepare_output(output_dir, args=args, asof_total=1)
    row = {"outcome_id": "o1", "horizon": "1h", "status": "COMPLETE", "forward_return_pct": "9.0"}
    mod._append_rows(output_dir / mod.OUTPUT_ROWS, [row])
    mod._finalize(
        output_dir,
        identity=identity,
        observation_count=1,
        asofs_completed=1,
        outcome_rows_written=1,
        last_asof_ts_utc="2026-07-18T00:00:00+00:00",
    )
    summary = json.loads((output_dir / mod.OUTPUT_SUMMARY).read_text())
    assert summary["db_writes"] == 0
    assert "average_forward_return" not in summary
    assert "holdout" not in summary
