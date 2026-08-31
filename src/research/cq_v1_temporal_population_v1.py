from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping

from src.research.cq_v1_model_candidate_v1 import (
    CANDIDATES,
    MODEL_FAMILY_VERSION,
    score_all_candidates,
)
from src.research.cq_v1_pit_extractor_v1 import ShadowObservation, extract_features
from src.research.entry_quality_shadow_v1 import EntryQualityInput, compute_entry_quality_shadow
from src.research.run_entry_quality_shadow_v1 import EVIDENCE_FIELDS
from src.selection.selection_engine_v2 import SelectionCandidate, rank_candidates

RUNNER_NAME = "cq_v1_temporal_population_v1"
CONTRACT_VERSION = "1.0.0"
START_ASOF_UTC = datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc)
END_ASOF_UTC = datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc)
MRP_MODEL_VERSION = "1.0"
GRID_HOURS = frozenset({0, 4, 8, 12, 16, 20})
UNIVERSE_BASIS = "CURRENT_ENABLED_TRADEABLE_ASSET_TABLE"


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, Mapping):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(v) for v in value]
    return value


def evidence_key(evidence: Mapping[str, Any]) -> str:
    normalized = {field: _iso(_dt(evidence.get(field))) for field in EVIDENCE_FIELDS}
    if any(normalized[field] is None for field in EVIDENCE_FIELDS):
        missing = [field for field in EVIDENCE_FIELDS if normalized[field] is None]
        raise ValueError(f"missing canonical evidence timestamps: {','.join(missing)}")
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def source_age_hours(candidate_asof: datetime, source_ts: Any) -> float | None:
    dt = _dt(source_ts)
    if dt is None:
        return None
    age = (candidate_asof - dt).total_seconds() / 3600.0
    if age < 0:
        raise ValueError("future source timestamp in PIT observation")
    return round(age, 6)


def fetch_sampling_grid(
    conn: Any,
    *,
    venue: str,
    start_asof: datetime = START_ASOF_UTC,
    end_asof: datetime = END_ASOF_UTC,
) -> list[datetime]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT as_of_ts_utc
            FROM market_rotation_pressure_snapshot_v1
            WHERE venue=%s
              AND model_version=%s
              AND as_of_ts_utc >= %s
              AND as_of_ts_utc <= %s
            ORDER BY as_of_ts_utc
            """,
            (venue, MRP_MODEL_VERSION, start_asof, end_asof),
        )
        rows = cur.fetchall()
    out: list[datetime] = []
    for row in rows:
        dt = _dt(row["as_of_ts_utc"])
        if dt is None:
            continue
        if dt.minute == 0 and dt.second == 0 and dt.microsecond == 0 and dt.hour in GRID_HOURS:
            out.append(dt)
    return out


def fetch_historical_candidates(
    conn: Any,
    *,
    venue: str,
    candidate_asof: datetime,
    limit: int,
) -> list[SelectionCandidate]:
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be within 1..1000")

    sql = """
    SELECT
        a.asset_id,
        a.symbol,
        COALESCE(q1d.quality_status, 'BLOCKED') AS quality_status_1d,
        COALESCE(q4h.quality_status, 'BLOCKED') AS quality_status_4h,
        COALESCE(q1h.quality_status, 'BLOCKED') AS quality_status_1h,
        COALESCE(s1d.trend_score, 0) AS trend_score_1d,
        COALESCE(s1d.setup_score, 0) AS setup_score_1d,
        COALESCE(s1d.signal_confidence, 0) AS signal_confidence_1d,
        COALESCE(s1d.risk_score, 0) AS risk_score_1d,
        COALESCE(s4h.volume_score, 0) AS volume_score_4h,
        COALESCE(s4h.compass_score, 0) AS compass_score_4h,
        COALESCE(s4h.setup_score, 0) AS setup_score_4h,
        COALESCE(s4h.relative_score, 0) AS relative_score_4h,
        COALESCE(s4h.signal_confidence, 0) AS signal_confidence_4h,
        COALESCE(s4h.expansion_position_score, 0) AS expansion_position_score_4h,
        COALESCE(s4h.pullback_quality_score, 0) AS pullback_quality_score_4h,
        COALESCE(s4h.risk_score, 0) AS risk_score_4h,
        COALESCE(s1h.setup_score, 0) AS setup_score_1h,
        COALESCE(s1h.signal_confidence, 0) AS signal_confidence_1h,
        COALESCE(s1h.risk_score, 0) AS risk_score_1h,
        CAST(GREATEST(
            COALESCE(q1d.asof_ts_utc, '1970-01-01 00:00:00'),
            COALESCE(q4h.asof_ts_utc, '1970-01-01 00:00:00'),
            COALESCE(q1h.asof_ts_utc, '1970-01-01 00:00:00')
        ) AS CHAR) AS latest_quality_asof_ts_utc,
        CAST(s1h.signal_ts_utc AS CHAR) AS advice_ts_1h_utc,
        CAST(s4h.signal_ts_utc AS CHAR) AS advice_ts_4h_utc
    FROM (
        SELECT asset_id, symbol
        FROM asset
        WHERE is_enabled=1 AND is_tradeable=1
        ORDER BY asset_id
        LIMIT %s
    ) a
    LEFT JOIN asset_interval_quality q1d
      ON q1d.asset_id=a.asset_id AND q1d.venue=%s AND q1d.interval_code='1d'
     AND q1d.asof_ts_utc=(SELECT MAX(q.asof_ts_utc) FROM asset_interval_quality q
                          WHERE q.asset_id=a.asset_id AND q.venue=%s AND q.interval_code='1d' AND q.asof_ts_utc<=%s)
    LEFT JOIN asset_interval_quality q4h
      ON q4h.asset_id=a.asset_id AND q4h.venue=%s AND q4h.interval_code='4h'
     AND q4h.asof_ts_utc=(SELECT MAX(q.asof_ts_utc) FROM asset_interval_quality q
                          WHERE q.asset_id=a.asset_id AND q.venue=%s AND q.interval_code='4h' AND q.asof_ts_utc<=%s)
    LEFT JOIN asset_interval_quality q1h
      ON q1h.asset_id=a.asset_id AND q1h.venue=%s AND q1h.interval_code='1h'
     AND q1h.asof_ts_utc=(SELECT MAX(q.asof_ts_utc) FROM asset_interval_quality q
                          WHERE q.asset_id=a.asset_id AND q.venue=%s AND q.interval_code='1h' AND q.asof_ts_utc<=%s)
    LEFT JOIN signal_engine_state s1d
      ON s1d.asset_id=a.asset_id AND s1d.venue=%s AND s1d.interval_code='1d'
     AND s1d.signal_ts_utc=(SELECT MAX(s.signal_ts_utc) FROM signal_engine_state s
                            WHERE s.asset_id=a.asset_id AND s.venue=%s AND s.interval_code='1d' AND s.signal_ts_utc<=%s)
    LEFT JOIN signal_engine_state s4h
      ON s4h.asset_id=a.asset_id AND s4h.venue=%s AND s4h.interval_code='4h'
     AND s4h.signal_ts_utc=(SELECT MAX(s.signal_ts_utc) FROM signal_engine_state s
                            WHERE s.asset_id=a.asset_id AND s.venue=%s AND s.interval_code='4h' AND s.signal_ts_utc<=%s)
    LEFT JOIN signal_engine_state s1h
      ON s1h.asset_id=a.asset_id AND s1h.venue=%s AND s1h.interval_code='1h'
     AND s1h.signal_ts_utc=(SELECT MAX(s.signal_ts_utc) FROM signal_engine_state s
                            WHERE s.asset_id=a.asset_id AND s.venue=%s AND s.interval_code='1h' AND s.signal_ts_utc<=%s)
    ORDER BY a.asset_id
    """
    params: list[Any] = [limit]
    for _ in range(6):
        params.extend([venue, venue, candidate_asof])

    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()

    return [
        SelectionCandidate(
            asset_id=int(row["asset_id"]),
            symbol=str(row["symbol"]),
            venue=venue,
            quality_status_1d=str(row.get("quality_status_1d") or "BLOCKED"),
            quality_status_4h=str(row.get("quality_status_4h") or "BLOCKED"),
            quality_status_1h=str(row.get("quality_status_1h") or "BLOCKED"),
            trend_score_1d=_decimal(row.get("trend_score_1d")),
            setup_score_1d=_decimal(row.get("setup_score_1d")),
            signal_confidence_1d=_decimal(row.get("signal_confidence_1d")),
            risk_score_1d=_decimal(row.get("risk_score_1d")),
            volume_score_4h=_decimal(row.get("volume_score_4h")),
            compass_score_4h=_decimal(row.get("compass_score_4h")),
            setup_score_4h=_decimal(row.get("setup_score_4h")),
            relative_score_4h=_decimal(row.get("relative_score_4h")),
            signal_confidence_4h=_decimal(row.get("signal_confidence_4h")),
            expansion_position_score_4h=_decimal(row.get("expansion_position_score_4h")),
            pullback_quality_score_4h=_decimal(row.get("pullback_quality_score_4h")),
            risk_score_4h=_decimal(row.get("risk_score_4h")),
            setup_score_1h=_decimal(row.get("setup_score_1h")),
            signal_confidence_1h=_decimal(row.get("signal_confidence_1h")),
            risk_score_1h=_decimal(row.get("risk_score_1h")),
            latest_quality_asof_ts_utc=(None if row.get("latest_quality_asof_ts_utc") is None else str(row["latest_quality_asof_ts_utc"])),
            advice_ts_1h_utc=(None if row.get("advice_ts_1h_utc") is None else str(row["advice_ts_1h_utc"])),
            advice_ts_4h_utc=(None if row.get("advice_ts_4h_utc") is None else str(row["advice_ts_4h_utc"])),
        )
        for row in rows
    ]


def fetch_historical_evidence(
    conn: Any,
    *,
    venue: str,
    candidate_asof: datetime,
    asset_ids: list[int],
) -> dict[int, dict[str, datetime | None]]:
    if not asset_ids:
        return {}
    placeholders = ",".join(["%s"] * len(asset_ids))
    sql = f"""
    SELECT a.asset_id,
      (SELECT MAX(q.asof_ts_utc) FROM asset_interval_quality q WHERE q.asset_id=a.asset_id AND q.venue=%s AND q.interval_code='1d' AND q.asof_ts_utc<=%s) quality_ts_1d_utc,
      (SELECT MAX(q.asof_ts_utc) FROM asset_interval_quality q WHERE q.asset_id=a.asset_id AND q.venue=%s AND q.interval_code='4h' AND q.asof_ts_utc<=%s) quality_ts_4h_utc,
      (SELECT MAX(q.asof_ts_utc) FROM asset_interval_quality q WHERE q.asset_id=a.asset_id AND q.venue=%s AND q.interval_code='1h' AND q.asof_ts_utc<=%s) quality_ts_1h_utc,
      (SELECT MAX(s.signal_ts_utc) FROM signal_engine_state s WHERE s.asset_id=a.asset_id AND s.venue=%s AND s.interval_code='1d' AND s.signal_ts_utc<=%s) signal_ts_1d_utc,
      (SELECT MAX(s.signal_ts_utc) FROM signal_engine_state s WHERE s.asset_id=a.asset_id AND s.venue=%s AND s.interval_code='4h' AND s.signal_ts_utc<=%s) signal_ts_4h_utc,
      (SELECT MAX(s.signal_ts_utc) FROM signal_engine_state s WHERE s.asset_id=a.asset_id AND s.venue=%s AND s.interval_code='1h' AND s.signal_ts_utc<=%s) signal_ts_1h_utc
    FROM asset a
    WHERE a.asset_id IN ({placeholders})
    ORDER BY a.asset_id
    """
    params: list[Any] = []
    for _ in range(6):
        params.extend([venue, candidate_asof])
    params.extend(asset_ids)
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    return {
        int(row["asset_id"]): {field: _dt(row.get(field)) for field in EVIDENCE_FIELDS}
        for row in rows
    }


def build_rows_for_asof(
    conn: Any,
    *,
    venue: str,
    candidate_asof: datetime,
    limit: int,
    selection_config: dict[str, Any],
    observation_id_start: int,
) -> list[dict[str, Any]]:
    candidates = fetch_historical_candidates(
        conn, venue=venue, candidate_asof=candidate_asof, limit=limit
    )
    ranked = rank_candidates(candidates, selection_config)
    evidence_by_asset = fetch_historical_evidence(
        conn,
        venue=venue,
        candidate_asof=candidate_asof,
        asset_ids=[row.asset_id for row in ranked],
    )

    rows: list[dict[str, Any]] = []
    for offset, row in enumerate(ranked):
        evidence = evidence_by_asset.get(row.asset_id) or {}
        if any(evidence.get(field) is None for field in EVIDENCE_FIELDS):
            continue
        key = evidence_key(evidence)
        cq = compute_entry_quality_shadow(
            EntryQualityInput(
                trade_quality_score=row.trade_quality_score,
                timing_refinement_score=row.timing_refinement_score,
                quality_penalty=row.quality_penalty,
                quality_status_1d=row.quality_status_1d,
                quality_status_4h=row.quality_status_4h,
                quality_status_1h=row.quality_status_1h,
            )
        )
        temporal_id = observation_id_start + offset
        observation = ShadowObservation(
            shadow_id=temporal_id,
            asset_id=row.asset_id,
            venue=venue,
            asof_ts_utc=candidate_asof,
            evidence_key=key,
            cq_model_version=cq.model_version,
            cq_v0=cq.entry_quality_score,
        )
        features = extract_features(conn.cursor(), observation)
        feature_payload = {
            "mrp_aggregate": features.mrp_aggregate,
            "mrp_asset": features.mrp_asset,
        }
        scores = score_all_candidates(cq_v0=cq.entry_quality_score, features=feature_payload)
        ages = {f"{field}_age_hours": source_age_hours(candidate_asof, evidence[field]) for field in EVIDENCE_FIELDS}
        rows.append(
            {
                "temporal_observation_id": temporal_id,
                "asset_id": row.asset_id,
                "symbol": row.symbol,
                "venue": venue,
                "candidate_asof_ts_utc": _iso(candidate_asof),
                "evidence_key": key,
                "cq_model_version": cq.model_version,
                "frozen_model_family_version": MODEL_FAMILY_VERSION,
                "universe_basis": UNIVERSE_BASIS,
                **{field: _iso(evidence[field]) for field in EVIDENCE_FIELDS},
                **ages,
                "trade_quality_score": _json_value(row.trade_quality_score),
                "selection_score": _json_value(row.selection_score),
                "timing_refinement_score": _json_value(row.timing_refinement_score),
                "quality_penalty": _json_value(row.quality_penalty),
                "quality_status_1d": row.quality_status_1d,
                "quality_status_4h": row.quality_status_4h,
                "quality_status_1h": row.quality_status_1h,
                "cq_v0": _json_value(cq.entry_quality_score),
                "cq_v0_state": cq.entry_quality_state,
                "mrp_aggregate": _json_value(features.mrp_aggregate),
                "mrp_asset": _json_value(features.mrp_asset),
                "primary_sector_code": features.primary_sector_code,
                "sector_rotation": _json_value(features.sector_rotation),
                "mrp_available": features.mrp_available,
                "sector_available": features.sector_available,
                "joint_available": features.joint_available,
                "cq_v1_scores": [_json_value(asdict(score)) for score in scores],
                "ppp_pct": None,
                "ppp_kind": None,
                "ppp_source_ref": None,
            }
        )
    return rows


def summarize(rows: Iterable[Mapping[str, Any]], *, grid: list[datetime]) -> dict[str, Any]:
    materialized = list(rows)
    per_asof: dict[str, int] = {}
    cq_v0_available = 0
    mrp_available = 0
    candidate_available = {spec.candidate_id: 0 for spec in CANDIDATES}
    max_signal_ages = {"signal_ts_1d_utc_age_hours": None, "signal_ts_1h_utc_age_hours": None}

    for row in materialized:
        asof = str(row["candidate_asof_ts_utc"])
        per_asof[asof] = per_asof.get(asof, 0) + 1
        cq_v0_available += int(row.get("cq_v0") is not None)
        mrp_available += int(bool(row.get("mrp_available")))
        for score in row.get("cq_v1_scores", []):
            if score.get("state") == "AVAILABLE":
                candidate_available[str(score["candidate_id"])] += 1
        for field in max_signal_ages:
            value = row.get(field)
            if value is not None:
                old = max_signal_ages[field]
                max_signal_ages[field] = value if old is None else max(old, value)

    return {
        "runner": RUNNER_NAME,
        "contract_version": CONTRACT_VERSION,
        "terminal_state": "FINISHED",
        "model_family_version": MODEL_FAMILY_VERSION,
        "universe_basis": UNIVERSE_BASIS,
        "sampling_contract": {
            "cadence": "4h",
            "grid_owner": "market_rotation_pressure_snapshot_v1",
            "grid_model_version": MRP_MODEL_VERSION,
            "first_bound": _iso(START_ASOF_UTC),
            "last_bound": _iso(END_ASOF_UTC),
            "synthetic_grid_points": 0,
        },
        "candidate_asof_count": len(grid),
        "included_asof_count": len(per_asof),
        "observation_count": len(materialized),
        "observations_per_asof": per_asof,
        "cq_v0_available_count": cq_v0_available,
        "mrp_available_count": mrp_available,
        "candidate_available_count": candidate_available,
        "max_signal_source_age_hours": max_signal_ages,
        "first_asof": min(per_asof) if per_asof else None,
        "last_asof": max(per_asof) if per_asof else None,
        "forward_outcome_reads": 0,
        "production_ranking_changes": 0,
    }
