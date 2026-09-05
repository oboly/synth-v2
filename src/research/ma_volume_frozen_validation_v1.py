from __future__ import annotations

"""Frozen #310 MA/volume validation contract and pure transformation helpers."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from src.research.ma_volume_candidate_features_v1 import (
    MODEL_ID as CANDIDATE_MODEL_ID,
    MODEL_VERSION as CANDIDATE_MODEL_VERSION,
    build_candidate_frame,
)

CONTRACT_NAME = "ma_volume_frozen_validation_run_v1"
CONTRACT_VERSION = "1.0.0"
DEFAULT_CONTRACT = "config/research/ma_volume_frozen_validation_run_v1.json"
PINNED_CONTRACT_SHA256 = "6fd40adc9e70d779ad1730af7d205dee31d6e04590ad5fef20f6bcfad2fad1a9"
PINNED_POPULATION_SHA256 = "61bab264b2921b93a25a22ec0d12cbc031ad0ef234fa989b2ea43c894bc263b4"
PINNED_OUTCOMES_SHA256 = "2c1b3b9e17e6e06eec3831ac47b48bfd91944730cf9c6e75929979a795727500"
CANDLE_INTERVAL = "4h"
CANDLE_HOURS = 4


def canonical_json_sha256(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_ts(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def load_contract(path: Path) -> dict[str, Any]:
    if str(path) != DEFAULT_CONTRACT:
        raise ValueError(f"contract path must remain pinned to {DEFAULT_CONTRACT}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if canonical_json_sha256(payload) != PINNED_CONTRACT_SHA256:
        raise ValueError("MA/volume frozen validation contract SHA256 mismatch")
    if payload.get("contract_name") != CONTRACT_NAME or payload.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("unexpected MA/volume frozen validation contract identity")
    if payload["source_population"]["population_sha256"] != PINNED_POPULATION_SHA256:
        raise ValueError("population SHA mismatch in contract")
    if payload["source_outcomes"]["outcomes_sha256"] != PINNED_OUTCOMES_SHA256:
        raise ValueError("outcomes SHA mismatch in contract")
    feature = payload["feature_contract"]
    if feature["model_id"] != CANDIDATE_MODEL_ID or feature["model_version"] != CANDIDATE_MODEL_VERSION:
        raise ValueError("candidate model identity mismatch")
    if feature["input_interval"] != CANDLE_INTERVAL:
        raise ValueError("candidate interval mismatch")
    return payload


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path} line {line_number} is not a JSON object")
        rows.append(value)
    return rows


def load_population(path: Path, contract: dict[str, Any]) -> list[dict[str, Any]]:
    actual_sha = sha256_path(path)
    if actual_sha != PINNED_POPULATION_SHA256:
        raise ValueError(f"population SHA256 mismatch expected={PINNED_POPULATION_SHA256} actual={actual_sha}")
    rows = load_jsonl(path)
    frozen = contract["source_population"]
    if len(rows) != int(frozen["row_count"]):
        raise ValueError("frozen population row count mismatch")
    ids = [str(row["observation_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate frozen population observation_id")
    asofs = sorted({parse_ts(row["asof_ts_utc"]) for row in rows})
    assets = {int(row["asset_id"]) for row in rows}
    if len(asofs) != int(frozen["unique_asofs"]) or len(assets) != int(frozen["unique_assets"]):
        raise ValueError("frozen population cardinality mismatch")
    if asofs[0] != parse_ts(frozen["first_asof_ts_utc"]) or asofs[-1] != parse_ts(frozen["last_asof_ts_utc"]):
        raise ValueError("frozen population as-of boundary mismatch")
    expected_splits = set(contract["split_contract"]["source_labels"])
    actual_splits = {str(row["split"]) for row in rows}
    if actual_splits != expected_splits:
        raise ValueError(f"frozen population split labels mismatch: {sorted(actual_splits)}")
    return rows


def load_outcomes(path: Path, contract: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    actual_sha = sha256_path(path)
    if actual_sha != PINNED_OUTCOMES_SHA256:
        raise ValueError(f"outcomes SHA256 mismatch expected={PINNED_OUTCOMES_SHA256} actual={actual_sha}")
    rows = load_jsonl(path)
    if len(rows) != int(contract["source_outcomes"]["row_count"]):
        raise ValueError("frozen outcomes row count mismatch")
    allowed_horizons = set(contract["source_outcomes"]["horizons"])
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["observation_id"]), str(row["horizon"]))
        if key in result:
            raise ValueError(f"duplicate frozen outcome identity: {key}")
        if key[1] not in allowed_horizons:
            raise ValueError(f"unknown frozen outcome horizon: {key[1]}")
        if str(row.get("population_sha256")) != PINNED_POPULATION_SHA256:
            raise ValueError("outcome row population SHA mismatch")
        result[key] = row
    return result


def validate_outcome_coverage(
    population: Iterable[dict[str, Any]],
    outcomes: dict[tuple[str, str], dict[str, Any]],
    horizons: Iterable[str],
) -> None:
    horizon_tuple = tuple(horizons)
    expected = {
        (str(row["observation_id"]), horizon)
        for row in population
        for horizon in horizon_tuple
    }
    actual = set(outcomes)
    if actual != expected:
        raise ValueError(
            "frozen outcome identity coverage mismatch "
            f"missing={len(expected - actual)} extra={len(actual - expected)}"
        )


def select_population_rows(
    rows: list[dict[str, Any]],
    *,
    asof_index: int | None,
    asset_id: int | None,
    limit_observations: int | None,
) -> list[dict[str, Any]]:
    selected = list(rows)
    if asof_index is not None:
        asofs = sorted({parse_ts(row["asof_ts_utc"]) for row in rows})
        if asof_index < 1 or asof_index > len(asofs):
            raise ValueError(f"asof_index must be within 1..{len(asofs)}")
        target = asofs[asof_index - 1]
        selected = [row for row in selected if parse_ts(row["asof_ts_utc"]) == target]
    if asset_id is not None:
        selected = [row for row in selected if int(row["asset_id"]) == asset_id]
    selected.sort(key=lambda row: (parse_ts(row["asof_ts_utc"]), int(row["asset_id"]), str(row["observation_id"])))
    if limit_observations is not None:
        if limit_observations < 1:
            raise ValueError("limit_observations must be >= 1")
        selected = selected[:limit_observations]
    if not selected:
        raise ValueError("bounded population selection is empty")
    return selected


def has_contiguous_final_history(
    candle_frame: pd.DataFrame,
    *,
    asof_ts_utc: datetime,
    required_history_bars: int,
) -> bool:
    if required_history_bars < 1 or len(candle_frame) < required_history_bars:
        return False
    timestamps = (
        pd.to_datetime(candle_frame["end_ts"], utc=True)
        .sort_values()
        .tail(required_history_bars)
        .reset_index(drop=True)
    )
    if timestamps.duplicated().any() or timestamps.iloc[-1] != pd.Timestamp(asof_ts_utc):
        return False
    if len(timestamps) == 1:
        return True
    return bool((timestamps.diff().dropna() == pd.Timedelta(hours=CANDLE_HOURS)).all())


def build_candidate_observation(
    observation: dict[str, Any],
    *,
    candle_frame: pd.DataFrame | None,
    market: str | None,
    contract: dict[str, Any],
) -> dict[str, Any]:
    asof = parse_ts(observation["asof_ts_utc"])
    candidates = tuple(contract["feature_contract"]["candidate_columns"])
    base = {
        "observation_id": str(observation["observation_id"]),
        "asset_id": int(observation["asset_id"]),
        "symbol": str(observation["symbol"]),
        "venue": str(observation["venue"]),
        "asof_ts_utc": asof,
        "split": str(observation["split"]).upper(),
        "market": market,
        "selection_score": observation.get("selection_score"),
        "trade_quality_score": observation.get("trade_quality_score"),
        "candidate_model_id": CANDIDATE_MODEL_ID,
        "candidate_model_version": CANDIDATE_MODEL_VERSION,
    }

    def unavailable(status: str) -> dict[str, Any]:
        return {**base, "candidate_status": status, **{name: None for name in candidates}}

    if market is None:
        return unavailable("UNAVAILABLE_MARKET_IDENTITY")
    if candle_frame is None or candle_frame.empty:
        return unavailable("INSUFFICIENT_CANDLE_HISTORY")

    required_history = int(contract["feature_contract"]["required_history_bars"])
    if len(candle_frame) < required_history:
        return unavailable("INSUFFICIENT_CANDLE_HISTORY")
    latest_end = max(pd.to_datetime(candle_frame["end_ts"], utc=True))
    if latest_end != pd.Timestamp(asof):
        return unavailable("MISSING_EXACT_ASOF_CANDLE")
    if not has_contiguous_final_history(
        candle_frame,
        asof_ts_utc=asof,
        required_history_bars=required_history,
    ):
        return unavailable("NONCONTIGUOUS_CANDLE_HISTORY")

    frame = build_candidate_frame(
        candle_frame,
        asof_ts_utc=asof,
        slope_bars=int(contract["feature_contract"]["slope_bars"]),
    )
    if frame.empty:
        return unavailable("INSUFFICIENT_CANDIDATE_FEATURES")
    row = frame.iloc[-1]
    values: dict[str, Any] = {}
    for name in candidates:
        value = row[name]
        if name == "bullish_ma_stack":
            values[name] = None if pd.isna(value) else int(bool(value))
        else:
            values[name] = None if pd.isna(value) else float(value)
    status = "AVAILABLE" if all(values[name] is not None for name in candidates) else "INSUFFICIENT_CANDIDATE_FEATURES"
    return {**base, "candidate_status": status, **values}


def attach_outcome(
    candidate_row: dict[str, Any],
    *,
    horizon: str,
    outcome_by_key: dict[tuple[str, str], dict[str, Any]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    outcome = outcome_by_key.get((candidate_row["observation_id"], horizon))
    outcome_value = None
    outcome_status = "MISSING_OUTCOME_ROW"
    if outcome is not None:
        if int(outcome["asset_id"]) != int(candidate_row["asset_id"]):
            raise ValueError("outcome asset identity mismatch")
        if str(outcome["venue"]) != str(candidate_row["venue"]):
            raise ValueError("outcome venue identity mismatch")
        if str(outcome["split"]).upper() != str(candidate_row["split"]):
            raise ValueError("outcome split identity mismatch")
        if parse_ts(outcome["observation_asof_ts_utc"]) != parse_ts(candidate_row["asof_ts_utc"]):
            raise ValueError("outcome as-of identity mismatch")
        outcome_status = str(outcome.get("status"))
        if outcome_status == str(contract["source_outcomes"]["required_status"]):
            raw = outcome.get(contract["source_outcomes"]["outcome_field"])
            outcome_value = None if raw is None else float(raw)
    return {
        **candidate_row,
        "horizon": horizon,
        "outcome_status": outcome_status,
        "forward_return_pct": outcome_value,
    }
