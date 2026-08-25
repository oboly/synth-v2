import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from src.research.forecast_confluence_pit_cohort_audit_v1 import (
    AUDIT_FILENAME,
    BASELINE_LEDGER_FILENAME,
    ENRICHED_LEDGER_FILENAME,
    FORECAST_LEDGER_FILENAME,
    MANIFEST_FILENAME,
    build_artifacts,
    iso_z,
)


def _row() -> dict:
    return {
        "asof_ts_utc": datetime(2026, 8, 1), "map_id": 7, "market": "AAA", "venue": "bitvavo",
        "reference_price": 100, "trend_score": .8, "setup_score": .8, "compass_score": .8,
        "volume_score": .8, "distance_entry_to_target_pct": .8, "rotation_pressure_score": None,
        "sector_rotation_score": None,
    }


def _candles() -> dict[str, list[dict]]:
    start = datetime(2026, 8, 1)
    return {"AAA": [
        {"close_ts_utc": start + timedelta(hours=4), "close_price": 101, "high_price": 102, "low_price": 99},
        {"close_ts_utc": start + timedelta(hours=24), "close_price": 102, "high_price": 103, "low_price": 98},
        {"close_ts_utc": start + timedelta(hours=168), "close_price": 103, "high_price": 104, "low_price": 97},
    ]}


def test_artifact_digests_bind_the_exact_ledger_bytes() -> None:
    files, audit = build_artifacts(
        rows=[_row()], candles_by_market=_candles(),
        pipeline_stage_counts={"raw": 1, "venue": 1, "interval": 1, "fib_status": 1, "asset": 1, "same_ts_signal": 1, "dedup": 1, "final": 1},
        start=datetime(2026, 8, 1), end=datetime(2026, 8, 2), venue="bitvavo",
    )
    assert audit["forecast_identity_ledger_sha256"] == hashlib.sha256(files[FORECAST_LEDGER_FILENAME]).hexdigest()
    assert audit["baseline_outcome_identity_ledger_sha256"] == hashlib.sha256(files[BASELINE_LEDGER_FILENAME]).hexdigest()
    assert audit["enriched_outcome_identity_ledger_sha256"] == hashlib.sha256(files[ENRICHED_LEDGER_FILENAME]).hexdigest()
    assert len(files[FORECAST_LEDGER_FILENAME].splitlines()) == 1
    assert len(files[BASELINE_LEDGER_FILENAME].splitlines()) == 3
    assert len(files[ENRICHED_LEDGER_FILENAME].splitlines()) == 3
    assert json.loads(files[AUDIT_FILENAME])["forecast_count"] == 1


def test_naive_replay_timestamps_are_rendered_as_utc() -> None:
    assert iso_z(datetime(2026, 8, 1)) == "2026-08-01T00:00:00Z"


def test_committed_audit_and_manifest_digests_are_verifiable() -> None:
    root = Path(__file__).resolve().parents[1] / "data/research/forecast_confluence_pit_replay_v1"
    audit = json.loads((root / AUDIT_FILENAME).read_text(encoding="utf-8"))
    manifest = json.loads((root / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert audit["forecast_identity_ledger_sha256"] == hashlib.sha256((root / FORECAST_LEDGER_FILENAME).read_bytes()).hexdigest()
    assert audit["baseline_outcome_identity_ledger_sha256"] == hashlib.sha256((root / BASELINE_LEDGER_FILENAME).read_bytes()).hexdigest()
    assert audit["enriched_outcome_identity_ledger_sha256"] == hashlib.sha256((root / ENRICHED_LEDGER_FILENAME).read_bytes()).hexdigest()
    assert manifest["canonical_audit_sha256"] == hashlib.sha256((root / AUDIT_FILENAME).read_bytes()).hexdigest()
