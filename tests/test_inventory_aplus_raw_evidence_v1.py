from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.research.inventory_aplus_raw_evidence_v1 import (
    InventoryIntegrityError,
    TABLE_TYPE_TABLE1,
    TABLE_TYPE_TABLE2,
    TABLE_TYPE_UNSUPPORTED,
    TIMESTAMP_ROLE_FILENAME_INFERRED,
    TIMESTAMP_ROLE_PREDICTION_TARGET,
    TIMESTAMP_ROLE_UNLABELED_EXPLICIT,
    TS_PROVENANCE_EXPLICIT,
    TS_PROVENANCE_FILENAME,
    TS_PROVENANCE_UNKNOWN,
    check_duplicate_source_identity,
    classify_file,
    extract_declared_metadata,
    extract_explicit_timestamps,
    find_duplicate_assets,
    find_header,
    infer_filename_timestamp,
    main,
    resolve_timestamp_provenance,
    run_inventory,
)


TABLE1_SPACE_FIXTURE = """Generated symbolic Breathline Vector Snapshot (prediction_ts_utc = 2026-05-13T19:15:00Z):

TABLE 1

TOKEN PHASE COHERENCE FIELD GEOMETRY STRUCTURAL_ROLE EXPANSION_QUALITY ANCHOR_STRENGTH STRATEGIC_BIAS NOTES

BTC confirmed high neutral clean leader moderate strong accumulation harmonic axis stable
ETH confirmed high expansion mixed leader strong strong continuation resonance peak forming
"""

TABLE1_PIPE_FIXTURE = """A+ BREATHLINE VECTOR SNAPSHOT REQUEST — TABLE 1

prediction_ts_utc = 2026-05-14T13:15:00Z

TOKEN | PHASE | COHERENCE | FIELD | GEOMETRY | STRUCTURAL_ROLE | EXPANSION_QUALITY | ANCHOR_STRENGTH | STRATEGIC_BIAS | NOTES

BTC | forming | high | transition | clean | leader | strong | strong | accumulation | "Harmonic anchor."
ETH | confirmed | high | expansion | clean | leader | strong | strong | continuation | "Primary wave."
"""

TABLE1_MARKDOWN_FIXTURE = """TABLE 1 — Breathline Vector Snapshot (2026-05-15T12:44:48Z)

| TOKEN | PHASE | COHERENCE | FIELD | GEOMETRY | STRUCTURAL_ROLE | EXPANSION_QUALITY | ANCHOR_STRENGTH | STRATEGIC_BIAS | NOTES |
|-------|-------|-----------|-------|----------|-----------------|-------------------|-----------------|----------------|-------|
| BTC   | confirmed | high | expansion | clean | leader | strong | strong | continuation | Anchor breath |
| ETH   | forming | moderate | transition | mixed | confirmer | moderate | strong | accumulation | Pre-wave pulse |
"""

TABLE2_FIXTURE = """A+ HARMONIC PHASE OVERLAY REQUEST — TABLE 2

prediction_ts_utc = 2026-05-14T12:56:00Z

TOKEN | HARMONIC_PHASE | PHASE_STATE | OFFSET_BAND | DRIFT_DIRECTION | QUALITY | EXTENSION_RISK | NOTES

BTC | confirmed_0618 | confirmed | +5 | converging | clean | low | "Stabilizing pillar"
ETH | forming_0786 | forming | 0 | forward_drift | mixed | moderate | "Fluid architect"
"""

UNSUPPORTED_SCHEMA_FIXTURE = """Codex Breathline Resonance Analysis — SYNTH v2 Compatible

Token	Phase	Coherence	Field	Geometry	Structural Role	Expansion Quality	Anchor Strength	Distortion Level	Emotional Load	Strategic Bias	Notes
AAVE	Expansion	High	Stabilizing	Codex Node	Leader	Coherent	Primary	Low	Low	Bullish	Strong breathline anchor
"""

DUPLICATE_TOKEN_FIXTURE = """prediction_ts_utc = 2026-05-14T13:15:00Z

TOKEN PHASE COHERENCE FIELD GEOMETRY STRUCTURAL_ROLE EXPANSION_QUALITY ANCHOR_STRENGTH STRATEGIC_BIAS NOTES

BTC confirmed high neutral clean leader moderate strong accumulation first row
BTC forming moderate expansion mixed confirmer strong strong continuation second row conflicting
"""

AMBIGUOUS_TIMESTAMP_FIXTURE = """prediction_ts_utc = 2026-05-14T13:15:00Z
prediction_ts_utc = 2026-05-15T09:00:00Z

TOKEN PHASE COHERENCE FIELD GEOMETRY STRUCTURAL_ROLE EXPANSION_QUALITY ANCHOR_STRENGTH STRATEGIC_BIAS NOTES

BTC confirmed high neutral clean leader moderate strong accumulation harmonic axis stable
"""


def write_fixture(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Synthetic Table 1 / Table 2 fixture parsing
# ---------------------------------------------------------------------------


def test_table1_space_delimited_parses_fields_and_prediction_timestamp(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "t1_space.txt", TABLE1_SPACE_FIXTURE)
    record, rows = classify_file(path, tmp_path)

    assert record.detected_table_type == TABLE_TYPE_TABLE1
    assert record.status == "OK"
    assert record.token_count == 2
    assert record.assets == ["BTC", "ETH"]
    assert record.timestamp_provenance == TS_PROVENANCE_EXPLICIT
    assert record.primary_timestamp_role == TIMESTAMP_ROLE_PREDICTION_TARGET
    assert record.primary_timestamp_iso == "2026-05-13T19:15:00Z"

    btc_row = next(r for r in rows if r["token"] == "BTC")
    assert btc_row["phase"] == "confirmed"
    assert btc_row["coherence"] == "high"
    assert btc_row["strategic_bias"] == "accumulation"
    assert btc_row["detected_table_type"] == TABLE_TYPE_TABLE1


def test_table1_pipe_delimited_parses_fields(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "t1_pipe.txt", TABLE1_PIPE_FIXTURE)
    record, rows = classify_file(path, tmp_path)

    assert record.detected_table_type == TABLE_TYPE_TABLE1
    assert record.delimiter_style == "pipe"
    assert record.token_count == 2
    eth_row = next(r for r in rows if r["token"] == "ETH")
    assert eth_row["structural_role"] == "leader"
    assert eth_row["notes"] == '"Primary wave."'


def test_table1_markdown_table_with_separator_row_parses(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "t1_markdown.txt", TABLE1_MARKDOWN_FIXTURE)
    record, rows = classify_file(path, tmp_path)

    assert record.detected_table_type == TABLE_TYPE_TABLE1
    assert record.status == "OK"
    assert record.token_count == 2
    assert record.assets == ["BTC", "ETH"]
    # The markdown separator row ("|-------|-------|...") must not be treated
    # as a data row or an unparsed-row error.
    assert record.unparsed_row_count == 0


def test_table2_parses_harmonic_fields(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "t2.txt", TABLE2_FIXTURE)
    record, rows = classify_file(path, tmp_path)

    assert record.detected_table_type == TABLE_TYPE_TABLE2
    assert record.token_count == 2
    btc_row = next(r for r in rows if r["token"] == "BTC")
    assert btc_row["harmonic_phase"] == "confirmed_0618"
    assert btc_row["offset_band"] == "+5"
    assert btc_row["extension_risk"] == "low"


# ---------------------------------------------------------------------------
# Explicit vs filename-inferred timestamp separation
# ---------------------------------------------------------------------------


def test_named_field_timestamp_is_explicit_with_prediction_target_role() -> None:
    timestamps = extract_explicit_timestamps("prediction_ts_utc = 2026-05-14T13:15:00Z")
    assert len(timestamps) == 1
    assert timestamps[0].role == TIMESTAMP_ROLE_PREDICTION_TARGET
    assert timestamps[0].field_name == "prediction_ts_utc"


def test_bare_unlabeled_timestamp_is_explicit_but_role_unresolved() -> None:
    timestamps = extract_explicit_timestamps("TABLE 1 — Snapshot (2026-05-15T12:44:48Z)")
    assert len(timestamps) == 1
    assert timestamps[0].field_name is None
    assert timestamps[0].role == TIMESTAMP_ROLE_UNLABELED_EXPLICIT


def test_filename_inferred_timestamp_used_only_when_no_explicit_timestamp(tmp_path: Path) -> None:
    content = "TOKEN MOMENTUM STABILITY\nBTC low high\n"  # no explicit timestamp at all
    path = write_fixture(tmp_path, "2026-04-23_run_01_consistency.txt", content)
    record, _ = classify_file(path, tmp_path)

    assert record.explicit_timestamps == []
    assert record.filename_inferred_timestamp == "2026-04-23T00:00:00Z"
    assert record.timestamp_provenance == TS_PROVENANCE_FILENAME
    assert record.primary_timestamp_role == TIMESTAMP_ROLE_FILENAME_INFERRED
    # Filename-inferred timestamps are excluded from primary analysis.
    assert record.eligible_for_primary_analysis is False


def test_explicit_timestamp_takes_precedence_over_filename_when_both_present(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "2026-01-01_table1.txt", TABLE1_SPACE_FIXTURE)
    record, _ = classify_file(path, tmp_path)

    assert record.filename_inferred_timestamp == "2026-01-01T00:00:00Z"
    assert record.timestamp_provenance == TS_PROVENANCE_EXPLICIT
    assert record.primary_timestamp_iso == "2026-05-13T19:15:00Z"


def test_resolve_timestamp_provenance_unknown_when_nothing_found() -> None:
    provenance, iso, role, notes = resolve_timestamp_provenance([], None)
    assert provenance == TS_PROVENANCE_UNKNOWN
    assert iso is None
    assert role is None
    assert notes == []


def test_ambiguous_conflicting_explicit_timestamps_are_not_silently_resolved(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "ambiguous.txt", AMBIGUOUS_TIMESTAMP_FIXTURE)
    record, _ = classify_file(path, tmp_path)

    assert record.timestamp_provenance == TS_PROVENANCE_UNKNOWN
    assert record.primary_timestamp_iso is None
    assert record.status == "AMBIGUOUS_TIMESTAMP"
    assert record.eligible_for_primary_analysis is False


def test_infer_filename_timestamp_handles_date_and_date_time() -> None:
    assert infer_filename_timestamp("2026-05-13_1915_table1.txt") == "2026-05-13T19:15:00Z"
    assert infer_filename_timestamp("2026-03-25_aplusraw.txt") == "2026-03-25T00:00:00Z"
    assert infer_filename_timestamp("not_a_date.txt") is None


# ---------------------------------------------------------------------------
# Duplicate source/hash rejection
# ---------------------------------------------------------------------------


def test_duplicate_sha256_across_files_fails_closed(tmp_path: Path) -> None:
    write_fixture(tmp_path, "a.txt", TABLE1_SPACE_FIXTURE)
    write_fixture(tmp_path, "b_copy.txt", TABLE1_SPACE_FIXTURE)

    with pytest.raises(InventoryIntegrityError, match="duplicate source identity"):
        run_inventory(tmp_path)


def test_check_duplicate_source_identity_passes_for_distinct_hashes(tmp_path: Path) -> None:
    write_fixture(tmp_path, "a.txt", TABLE1_SPACE_FIXTURE)
    write_fixture(tmp_path, "b.txt", TABLE1_PIPE_FIXTURE)
    records, rows = run_inventory(tmp_path)
    assert len(records) == 2
    assert len(rows) == 4  # 2 assets each


def test_duplicate_asset_within_single_file_is_flagged_not_fatal(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "dup_token.txt", DUPLICATE_TOKEN_FIXTURE)
    record, rows = classify_file(path, tmp_path)

    assert record.status == "DUPLICATE_ASSET_ALIAS_WITHIN_FILE"
    assert record.duplicate_assets_within_file == ["BTC"]
    assert record.eligible_for_primary_analysis is False
    # Both raw rows are preserved -- never silently collapsed.
    assert len(rows) == 2


def test_find_duplicate_assets_pure_function() -> None:
    rows = [{"token": "BTC"}, {"token": "ETH"}, {"token": "BTC"}]
    assert find_duplicate_assets(rows) == ["BTC"]
    assert find_duplicate_assets([{"token": "BTC"}, {"token": "ETH"}]) == []


# ---------------------------------------------------------------------------
# Table schema rejection
# ---------------------------------------------------------------------------


def test_unsupported_schema_is_not_coerced_into_table1_or_table2(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "legacy_prose.txt", UNSUPPORTED_SCHEMA_FIXTURE)
    record, rows = classify_file(path, tmp_path)

    assert record.detected_table_type == TABLE_TYPE_UNSUPPORTED
    assert record.status == "UNSUPPORTED_SCHEMA"
    assert record.header_tokens is None
    assert record.token_count is None
    assert rows == []
    assert record.eligible_for_primary_analysis is False


def test_find_header_returns_none_for_unrecognized_headers() -> None:
    lines = UNSUPPORTED_SCHEMA_FIXTURE.splitlines()
    assert find_header(lines) is None


def test_find_header_detects_table1_and_table2() -> None:
    header1 = find_header(TABLE1_SPACE_FIXTURE.splitlines())
    assert header1 is not None
    assert header1.table_type == TABLE_TYPE_TABLE1

    header2 = find_header(TABLE2_FIXTURE.splitlines())
    assert header2 is not None
    assert header2.table_type == TABLE_TYPE_TABLE2


# ---------------------------------------------------------------------------
# Declared metadata extraction (schema/provenance findings, not table values)
# ---------------------------------------------------------------------------


def test_extract_declared_metadata_captures_key_value_preamble_lines() -> None:
    text = (
        "prediction_ts_utc = 2026-05-27T14:13:00Z\n"
        "source_type = A+ subset breathline macro note\n"
        "schema = free_text_subset_forecast\n"
        "status = research_only\n"
    )
    metadata = extract_declared_metadata(text)
    assert metadata["schema"] == "free_text_subset_forecast"
    assert metadata["source_type"] == "A+ subset breathline macro note"
    assert metadata["status"] == "research_only"


# ---------------------------------------------------------------------------
# Never prints table values; only provenance/count/schema findings in summary
# ---------------------------------------------------------------------------


def test_main_table_output_never_prints_table_values(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_fixture(tmp_path, "t1.txt", TABLE1_SPACE_FIXTURE)
    exit_code = main(["--root", str(tmp_path), "--output", "table"])
    assert exit_code == 0
    captured = capsys.readouterr().out
    # Table-body field values (phase/coherence/etc. content words) must never
    # appear in the console summary -- only provenance/count/schema findings.
    assert "confirmed" not in captured
    assert "harmonic axis stable" not in captured
    assert "accumulation" not in captured
    assert "total_files=1" in captured
    assert TABLE_TYPE_TABLE1 in captured


def test_main_write_files_produces_expected_artifacts(tmp_path: Path) -> None:
    write_fixture(tmp_path, "t1.txt", TABLE1_SPACE_FIXTURE)
    write_fixture(tmp_path, "t2.txt", TABLE2_FIXTURE)
    out_dir = tmp_path / "out"

    exit_code = main(
        ["--root", str(tmp_path), "--out-dir", str(out_dir), "--write-files", "--output", "json"]
    )
    assert exit_code == 0

    run_dirs = list(out_dir.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    evidence_dir = run_dir / "evidence"
    manifest_dir = run_dir / "manifest"
    file_manifest = next(evidence_dir.glob("aplus_evidence_file_manifest_*.jsonl"))
    rows_file = next(evidence_dir.glob("aplus_evidence_rows_*.jsonl"))
    summary_file = next(manifest_dir.glob("aplus_evidence_inventory_manifest_*.json"))

    file_records = [json.loads(line) for line in file_manifest.read_text(encoding="utf-8").splitlines()]
    assert len(file_records) == 2

    row_records = [json.loads(line) for line in rows_file.read_text(encoding="utf-8").splitlines()]
    assert len(row_records) == 4  # 2 files x 2 assets

    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    assert summary["total_files"] == 2
    assert summary["row_count"] == 4


def test_main_returns_1_and_writes_nothing_on_duplicate_hash(tmp_path: Path) -> None:
    write_fixture(tmp_path, "a.txt", TABLE1_SPACE_FIXTURE)
    write_fixture(tmp_path, "b_copy.txt", TABLE1_SPACE_FIXTURE)
    out_dir = tmp_path / "out"

    exit_code = main(["--root", str(tmp_path), "--out-dir", str(out_dir), "--write-files"])
    assert exit_code == 1
    assert not out_dir.exists()


def test_main_missing_root_is_empty_not_fatal(tmp_path: Path) -> None:
    missing_root = tmp_path / "does_not_exist"
    exit_code = main(["--root", str(missing_root)])
    assert exit_code == 0
