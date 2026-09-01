from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.research.run_cq_v1_temporal_population_smoke_v1 as smoke


def _args(*, asof_index: int = 1, asset_id: int | None = None, symbol: str = "ADA-EUR") -> SimpleNamespace:
    return SimpleNamespace(
        venue="bitvavo",
        asof_index=asof_index,
        symbol=symbol,
        asset_id=asset_id,
        selection_config=smoke.DEFAULT_SELECTION_CONFIG,
    )


def _prepare(monkeypatch, rows, captured=None, resolved_asset_id: int = 9):
    asof = datetime(2026, 7, 18, tzinfo=UTC)
    monkeypatch.setattr(smoke, "load_temporal_contract", lambda: {"x": 1})
    monkeypatch.setattr(smoke, "derive_asofs", lambda _contract: [asof] * 45)
    monkeypatch.setattr(
        smoke,
        "_validate_selection_config",
        lambda _raw: (Path(smoke.DEFAULT_SELECTION_CONFIG), smoke.PINNED_SELECTION_CONFIG_SHA256),
    )
    monkeypatch.setattr(smoke, "load_selection_config", lambda _path: {})

    class Conn:
        def close(self):
            pass

    monkeypatch.setattr(smoke, "get_db_connection", lambda: Conn())
    monkeypatch.setattr(
        smoke,
        "_resolve_asset_id",
        lambda _conn, *, symbol, explicit_asset_id: explicit_asset_id if explicit_asset_id is not None else resolved_asset_id,
    )

    def fake_build(*_a, **kwargs):
        if captured is not None:
            captured.update(kwargs)
        return rows

    monkeypatch.setattr(smoke, "build_asof_population", fake_build)
    monkeypatch.setattr(smoke, "_bind_selection_config_provenance", lambda values, _sha: values)
    return asof


def test_smoke_cli_defaults_to_bounded_ada() -> None:
    args = smoke.parse_args([])
    assert args.venue == "bitvavo"
    assert args.asof_index == 1
    assert args.symbol == "ADA-EUR"
    assert args.asset_id is None
    assert args.selection_config == smoke.DEFAULT_SELECTION_CONFIG


def test_smoke_rejects_asof_outside_frozen_contract(monkeypatch, capsys) -> None:
    monkeypatch.setattr(smoke, "load_temporal_contract", lambda: {"x": 1})
    monkeypatch.setattr(smoke, "derive_asofs", lambda _contract: [object()] * 45)
    with pytest.raises(ValueError, match="--asof-index must be between 1 and 45"):
        smoke.run(_args(asof_index=46))
    assert "FAILED runner=cq_v1_temporal_population_smoke_v1" in capsys.readouterr().out


def test_default_ada_smoke_resolves_and_pushes_asset_bound(monkeypatch, capsys) -> None:
    asof = datetime(2026, 7, 18, tzinfo=UTC)
    rows = [
        {"asset_id": 9, "venue": "bitvavo", "asof_ts_utc": asof.isoformat(), "evidence_key": "b", "cq_model_version": "cq_shadow_v1", "model_family_version": "1.0.0", "coverage_artifact_sha256": "coverage"},
    ]
    captured = {}
    _prepare(monkeypatch, rows, captured, resolved_asset_id=9)
    assert smoke.run(_args()) == 0
    out = capsys.readouterr().out
    assert captured["asset_id"] == 9
    assert "BOUND symbol=ADA-EUR asset_id=9" in out
    assert '"asset_id": 9' in out
    assert "decision_gate=none execution_planner=none executor=none" in out
    assert "live_orders=0 runtime_activation=0" in out
    assert "FINISHED runner=cq_v1_temporal_population_smoke_v1" in out
    assert "source_rows=1 output_rows=1 outcomes_read=0 db_writes=0" in out


def test_explicit_asset_id_overrides_symbol_resolution(monkeypatch, capsys) -> None:
    asof = datetime(2026, 7, 18, tzinfo=UTC)
    rows = [
        {"asset_id": 7, "venue": "bitvavo", "asof_ts_utc": asof.isoformat(), "evidence_key": "a", "cq_model_version": "cq_shadow_v1", "model_family_version": "1.0.0", "coverage_artifact_sha256": "coverage"},
    ]
    captured = {}
    _prepare(monkeypatch, rows, captured, resolved_asset_id=99)
    assert smoke.run(_args(asset_id=7)) == 0
    assert captured["asset_id"] == 7
    assert "BOUND symbol=ADA-EUR asset_id=7" in capsys.readouterr().out


def test_signal_interrupt_emits_single_interrupted_terminal(monkeypatch, capsys) -> None:
    _prepare(monkeypatch, [])

    def interrupt(*_a, **_k):
        raise smoke._Interrupted(15)

    monkeypatch.setattr(smoke, "build_asof_population", interrupt)
    assert smoke.run(_args()) == 130
    out = capsys.readouterr().out
    assert out.count("INTERRUPTED runner=cq_v1_temporal_population_smoke_v1") == 1
    assert "signal=15 outcomes_read=0 db_writes=0" in out
    assert "FINISHED runner=cq_v1_temporal_population_smoke_v1" not in out
