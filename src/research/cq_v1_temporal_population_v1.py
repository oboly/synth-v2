from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from src.research.cq_v1_model_candidate_v1 import COVERAGE_ARTIFACT_SHA256, MODEL_FAMILY_VERSION
from src.research.cq_v1_pit_extractor_v1 import MRP_MODEL_VERSION
from src.research.cq_v1_temporal_sampling_v1 import derive_asofs, split_for_asof
from src.research.entry_quality_shadow_v1 import EntryQualityInput, compute_entry_quality_shadow
from src.selection.selection_engine_v2 import SelectionCandidate, load_selection_config, rank_candidates

CQ_MODEL_VERSION = "cq_shadow_v1"
DEFAULT_SELECTION_CONFIG = "configs/selection_engine_v2.yaml"
CONTRACT_PATH = Path("config/research/cq_v1_temporal_sampling_v1.json")

EVIDENCE_TS_FIELDS = (
    "quality_ts_1d_utc",
    "quality_ts_4h_utc",
    "quality_ts_1h_utc",
    "signal_ts_1d_utc",
    "signal_ts_4h_utc",
    "signal_ts_1h_utc",
)


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def canonical_json_sha256(payload: Any) -> str:
    raw = json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_temporal_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("temporal contract must be an object")
    frozen = payload["frozen_model_family"]
    if frozen["model_family_version"] != MODEL_FAMILY_VERSION:
        raise ValueError("frozen model family version mismatch")
    if frozen["coverage_artifact_sha256"] != COVERAGE_ARTIFACT_SHA256:
        raise ValueError("frozen coverage artifact hash mismatch")
    if len(derive_asofs(payload)) != 45:
        raise ValueError("temporal contract must contain exactly 45 frozen as-ofs")
    return payload


def fetch_selection_candidates_asof(conn: Any, *, venue: str, asof_ts_utc: datetime) -> tuple[list[SelectionCandidate], dict[int, dict[str, str | None]]]:
    sql = """
    WITH quality_latest AS (
        SELECT q.* FROM asset_interval_quality q
        JOIN (
            SELECT asset_id, venue, interval_code, MAX(asof_ts_utc) max_ts
            FROM asset_interval_quality
            WHERE venue=%s AND interval_code IN ('1d','4h','1h') AND asof_ts_utc <= %s
            GROUP BY asset_id, venue, interval_code
        ) x ON x.asset_id=q.asset_id AND x.venue=q.venue AND x.interval_code=q.interval_code AND x.max_ts=q.asof_ts_utc
        WHERE q.venue=%s
    ), signal_latest AS (
        SELECT s.* FROM signal_engine_state s
        JOIN (
            SELECT asset_id, venue, interval_code, MAX(signal_ts_utc) max_ts
            FROM signal_engine_state
            WHERE venue=%s AND interval_code IN ('1d','4h','1h') AND signal_ts_utc <= %s
            GROUP BY asset_id, venue, interval_code
        ) x ON x.asset_id=s.asset_id AND x.venue=s.venue AND x.interval_code=s.interval_code AND x.max_ts=s.signal_ts_utc
        WHERE s.venue=%s
    )
    SELECT a.asset_id,a.symbol,%s venue,
      COALESCE(q1d.quality_status,'BLOCKED') quality_status_1d,
      COALESCE(q4h.quality_status,'BLOCKED') quality_status_4h,
      COALESCE(q1h.quality_status,'BLOCKED') quality_status_1h,
      COALESCE(s1d.trend_score,0) trend_score_1d,COALESCE(s1d.setup_score,0) setup_score_1d,
      COALESCE(s1d.signal_confidence,0) signal_confidence_1d,COALESCE(s1d.risk_score,0) risk_score_1d,
      COALESCE(s4h.volume_score,0) volume_score_4h,COALESCE(s4h.compass_score,0) compass_score_4h,
      COALESCE(s4h.setup_score,0) setup_score_4h,COALESCE(s4h.relative_score,0) relative_score_4h,
      COALESCE(s4h.signal_confidence,0) signal_confidence_4h,
      COALESCE(s4h.expansion_position_score,0) expansion_position_score_4h,
      COALESCE(s4h.pullback_quality_score,0) pullback_quality_score_4h,COALESCE(s4h.risk_score,0) risk_score_4h,
      COALESCE(s1h.setup_score,0) setup_score_1h,COALESCE(s1h.signal_confidence,0) signal_confidence_1h,
      COALESCE(s1h.risk_score,0) risk_score_1h,
      q1d.asof_ts_utc quality_ts_1d_utc,q4h.asof_ts_utc quality_ts_4h_utc,q1h.asof_ts_utc quality_ts_1h_utc,
      s1d.signal_ts_utc signal_ts_1d_utc,s4h.signal_ts_utc signal_ts_4h_utc,s1h.signal_ts_utc signal_ts_1h_utc
    FROM asset a
    LEFT JOIN quality_latest q1d ON q1d.asset_id=a.asset_id AND q1d.interval_code='1d'
    LEFT JOIN quality_latest q4h ON q4h.asset_id=a.asset_id AND q4h.interval_code='4h'
    LEFT JOIN quality_latest q1h ON q1h.asset_id=a.asset_id AND q1h.interval_code='1h'
    LEFT JOIN signal_latest s1d ON s1d.asset_id=a.asset_id AND s1d.interval_code='1d'
    LEFT JOIN signal_latest s4h ON s4h.asset_id=a.asset_id AND s4h.interval_code='4h'
    LEFT JOIN signal_latest s1h ON s1h.asset_id=a.asset_id AND s1h.interval_code='1h'
    WHERE a.is_enabled=1 AND a.is_tradeable=1
    ORDER BY a.asset_id
    """
    params = (venue, asof_ts_utc, venue, venue, asof_ts_utc, venue, venue)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    candidates: list[SelectionCandidate] = []
    evidence: dict[int, dict[str, str | None]] = {}
    seen: set[int] = set()
    for row in rows:
        asset_id = int(row["asset_id"])
        if asset_id in seen:
            raise ValueError(f"duplicate PIT selection source row asset_id={asset_id}")
        seen.add(asset_id)
        ev = {field: _iso(row.get(field)) for field in EVIDENCE_TS_FIELDS}
        evidence[asset_id] = ev
        candidates.append(SelectionCandidate(
            asset_id=asset_id,symbol=str(row["symbol"]),venue=str(row["venue"]),
            quality_status_1d=str(row["quality_status_1d"]),quality_status_4h=str(row["quality_status_4h"]),quality_status_1h=str(row["quality_status_1h"]),
            trend_score_1d=_decimal(row.get("trend_score_1d")),setup_score_1d=_decimal(row.get("setup_score_1d")),signal_confidence_1d=_decimal(row.get("signal_confidence_1d")),risk_score_1d=_decimal(row.get("risk_score_1d")),
            volume_score_4h=_decimal(row.get("volume_score_4h")),compass_score_4h=_decimal(row.get("compass_score_4h")),setup_score_4h=_decimal(row.get("setup_score_4h")),relative_score_4h=_decimal(row.get("relative_score_4h")),signal_confidence_4h=_decimal(row.get("signal_confidence_4h")),expansion_position_score_4h=_decimal(row.get("expansion_position_score_4h")),pullback_quality_score_4h=_decimal(row.get("pullback_quality_score_4h")),risk_score_4h=_decimal(row.get("risk_score_4h")),
            setup_score_1h=_decimal(row.get("setup_score_1h")),signal_confidence_1h=_decimal(row.get("signal_confidence_1h")),risk_score_1h=_decimal(row.get("risk_score_1h")),
            latest_quality_asof_ts_utc=max((v for k,v in ev.items() if k.startswith("quality_") and v is not None), default=None),
            advice_ts_1h_utc=ev["signal_ts_1h_utc"],advice_ts_4h_utc=ev["signal_ts_4h_utc"],
        ))
    return candidates, evidence


def fetch_mrp_aggregate_asof(conn: Any, *, venue: str, asof_ts_utc: datetime) -> Mapping[str, Any] | None:
    sql = """SELECT pressure_snapshot_id,as_of_ts_utc,venue,model_version,market_score,positive_breadth_ratio,negative_breadth_ratio,acceleration_state,concentration_state,confirmation_state,market_direction,evidence_light_count,eligible_asset_count FROM market_rotation_pressure_snapshot_v1 WHERE venue=%s AND model_version=%s AND as_of_ts_utc <= %s ORDER BY as_of_ts_utc DESC,pressure_snapshot_id DESC LIMIT 1"""
    with conn.cursor() as cur:
        cur.execute(sql, (venue, MRP_MODEL_VERSION, asof_ts_utc))
        return cur.fetchone() or None


def fetch_mrp_assets_asof(conn: Any, *, venue: str, asof_ts_utc: datetime) -> dict[int, Mapping[str, Any]]:
    sql = """
    SELECT o.pressure_obs_id,o.pressure_snapshot_id,o.asset_id,o.as_of_ts_utc,o.model_version,o.score_total,o.pressure_state,o.phase_state,o.raw_market_relative_pct
    FROM market_rotation_pressure_observation_v1 o
    JOIN market_rotation_pressure_snapshot_v1 s ON s.pressure_snapshot_id=o.pressure_snapshot_id
    JOIN (
      SELECT o2.asset_id,MAX(o2.as_of_ts_utc) max_ts
      FROM market_rotation_pressure_observation_v1 o2
      JOIN market_rotation_pressure_snapshot_v1 s2 ON s2.pressure_snapshot_id=o2.pressure_snapshot_id
      WHERE s2.venue=%s AND o2.model_version=%s AND s2.model_version=%s AND o2.as_of_ts_utc <= %s AND s2.as_of_ts_utc <= %s
      GROUP BY o2.asset_id
    ) x ON x.asset_id=o.asset_id AND x.max_ts=o.as_of_ts_utc
    WHERE s.venue=%s AND o.model_version=%s AND s.model_version=%s AND o.as_of_ts_utc <= %s AND s.as_of_ts_utc <= %s
    ORDER BY o.asset_id,o.pressure_obs_id DESC
    """
    params = (venue,MRP_MODEL_VERSION,MRP_MODEL_VERSION,asof_ts_utc,asof_ts_utc,venue,MRP_MODEL_VERSION,MRP_MODEL_VERSION,asof_ts_utc,asof_ts_utc)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    out: dict[int, Mapping[str, Any]] = {}
    for row in rows:
        asset_id = int(row["asset_id"])
        out.setdefault(asset_id, row)
    return out


def build_asof_population(conn: Any, *, contract: dict[str, Any], asof_ts_utc: datetime, venue: str, selection_config: dict[str, Any]) -> list[dict[str, Any]]:
    split = split_for_asof(asof_ts_utc, contract)
    candidates, evidence_by_asset = fetch_selection_candidates_asof(conn, venue=venue, asof_ts_utc=asof_ts_utc)
    selection_rows = rank_candidates(candidates, selection_config)
    aggregate = fetch_mrp_aggregate_asof(conn, venue=venue, asof_ts_utc=asof_ts_utc)
    mrp_assets = fetch_mrp_assets_asof(conn, venue=venue, asof_ts_utc=asof_ts_utc)
    rows: list[dict[str, Any]] = []
    for selection in selection_rows:
        evidence = evidence_by_asset[selection.asset_id]
        evidence_key = canonical_json_sha256(evidence)
        cq = compute_entry_quality_shadow(EntryQualityInput(
            trade_quality_score=selection.trade_quality_score,
            timing_refinement_score=selection.timing_refinement_score,
            quality_penalty=selection.quality_penalty,
            quality_status_1d=selection.quality_status_1d,
            quality_status_4h=selection.quality_status_4h,
            quality_status_1h=selection.quality_status_1h,
        ))
        mrp_asset = mrp_assets.get(selection.asset_id)
        identity = {
            "asset_id": selection.asset_id,"venue": venue,"asof_ts_utc": asof_ts_utc.isoformat(),
            "evidence_key": evidence_key,"cq_model_version": CQ_MODEL_VERSION,
            "model_family_version": MODEL_FAMILY_VERSION,"coverage_artifact_sha256": COVERAGE_ARTIFACT_SHA256,
        }
        rows.append({
            **identity,"observation_id": canonical_json_sha256(identity),"symbol": selection.symbol,"split": split,
            **evidence,"trade_quality_score": selection.trade_quality_score,"selection_score": selection.selection_score,
            "timing_refinement_score": selection.timing_refinement_score,"quality_penalty": selection.quality_penalty,
            "quality_status_1d": selection.quality_status_1d,"quality_status_4h": selection.quality_status_4h,"quality_status_1h": selection.quality_status_1h,
            "cq_v0": cq.entry_quality_score,"cq_v0_state": cq.entry_quality_state,"cq_v0_reasons": cq.reasons,"cq_v0_blockers": cq.blockers,
            "mrp_aggregate": aggregate,"mrp_aggregate_status": "AVAILABLE" if aggregate else "UNAVAILABLE_MRP_AGGREGATE",
            "mrp_asset": mrp_asset,"mrp_asset_status": "AVAILABLE" if mrp_asset else "UNAVAILABLE_MRP_ASSET",
            "sector_context_status": "UNAVAILABLE_HISTORICAL_MEMBERSHIP",
            "ppp_status": "UNAVAILABLE_UNLESS_CANONICAL_PIT_ARTIFACT_SUPPLIED",
            "canonical_candles_15m_status": "NOT_DIRECTLY_CONSUMED_BY_FROZEN_CQ_V1_FEATURE_RECONSTRUCTION",
        })
    ids = [row["observation_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate observation identity at {asof_ts_utc.isoformat()}")
    return rows


def summarize_population(rows: list[dict[str, Any]]) -> dict[str, Any]:
    asofs = sorted({str(row["asof_ts_utc"]) for row in rows})
    assets = {int(row["asset_id"]) for row in rows}
    return {
        "row_count": len(rows),"unique_asset_count": len(assets),"unique_asof_count": len(asofs),
        "first_asof_ts_utc": asofs[0] if asofs else None,"last_asof_ts_utc": asofs[-1] if asofs else None,
        "mrp_aggregate_unavailable_count": sum(row["mrp_aggregate_status"] != "AVAILABLE" for row in rows),
        "mrp_asset_unavailable_count": sum(row["mrp_asset_status"] != "AVAILABLE" for row in rows),
        "cq_v0_unavailable_count": sum(row["cq_v0"] is None for row in rows),
        "sector_context_unavailable_count": len(rows),"ppp_unavailable_count": len(rows),
    }
