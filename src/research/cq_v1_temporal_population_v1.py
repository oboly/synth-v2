from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from src.research.cq_v1_model_candidate_v1 import (
    CANDIDATES,
    COVERAGE_ARTIFACT_SHA256,
    MODEL_FAMILY_VERSION,
    score_all_candidates,
)
from src.research.cq_v1_temporal_sampling_v1 import derive_asofs, split_for_asof
from src.research.entry_quality_shadow_v1 import EntryQualityInput, compute_entry_quality_shadow
from src.research.run_entry_quality_shadow_v1 import EVIDENCE_FIELDS
from src.selection.selection_engine_v2 import SelectionCandidate, rank_candidates

RUNNER_NAME = "cq_v1_temporal_population_v1"
CONTRACT_VERSION = "1.0.0"
MRP_MODEL_VERSION = "1.0"
UNIVERSE_BASIS = "CURRENT_ENABLED_TRADEABLE_ASSET_TABLE"
SECTOR_CONTEXT_STATE = "UNAVAILABLE_HISTORICAL_MEMBERSHIP"


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


def sampling_grid(contract: dict[str, Any]) -> list[datetime]:
    return list(derive_asofs(contract))


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
        a.asset_id, a.symbol,
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

    return [SelectionCandidate(
        asset_id=int(row["asset_id"]), symbol=str(row["symbol"]), venue=venue,
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
        latest_quality_asof_ts_utc=None if row.get("latest_quality_asof_ts_utc") is None else str(row["latest_quality_asof_ts_utc"]),
        advice_ts_1h_utc=None if row.get("advice_ts_1h_utc") is None else str(row["advice_ts_1h_utc"]),
        advice_ts_4h_utc=None if row.get("advice_ts_4h_utc") is None else str(row["advice_ts_4h_utc"]),
    ) for row in rows]


def fetch_historical_evidence(conn: Any, *, venue: str, candidate_asof: datetime, asset_ids: list[int]) -> dict[int, dict[str, datetime | None]]:
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
    FROM asset a WHERE a.asset_id IN ({placeholders}) ORDER BY a.asset_id
    """
    params: list[Any] = []
    for _ in range(6):
        params.extend([venue, candidate_asof])
    params.extend(asset_ids)
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    return {int(row["asset_id"]): {field: _dt(row.get(field)) for field in EVIDENCE_FIELDS} for row in rows}


def fetch_mrp_for_asof(conn: Any, *, venue: str, candidate_asof: datetime, asset_ids: list[int]) -> tuple[Mapping[str, Any] | None, dict[int, Mapping[str, Any]]]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT pressure_snapshot_id, as_of_ts_utc, venue, model_version, market_score,
                      positive_breadth_ratio, negative_breadth_ratio, acceleration_state,
                      concentration_state, confirmation_state, market_direction,
                      evidence_light_count, eligible_asset_count
               FROM market_rotation_pressure_snapshot_v1
               WHERE venue=%s AND model_version=%s AND as_of_ts_utc<=%s
               ORDER BY as_of_ts_utc DESC, pressure_snapshot_id DESC LIMIT 1""",
            (venue, MRP_MODEL_VERSION, candidate_asof),
        )
        aggregate = cur.fetchone()
        if not asset_ids:
            return aggregate, {}
        placeholders = ",".join(["%s"] * len(asset_ids))
        cur.execute(
            f"""SELECT o.pressure_obs_id, o.pressure_snapshot_id, o.asset_id, o.as_of_ts_utc,
                       o.model_version, o.score_total, o.pressure_state, o.phase_state,
                       o.raw_market_relative_pct, s.venue
                FROM market_rotation_pressure_observation_v1 o
                JOIN market_rotation_pressure_snapshot_v1 s ON s.pressure_snapshot_id=o.pressure_snapshot_id
                JOIN (
                    SELECT o2.asset_id, MAX(o2.as_of_ts_utc) AS max_asof
                    FROM market_rotation_pressure_observation_v1 o2
                    JOIN market_rotation_pressure_snapshot_v1 s2 ON s2.pressure_snapshot_id=o2.pressure_snapshot_id
                    WHERE o2.asset_id IN ({placeholders}) AND s2.venue=%s
                      AND o2.model_version=%s AND s2.model_version=%s
                      AND o2.as_of_ts_utc<=%s AND s2.as_of_ts_utc<=%s
                    GROUP BY o2.asset_id
                ) latest ON latest.asset_id=o.asset_id AND latest.max_asof=o.as_of_ts_utc
                WHERE o.asset_id IN ({placeholders}) AND s.venue=%s
                  AND o.model_version=%s AND s.model_version=%s""",
            tuple(asset_ids) + (venue, MRP_MODEL_VERSION, MRP_MODEL_VERSION, candidate_asof, candidate_asof)
            + tuple(asset_ids) + (venue, MRP_MODEL_VERSION, MRP_MODEL_VERSION),
        )
        asset_rows = cur.fetchall()
    return aggregate, {int(row["asset_id"]): row for row in asset_rows}


def build_rows_for_asof(
    conn: Any,
    *,
    venue: str,
    candidate_asof: datetime,
    limit: int,
    selection_config: dict[str, Any],
    temporal_contract: dict[str, Any],
    observation_id_start: int,
) -> list[dict[str, Any]]:
    candidates = fetch_historical_candidates(conn, venue=venue, candidate_asof=candidate_asof, limit=limit)
    ranked = rank_candidates(candidates, selection_config)
    asset_ids = [row.asset_id for row in ranked]
    evidence_by_asset = fetch_historical_evidence(conn, venue=venue, candidate_asof=candidate_asof, asset_ids=asset_ids)
    mrp_aggregate, mrp_assets = fetch_mrp_for_asof(conn, venue=venue, candidate_asof=candidate_asof, asset_ids=asset_ids)

    rows: list[dict[str, Any]] = []
    for row in ranked:
        evidence = evidence_by_asset.get(row.asset_id) or {}
        if any(evidence.get(field) is None for field in EVIDENCE_FIELDS):
            continue
        key = evidence_key(evidence)
        cq = compute_entry_quality_shadow(EntryQualityInput(
            trade_quality_score=row.trade_quality_score,
            timing_refinement_score=row.timing_refinement_score,
            quality_penalty=row.quality_penalty,
            quality_status_1d=row.quality_status_1d,
            quality_status_4h=row.quality_status_4h,
            quality_status_1h=row.quality_status_1h,
        ))
        mrp_asset = mrp_assets.get(row.asset_id)
        scores = score_all_candidates(cq_v0=cq.entry_quality_score, features={"mrp_aggregate": mrp_aggregate, "mrp_asset": mrp_asset})
        temporal_id = observation_id_start + len(rows)
        payload: dict[str, Any] = {
            "temporal_observation_id": temporal_id,
            "asset_id": row.asset_id,
            "symbol": row.symbol,
            "venue": venue,
            "asof_ts_utc": _iso(candidate_asof),
            "chronological_split": split_for_asof(candidate_asof, temporal_contract),
            "evidence_key": key,
            "cq_model_version": cq.model_version,
            "model_family_version": MODEL_FAMILY_VERSION,
            "coverage_artifact_sha256": COVERAGE_ARTIFACT_SHA256,
            "universe_basis": UNIVERSE_BASIS,
            **{field: _iso(evidence[field]) for field in EVIDENCE_FIELDS},
            **{f"{field}_age_hours": source_age_hours(candidate_asof, evidence[field]) for field in EVIDENCE_FIELDS},
            "selection_score": _json_value(row.selection_score),
            "trade_quality_score": _json_value(row.trade_quality_score),
            "cq_v0": _json_value(cq.entry_quality_score),
            "cq_v0_state": cq.entry_quality_state,
            "mrp_aggregate": _json_value(mrp_aggregate),
            "mrp_aggregate_ts_utc": None if mrp_aggregate is None else _iso(_dt(mrp_aggregate.get("as_of_ts_utc"))),
            "mrp_aggregate_age_hours": None if mrp_aggregate is None else source_age_hours(candidate_asof, mrp_aggregate.get("as_of_ts_utc")),
            "mrp_aggregate_state": "AVAILABLE" if mrp_aggregate is not None else "UNAVAILABLE_MRP_AGGREGATE",
            "mrp_asset": _json_value(mrp_asset),
            "mrp_asset_ts_utc": None if mrp_asset is None else _iso(_dt(mrp_asset.get("as_of_ts_utc"))),
            "mrp_asset_age_hours": None if mrp_asset is None else source_age_hours(candidate_asof, mrp_asset.get("as_of_ts_utc")),
            "mrp_asset_state": "AVAILABLE" if mrp_asset is not None else "UNAVAILABLE_MRP_ASSET",
            "sector_context_state": SECTOR_CONTEXT_STATE,
            "ppp_pct": None, "ppp_kind": None, "ppp_source_ref": None,
        }
        for score in scores:
            payload[score.candidate_id] = _json_value(score.score)
            payload[f"{score.candidate_id}_state"] = score.state
            payload[f"{score.candidate_id}_reason"] = score.reason
        rows.append(payload)
    return rows


def summarize(rows: list[Mapping[str, Any]], *, grid: list[datetime]) -> dict[str, Any]:
    per_asof: dict[str, int] = {}
    split_counts = {"discovery": 0, "validation": 0, "holdout": 0}
    mrp_aggregate_available = mrp_asset_available = 0
    candidate_available = {spec.candidate_id: 0 for spec in CANDIDATES}
    max_ages: dict[str, float | None] = {
        **{f"{field}_age_hours": None for field in EVIDENCE_FIELDS},
        "mrp_aggregate_age_hours": None,
        "mrp_asset_age_hours": None,
    }
    for row in rows:
        asof = str(row["asof_ts_utc"])
        per_asof[asof] = per_asof.get(asof, 0) + 1
        split = str(row["chronological_split"])
        split_counts[split] += 1
        mrp_aggregate_available += int(row.get("mrp_aggregate_state") == "AVAILABLE")
        mrp_asset_available += int(row.get("mrp_asset_state") == "AVAILABLE")
        for spec in CANDIDATES:
            candidate_available[spec.candidate_id] += int(row.get(f"{spec.candidate_id}_state") == "AVAILABLE")
        for field in max_ages:
            value = row.get(field)
            if value is not None:
                previous = max_ages[field]
                max_ages[field] = float(value) if previous is None else max(previous, float(value))
    return {
        "runner": RUNNER_NAME,
        "contract_version": CONTRACT_VERSION,
        "terminal_state": "FINISHED",
        "model_family_version": MODEL_FAMILY_VERSION,
        "coverage_artifact_sha256": COVERAGE_ARTIFACT_SHA256,
        "universe_basis": UNIVERSE_BASIS,
        "sector_context_state": SECTOR_CONTEXT_STATE,
        "candidate_asof_count": len(grid),
        "included_asof_count": len(per_asof),
        "observation_count": len(rows),
        "observations_per_asof": per_asof,
        "observation_split_counts": split_counts,
        "mrp_aggregate_available_count": mrp_aggregate_available,
        "mrp_asset_available_count": mrp_asset_available,
        "candidate_available_count": candidate_available,
        "max_source_age_hours": max_ages,
        "first_asof": _iso(grid[0]) if grid else None,
        "last_asof": _iso(grid[-1]) if grid else None,
        "forward_outcome_reads": 0,
        "production_ranking_changes": 0,
    }
