from __future__ import annotations

import csv
from pathlib import Path

import pytest


EXPECTED_FILES = {
    "ranked_shift_candidates.csv",
    "marker_sequence_evidence.csv",
    "extension_marker_evidence.csv",
    "epoch_shift_continuity.csv",
    "tolerance_sensitivity_summary.csv",
    "manifest.txt",
    "command.txt",
    "run.log",
}

EXPECTED_SYMBOLS = {"BTC", "ETH", "FIL", "HBAR", "PEPE", "RENDER", "TAO", "XLM"}
EXPECTED_MODES = {"STRICT", "NORMAL", "MAX"}
EXPECTED_ANCHORS = 28
EXPECTED_EPOCHS = 8 * 28  # 224
EXPECTED_TOP_ROWS = 8 * 28 * 3  # 672


def _find_canonical_archive() -> Path | None:
    base = Path("data/research/breathline_lattice_shift_calibration_v2")
    if not base.exists():
        return None
    dirs = [
        d
        for d in base.iterdir()
        if d.is_dir() and d.name.startswith("breathline_v2_canonical_28_anchor_8_asset_")
    ]
    return max(dirs, key=lambda d: d.name) if dirs else None


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture()
def archive() -> Path:
    found = _find_canonical_archive()
    if found is None:
        pytest.skip("No canonical campaign archive found under data/research/breathline_lattice_shift_calibration_v2/")
    return found


def test_canonical_archive_has_all_required_files(archive: Path) -> None:
    present = {f.name for f in archive.iterdir()}
    missing = EXPECTED_FILES - present
    assert not missing, f"Missing archive files: {sorted(missing)}"


def test_canonical_archive_manifest_has_zero_db_writes(archive: Path) -> None:
    manifest = (archive / "manifest.txt").read_text(encoding="utf-8")
    assert "db_writes=0" in manifest
    assert "broker_calls=0" in manifest
    assert "broker_writes=0" in manifest
    assert "order_submission=0" in manifest


def test_canonical_archive_manifest_preserves_input_sha256(archive: Path) -> None:
    manifest = (archive / "manifest.txt").read_text(encoding="utf-8")
    lines = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in manifest.splitlines() if "=" in line}
    assert lines.get("input_sha256", "").strip() != "", "manifest must record input SHA256"
    assert lines.get("source_git_commit", "").strip() not in ("", "unavailable"), (
        "manifest must record source git commit"
    )


def test_canonical_campaign_covers_all_28_anchors_8_assets_3_modes(archive: Path) -> None:
    rows = _read_csv(archive / "ranked_shift_candidates.csv")
    top_rows = [r for r in rows if r["candidate_rank"] == "1"]

    symbols = {r["symbol"] for r in top_rows}
    anchors = {r["raw_lattice_anchor_ts_utc"] for r in top_rows}
    modes = {r["sensitivity_mode"] for r in top_rows}

    assert symbols == EXPECTED_SYMBOLS, f"Symbol mismatch: got {sorted(symbols)}"
    assert len(anchors) == EXPECTED_ANCHORS, f"Expected {EXPECTED_ANCHORS} anchors, got {len(anchors)}"
    assert modes == EXPECTED_MODES, f"Mode mismatch: got {sorted(modes)}"
    assert len(top_rows) == EXPECTED_TOP_ROWS, (
        f"Expected {EXPECTED_TOP_ROWS} top-candidate rows, got {len(top_rows)}"
    )


def test_canonical_campaign_tolerance_summary_covers_all_three_modes(archive: Path) -> None:
    rows = _read_csv(archive / "tolerance_sensitivity_summary.csv")
    modes = {r["sensitivity_mode"] for r in rows}
    assert modes == EXPECTED_MODES, f"Tolerance summary mode mismatch: {sorted(modes)}"
    for row in rows:
        assert int(row["epoch_count"]) == EXPECTED_EPOCHS, (
            f"Mode {row['sensitivity_mode']}: expected {EXPECTED_EPOCHS} epochs, got {row['epoch_count']}"
        )


def test_canonical_campaign_continuity_covers_all_symbols_and_modes(archive: Path) -> None:
    rows = _read_csv(archive / "epoch_shift_continuity.csv")
    symbols = {r["symbol"] for r in rows}
    modes = {r["sensitivity_mode"] for r in rows}
    assert symbols == EXPECTED_SYMBOLS
    assert modes == EXPECTED_MODES
