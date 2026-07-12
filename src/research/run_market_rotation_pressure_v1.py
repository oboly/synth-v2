from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median
from typing import Any, Iterable

from src.common.db import get_connection


RUNNER_NAME = "market_rotation_pressure_v1"
MODEL_VERSION = "1.0"
VENUE_DEFAULT = "bitvavo"
HORIZON_24H = 24
HORIZON_7D = 168
HORIZONS = (HORIZON_24H, HORIZON_7D)
HISTORY_SNAPSHOT_COUNT = 6
TOP_N = 5

PRESSURE_IN_THRESHOLD = 30.0
STRONG_PRESSURE_THRESHOLD = 60.0
MARKET_DIRECTION_THRESHOLD = 15.0
BREADTH_DIRECTION_GAP = 0.15

WEIGHTS = {
    "return_24h": 25.0,
    "signed_volume_24h": 20.0,
    "return_7d": 15.0,
    "signed_volume_7d": 10.0,
    "acceleration": 15.0,
    "market_relative": 10.0,
    "persistence": 5.0,
}

REQUIRED_SOURCE_TABLES = (
    "market_rotation_snapshot_v1",
    "market_rotation_observation_v1",
)
REQUIRED_TARGET_TABLES = (
    "market_rotation_pressure_snapshot_v1",
    "market_rotation_pressure_observation_v1",
)
REQUIRED_TABLES = REQUIRED_SOURCE_TABLES + REQUIRED_TARGET_TABLES


@dataclass(frozen=True)
class RotationPair:
    asset_id: int
    market: str
    source_snapshot_24h_id: int
    source_snapshot_7d_id: int
    return_24h_pct: float
    relative_volume_24h: float
    return_7d_pct: float
    relative_volume_7d: float


@dataclass(frozen=True)
class RawFactors:
    return_24h: float
    signed_volume_24h: float
    return_7d: float
    signed_volume_7d: float
    acceleration: float
    market_relative: float
    persistence: float


@dataclass(frozen=True)
class PressureObservation:
    asset_id: int
    market: str
    source_snapshot_24h_id: int
    source_snapshot_7d_id: int
    as_of_ts_utc: datetime
    raw_return_24h_pct: float
    raw_relative_volume_24h: float
    raw_return_7d_pct: float
    raw_relative_volume_7d: float
    raw_acceleration_pct: float
    raw_market_relative_pct: float
    score_return_24h: float
    score_signed_volume_24h: float
    score_return_7d: float
    score_signed_volume_7d: float
    score_acceleration: float
    score_market_relative: float
    score_persistence: float
    score_total: float
    pressure_state: str
    phase_state: str


@dataclass(frozen=True)
class MarketAggregate:
    market_direction: str
    market_score: float
    positive_count: int
    neutral_count: int
    negative_count: int
    positive_breadth_ratio: float
    negative_breadth_ratio: float
    acceleration_state: str
    concentration_state: str
    confirmation_state: str
    evidence_light_count: int


def _sign(value: float, *, epsilon: float = 1e-12) -> int:
    if value > epsilon:
        return 1
    if value < -epsilon:
        return -1
    return 0


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round4(value: float) -> float:
    return round(float(value), 4)


def _safe_float(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite numeric value: {value!r}")
    return result


def centered_percentile_scores(values: list[float]) -> list[float]:
    """Return deterministic tie-aware midrank scores in [-100, 100]."""
    if not values:
        return []
    if any(not math.isfinite(v) for v in values):
        raise ValueError("percentile input contains non-finite value")
    if len(values) == 1 or min(values) == max(values):
        return [0.0 for _ in values]

    indexed = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    output = [0.0 for _ in values]
    cursor = 0
    denominator = len(values) - 1
    while cursor < len(indexed):
        end = cursor
        tied_value = indexed[cursor][1]
        while end + 1 < len(indexed) and indexed[end + 1][1] == tied_value:
            end += 1
        midrank = (cursor + end) / 2.0
        score = (midrank / denominator) * 200.0 - 100.0
        for rank_pos in range(cursor, end + 1):
            original_index = indexed[rank_pos][0]
            output[original_index] = _round4(score)
        cursor = end + 1
    return output


def signed_volume_factor(return_pct: float, relative_volume: float) -> float:
    """Directional volume confirmation; sub-baseline volume adds no pressure."""
    if relative_volume <= 0 or not math.isfinite(relative_volume):
        raise ValueError("relative_volume must be finite and > 0")
    direction = _sign(return_pct)
    if direction == 0 or relative_volume <= 1.0:
        return 0.0
    capped = min(relative_volume, 4.0)
    return direction * math.log(capped)


def acceleration_factor(return_24h_pct: float, return_7d_pct: float) -> float:
    return return_24h_pct - (return_7d_pct / 7.0)


def raw_direction_pressure(return_24h_pct: float, return_7d_pct: float) -> float:
    return 0.70 * return_24h_pct + 0.30 * (return_7d_pct / 7.0)


def compute_persistence_score(
    return_24h_pct: float,
    return_7d_pct: float,
    history_pairs: Iterable[tuple[float, float]],
) -> float:
    current_direction = _sign(raw_direction_pressure(return_24h_pct, return_7d_pct))
    if current_direction == 0:
        return 0.0

    directional_matches: list[int] = []
    for historical_24h, historical_7d in history_pairs:
        historical_direction = _sign(raw_direction_pressure(historical_24h, historical_7d))
        if historical_direction == current_direction:
            directional_matches.append(1)
        elif historical_direction == -current_direction:
            directional_matches.append(-1)
        else:
            directional_matches.append(0)

    if not directional_matches:
        return 0.0
    return _round4(100.0 * sum(directional_matches) / len(directional_matches))


def classify_pressure_state(score_total: float) -> str:
    if score_total >= STRONG_PRESSURE_THRESHOLD:
        return "STRONG_ROTATION_IN"
    if score_total >= PRESSURE_IN_THRESHOLD:
        return "ROTATION_IN"
    if score_total <= -STRONG_PRESSURE_THRESHOLD:
        return "STRONG_ROTATION_OUT"
    if score_total <= -PRESSURE_IN_THRESHOLD:
        return "ROTATION_OUT"
    return "NEUTRAL_OR_MIXED"


def classify_phase_state(
    *,
    score_total: float,
    return_24h_pct: float,
    return_7d_pct: float,
    score_acceleration: float,
    score_signed_volume_24h: float,
    score_persistence: float,
) -> str:
    if score_total >= PRESSURE_IN_THRESHOLD:
        if return_24h_pct > 0 and return_7d_pct <= 0:
            return "EARLY_REVERSAL_IN"
        if score_acceleration >= 25:
            return "ACCELERATING_IN"
        if score_persistence >= 40:
            return "SUSTAINED_IN"
        return "ROTATION_IN"

    if score_total <= -PRESSURE_IN_THRESHOLD:
        if return_24h_pct < 0 and return_7d_pct >= 0:
            if score_signed_volume_24h <= -25:
                return "DISTRIBUTION_RISK"
            return "COOLING_IN_UPTREND"
        if score_acceleration <= -25:
            return "ACCELERATING_OUT"
        if score_persistence <= -40:
            return "SUSTAINED_OUT"
        return "ROTATION_OUT"

    if return_24h_pct < 0 < return_7d_pct:
        return "COOLING_IN_UPTREND"
    if return_24h_pct > 0 > return_7d_pct:
        return "BOUNCE_IN_DOWNTREND"
    return "MIXED"


def build_pressure_observations(
    pairs: list[RotationPair],
    history_by_asset: dict[int, list[tuple[float, float]]],
    as_of_ts_utc: datetime,
) -> list[PressureObservation]:
    if not pairs:
        return []

    median_24h = float(median(pair.return_24h_pct for pair in pairs))
    median_7d_daily = float(median(pair.return_7d_pct / 7.0 for pair in pairs))

    raw_by_asset: dict[int, RawFactors] = {}
    for pair in pairs:
        raw_by_asset[pair.asset_id] = RawFactors(
            return_24h=pair.return_24h_pct,
            signed_volume_24h=signed_volume_factor(pair.return_24h_pct, pair.relative_volume_24h),
            return_7d=pair.return_7d_pct,
            signed_volume_7d=signed_volume_factor(pair.return_7d_pct, pair.relative_volume_7d),
            acceleration=acceleration_factor(pair.return_24h_pct, pair.return_7d_pct),
            market_relative=(pair.return_24h_pct - median_24h)
            + 0.35 * ((pair.return_7d_pct / 7.0) - median_7d_daily),
            persistence=compute_persistence_score(
                pair.return_24h_pct,
                pair.return_7d_pct,
                history_by_asset.get(pair.asset_id, []),
            ),
        )

    factor_names = (
        "return_24h",
        "signed_volume_24h",
        "return_7d",
        "signed_volume_7d",
        "acceleration",
        "market_relative",
    )
    normalized: dict[str, dict[int, float]] = {}
    for factor_name in factor_names:
        raw_values = [getattr(raw_by_asset[pair.asset_id], factor_name) for pair in pairs]
        scores = centered_percentile_scores(raw_values)
        normalized[factor_name] = {
            pair.asset_id: scores[index]
            for index, pair in enumerate(pairs)
        }

    output: list[PressureObservation] = []
    for pair in pairs:
        raw = raw_by_asset[pair.asset_id]
        components = {
            "return_24h": normalized["return_24h"][pair.asset_id],
            "signed_volume_24h": normalized["signed_volume_24h"][pair.asset_id],
            "return_7d": normalized["return_7d"][pair.asset_id],
            "signed_volume_7d": normalized["signed_volume_7d"][pair.asset_id],
            "acceleration": normalized["acceleration"][pair.asset_id],
            "market_relative": normalized["market_relative"][pair.asset_id],
            "persistence": _clip(raw.persistence, -100.0, 100.0),
        }
        score_total = _round4(sum(components[name] * WEIGHTS[name] for name in WEIGHTS) / 100.0)
        pressure_state = classify_pressure_state(score_total)
        phase_state = classify_phase_state(
            score_total=score_total,
            return_24h_pct=pair.return_24h_pct,
            return_7d_pct=pair.return_7d_pct,
            score_acceleration=components["acceleration"],
            score_signed_volume_24h=components["signed_volume_24h"],
            score_persistence=components["persistence"],
        )
        output.append(PressureObservation(
            asset_id=pair.asset_id,
            market=pair.market,
            source_snapshot_24h_id=pair.source_snapshot_24h_id,
            source_snapshot_7d_id=pair.source_snapshot_7d_id,
            as_of_ts_utc=as_of_ts_utc,
            raw_return_24h_pct=_round4(pair.return_24h_pct),
            raw_relative_volume_24h=_round4(pair.relative_volume_24h),
            raw_return_7d_pct=_round4(pair.return_7d_pct),
            raw_relative_volume_7d=_round4(pair.relative_volume_7d),
            raw_acceleration_pct=_round4(raw.acceleration),
            raw_market_relative_pct=_round4(raw.market_relative),
            score_return_24h=_round4(components["return_24h"]),
            score_signed_volume_24h=_round4(components["signed_volume_24h"]),
            score_return_7d=_round4(components["return_7d"]),
            score_signed_volume_7d=_round4(components["signed_volume_7d"]),
            score_acceleration=_round4(components["acceleration"]),
            score_market_relative=_round4(components["market_relative"]),
            score_persistence=_round4(components["persistence"]),
            score_total=score_total,
            pressure_state=pressure_state,
            phase_state=phase_state,
        ))
    return output


def _direction_from_market_state(
    market_score: float,
    positive_breadth: float,
    negative_breadth: float,
) -> str:
    if market_score >= MARKET_DIRECTION_THRESHOLD and positive_breadth > negative_breadth:
        return "ROTATION_IN"
    if market_score <= -MARKET_DIRECTION_THRESHOLD and negative_breadth > positive_breadth:
        return "ROTATION_OUT"
    breadth_gap = positive_breadth - negative_breadth
    if breadth_gap >= BREADTH_DIRECTION_GAP:
        return "ROTATION_IN"
    if breadth_gap <= -BREADTH_DIRECTION_GAP:
        return "ROTATION_OUT"
    return "MIXED"


def _concentration_state(observations: list[PressureObservation], direction: str) -> str:
    if direction == "MIXED":
        return "MIXED"
    sign = 1 if direction == "ROTATION_IN" else -1
    directional_scores = sorted(
        (abs(obs.score_total) for obs in observations if _sign(obs.score_total) == sign),
        reverse=True,
    )
    total = sum(directional_scores)
    if total <= 0:
        return "UNKNOWN"
    top_share = sum(directional_scores[:TOP_N]) / total
    if top_share <= 0.45:
        return "BROAD"
    if top_share <= 0.65:
        return "SELECTIVE"
    return "CONCENTRATED"


def _confirmation_state(observations: list[PressureObservation], direction: str) -> str:
    if direction == "MIXED" or not observations:
        return "MIXED"
    sign = 1 if direction == "ROTATION_IN" else -1
    median_24 = float(median(obs.score_return_24h for obs in observations))
    median_7d = float(median(obs.score_return_7d for obs in observations))
    confirms = int(_sign(median_24) == sign) + int(_sign(median_7d) == sign)
    if confirms == 2:
        return "CONFIRMED"
    if confirms == 1:
        return "PARTIAL"
    return "CONFLICTING"


def _acceleration_state(market_score: float, prior_market_score: float | None) -> str:
    if prior_market_score is None:
        return "UNKNOWN"
    delta = market_score - prior_market_score
    if delta >= 5.0:
        return "ACCELERATING_IN"
    if delta <= -5.0:
        return "ACCELERATING_OUT"
    return "STABLE"


def build_market_aggregate(
    observations: list[PressureObservation],
    prior_market_score: float | None,
) -> MarketAggregate:
    if not observations:
        return MarketAggregate(
            market_direction="MIXED",
            market_score=0.0,
            positive_count=0,
            neutral_count=0,
            negative_count=0,
            positive_breadth_ratio=0.0,
            negative_breadth_ratio=0.0,
            acceleration_state="UNKNOWN",
            concentration_state="UNKNOWN",
            confirmation_state="MIXED",
            evidence_light_count=0,
        )

    total_count = len(observations)
    positive_count = sum(obs.score_total >= PRESSURE_IN_THRESHOLD for obs in observations)
    negative_count = sum(obs.score_total <= -PRESSURE_IN_THRESHOLD for obs in observations)
    neutral_count = total_count - positive_count - negative_count
    positive_breadth = positive_count / total_count
    negative_breadth = negative_count / total_count
    market_score = _round4(float(median(obs.score_total for obs in observations)))
    direction = _direction_from_market_state(market_score, positive_breadth, negative_breadth)
    concentration = _concentration_state(observations, direction)
    confirmation = _confirmation_state(observations, direction)
    acceleration = _acceleration_state(market_score, prior_market_score)

    lights = 0
    if direction != "MIXED":
        sign = 1 if direction == "ROTATION_IN" else -1
        dominant_breadth = positive_breadth if sign == 1 else negative_breadth
        opposite_breadth = negative_breadth if sign == 1 else positive_breadth
        median_persistence = float(median(obs.score_persistence for obs in observations))
        lights += int(abs(market_score) >= MARKET_DIRECTION_THRESHOLD)
        lights += int(dominant_breadth >= 0.30 and dominant_breadth > opposite_breadth)
        lights += int(confirmation == "CONFIRMED")
        lights += int(
            (sign == 1 and acceleration == "ACCELERATING_IN")
            or (sign == -1 and acceleration == "ACCELERATING_OUT")
            or _sign(median_persistence) == sign and abs(median_persistence) >= 20
        )
        lights += int(concentration in {"BROAD", "SELECTIVE"})

    return MarketAggregate(
        market_direction=direction,
        market_score=market_score,
        positive_count=positive_count,
        neutral_count=neutral_count,
        negative_count=negative_count,
        positive_breadth_ratio=_round4(positive_breadth),
        negative_breadth_ratio=_round4(negative_breadth),
        acceleration_state=acceleration,
        concentration_state=concentration,
        confirmation_state=confirmation,
        evidence_light_count=lights,
    )


def check_schema_ready(conn: Any) -> list[str]:
    placeholders = ", ".join(["%s"] * len(REQUIRED_TABLES))
    sql = (
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        f"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ({placeholders})"
    )
    with conn.cursor() as cur:
        cur.execute(sql, list(REQUIRED_TABLES))
        found = {row["TABLE_NAME"] for row in cur.fetchall()}
    return [table for table in REQUIRED_TABLES if table not in found]


def resolve_latest_common_as_of(conn: Any, venue: str) -> datetime | None:
    sql = """
    SELECT as_of_ts_utc
    FROM market_rotation_snapshot_v1
    WHERE venue = %s AND horizon_h IN (24, 168)
    GROUP BY as_of_ts_utc
    HAVING COUNT(DISTINCT horizon_h) = 2
    ORDER BY as_of_ts_utc DESC
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue,))
        row = cur.fetchone()
    return row["as_of_ts_utc"] if row else None


def resolve_as_of_arg(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed.replace(minute=0, second=0, microsecond=0)


def fetch_rotation_pairs(
    conn: Any,
    venue: str,
    as_of_ts_utc: datetime,
) -> tuple[list[RotationPair], int]:
    sql = """
    SELECT
      o.asset_id,
      MAX(o.market) AS market,
      MAX(CASE WHEN o.horizon_h = 24 THEN o.snapshot_id END) AS snapshot_24h_id,
      MAX(CASE WHEN o.horizon_h = 168 THEN o.snapshot_id END) AS snapshot_7d_id,
      MAX(CASE WHEN o.horizon_h = 24 THEN o.price_change_pct END) AS return_24h_pct,
      MAX(CASE WHEN o.horizon_h = 24 THEN o.relative_volume END) AS relative_volume_24h,
      MAX(CASE WHEN o.horizon_h = 168 THEN o.price_change_pct END) AS return_7d_pct,
      MAX(CASE WHEN o.horizon_h = 168 THEN o.relative_volume END) AS relative_volume_7d,
      COUNT(DISTINCT o.horizon_h) AS horizon_count
    FROM market_rotation_observation_v1 o
    JOIN market_rotation_snapshot_v1 s ON s.snapshot_id = o.snapshot_id
    WHERE s.venue = %s
      AND s.as_of_ts_utc = %s
      AND o.horizon_h IN (24, 168)
    GROUP BY o.asset_id
    ORDER BY o.asset_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, as_of_ts_utc))
        rows = cur.fetchall()

    pairs: list[RotationPair] = []
    for row in rows:
        if int(row["horizon_count"]) != 2:
            continue
        pairs.append(RotationPair(
            asset_id=int(row["asset_id"]),
            market=str(row["market"]),
            source_snapshot_24h_id=int(row["snapshot_24h_id"]),
            source_snapshot_7d_id=int(row["snapshot_7d_id"]),
            return_24h_pct=_safe_float(row["return_24h_pct"]),
            relative_volume_24h=_safe_float(row["relative_volume_24h"]),
            return_7d_pct=_safe_float(row["return_7d_pct"]),
            relative_volume_7d=_safe_float(row["relative_volume_7d"]),
        ))
    excluded_missing_pair_count = len(rows) - len(pairs)
    return pairs, excluded_missing_pair_count


def fetch_history_by_asset(
    conn: Any,
    venue: str,
    before_as_of_ts_utc: datetime,
    snapshot_count: int = HISTORY_SNAPSHOT_COUNT,
) -> dict[int, list[tuple[float, float]]]:
    timestamp_sql = """
    SELECT as_of_ts_utc
    FROM market_rotation_snapshot_v1
    WHERE venue = %s
      AND horizon_h IN (24, 168)
      AND as_of_ts_utc < %s
    GROUP BY as_of_ts_utc
    HAVING COUNT(DISTINCT horizon_h) = 2
    ORDER BY as_of_ts_utc DESC
    LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(timestamp_sql, (venue, before_as_of_ts_utc, snapshot_count))
        timestamp_rows = cur.fetchall()
    timestamps = [row["as_of_ts_utc"] for row in timestamp_rows]
    if not timestamps:
        return {}

    placeholders = ", ".join(["%s"] * len(timestamps))
    history_sql = f"""
    SELECT
      o.as_of_ts_utc,
      o.asset_id,
      MAX(CASE WHEN o.horizon_h = 24 THEN o.price_change_pct END) AS return_24h_pct,
      MAX(CASE WHEN o.horizon_h = 168 THEN o.price_change_pct END) AS return_7d_pct,
      COUNT(DISTINCT o.horizon_h) AS horizon_count
    FROM market_rotation_observation_v1 o
    JOIN market_rotation_snapshot_v1 s ON s.snapshot_id = o.snapshot_id
    WHERE s.venue = %s
      AND o.as_of_ts_utc IN ({placeholders})
      AND o.horizon_h IN (24, 168)
    GROUP BY o.as_of_ts_utc, o.asset_id
    HAVING COUNT(DISTINCT o.horizon_h) = 2
    ORDER BY o.asset_id, o.as_of_ts_utc DESC
    """
    params: list[Any] = [venue] + timestamps
    with conn.cursor() as cur:
        cur.execute(history_sql, params)
        rows = cur.fetchall()

    history: dict[int, list[tuple[float, float]]] = {}
    for row in rows:
        history.setdefault(int(row["asset_id"]), []).append((
            _safe_float(row["return_24h_pct"]),
            _safe_float(row["return_7d_pct"]),
        ))
    return history


def fetch_prior_market_score(conn: Any, venue: str, before_as_of_ts_utc: datetime) -> float | None:
    sql = """
    SELECT market_score
    FROM market_rotation_pressure_snapshot_v1
    WHERE venue = %s
      AND model_version = %s
      AND as_of_ts_utc < %s
    ORDER BY as_of_ts_utc DESC
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, MODEL_VERSION, before_as_of_ts_utc))
        row = cur.fetchone()
    return _safe_float(row["market_score"]) if row else None


def write_pressure_snapshot(
    conn: Any,
    *,
    as_of_ts_utc: datetime,
    venue: str,
    excluded_missing_pair_count: int,
    aggregate: MarketAggregate,
    observations: list[PressureObservation],
) -> tuple[str, int]:
    insert_header = """
    INSERT IGNORE INTO market_rotation_pressure_snapshot_v1 (
      as_of_ts_utc, venue, model_version,
      eligible_asset_count, excluded_missing_pair_count,
      positive_count, neutral_count, negative_count,
      market_score, positive_breadth_ratio, negative_breadth_ratio,
      acceleration_state, concentration_state, confirmation_state,
      market_direction, evidence_light_count
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        created = int(cur.execute(insert_header, (
            as_of_ts_utc, venue, MODEL_VERSION,
            len(observations), excluded_missing_pair_count,
            aggregate.positive_count, aggregate.neutral_count, aggregate.negative_count,
            aggregate.market_score, aggregate.positive_breadth_ratio, aggregate.negative_breadth_ratio,
            aggregate.acceleration_state, aggregate.concentration_state, aggregate.confirmation_state,
            aggregate.market_direction, aggregate.evidence_light_count,
        ))) > 0

    with conn.cursor() as cur:
        cur.execute(
            "SELECT pressure_snapshot_id FROM market_rotation_pressure_snapshot_v1 "
            "WHERE as_of_ts_utc = %s AND venue = %s AND model_version = %s FOR UPDATE",
            (as_of_ts_utc, venue, MODEL_VERSION),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("pressure snapshot header missing after INSERT IGNORE")
    pressure_snapshot_id = int(row["pressure_snapshot_id"])

    insert_observation = """
    INSERT IGNORE INTO market_rotation_pressure_observation_v1 (
      pressure_snapshot_id, asset_id, market,
      source_snapshot_24h_id, source_snapshot_7d_id,
      as_of_ts_utc, model_version,
      raw_return_24h_pct, raw_relative_volume_24h,
      raw_return_7d_pct, raw_relative_volume_7d,
      raw_acceleration_pct, raw_market_relative_pct,
      score_return_24h, score_signed_volume_24h,
      score_return_7d, score_signed_volume_7d,
      score_acceleration, score_market_relative, score_persistence,
      score_total, pressure_state, phase_state
    ) VALUES (
      %s, %s, %s, %s, %s, %s, %s,
      %s, %s, %s, %s, %s, %s,
      %s, %s, %s, %s, %s, %s, %s,
      %s, %s, %s
    )
    """
    observations_written = 0
    with conn.cursor() as cur:
        for obs in observations:
            observations_written += int(cur.execute(insert_observation, (
                pressure_snapshot_id, obs.asset_id, obs.market,
                obs.source_snapshot_24h_id, obs.source_snapshot_7d_id,
                obs.as_of_ts_utc, MODEL_VERSION,
                obs.raw_return_24h_pct, obs.raw_relative_volume_24h,
                obs.raw_return_7d_pct, obs.raw_relative_volume_7d,
                obs.raw_acceleration_pct, obs.raw_market_relative_pct,
                obs.score_return_24h, obs.score_signed_volume_24h,
                obs.score_return_7d, obs.score_signed_volume_7d,
                obs.score_acceleration, obs.score_market_relative, obs.score_persistence,
                obs.score_total, obs.pressure_state, obs.phase_state,
            )))

    update_header = """
    UPDATE market_rotation_pressure_snapshot_v1
    SET eligible_asset_count = %s,
        excluded_missing_pair_count = %s,
        positive_count = %s,
        neutral_count = %s,
        negative_count = %s,
        market_score = %s,
        positive_breadth_ratio = %s,
        negative_breadth_ratio = %s,
        acceleration_state = %s,
        concentration_state = %s,
        confirmation_state = %s,
        market_direction = %s,
        evidence_light_count = %s
    WHERE pressure_snapshot_id = %s
      AND (
        eligible_asset_count <> %s OR excluded_missing_pair_count <> %s OR
        positive_count <> %s OR neutral_count <> %s OR negative_count <> %s OR
        market_score <> %s OR positive_breadth_ratio <> %s OR negative_breadth_ratio <> %s OR
        acceleration_state <> %s OR concentration_state <> %s OR confirmation_state <> %s OR
        market_direction <> %s OR evidence_light_count <> %s
      )
    """
    update_values = (
        len(observations), excluded_missing_pair_count,
        aggregate.positive_count, aggregate.neutral_count, aggregate.negative_count,
        aggregate.market_score, aggregate.positive_breadth_ratio, aggregate.negative_breadth_ratio,
        aggregate.acceleration_state, aggregate.concentration_state, aggregate.confirmation_state,
        aggregate.market_direction, aggregate.evidence_light_count,
    )
    with conn.cursor() as cur:
        header_changed = int(cur.execute(
            update_header,
            update_values + (pressure_snapshot_id,) + update_values,
        )) > 0

    if created:
        return "CREATED", observations_written
    if observations_written > 0 or header_changed:
        return "RECONCILED", observations_written
    return "NOOP_ALREADY_COMPLETE", 0


def print_report(
    *,
    as_of_ts_utc: datetime,
    venue: str,
    aggregate: MarketAggregate,
    observations: list[PressureObservation],
    excluded_missing_pair_count: int,
    write_status: str,
) -> None:
    print(
        f"MARKET ROTATION  as_of={as_of_ts_utc.isoformat()}Z  venue={venue}  "
        f"direction={aggregate.market_direction}  score={aggregate.market_score:+.2f}  "
        f"lights={aggregate.evidence_light_count}/5"
    )
    print(
        f"BREADTH  in={aggregate.positive_breadth_ratio:.1%}  "
        f"out={aggregate.negative_breadth_ratio:.1%}  neutral={aggregate.neutral_count}/{len(observations)}  "
        f"eligible={len(observations)}  missing_pair={excluded_missing_pair_count}"
    )
    print(
        f"CONTEXT  acceleration={aggregate.acceleration_state}  "
        f"confirmation={aggregate.confirmation_state}  concentration={aggregate.concentration_state}  "
        f"status={write_status}"
    )

    top_in = sorted(observations, key=lambda obs: (-obs.score_total, obs.market))[:TOP_N]
    top_out = sorted(observations, key=lambda obs: (obs.score_total, obs.market))[:TOP_N]
    print("TOP ROTATION IN")
    for obs in top_in:
        print(
            f"  {obs.market:<14} {obs.score_total:+7.2f}  {obs.phase_state:<24} "
            f"24h={obs.raw_return_24h_pct:+7.2f}%  7d={obs.raw_return_7d_pct:+7.2f}%  "
            f"rv24={obs.raw_relative_volume_24h:.2f}x"
        )
    print("TOP ROTATION OUT")
    for obs in top_out:
        print(
            f"  {obs.market:<14} {obs.score_total:+7.2f}  {obs.phase_state:<24} "
            f"24h={obs.raw_return_24h_pct:+7.2f}%  7d={obs.raw_return_7d_pct:+7.2f}%  "
            f"rv24={obs.raw_relative_volume_24h:.2f}x"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Synth-native market rotation pressure scoring. "
            "Research-only, market-only, account-agnostic."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--write-db", action="store_true")
    parser.add_argument("--venue", default=VENUE_DEFAULT)
    parser.add_argument("--as-of-ts", dest="as_of_ts", default=None)
    return parser.parse_args(argv)


def print_validation_contract(args: argparse.Namespace) -> None:
    as_of = resolve_as_of_arg(args.as_of_ts)
    print(f"RUNNER {RUNNER_NAME} model={MODEL_VERSION} mode=validate-only")
    print(f"venue={args.venue} as_of={'latest common 24h/7d snapshot' if as_of is None else as_of.isoformat() + 'Z'}")
    print("source=market_rotation_snapshot_v1 + market_rotation_observation_v1")
    print(f"weights={WEIGHTS}")
    print("score_range=-100..100 thresholds=+/-30 strong=+/-60")
    print("broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    print("selection_engine=none decision_gate=none execution_planner=none executor=none")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.validate_only:
        print_validation_contract(args)
        return 0

    conn = get_connection()
    try:
        missing_tables = check_schema_ready(conn)
        missing_source = [table for table in missing_tables if table in REQUIRED_SOURCE_TABLES]
        missing_target = [table for table in missing_tables if table in REQUIRED_TARGET_TABLES]
        if missing_source:
            print(f"FAILED SOURCE_SCHEMA_MISSING missing={missing_source}")
            return 1
        if args.write_db and missing_target:
            print(f"FAILED TARGET_SCHEMA_MISSING missing={missing_target}")
            return 1

        requested_as_of = resolve_as_of_arg(args.as_of_ts)
        as_of_ts_utc = requested_as_of or resolve_latest_common_as_of(conn, args.venue)
        if as_of_ts_utc is None:
            print("FAILED NO_COMMON_24H_7D_SOURCE_SNAPSHOT")
            return 1

        pairs, excluded_missing_pair_count = fetch_rotation_pairs(conn, args.venue, as_of_ts_utc)
        if not pairs:
            print(f"FAILED NO_COMPLETE_ASSET_PAIRS as_of={as_of_ts_utc.isoformat()}Z")
            return 1

        history_by_asset = fetch_history_by_asset(conn, args.venue, as_of_ts_utc)
        observations = build_pressure_observations(pairs, history_by_asset, as_of_ts_utc)
        prior_market_score = None
        if not missing_target:
            prior_market_score = fetch_prior_market_score(conn, args.venue, as_of_ts_utc)
        aggregate = build_market_aggregate(observations, prior_market_score)

        if args.dry_run:
            write_status = "DRY_RUN"
        else:
            try:
                write_status, observations_written = write_pressure_snapshot(
                    conn,
                    as_of_ts_utc=as_of_ts_utc,
                    venue=args.venue,
                    excluded_missing_pair_count=excluded_missing_pair_count,
                    aggregate=aggregate,
                    observations=observations,
                )
                conn.commit()
                write_status = f"{write_status} observations_written={observations_written}"
            except Exception:
                conn.rollback()
                raise

        print_report(
            as_of_ts_utc=as_of_ts_utc,
            venue=args.venue,
            aggregate=aggregate,
            observations=observations,
            excluded_missing_pair_count=excluded_missing_pair_count,
            write_status=write_status,
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
