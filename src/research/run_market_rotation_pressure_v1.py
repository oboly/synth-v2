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
ROBUST_SCALE_FLOORS = {
    "return_24h": 1.0,
    "signed_volume_24h": 0.15,
    "return_7d": 3.0,
    "signed_volume_7d": 0.15,
    "acceleration": 1.0,
}
SOURCE_TABLES = ("market_rotation_snapshot_v1", "market_rotation_observation_v1")
TARGET_TABLES = ("market_rotation_pressure_snapshot_v1", "market_rotation_pressure_observation_v1")
REQUIRED_TABLES = SOURCE_TABLES + TARGET_TABLES


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


def _sign(value: float, epsilon: float = 1e-12) -> int:
    return 1 if value > epsilon else (-1 if value < -epsilon else 0)


def _round4(value: float) -> float:
    return round(float(value), 4)


def _safe_float(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite numeric value: {value!r}")
    return result


def centered_percentile_scores(values: list[float]) -> list[float]:
    if not values:
        return []
    if any(not math.isfinite(value) for value in values):
        raise ValueError("percentile input contains non-finite value")
    if len(values) == 1 or min(values) == max(values):
        return [0.0] * len(values)
    ranked = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    result = [0.0] * len(values)
    start = 0
    denominator = len(values) - 1
    while start < len(ranked):
        end = start
        while end + 1 < len(ranked) and ranked[end + 1][1] == ranked[start][1]:
            end += 1
        score = (((start + end) / 2.0) / denominator) * 200.0 - 100.0
        for index in range(start, end + 1):
            result[ranked[index][0]] = _round4(score)
        start = end + 1
    return result


def zero_centered_robust_scores(values: list[float], *, floor_scale: float) -> list[float]:
    if not values:
        return []
    if floor_scale <= 0 or not math.isfinite(floor_scale):
        raise ValueError("floor_scale must be finite and > 0")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("robust-score input contains non-finite value")
    scale = max(float(median(abs(value) for value in values)), floor_scale)
    return [_round4(100.0 * math.tanh(value / scale)) for value in values]


def signed_volume_factor(return_pct: float, relative_volume: float) -> float:
    if relative_volume <= 0 or not math.isfinite(relative_volume):
        raise ValueError("relative_volume must be finite and > 0")
    if _sign(return_pct) == 0 or relative_volume <= 1.0:
        return 0.0
    return _sign(return_pct) * math.log(min(relative_volume, 4.0))


def acceleration_factor(return_24h_pct: float, return_7d_pct: float) -> float:
    return return_24h_pct - return_7d_pct / 7.0


def raw_direction_pressure(return_24h_pct: float, return_7d_pct: float) -> float:
    return 0.70 * return_24h_pct + 0.30 * (return_7d_pct / 7.0)


def compute_persistence_score(
    return_24h_pct: float,
    return_7d_pct: float,
    history_pairs: Iterable[tuple[float, float]],
) -> float:
    direction = _sign(raw_direction_pressure(return_24h_pct, return_7d_pct))
    if direction == 0:
        return 0.0
    votes = []
    for historical_24h, historical_7d in history_pairs:
        historical_direction = _sign(raw_direction_pressure(historical_24h, historical_7d))
        votes.append(1 if historical_direction == direction else (-1 if historical_direction == -direction else 0))
    return 0.0 if not votes else _round4(100.0 * sum(votes) / len(votes))


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
    *, score_total: float, return_24h_pct: float, return_7d_pct: float,
    score_acceleration: float, score_signed_volume_24h: float, score_persistence: float,
) -> str:
    if score_total >= PRESSURE_IN_THRESHOLD:
        if return_24h_pct > 0 >= return_7d_pct:
            return "EARLY_REVERSAL_IN"
        if score_acceleration >= 25:
            return "ACCELERATING_IN"
        if score_persistence >= 40:
            return "SUSTAINED_IN"
        return "ROTATION_IN"
    if score_total <= -PRESSURE_IN_THRESHOLD:
        if return_24h_pct < 0 <= return_7d_pct:
            return "DISTRIBUTION_RISK" if score_signed_volume_24h <= -25 else "COOLING_IN_UPTREND"
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
    pairs: list[RotationPair], history_by_asset: dict[int, list[tuple[float, float]]], as_of_ts_utc: datetime,
) -> list[PressureObservation]:
    if not pairs:
        return []
    median_24h = float(median(pair.return_24h_pct for pair in pairs))
    median_7d_daily = float(median(pair.return_7d_pct / 7.0 for pair in pairs))
    raw: dict[int, dict[str, float]] = {}
    for pair in pairs:
        raw[pair.asset_id] = {
            "return_24h": pair.return_24h_pct,
            "signed_volume_24h": signed_volume_factor(pair.return_24h_pct, pair.relative_volume_24h),
            "return_7d": pair.return_7d_pct,
            "signed_volume_7d": signed_volume_factor(pair.return_7d_pct, pair.relative_volume_7d),
            "acceleration": acceleration_factor(pair.return_24h_pct, pair.return_7d_pct),
            "market_relative": (pair.return_24h_pct - median_24h)
            + 0.35 * ((pair.return_7d_pct / 7.0) - median_7d_daily),
            "persistence": compute_persistence_score(
                pair.return_24h_pct, pair.return_7d_pct, history_by_asset.get(pair.asset_id, [])
            ),
        }
    normalized: dict[str, dict[int, float]] = {}
    for factor in ("return_24h", "signed_volume_24h", "return_7d", "signed_volume_7d", "acceleration", "market_relative"):
        values = [raw[pair.asset_id][factor] for pair in pairs]
        scores = centered_percentile_scores(values) if factor == "market_relative" else zero_centered_robust_scores(
            values, floor_scale=ROBUST_SCALE_FLOORS[factor]
        )
        normalized[factor] = {pair.asset_id: scores[index] for index, pair in enumerate(pairs)}

    observations = []
    for pair in pairs:
        asset_raw = raw[pair.asset_id]
        components = {factor: normalized[factor][pair.asset_id] for factor in normalized}
        components["persistence"] = max(-100.0, min(100.0, asset_raw["persistence"]))
        total = _round4(sum(components[name] * WEIGHTS[name] for name in WEIGHTS) / 100.0)
        observations.append(PressureObservation(
            asset_id=pair.asset_id,
            market=pair.market,
            source_snapshot_24h_id=pair.source_snapshot_24h_id,
            source_snapshot_7d_id=pair.source_snapshot_7d_id,
            as_of_ts_utc=as_of_ts_utc,
            raw_return_24h_pct=_round4(pair.return_24h_pct),
            raw_relative_volume_24h=_round4(pair.relative_volume_24h),
            raw_return_7d_pct=_round4(pair.return_7d_pct),
            raw_relative_volume_7d=_round4(pair.relative_volume_7d),
            raw_acceleration_pct=_round4(asset_raw["acceleration"]),
            raw_market_relative_pct=_round4(asset_raw["market_relative"]),
            score_return_24h=_round4(components["return_24h"]),
            score_signed_volume_24h=_round4(components["signed_volume_24h"]),
            score_return_7d=_round4(components["return_7d"]),
            score_signed_volume_7d=_round4(components["signed_volume_7d"]),
            score_acceleration=_round4(components["acceleration"]),
            score_market_relative=_round4(components["market_relative"]),
            score_persistence=_round4(components["persistence"]),
            score_total=total,
            pressure_state=classify_pressure_state(total),
            phase_state=classify_phase_state(
                score_total=total,
                return_24h_pct=pair.return_24h_pct,
                return_7d_pct=pair.return_7d_pct,
                score_acceleration=components["acceleration"],
                score_signed_volume_24h=components["signed_volume_24h"],
                score_persistence=components["persistence"],
            ),
        ))
    return observations


def _direction(market_score: float, positive_breadth: float, negative_breadth: float) -> str:
    if market_score >= MARKET_DIRECTION_THRESHOLD and positive_breadth > negative_breadth:
        return "ROTATION_IN"
    if market_score <= -MARKET_DIRECTION_THRESHOLD and negative_breadth > positive_breadth:
        return "ROTATION_OUT"
    gap = positive_breadth - negative_breadth
    return "ROTATION_IN" if gap >= BREADTH_DIRECTION_GAP else ("ROTATION_OUT" if gap <= -BREADTH_DIRECTION_GAP else "MIXED")


def _concentration(observations: list[PressureObservation], direction: str) -> str:
    if direction == "MIXED":
        return "MIXED"
    sign = 1 if direction == "ROTATION_IN" else -1
    scores = sorted((abs(obs.score_total) for obs in observations if _sign(obs.score_total) == sign), reverse=True)
    if not scores or sum(scores) <= 0:
        return "UNKNOWN"
    share = sum(scores[:TOP_N]) / sum(scores)
    return "BROAD" if share <= 0.45 else ("SELECTIVE" if share <= 0.65 else "CONCENTRATED")


def _confirmation(observations: list[PressureObservation], direction: str) -> str:
    if direction == "MIXED" or not observations:
        return "MIXED"
    sign = 1 if direction == "ROTATION_IN" else -1
    confirms = sum(_sign(float(median(getattr(obs, field) for obs in observations))) == sign for field in ("score_return_24h", "score_return_7d"))
    return "CONFIRMED" if confirms == 2 else ("PARTIAL" if confirms == 1 else "CONFLICTING")


def build_market_aggregate(observations: list[PressureObservation], prior_market_score: float | None) -> MarketAggregate:
    if not observations:
        return MarketAggregate("MIXED", 0.0, 0, 0, 0, 0.0, 0.0, "UNKNOWN", "UNKNOWN", "MIXED", 0)
    total_count = len(observations)
    positive = sum(obs.score_total >= PRESSURE_IN_THRESHOLD for obs in observations)
    negative = sum(obs.score_total <= -PRESSURE_IN_THRESHOLD for obs in observations)
    neutral = total_count - positive - negative
    positive_breadth = positive / total_count
    negative_breadth = negative / total_count
    market_score = _round4(float(median(obs.score_total for obs in observations)))
    direction = _direction(market_score, positive_breadth, negative_breadth)
    concentration = _concentration(observations, direction)
    confirmation = _confirmation(observations, direction)
    if prior_market_score is None:
        acceleration = "UNKNOWN"
    elif market_score - prior_market_score >= 5:
        acceleration = "ACCELERATING_IN"
    elif market_score - prior_market_score <= -5:
        acceleration = "ACCELERATING_OUT"
    else:
        acceleration = "STABLE"
    lights = 0
    if direction != "MIXED":
        sign = 1 if direction == "ROTATION_IN" else -1
        dominant = positive_breadth if sign == 1 else negative_breadth
        opposite = negative_breadth if sign == 1 else positive_breadth
        persistence = float(median(obs.score_persistence for obs in observations))
        lights = sum((
            abs(market_score) >= MARKET_DIRECTION_THRESHOLD,
            dominant >= 0.30 and dominant > opposite,
            confirmation == "CONFIRMED",
            (sign == 1 and acceleration == "ACCELERATING_IN")
            or (sign == -1 and acceleration == "ACCELERATING_OUT")
            or (_sign(persistence) == sign and abs(persistence) >= 20),
            concentration in {"BROAD", "SELECTIVE"},
        ))
    return MarketAggregate(
        direction, market_score, positive, neutral, negative,
        _round4(positive_breadth), _round4(negative_breadth),
        acceleration, concentration, confirmation, int(lights),
    )


def check_schema_ready(conn: Any) -> list[str]:
    placeholders = ", ".join(["%s"] * len(REQUIRED_TABLES))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            f"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ({placeholders})",
            list(REQUIRED_TABLES),
        )
        found = {row["TABLE_NAME"] for row in cur.fetchall()}
    return [table for table in REQUIRED_TABLES if table not in found]


def resolve_as_of_arg(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed.replace(minute=0, second=0, microsecond=0)


def resolve_latest_common_as_of(conn: Any, venue: str) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT as_of_ts_utc FROM market_rotation_snapshot_v1 "
            "WHERE venue=%s AND horizon_h IN (24,168) GROUP BY as_of_ts_utc "
            "HAVING COUNT(DISTINCT horizon_h)=2 ORDER BY as_of_ts_utc DESC LIMIT 1",
            (venue,),
        )
        row = cur.fetchone()
    return row["as_of_ts_utc"] if row else None


def fetch_rotation_pairs(conn: Any, venue: str, as_of_ts_utc: datetime) -> tuple[list[RotationPair], int]:
    sql = """
    SELECT o.asset_id, MAX(o.market) market,
      MAX(CASE WHEN o.horizon_h=24 THEN o.snapshot_id END) snapshot_24h_id,
      MAX(CASE WHEN o.horizon_h=168 THEN o.snapshot_id END) snapshot_7d_id,
      MAX(CASE WHEN o.horizon_h=24 THEN o.price_change_pct END) return_24h_pct,
      MAX(CASE WHEN o.horizon_h=24 THEN o.relative_volume END) relative_volume_24h,
      MAX(CASE WHEN o.horizon_h=168 THEN o.price_change_pct END) return_7d_pct,
      MAX(CASE WHEN o.horizon_h=168 THEN o.relative_volume END) relative_volume_7d,
      COUNT(DISTINCT o.horizon_h) horizon_count
    FROM market_rotation_observation_v1 o
    JOIN market_rotation_snapshot_v1 s ON s.snapshot_id=o.snapshot_id
    WHERE s.venue=%s AND s.as_of_ts_utc=%s AND o.horizon_h IN (24,168)
    GROUP BY o.asset_id ORDER BY o.asset_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, as_of_ts_utc))
        rows = cur.fetchall()
    pairs = [RotationPair(
        int(row["asset_id"]), str(row["market"]), int(row["snapshot_24h_id"]), int(row["snapshot_7d_id"]),
        _safe_float(row["return_24h_pct"]), _safe_float(row["relative_volume_24h"]),
        _safe_float(row["return_7d_pct"]), _safe_float(row["relative_volume_7d"]),
    ) for row in rows if int(row["horizon_count"]) == 2]
    return pairs, len(rows) - len(pairs)


def fetch_history_by_asset(conn: Any, venue: str, before: datetime) -> dict[int, list[tuple[float, float]]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT as_of_ts_utc FROM market_rotation_snapshot_v1 "
            "WHERE venue=%s AND horizon_h IN (24,168) AND as_of_ts_utc<%s "
            "GROUP BY as_of_ts_utc HAVING COUNT(DISTINCT horizon_h)=2 "
            "ORDER BY as_of_ts_utc DESC LIMIT %s",
            (venue, before, HISTORY_SNAPSHOT_COUNT),
        )
        timestamps = [row["as_of_ts_utc"] for row in cur.fetchall()]
    if not timestamps:
        return {}
    placeholders = ", ".join(["%s"] * len(timestamps))
    sql = f"""
    SELECT o.asset_id,
      MAX(CASE WHEN o.horizon_h=24 THEN o.price_change_pct END) return_24h_pct,
      MAX(CASE WHEN o.horizon_h=168 THEN o.price_change_pct END) return_7d_pct
    FROM market_rotation_observation_v1 o
    JOIN market_rotation_snapshot_v1 s ON s.snapshot_id=o.snapshot_id
    WHERE s.venue=%s AND o.as_of_ts_utc IN ({placeholders}) AND o.horizon_h IN (24,168)
    GROUP BY o.as_of_ts_utc, o.asset_id HAVING COUNT(DISTINCT o.horizon_h)=2
    ORDER BY o.asset_id, o.as_of_ts_utc DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql, [venue] + timestamps)
        rows = cur.fetchall()
    history: dict[int, list[tuple[float, float]]] = {}
    for row in rows:
        history.setdefault(int(row["asset_id"]), []).append((
            _safe_float(row["return_24h_pct"]), _safe_float(row["return_7d_pct"])
        ))
    return history


def fetch_prior_market_score(conn: Any, venue: str, before: datetime) -> float | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT market_score FROM market_rotation_pressure_snapshot_v1 "
            "WHERE venue=%s AND model_version=%s AND as_of_ts_utc<%s "
            "ORDER BY as_of_ts_utc DESC LIMIT 1",
            (venue, MODEL_VERSION, before),
        )
        row = cur.fetchone()
    return _safe_float(row["market_score"]) if row else None


def write_pressure_snapshot(
    conn: Any, *, as_of_ts_utc: datetime, venue: str, excluded_missing_pair_count: int,
    aggregate: MarketAggregate, observations: list[PressureObservation],
) -> tuple[str, int]:
    header_values = (
        len(observations), excluded_missing_pair_count,
        aggregate.positive_count, aggregate.neutral_count, aggregate.negative_count,
        aggregate.market_score, aggregate.positive_breadth_ratio, aggregate.negative_breadth_ratio,
        aggregate.acceleration_state, aggregate.concentration_state, aggregate.confirmation_state,
        aggregate.market_direction, aggregate.evidence_light_count,
    )
    with conn.cursor() as cur:
        created = int(cur.execute(
            "INSERT IGNORE INTO market_rotation_pressure_snapshot_v1 "
            "(as_of_ts_utc,venue,model_version,eligible_asset_count,excluded_missing_pair_count,"
            "positive_count,neutral_count,negative_count,market_score,positive_breadth_ratio,negative_breadth_ratio,"
            "acceleration_state,concentration_state,confirmation_state,market_direction,evidence_light_count) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (as_of_ts_utc, venue, MODEL_VERSION) + header_values,
        )) > 0
        cur.execute(
            "SELECT pressure_snapshot_id FROM market_rotation_pressure_snapshot_v1 "
            "WHERE as_of_ts_utc=%s AND venue=%s AND model_version=%s FOR UPDATE",
            (as_of_ts_utc, venue, MODEL_VERSION),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("pressure snapshot header missing after INSERT IGNORE")
    snapshot_id = int(row["pressure_snapshot_id"])
    insert_sql = """
    INSERT IGNORE INTO market_rotation_pressure_observation_v1 (
      pressure_snapshot_id,asset_id,market,source_snapshot_24h_id,source_snapshot_7d_id,as_of_ts_utc,model_version,
      raw_return_24h_pct,raw_relative_volume_24h,raw_return_7d_pct,raw_relative_volume_7d,
      raw_acceleration_pct,raw_market_relative_pct,score_return_24h,score_signed_volume_24h,
      score_return_7d,score_signed_volume_7d,score_acceleration,score_market_relative,score_persistence,
      score_total,pressure_state,phase_state
    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    written = 0
    with conn.cursor() as cur:
        for obs in observations:
            written += int(cur.execute(insert_sql, (
                snapshot_id, obs.asset_id, obs.market, obs.source_snapshot_24h_id, obs.source_snapshot_7d_id,
                obs.as_of_ts_utc, MODEL_VERSION, obs.raw_return_24h_pct, obs.raw_relative_volume_24h,
                obs.raw_return_7d_pct, obs.raw_relative_volume_7d, obs.raw_acceleration_pct,
                obs.raw_market_relative_pct, obs.score_return_24h, obs.score_signed_volume_24h,
                obs.score_return_7d, obs.score_signed_volume_7d, obs.score_acceleration,
                obs.score_market_relative, obs.score_persistence, obs.score_total, obs.pressure_state, obs.phase_state,
            )))
        changed = int(cur.execute(
            "UPDATE market_rotation_pressure_snapshot_v1 SET eligible_asset_count=%s,excluded_missing_pair_count=%s,"
            "positive_count=%s,neutral_count=%s,negative_count=%s,market_score=%s,positive_breadth_ratio=%s,"
            "negative_breadth_ratio=%s,acceleration_state=%s,concentration_state=%s,confirmation_state=%s,"
            "market_direction=%s,evidence_light_count=%s WHERE pressure_snapshot_id=%s",
            header_values + (snapshot_id,),
        )) > 0
    return ("CREATED" if created else ("RECONCILED" if written or changed else "NOOP_ALREADY_COMPLETE"), written)


def print_report(as_of_ts_utc: datetime, venue: str, aggregate: MarketAggregate,
                 observations: list[PressureObservation], missing_pairs: int, status: str) -> None:
    print(
        f"MARKET ROTATION as_of={as_of_ts_utc.isoformat()}Z venue={venue} "
        f"direction={aggregate.market_direction} score={aggregate.market_score:+.2f} "
        f"lights={aggregate.evidence_light_count}/5"
    )
    print(
        f"BREADTH in={aggregate.positive_breadth_ratio:.1%} out={aggregate.negative_breadth_ratio:.1%} "
        f"neutral={aggregate.neutral_count}/{len(observations)} eligible={len(observations)} missing_pair={missing_pairs}"
    )
    print(
        f"CONTEXT acceleration={aggregate.acceleration_state} confirmation={aggregate.confirmation_state} "
        f"concentration={aggregate.concentration_state} status={status}"
    )
    for label, rows in (
        ("TOP ROTATION IN", sorted((obs for obs in observations if obs.score_total >= PRESSURE_IN_THRESHOLD), key=lambda o: -o.score_total)[:TOP_N]),
        ("TOP ROTATION OUT", sorted((obs for obs in observations if obs.score_total <= -PRESSURE_IN_THRESHOLD), key=lambda o: o.score_total)[:TOP_N]),
    ):
        print(label)
        if not rows:
            print("  none")
        for obs in rows:
            print(
                f"  {obs.market:<14} {obs.score_total:+7.2f} {obs.phase_state:<24} "
                f"24h={obs.raw_return_24h_pct:+7.2f}% 7d={obs.raw_return_7d_pct:+7.2f}% rv24={obs.raw_relative_volume_24h:.2f}x"
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Synth market rotation pressure scoring")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--write-db", action="store_true")
    parser.add_argument("--venue", default=VENUE_DEFAULT)
    parser.add_argument("--as-of-ts", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.validate_only:
        print(f"RUNNER {RUNNER_NAME} model={MODEL_VERSION} mode=validate-only")
        print(f"weights={WEIGHTS} robust_scale_floors={ROBUST_SCALE_FLOORS}")
        print("broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0")
        print("selection_engine=none decision_gate=none execution_planner=none executor=none")
        return 0
    conn = get_connection()
    try:
        missing = check_schema_ready(conn)
        missing_source = [table for table in missing if table in SOURCE_TABLES]
        missing_target = [table for table in missing if table in TARGET_TABLES]
        if missing_source:
            print(f"FAILED SOURCE_SCHEMA_MISSING missing={missing_source}")
            return 1
        if args.write_db and missing_target:
            print(f"FAILED TARGET_SCHEMA_MISSING missing={missing_target}")
            return 1
        as_of = resolve_as_of_arg(args.as_of_ts) or resolve_latest_common_as_of(conn, args.venue)
        if as_of is None:
            print("FAILED NO_COMMON_24H_7D_SOURCE_SNAPSHOT")
            return 1
        pairs, missing_pairs = fetch_rotation_pairs(conn, args.venue, as_of)
        if not pairs:
            print(f"FAILED NO_COMPLETE_ASSET_PAIRS as_of={as_of.isoformat()}Z")
            return 1
        observations = build_pressure_observations(pairs, fetch_history_by_asset(conn, args.venue, as_of), as_of)
        prior_score = None if missing_target else fetch_prior_market_score(conn, args.venue, as_of)
        aggregate = build_market_aggregate(observations, prior_score)
        status = "DRY_RUN"
        if args.write_db:
            try:
                status, written = write_pressure_snapshot(
                    conn, as_of_ts_utc=as_of, venue=args.venue,
                    excluded_missing_pair_count=missing_pairs,
                    aggregate=aggregate, observations=observations,
                )
                conn.commit()
                status = f"{status} observations_written={written}"
            except Exception:
                conn.rollback()
                raise
        print_report(as_of, args.venue, aggregate, observations, missing_pairs, status)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
