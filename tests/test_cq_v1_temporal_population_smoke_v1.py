from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.research.run_cq_v1_temporal_population_smoke_v1 as smoke


def test_smoke_cli_defaults_are_bounded_and_read_only() -> None:
    args = smoke.parse_args([])
    assert args.venue == "bitvavo"
    assert args.asof_index == 1
    assert args.asset_id is None
    assert args.selection_config == smoke.DEFAULT_SELECTION_CONFIG


def test_smoke_rejects_asof_outside_frozen_contract(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "load_temporal_contract", lambda: {"x": 1})
    monkeypatch.setattr(smoke, "derive_asofs", lambda _contract: [object()] * 45)
    args = SimpleNamespace(
        venue="bitvavo",
        asof_index=46,
        asset_id=None,
        selection_config=smoke.DEFAULT_SELECTION_CONFIG,
    )
    with pytest.raises(ValueError, match="--asof-index must be between 1 and 45"):
        smoke.run(args)


def test_single_asset_smoke_filters_output_after_canonical_asof_build(monkeypatch, capsys) -> None:
    asof = __import__("datetime").datetime(2026, 7, 18, tzinfo=__import__("datetime").UTC)
    monkeypatch.setattr(smoke, "load_temporal_contract", lambda: {"x": 1})
    monkeypatch.setattr(smoke, "derive_asofs", lambda _contract: [asof] * 45)
    monkeypatch.setattr(
        smoke,
        "_validate_selection_config",
        lambda _raw: (__import__("pathlib").Path(smoke.DEFAULT_SELECTION_CONFIG), smoke.PINNED_SELECTION_CONFIG_SHA256),
    )
    monkeypatch.setattr(smoke, "load_selection_config", lambda _path: {})

    class Conn:
        def close(self):
            pass

    monkeypatch.setattr(smoke, "get_db_connection", lambda: Conn())
    monkeypatch.setattr(
        smoke,
        "build_asof_population",
        lambda *_a, **_k: [
            {"asset_id": 7, "venue": "bitvavo", "asof_ts_utc": asof.isoformat(), "evidence_key": "a", "cq_model_version": "cq_shadow_v1", "model_family_version": "1.0.0", "coverage_artifact_sha256": "coverage"},
            {"asset_id": 9, "venue": "bitvavo", "asof_ts_utc": asof.isoformat(), "evidence_key": "b", "cq_model_version": "cq_shadow_v1", "model_family_version": "1.0.0", "coverage_artifact_sha256": "coverage"},
        ],
    )
    monkeypatch.setattr(smoke, "_bind_selection_config_provenance", lambda rows, _sha: rows)
    args = SimpleNamespace(
        venue="bitvavo",
        asof_index=1,
        asset_id=9,
        selection_config=smoke.DEFAULT_SELECTION_CONFIG,
    )
    assert smoke.run(args) == 0
    out = capsys.readouterr().out
    assert '"asset_id": 9' in out
    assert '"asset_id": 7' not in out
    assert "source_rows=2 output_rows=1 outcomes_read=0 db_writes=0" in out
