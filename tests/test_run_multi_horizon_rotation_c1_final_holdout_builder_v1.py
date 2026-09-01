from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.research.run_multi_horizon_rotation_c1_final_holdout_builder_v1 import (
    CANDIDATE_ID,
    PHASE,
    load_manifest,
    select_c1_spec,
)


def _manifest() -> dict[str, object]:
    return {
        "manifest_version": "1.0.0",
        "venue": "bitvavo",
        "source_span": {
            "start": "2026-07-13T22:00:00Z",
            "end": "2026-09-01T02:00:00Z",
        },
        "splits": {
            "discovery": {"start": "2026-07-13T22:00:00Z", "end": "2026-08-12T10:00:00Z"},
            "validation": {"start": "2026-08-12T10:00:00Z", "end": "2026-08-22T06:00:00Z"},
            "final_holdout": {"start": "2026-08-22T06:00:00Z", "end": "2026-09-01T02:00:00Z"},
        },
        "final_holdout_inspected": False,
    }


def test_holdout_contract_is_c1_only() -> None:
    assert PHASE == "final_holdout"
    assert CANDIDATE_ID == "C1"
    spec = select_c1_spec()
    assert spec.candidate_id == "C1"


def test_manifest_must_be_unopened_and_match_venue(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    manifest = _manifest()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = load_manifest(path, venue="bitvavo")
    assert loaded["final_holdout_inspected"] is False

    with pytest.raises(ValueError, match="venue"):
        load_manifest(path, venue="kraken")

    manifest["final_holdout_inspected"] = True
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="unopened"):
        load_manifest(path, venue="bitvavo")


def test_manifest_requires_final_holdout_split(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    manifest = _manifest()
    del manifest["splits"]["final_holdout"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="missing final_holdout"):
        load_manifest(path, venue="bitvavo")
