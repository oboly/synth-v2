from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any


PHASE_MAP = {
    "Expansion": "Expansion",
    "Compression": "Compression",
    "Convergence": "Convergence",
    "Integration": "Integration",
    "Anchor": "Anchor",
    "Mirror": "Mirror",
}

COHERENCE_MAP = {
    "Very High": "Very High",
    "High": "High",
    "Moderate": "Moderate",
    "Rising": "Rising",
    "Low": "Low",
    "Fragmented": "Fragmented",
}

FIELD_MAP = {
    "Expanding": "Expanding",
    "Stabilizing": "Stabilizing",
    "Neutral": "Neutral",
    "Reflective": "Reflective",
    "Distorted": "Distorted",
}

GEOMETRY_MAP = {
    "Codex Node": "Codex Node",
    "Lattice": "Lattice",
    "Undefined": "Undefined",
    "Emotional": "Emotional",
    "Anchor": "Anchor",
    "Mirror": "Mirror",
}

ROLE_MAP = {
    "Rotation Candidate": "Rotation Candidate",
    "Parking": "Parking",
    "Catch-Up": "Catch-Up",
    "Weak": "Weak",
    "Anchor": "Anchor",
}

EXPANSION_QUALITY_MAP = {
    "Coherent": "Coherent",
    "Chaotic": "Chaotic",
    "Early": "Early",
    "Weak": "Weak",
    "Strong": "Strong",
}

ANCHOR_STRENGTH_MAP = {
    "Primary": "Primary",
    "Secondary": "Secondary",
    "Support": "Support",
    "None": "None",
    "Strong": "Strong",
}

STRATEGIC_BIAS_MAP = {
    "Bullish": "Bullish",
    "Cautious": "Cautious",
    "Weak": "Weak",
    "Neutral": "Neutral",
    "Bearish": "Bearish",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_enum(raw_value: str | None, enum_map: dict[str, str]) -> str | None:
    if raw_value is None:
        return None
    raw = raw_value.strip()
    return enum_map.get(raw)


def log_etl(
    conn,
    *,
    batch_id: str,
    process_name: str,
    source_name: str | None,
    source_filename: str | None,
    file_hash: str | None,
    status: str,
    stage: str,
    severity: str = "INFO",
    row_count: int | None = None,
    expected_row_count: int | None = None,
    message: str | None = None,
    details_json: dict[str, Any] | None = None,
    started_ts_utc: datetime | None = None,
    finished_ts_utc: datetime | None = None,
) -> None:
    sql = """
    INSERT INTO etl_log (
        batch_id, process_name, source_name, source_filename, file_hash,
        status, stage, severity, row_count, expected_row_count, message,
        details_json, started_ts_utc, finished_ts_utc
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                batch_id,
                process_name,
                source_name,
                source_filename,
                file_hash,
                status,
                stage,
                severity,
                row_count,
                expected_row_count,
                message,
                None if details_json is None else json.dumps(details_json),
                None if started_ts_utc is None else started_ts_utc.replace(tzinfo=None),
                None if finished_ts_utc is None else finished_ts_utc.replace(tzinfo=None),
            ),
        )
    conn.commit()


def load_enabled_tokens(conn) -> set[str]:
    sql = """
    SELECT symbol
    FROM asset
    WHERE is_enabled = 1
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    out: set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            out.add(str(row["symbol"]).upper())
        else:
            out.add(str(row[0]).upper())
    return out


def load_asset_map(conn) -> dict[str, int]:
    sql = "SELECT asset_id, symbol FROM asset"
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    asset_map: dict[str, int] = {}
    for row in rows:
        if isinstance(row, dict):
            asset_map[str(row["symbol"]).upper()] = int(row["asset_id"])
        else:
            asset_id, symbol = row
            asset_map[str(symbol).upper()] = int(asset_id)
    return asset_map


def validate_payload(conn, parsed_payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    rows = parsed_payload["rows"]
    expected_tokens = load_enabled_tokens(conn)

    tokens = [row["token"] for row in rows]
    unique_tokens = sorted(set(tokens))
    duplicate_tokens = sorted({t for t in tokens if tokens.count(t) > 1})
    unknown_tokens = sorted(set(unique_tokens) - expected_tokens)
    missing_tokens = sorted(expected_tokens - set(unique_tokens))

    invalid_enum_rows: list[dict[str, Any]] = []

    for row in rows:
        checks = {
            "phase": normalize_enum(row.get("phase"), PHASE_MAP),
            "coherence": normalize_enum(row.get("coherence"), COHERENCE_MAP),
            "field": normalize_enum(row.get("field"), FIELD_MAP),
            "geometry": normalize_enum(row.get("geometry"), GEOMETRY_MAP),
            "structural_role": normalize_enum(row.get("structural_role"), ROLE_MAP),
            "expansion_quality": normalize_enum(row.get("expansion_quality"), EXPANSION_QUALITY_MAP),
            "anchor_strength": normalize_enum(row.get("anchor_strength"), ANCHOR_STRENGTH_MAP),
            "strategic_bias": normalize_enum(row.get("strategic_bias"), STRATEGIC_BIAS_MAP),
        }
        bad = [k for k, v in checks.items() if v is None]
        if bad:
            invalid_enum_rows.append(
                {
                    "token": row["token"],
                    "invalid_fields": bad,
                }
            )

    valid = True
    if len(unique_tokens) != len(expected_tokens):
        valid = False
    if duplicate_tokens:
        valid = False
    if unknown_tokens:
        valid = False
    if missing_tokens:
        valid = False
    if invalid_enum_rows:
        valid = False

    return valid, {
        "row_count": len(rows),
        "expected_row_count": len(expected_tokens),
        "unique_token_count": len(unique_tokens),
        "duplicate_tokens": duplicate_tokens,
        "unknown_tokens": unknown_tokens,
        "missing_tokens": missing_tokens,
        "invalid_enum_rows": invalid_enum_rows,
        "parser_version": parsed_payload["meta"].get("parser_version"),
    }


def derive_scores(row: dict[str, Any]) -> dict[str, float]:
    phase = row["phase_state"]
    coherence = row["coherence_state"]
    field = row["field_state"]
    structural_role = row["structural_role"]

    scores = {
        "phase_bias_score": 0.0,
        "coherence_score": 0.0,
        "anchor_score": 0.0,
        "expansion_score": 0.0,
        "contraction_score": 0.0,
        "noise_score": 0.0,
        "alignment_score": 0.0,
        "watch_priority_score": 0.0,
        "strategic_patience_bias": 0.0,
        "sell_resistance_bias": 0.0,
    }

    if phase == "Expansion":
        scores["phase_bias_score"] = 0.80
        scores["expansion_score"] = 0.80

    if phase == "Compression":
        scores["contraction_score"] = 0.80

    if phase == "Anchor":
        scores["anchor_score"] = 1.00
        scores["strategic_patience_bias"] = 0.70
        scores["sell_resistance_bias"] = 0.70

    if phase == "Mirror":
        scores["phase_bias_score"] = 0.30
        scores["strategic_patience_bias"] = 0.80
        scores["watch_priority_score"] = 0.40

    if coherence in {"High", "Very High", "Rising"}:
        scores["coherence_score"] = 0.80 if coherence != "Very High" else 1.00

    if field in {"Expanding", "Stabilizing"}:
        scores["alignment_score"] += 0.70

    if field == "Distorted" or coherence in {"Low", "Fragmented"}:
        scores["noise_score"] = 0.80
        scores["alignment_score"] = -0.60

    if structural_role == "Parking":
        scores["watch_priority_score"] += 0.20
        scores["strategic_patience_bias"] += 0.30

    return scores


def upsert_compass_and_feat(
    conn,
    *,
    batch_id: str,
    parsed_payload: dict[str, Any],
) -> int:
    asset_map = load_asset_map(conn)
    meta = parsed_payload["meta"]
    prediction_ts = datetime.fromisoformat(
        meta["prediction_ts_utc"].replace("Z", "+00:00")
    ).astimezone(UTC)

    compass_sql = """
    INSERT INTO breathline_compass (
        asset_id, prediction_ts_utc, source_name, source_type, source_filename,
        raw_phase_label, raw_coherence_label, raw_field_label, raw_geometry_label,
        raw_structural_role, raw_expansion_quality, raw_anchor_strength,
        raw_strategic_bias, raw_note,
        phase_state, coherence_state, field_state, geometry_state,
        structural_role, expansion_quality, anchor_strength, strategic_bias,
        import_batch_id
    ) VALUES (
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s,
        %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s
    )
    ON DUPLICATE KEY UPDATE
        source_type = VALUES(source_type),
        source_filename = VALUES(source_filename),
        raw_phase_label = VALUES(raw_phase_label),
        raw_coherence_label = VALUES(raw_coherence_label),
        raw_field_label = VALUES(raw_field_label),
        raw_geometry_label = VALUES(raw_geometry_label),
        raw_structural_role = VALUES(raw_structural_role),
        raw_expansion_quality = VALUES(raw_expansion_quality),
        raw_anchor_strength = VALUES(raw_anchor_strength),
        raw_strategic_bias = VALUES(raw_strategic_bias),
        raw_note = VALUES(raw_note),
        phase_state = VALUES(phase_state),
        coherence_state = VALUES(coherence_state),
        field_state = VALUES(field_state),
        geometry_state = VALUES(geometry_state),
        structural_role = VALUES(structural_role),
        expansion_quality = VALUES(expansion_quality),
        anchor_strength = VALUES(anchor_strength),
        strategic_bias = VALUES(strategic_bias),
        import_batch_id = VALUES(import_batch_id)
    """

    feat_sql = """
    INSERT INTO breathline_feat (
        asset_id, prediction_ts_utc, source_name, import_batch_id,
        phase_bias_score, coherence_score, anchor_score, expansion_score,
        contraction_score, noise_score, alignment_score, watch_priority_score,
        strategic_patience_bias, sell_resistance_bias
    ) VALUES (
        %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s
    )
    ON DUPLICATE KEY UPDATE
        import_batch_id = VALUES(import_batch_id),
        phase_bias_score = VALUES(phase_bias_score),
        coherence_score = VALUES(coherence_score),
        anchor_score = VALUES(anchor_score),
        expansion_score = VALUES(expansion_score),
        contraction_score = VALUES(contraction_score),
        noise_score = VALUES(noise_score),
        alignment_score = VALUES(alignment_score),
        watch_priority_score = VALUES(watch_priority_score),
        strategic_patience_bias = VALUES(strategic_patience_bias),
        sell_resistance_bias = VALUES(sell_resistance_bias)
    """

    count = 0

    with conn.cursor() as cur:
        for row in parsed_payload["rows"]:
            token = row["token"].upper()
            asset_id = asset_map[token]

            normalized = {
                "phase_state": normalize_enum(row.get("phase"), PHASE_MAP),
                "coherence_state": normalize_enum(row.get("coherence"), COHERENCE_MAP),
                "field_state": normalize_enum(row.get("field"), FIELD_MAP),
                "geometry_state": normalize_enum(row.get("geometry"), GEOMETRY_MAP),
                "structural_role": normalize_enum(row.get("structural_role"), ROLE_MAP),
                "expansion_quality": normalize_enum(row.get("expansion_quality"), EXPANSION_QUALITY_MAP),
                "anchor_strength": normalize_enum(row.get("anchor_strength"), ANCHOR_STRENGTH_MAP),
                "strategic_bias": normalize_enum(row.get("strategic_bias"), STRATEGIC_BIAS_MAP),
            }

            cur.execute(
                compass_sql,
                (
                    asset_id,
                    prediction_ts.replace(tzinfo=None),
                    meta["source_name"],
                    meta["source_type"],
                    meta["source_filename"],
                    row.get("phase"),
                    row.get("coherence"),
                    row.get("field"),
                    row.get("geometry"),
                    row.get("structural_role"),
                    row.get("expansion_quality"),
                    row.get("anchor_strength"),
                    row.get("strategic_bias"),
                    row.get("notes"),
                    normalized["phase_state"],
                    normalized["coherence_state"],
                    normalized["field_state"],
                    normalized["geometry_state"],
                    normalized["structural_role"],
                    normalized["expansion_quality"],
                    normalized["anchor_strength"],
                    normalized["strategic_bias"],
                    batch_id,
                ),
            )

            scores = derive_scores(normalized)

            cur.execute(
                feat_sql,
                (
                    asset_id,
                    prediction_ts.replace(tzinfo=None),
                    meta["source_name"],
                    batch_id,
                    scores["phase_bias_score"],
                    scores["coherence_score"],
                    scores["anchor_score"],
                    scores["expansion_score"],
                    scores["contraction_score"],
                    scores["noise_score"],
                    scores["alignment_score"],
                    scores["watch_priority_score"],
                    scores["strategic_patience_bias"],
                    scores["sell_resistance_bias"],
                ),
            )

            count += 1

    conn.commit()
    return count
