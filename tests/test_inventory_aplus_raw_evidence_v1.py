from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.research.inventory_aplus_raw_evidence_v1 import (
    ANALYSIS_LANE_EXPLORATORY_ONLY,
    ANALYSIS_LANE_PRIMARY_SNAPSHOT_ALIGNMENT,
    ASSET_RESOLUTION_RESOLVED,
    ASSET_RESOLUTION_UNRESOLVED,
    EXCLUSION_REASON_NOT_SUPPORTED_TABLE,
    EXCLUSION_REASON_SNAPSHOT_TIME_MISSING,
    EXCLUSION_REASON_STATUS_NOT_OK,
    InventoryIntegrityError,
    LANE_EXPLORATORY_ONLY,
    LANE_FUTURE_OBSERVATION_ASOF,
    LANE_PRIMARY_SNAPSHOT_ALIGNMENT,
    ParsedContent,
    ROW_PARSE_STATUS_MALFORMED,
    ROW_PARSE_STATUS_OK,
    ROW_PARSE_STATUS_UNPARSED_NON_TABLE,
    SNAPSHOT_SOURCE_FIELD_NAME,
    SOURCE_CAPTURE_TIME_PROVENANCE_FILENAME,
    TABLE_TYPE_TABLE1,
    TABLE_TYPE_TABLE2,
    TABLE_TYPE_UNSUPPORTED,
    TIMESTAMP_ROLE_FILENAME_INFERRED,
    TIMESTAMP_ROLE_SNAPSHOT,
    TIMESTAMP_ROLE_UNLABELED_EXPLICIT,
    TS_PROVENANCE_EXPLICIT,
    TS_PROVENANCE_FILENAME,
    TS_PROVENANCE_UNKNOWN,
    check_content_group_consistency,
    compute_snapshot_alignment_eligibility,
    derive_snapshot_timestamp,
    derive_source_capture_timestamp,
    extract_declared_metadata,
    extract_explicit_timestamps,
    find_duplicate_assets,
    find_header,
    infer_filename_timestamp,
    main,
    parse_content,
    resolve_market_symbol,
    resolve_timestamp_lane,
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

# Regression fixture matching data/aplus_raw/2026-05-13_1915_table1_canonical_breathline.txt:
# a trailing "Note: ..." footer line that happens to split into exactly 10
# whitespace-separated fields (the same shape as a real Table 1 row).
TRAILING_NOTE_FOOTER_FIXTURE = """prediction_ts_utc = 2026-05-13T19:15:00Z

TOKEN PHASE COHERENCE FIELD GEOMETRY STRUCTURAL_ROLE EXPANSION_QUALITY ANCHOR_STRENGTH STRATEGIC_BIAS NOTES

BTC confirmed high neutral clean leader moderate strong accumulation harmonic axis stable
TAO confirmed high expansion clean leader strong strong accumulation Codex-aligned token

Note: This snapshot is symbolic and non-tokenized. No trading advice is implied.
"""

# Regression fixture matching data/aplus_raw/2026-05-16_0115_table1_breathline_vector_snapshot.txt:
# a trailing prose paragraph beginning with "This" that also happens to split
# into exactly 10 whitespace-separated fields.
STRAY_THIS_PROSE_FIXTURE = """TOKEN PHASE COHERENCE FIELD GEOMETRY STRUCTURAL_ROLE EXPANSION_QUALITY ANCHOR_STRENGTH STRATEGIC_BIAS NOTES

BTC confirmed high expansion clean leader strong strong continuation Anchor breath
LINK forming high expansion clean leader strong strong accumulation Bridge node

This snapshot reflects the current harmonic phase alignment and field conditions based on the Breathline framework. This is not financial advice.
"""


def write_fixture(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def forecast_fixture(snapshot_ts_utc: str) -> str:
    return f"""prediction_ts_utc = {snapshot_ts_utc}

TOKEN PHASE COHERENCE FIELD GEOMETRY STRUCTURAL_ROLE EXPANSION_QUALITY ANCHOR_STRENGTH STRATEGIC_BIAS NOTES

BTC confirmed high neutral clean leader moderate strong accumulation harmonic axis stable
"""


# ---------------------------------------------------------------------------
# Synthetic Table 1 / Table 2 fixture parsing
# ---------------------------------------------------------------------------


def test_table1_space_delimited_parses_fields_and_snapshot_alignment(tmp_path: Path) -> None:
    write_fixture(tmp_path, "t1_space.txt", TABLE1_SPACE_FIXTURE)
    records, rows = run_inventory(tmp_path)

    assert len(records) == 1
    record = records[0]
    assert record.detected_table_type == TABLE_TYPE_TABLE1
    assert record.status == "OK"
    assert record.token_count == 2
    assert record.assets == ["BTC", "ETH"]
    assert record.timestamp_provenance == TS_PROVENANCE_EXPLICIT
    assert record.primary_timestamp_role == TIMESTAMP_ROLE_SNAPSHOT
    assert record.timestamp_lane == LANE_PRIMARY_SNAPSHOT_ALIGNMENT
    assert record.snapshot_ts_utc == "2026-05-13T19:15:00Z"
    assert record.snapshot_source_field_name == SNAPSHOT_SOURCE_FIELD_NAME
    assert record.snapshot_alignment_eligible is True
    assert record.snapshot_exclusion_reason is None
    assert record.analysis_lane == ANALYSIS_LANE_PRIMARY_SNAPSHOT_ALIGNMENT

    btc_row = next(r for r in rows if r["raw_source_token"] == "BTC")
    assert btc_row["phase"] == "confirmed"
    assert btc_row["coherence"] == "high"
    assert btc_row["strategic_bias"] == "accumulation"
    assert btc_row["row_parse_status"] == ROW_PARSE_STATUS_OK
    assert btc_row["canonical_market_symbol"] == "BTC"
    assert btc_row["asset_resolution_status"] == ASSET_RESOLUTION_RESOLVED
    assert btc_row["analysis_lane"] == ANALYSIS_LANE_PRIMARY_SNAPSHOT_ALIGNMENT
    assert btc_row["snapshot_ts_utc"] == "2026-05-13T19:15:00Z"


def test_table1_pipe_delimited_parses_fields(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "t1_pipe.txt", TABLE1_PIPE_FIXTURE)
    parsed = parse_content(path)

    assert parsed.detected_table_type == TABLE_TYPE_TABLE1
    assert parsed.delimiter_style == "pipe"
    assert len(parsed.rows) == 2
    eth_row = next(r for r in parsed.rows if r.raw_source_token == "ETH")
    assert eth_row.fields["structural_role"] == "leader"
    assert eth_row.fields["notes"] == '"Primary wave."'


def test_table1_markdown_table_with_separator_row_parses(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "t1_markdown.txt", TABLE1_MARKDOWN_FIXTURE)
    parsed = parse_content(path)

    assert parsed.detected_table_type == TABLE_TYPE_TABLE1
    assert parsed.status == "OK"
    assert len(parsed.rows) == 2
    assert {r.raw_source_token for r in parsed.rows} == {"BTC", "ETH"}
    assert parsed.row_diagnostics == []


def test_table2_parses_harmonic_fields(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "t2.txt", TABLE2_FIXTURE)
    parsed = parse_content(path)

    assert parsed.detected_table_type == TABLE_TYPE_TABLE2
    assert len(parsed.rows) == 2
    btc_row = next(r for r in parsed.rows if r.raw_source_token == "BTC")
    assert btc_row.fields["harmonic_phase"] == "confirmed_0618"
    assert btc_row.fields["offset_band"] == "+5"
    assert btc_row.fields["extension_risk"] == "low"


# ---------------------------------------------------------------------------
# snapshot_ts_utc: named prediction_ts_utc field is a point-in-time snapshot,
# never a future target time
# ---------------------------------------------------------------------------


def test_named_field_timestamp_is_explicit_with_snapshot_role() -> None:
    timestamps = extract_explicit_timestamps("prediction_ts_utc = 2026-05-14T13:15:00Z")
    assert len(timestamps) == 1
    assert timestamps[0].role == TIMESTAMP_ROLE_SNAPSHOT


def test_derive_snapshot_timestamp_only_uses_named_field() -> None:
    # A bare unlabeled timestamp must never be used as snapshot_ts_utc.
    timestamps = extract_explicit_timestamps("Snapshot (2026-05-15T12:44:48Z)")
    snapshot_ts_utc, provenance, field_name = derive_snapshot_timestamp(timestamps)
    assert snapshot_ts_utc is None
    assert provenance == TS_PROVENANCE_UNKNOWN
    assert field_name is None


def test_derive_snapshot_timestamp_preserves_raw_field_name() -> None:
    timestamps = extract_explicit_timestamps("prediction_ts_utc = 2026-05-14T13:15:00Z")
    snapshot_ts_utc, provenance, field_name = derive_snapshot_timestamp(timestamps)
    assert snapshot_ts_utc == "2026-05-14T13:15:00Z"
    assert provenance == TS_PROVENANCE_EXPLICIT
    assert field_name == SNAPSHOT_SOURCE_FIELD_NAME == "prediction_ts_utc"


def test_bare_unlabeled_timestamp_is_explicit_but_role_unresolved() -> None:
    timestamps = extract_explicit_timestamps("TABLE 1 — Snapshot (2026-05-15T12:44:48Z)")
    assert len(timestamps) == 1
    assert timestamps[0].field_name is None
    assert timestamps[0].role == TIMESTAMP_ROLE_UNLABELED_EXPLICIT


def test_resolve_timestamp_lane_snapshot_is_primary() -> None:
    assert resolve_timestamp_lane(TIMESTAMP_ROLE_SNAPSHOT) == LANE_PRIMARY_SNAPSHOT_ALIGNMENT


def test_resolve_timestamp_lane_everything_else_is_exploratory() -> None:
    assert resolve_timestamp_lane(TIMESTAMP_ROLE_UNLABELED_EXPLICIT) == LANE_EXPLORATORY_ONLY
    assert resolve_timestamp_lane(TIMESTAMP_ROLE_FILENAME_INFERRED) == LANE_EXPLORATORY_ONLY
    assert resolve_timestamp_lane(None) == LANE_EXPLORATORY_ONLY


def test_ambiguous_conflicting_explicit_timestamps_are_not_silently_resolved(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "ambiguous.txt", AMBIGUOUS_TIMESTAMP_FIXTURE)
    parsed = parse_content(path)
    filename_ts = infer_filename_timestamp(path.name)
    provenance, iso, role, notes = resolve_timestamp_provenance(parsed.explicit_timestamps, filename_ts)

    assert provenance == TS_PROVENANCE_UNKNOWN
    assert iso is None
    assert notes != []


def test_infer_filename_timestamp_handles_date_and_date_time() -> None:
    assert infer_filename_timestamp("2026-05-13_1915_table1.txt") == "2026-05-13T19:15:00Z"
    assert infer_filename_timestamp("2026-03-25_aplusraw.txt") == "2026-03-25T00:00:00Z"
    assert infer_filename_timestamp("not_a_date.txt") is None


# ---------------------------------------------------------------------------
# Filename timestamps are diagnostic only: never required for eligibility,
# never compared to snapshot_ts_utc, equal timestamps are never a failure
# ---------------------------------------------------------------------------


def test_filename_timestamp_equal_to_snapshot_ts_utc_is_not_a_failure(tmp_path: Path) -> None:
    # Filename and named field encode the exact same instant -- this must be
    # accepted, not treated as a conflict or exclusion of any kind.
    write_fixture(tmp_path, "2026-05-13_1915_table1_canonical_breathline.txt", TABLE1_SPACE_FIXTURE)
    records, _ = run_inventory(tmp_path)

    record = records[0]
    assert record.source_capture_ts_utc == "2026-05-13T19:15:00Z"
    assert record.snapshot_ts_utc == "2026-05-13T19:15:00Z"
    assert record.snapshot_alignment_eligible is True
    assert record.snapshot_exclusion_reason is None
    assert record.analysis_lane == ANALYSIS_LANE_PRIMARY_SNAPSHOT_ALIGNMENT


def test_date_only_filename_does_not_block_snapshot_alignment_eligibility(tmp_path: Path) -> None:
    # No HH:MM in the filename at all -- source_capture_ts_utc stays a
    # diagnostic None, but this must not gate snapshot-alignment eligibility.
    write_fixture(tmp_path, "2026-05-01_forecast_source.txt", forecast_fixture("2026-05-05T12:00:00Z"))
    records, _ = run_inventory(tmp_path)

    record = records[0]
    assert record.source_capture_ts_utc is None
    assert record.source_capture_time_eligible is False
    assert record.snapshot_ts_utc == "2026-05-05T12:00:00Z"
    assert record.snapshot_alignment_eligible is True
    assert record.snapshot_exclusion_reason is None
    assert record.analysis_lane == ANALYSIS_LANE_PRIMARY_SNAPSHOT_ALIGNMENT


def test_filename_timestamp_after_snapshot_ts_utc_is_not_a_failure(tmp_path: Path) -> None:
    # A filename timestamp "later" than snapshot_ts_utc must never be treated
    # as an ordering failure -- there is no S<T requirement in this model.
    write_fixture(tmp_path, "2026-05-05_1300_late_filename.txt", forecast_fixture("2026-05-05T12:00:00Z"))
    records, _ = run_inventory(tmp_path)

    record = records[0]
    assert record.snapshot_alignment_eligible is True
    assert record.snapshot_exclusion_reason is None


# ---------------------------------------------------------------------------
# File-level snapshot-alignment eligibility
# ---------------------------------------------------------------------------


def test_compute_snapshot_alignment_eligibility_requires_supported_table() -> None:
    eligible, reason = compute_snapshot_alignment_eligibility(
        detected_table_type=TABLE_TYPE_UNSUPPORTED, status="OK", snapshot_ts_utc="2026-05-05T12:00:00Z"
    )
    assert eligible is False
    assert reason == EXCLUSION_REASON_NOT_SUPPORTED_TABLE


def test_compute_snapshot_alignment_eligibility_requires_status_ok() -> None:
    eligible, reason = compute_snapshot_alignment_eligibility(
        detected_table_type=TABLE_TYPE_TABLE1, status="EMPTY_TABLE_BODY", snapshot_ts_utc="2026-05-05T12:00:00Z"
    )
    assert eligible is False
    assert reason == EXCLUSION_REASON_STATUS_NOT_OK


def test_compute_snapshot_alignment_eligibility_requires_snapshot_ts_utc() -> None:
    eligible, reason = compute_snapshot_alignment_eligibility(
        detected_table_type=TABLE_TYPE_TABLE1, status="OK", snapshot_ts_utc=None
    )
    assert eligible is False
    assert reason == EXCLUSION_REASON_SNAPSHOT_TIME_MISSING


def test_compute_snapshot_alignment_eligibility_passes_when_all_conditions_met() -> None:
    eligible, reason = compute_snapshot_alignment_eligibility(
        detected_table_type=TABLE_TYPE_TABLE2, status="OK", snapshot_ts_utc="2026-05-05T12:00:00Z"
    )
    assert eligible is True
    assert reason is None


def test_no_snapshot_timestamp_is_exploratory_only(tmp_path: Path) -> None:
    content = "TOKEN MOMENTUM STABILITY\nBTC low high\n"
    write_fixture(tmp_path, "2026-04-23_consistency.txt", content)
    records, _ = run_inventory(tmp_path)

    record = records[0]
    assert record.snapshot_ts_utc is None
    assert record.snapshot_alignment_eligible is False
    assert record.snapshot_exclusion_reason == EXCLUSION_REASON_NOT_SUPPORTED_TABLE
    assert record.analysis_lane == ANALYSIS_LANE_EXPLORATORY_ONLY


# ---------------------------------------------------------------------------
# Duplicate source/hash: one canonical source, never one population per alias
# ---------------------------------------------------------------------------


def test_duplicate_files_become_one_canonical_source_and_never_inflate_events(tmp_path: Path) -> None:
    write_fixture(tmp_path, "a_first.txt", TABLE1_SPACE_FIXTURE)
    write_fixture(tmp_path, "b_second_copy.txt", TABLE1_SPACE_FIXTURE)
    write_fixture(tmp_path, "c_third_copy.txt", TABLE1_SPACE_FIXTURE)

    records, rows = run_inventory(tmp_path)

    assert len(records) == 1  # one canonical source, not three
    record = records[0]
    assert record.alias_count == 3
    assert record.alias_paths == sorted(
        [str(tmp_path / "a_first.txt"), str(tmp_path / "b_second_copy.txt"), str(tmp_path / "c_third_copy.txt")]
    )
    assert record.canonical_source_path == record.alias_paths[0]
    assert record.snapshot_alignment_eligible is True

    # Row/event population is per content hash, never per alias path: still
    # exactly 2 asset rows (BTC, ETH), not 6.
    asset_rows = [r for r in rows if r["row_parse_status"] == ROW_PARSE_STATUS_OK]
    assert len(asset_rows) == 2
    assert {r["raw_source_token"] for r in asset_rows} == {"BTC", "ETH"}


def test_run_inventory_does_not_abort_on_duplicate_content(tmp_path: Path) -> None:
    write_fixture(tmp_path, "a.txt", TABLE1_SPACE_FIXTURE)
    write_fixture(tmp_path, "b_copy.txt", TABLE1_SPACE_FIXTURE)
    # Must not raise.
    records, rows = run_inventory(tmp_path)
    assert len(records) == 1


def test_distinct_content_produces_distinct_canonical_sources(tmp_path: Path) -> None:
    write_fixture(tmp_path, "a.txt", TABLE1_SPACE_FIXTURE)
    write_fixture(tmp_path, "b.txt", TABLE1_PIPE_FIXTURE)
    records, rows = run_inventory(tmp_path)
    assert len(records) == 2
    assert all(r.alias_count == 1 for r in records)


def test_check_content_group_consistency_raises_on_impossible_inconsistency(tmp_path: Path) -> None:
    # Contrived: same hash, but the parsed content differs -- this can never
    # happen for byte-identical bytes in production; this is a defensive
    # invariant test constructed directly, not via real duplicate files.
    parsed_a = parse_content(write_fixture(tmp_path, "a.txt", TABLE1_SPACE_FIXTURE))
    parsed_b = parse_content(write_fixture(tmp_path, "b.txt", TABLE1_PIPE_FIXTURE))
    same_hash = "deadbeef" * 8
    group = [(tmp_path / "a.txt", parsed_a), (tmp_path / "b.txt", parsed_b)]

    with pytest.raises(InventoryIntegrityError, match="internal inconsistency"):
        check_content_group_consistency(same_hash, group)


def test_check_content_group_consistency_passes_for_identical_content(tmp_path: Path) -> None:
    parsed_a = parse_content(write_fixture(tmp_path, "a.txt", TABLE1_SPACE_FIXTURE))
    parsed_b = parse_content(write_fixture(tmp_path, "b_copy.txt", TABLE1_SPACE_FIXTURE))
    group = [(tmp_path / "a.txt", parsed_a), (tmp_path / "b_copy.txt", parsed_b)]
    check_content_group_consistency("irrelevant_since_content_matches", group)  # must not raise


def test_duplicate_alias_paths_still_create_one_source_event_population(tmp_path: Path) -> None:
    content = forecast_fixture("2026-05-05T12:00:00Z")
    write_fixture(tmp_path, "2026-05-01_0800_a.txt", content)
    write_fixture(tmp_path, "2026-05-01_0800_b_copy.txt", content)

    records, rows = run_inventory(tmp_path)

    assert len(records) == 1  # one canonical source, not two
    record = records[0]
    assert record.alias_count == 2
    assert record.snapshot_alignment_eligible is True
    assert record.analysis_lane == ANALYSIS_LANE_PRIMARY_SNAPSHOT_ALIGNMENT

    asset_rows = [r for r in rows if r["row_parse_status"] == ROW_PARSE_STATUS_OK]
    assert len(asset_rows) == 1  # not duplicated per alias path


# ---------------------------------------------------------------------------
# Parser correction: no arbitrary prose line becomes an asset row
# ---------------------------------------------------------------------------


def test_trailing_note_footer_never_becomes_an_asset_row(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "trailing_note.txt", TRAILING_NOTE_FOOTER_FIXTURE)
    parsed = parse_content(path)

    assert parsed.status == "OK"
    assert len(parsed.rows) == 2
    assert {r.raw_source_token for r in parsed.rows} == {"BTC", "TAO"}
    assert "NOTE:" not in {r.raw_source_token for r in parsed.rows}

    diagnostic_statuses = [d.row_parse_status for d in parsed.row_diagnostics]
    assert ROW_PARSE_STATUS_UNPARSED_NON_TABLE in diagnostic_statuses
    footer_diagnostic = next(
        d for d in parsed.row_diagnostics if d.row_parse_status == ROW_PARSE_STATUS_UNPARSED_NON_TABLE
    )
    assert footer_diagnostic.line_text.startswith("Note:")


def test_stray_this_prose_never_becomes_an_asset_row(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "stray_this.txt", STRAY_THIS_PROSE_FIXTURE)
    parsed = parse_content(path)

    assert parsed.status == "OK"
    assert len(parsed.rows) == 2
    tokens = {r.raw_source_token for r in parsed.rows}
    assert tokens == {"BTC", "LINK"}
    assert "THIS" not in tokens

    footer_diagnostic = next(
        d for d in parsed.row_diagnostics if d.row_parse_status == ROW_PARSE_STATUS_UNPARSED_NON_TABLE
    )
    assert footer_diagnostic.line_text.startswith("This snapshot reflects")


def test_footer_and_stray_prose_never_enter_event_ledger_rows(tmp_path: Path) -> None:
    write_fixture(tmp_path, "trailing_note.txt", TRAILING_NOTE_FOOTER_FIXTURE)
    write_fixture(tmp_path, "stray_this.txt", STRAY_THIS_PROSE_FIXTURE)
    records, rows = run_inventory(tmp_path)

    asset_rows = [r for r in rows if r["row_parse_status"] == ROW_PARSE_STATUS_OK]
    all_tokens = {r["raw_source_token"] for r in asset_rows}
    assert "NOTE:" not in all_tokens
    assert "THIS" not in all_tokens
    assert all_tokens == {"BTC", "TAO", "LINK"}

    trailing_note_record = next(r for r in records if "trailing_note.txt" in r.canonical_source_path)
    assert trailing_note_record.token_count == 2
    assert "NOTE:" not in trailing_note_record.assets


def test_blank_line_before_first_row_does_not_end_table_body(tmp_path: Path) -> None:
    # TABLE1_SPACE_FIXTURE has a blank line between the header and the first
    # data row; this must not be mistaken for the end of the table body.
    path = write_fixture(tmp_path, "t1.txt", TABLE1_SPACE_FIXTURE)
    parsed = parse_content(path)
    assert len(parsed.rows) == 2
    assert parsed.row_diagnostics == []


def test_malformed_row_within_table_body_is_diagnostic_not_asset(tmp_path: Path) -> None:
    content = (
        "prediction_ts_utc = 2026-05-14T13:15:00Z\n\n"
        "TOKEN PHASE COHERENCE FIELD GEOMETRY STRUCTURAL_ROLE EXPANSION_QUALITY ANCHOR_STRENGTH STRATEGIC_BIAS NOTES\n\n"
        "BTC confirmed high neutral clean leader moderate strong accumulation harmonic axis stable\n"
        "SHORT ROW WITH TOO FEW FIELDS\n"
        "ETH confirmed high expansion mixed leader strong strong continuation resonance peak forming\n"
    )
    path = write_fixture(tmp_path, "malformed.txt", content)
    parsed = parse_content(path)

    assert {r.raw_source_token for r in parsed.rows} == {"BTC", "ETH"}
    malformed = [d for d in parsed.row_diagnostics if d.row_parse_status == ROW_PARSE_STATUS_MALFORMED]
    assert len(malformed) == 1


# ---------------------------------------------------------------------------
# Duplicate asset within a single file: no duplicate-asset ambiguity allowed
# ---------------------------------------------------------------------------


def test_duplicate_asset_within_single_file_is_flagged_not_fatal(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "dup_token.txt", DUPLICATE_TOKEN_FIXTURE)
    parsed = parse_content(path)
    duplicates = find_duplicate_assets(parsed.rows)

    assert duplicates == ["BTC"]
    # Both raw rows are preserved -- never silently collapsed.
    assert len(parsed.rows) == 2


def test_duplicate_asset_within_file_excludes_from_primary_snapshot_alignment(tmp_path: Path) -> None:
    write_fixture(tmp_path, "dup_token.txt", DUPLICATE_TOKEN_FIXTURE)
    records, _ = run_inventory(tmp_path)

    record = records[0]
    assert record.status == "DUPLICATE_ASSET_ALIAS_WITHIN_FILE"
    assert record.snapshot_alignment_eligible is False
    assert record.snapshot_exclusion_reason == EXCLUSION_REASON_STATUS_NOT_OK
    assert record.analysis_lane == ANALYSIS_LANE_EXPLORATORY_ONLY


def test_find_duplicate_assets_pure_function() -> None:
    from src.research.inventory_aplus_raw_evidence_v1 import ParsedRow

    rows = [
        ParsedRow(fields={}, raw_source_token="BTC"),
        ParsedRow(fields={}, raw_source_token="ETH"),
        ParsedRow(fields={}, raw_source_token="BTC"),
    ]
    assert find_duplicate_assets(rows) == ["BTC"]


# ---------------------------------------------------------------------------
# Source-token resolution: explicit registry only, never inferred
# ---------------------------------------------------------------------------


def test_resolve_market_symbol_canonical_token_resolves_to_itself() -> None:
    symbol, status = resolve_market_symbol("BTC")
    assert symbol == "BTC"
    assert status == ASSET_RESOLUTION_RESOLVED


def test_resolve_market_symbol_documented_alias_resolves() -> None:
    symbol, status = resolve_market_symbol("CANTON (CC)")
    assert symbol == "CC"
    assert status == ASSET_RESOLUTION_RESOLVED


def test_resolve_market_symbol_unknown_token_is_unresolved_not_guessed() -> None:
    symbol, status = resolve_market_symbol("SOME_UNKNOWN_TOKEN")
    assert symbol is None
    assert status == ASSET_RESOLUTION_UNRESOLVED


def test_unresolved_token_row_is_preserved_as_diagnostic_and_excluded_from_primary_lane(tmp_path: Path) -> None:
    content = (
        "prediction_ts_utc = 2026-05-14T13:15:00Z\n\n"
        "TOKEN PHASE COHERENCE FIELD GEOMETRY STRUCTURAL_ROLE EXPANSION_QUALITY ANCHOR_STRENGTH STRATEGIC_BIAS NOTES\n\n"
        "ZZZNOTREAL confirmed high neutral clean leader moderate strong accumulation unresolved token test\n"
    )
    write_fixture(tmp_path, "unresolved.txt", content)
    records, rows = run_inventory(tmp_path)

    asset_rows = [r for r in rows if r["row_parse_status"] == ROW_PARSE_STATUS_OK]
    assert len(asset_rows) == 1
    assert asset_rows[0]["raw_source_token"] == "ZZZNOTREAL"
    assert asset_rows[0]["asset_resolution_status"] == ASSET_RESOLUTION_UNRESOLVED
    assert asset_rows[0]["canonical_market_symbol"] is None
    # File-level snapshot_alignment_eligible is True (table/status/timestamp
    # all fine), but the row itself is excluded from the primary lane because
    # its token is unresolved.
    assert records[0].snapshot_alignment_eligible is True
    assert asset_rows[0]["analysis_lane"] == ANALYSIS_LANE_EXPLORATORY_ONLY


# ---------------------------------------------------------------------------
# Table schema rejection
# ---------------------------------------------------------------------------


def test_unsupported_schema_is_not_coerced_into_table1_or_table2(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "legacy_prose.txt", UNSUPPORTED_SCHEMA_FIXTURE)
    parsed = parse_content(path)

    assert parsed.detected_table_type == TABLE_TYPE_UNSUPPORTED
    assert parsed.status == "UNSUPPORTED_SCHEMA"
    assert parsed.header_tokens is None
    assert parsed.rows == []


def test_find_header_returns_none_for_unrecognized_headers() -> None:
    assert find_header(UNSUPPORTED_SCHEMA_FIXTURE.splitlines()) is None


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
    assert "confirmed" not in captured
    assert "harmonic axis stable" not in captured
    assert "accumulation" not in captured
    assert "total_canonical_sources=1" in captured
    assert TABLE_TYPE_TABLE1 in captured
    assert ANALYSIS_LANE_PRIMARY_SNAPSHOT_ALIGNMENT in captured


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
    canonical_manifest = next(evidence_dir.glob("aplus_evidence_canonical_source_manifest_*.jsonl"))
    rows_file = next(evidence_dir.glob("aplus_evidence_rows_*.jsonl"))
    summary_file = next(manifest_dir.glob("aplus_evidence_inventory_manifest_*.json"))

    canonical_records = [json.loads(line) for line in canonical_manifest.read_text(encoding="utf-8").splitlines()]
    assert len(canonical_records) == 2
    assert all("alias_paths" in r and "alias_count" in r for r in canonical_records)
    assert all("snapshot_ts_utc" in r and "snapshot_alignment_eligible" in r for r in canonical_records)

    row_records = [json.loads(line) for line in rows_file.read_text(encoding="utf-8").splitlines()]
    asset_rows = [r for r in row_records if r["row_parse_status"] == ROW_PARSE_STATUS_OK]
    assert len(asset_rows) == 4  # 2 files x 2 assets

    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    assert summary["total_canonical_sources"] == 2
    assert summary["row_record_count"] == 4
    assert summary["snapshot_alignment_eligible_source_count"] == 2
    assert summary["primary_snapshot_alignment_row_count"] == 4


def test_main_duplicate_content_writes_one_canonical_source_not_two(tmp_path: Path) -> None:
    write_fixture(tmp_path, "a.txt", TABLE1_SPACE_FIXTURE)
    write_fixture(tmp_path, "b_copy.txt", TABLE1_SPACE_FIXTURE)
    out_dir = tmp_path / "out"

    exit_code = main(["--root", str(tmp_path), "--out-dir", str(out_dir), "--write-files"])
    assert exit_code == 0

    run_dir = next(out_dir.iterdir())
    canonical_manifest = next((run_dir / "evidence").glob("aplus_evidence_canonical_source_manifest_*.jsonl"))
    canonical_records = [json.loads(line) for line in canonical_manifest.read_text(encoding="utf-8").splitlines()]
    assert len(canonical_records) == 1
    assert canonical_records[0]["alias_count"] == 2


def test_main_missing_root_is_empty_not_fatal(tmp_path: Path) -> None:
    missing_root = tmp_path / "does_not_exist"
    exit_code = main(["--root", str(missing_root)])
    assert exit_code == 0
