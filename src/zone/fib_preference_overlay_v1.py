from __future__ import annotations

import json
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


PREFERENCE_DB = "synth_bt"
DEFAULT_PRIMARY_BONUS = Decimal("0.12000000")
DEFAULT_SECONDARY_BONUS = Decimal("0.06000000")
DEFAULT_DISTANCE_CAP_BPS = Decimal("250.0")
DEFAULT_MIN_EXECUTION_SCORE = Decimal("0.30")


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    if value < low:
        return low
    if value > high:
        return high
    return value


def _safe_json_loads(raw: str | None) -> dict[str, Any]:
    if raw is None or raw.strip() == "":
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@dataclass(frozen=True)
class FibPreferenceLevel:
    fib_level: Decimal
    score: Decimal


@dataclass(frozen=True)
class FibPreferenceProfile:
    asset_id: int
    venue: str
    interval_code: str
    regime_label: str
    execution_primary: FibPreferenceLevel | None
    execution_secondary: FibPreferenceLevel | None
    reaction_primary: FibPreferenceLevel | None
    reaction_secondary: FibPreferenceLevel | None


@dataclass(frozen=True)
class AppliedFibOverlay:
    regime_label: str
    execution_primary_fib: Decimal | None
    execution_secondary_fib: Decimal | None
    execution_primary_score: Decimal | None
    execution_secondary_score: Decimal | None
    entry_fib_distance_bps_primary: Decimal | None
    entry_fib_distance_bps_secondary: Decimal | None
    applied_bonus_primary: Decimal
    applied_bonus_secondary: Decimal
    total_bonus: Decimal


def _distance_bps(price_a: Decimal | None, price_b: Decimal | None) -> Decimal | None:
    if price_a is None or price_b is None or price_b == 0:
        return None
    return abs(price_a - price_b) / price_b * Decimal("10000")


def _bonus_from_distance(
    *,
    distance_bps: Decimal | None,
    max_bonus: Decimal,
    cap_bps: Decimal,
) -> Decimal:
    if distance_bps is None:
        return Decimal("0")
    if distance_bps >= cap_bps:
        return Decimal("0")
    closeness = Decimal("1") - (distance_bps / cap_bps)
    return _clamp(max_bonus * closeness, Decimal("0"), max_bonus)


def infer_regime_candidates(leg_direction: str | None) -> list[str]:
    normalized = (leg_direction or "").strip().upper()
    if normalized == "UP":
        return ["TREND_UP", "RANGE"]
    if normalized == "DOWN":
        return ["TREND_DOWN", "RANGE"]
    return ["RANGE"]


def fetch_latest_fib_preference_profile(
    *,
    asset_id: int,
    venue: str,
    interval_code: str,
    regime_candidates: list[str],
    min_execution_score: Decimal = DEFAULT_MIN_EXECUTION_SCORE,
) -> FibPreferenceProfile | None:
    if not regime_candidates:
        return None

    placeholders = ",".join(["%s"] * len(regime_candidates))
    params: list[Any] = [
        asset_id,
        venue,
        interval_code,
        *regime_candidates,
        min_execution_score,
    ]

    sql = f"""
    SELECT
        asset_id,
        venue,
        interval_code,
        regime_label,
        execution_fib_level_primary,
        execution_fib_level_secondary,
        execution_primary_score,
        execution_secondary_score,
        reaction_fib_level_primary,
        reaction_fib_level_secondary,
        reaction_primary_score,
        reaction_secondary_score,
        from_ts_utc,
        to_ts_utc
    FROM fib_preference_profile
    WHERE asset_id = %s
      AND venue = %s
      AND interval_code = %s
      AND regime_label IN ({placeholders})
      AND (
            execution_primary_score IS NULL
            OR execution_primary_score >= %s
          )
    ORDER BY
        FIELD(regime_label, {placeholders}),
        to_ts_utc DESC,
        from_ts_utc DESC
    LIMIT 1
    """
    params.extend(regime_candidates)

    conn = get_connection(database=PREFERENCE_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        return None

    execution_primary = None
    if row["execution_fib_level_primary"] is not None:
        execution_primary = FibPreferenceLevel(
            fib_level=_to_decimal(row["execution_fib_level_primary"]),
            score=_to_decimal(row["execution_primary_score"]),
        )

    execution_secondary = None
    if row["execution_fib_level_secondary"] is not None:
        execution_secondary = FibPreferenceLevel(
            fib_level=_to_decimal(row["execution_fib_level_secondary"]),
            score=_to_decimal(row["execution_secondary_score"]),
        )

    reaction_primary = None
    if row["reaction_fib_level_primary"] is not None:
        reaction_primary = FibPreferenceLevel(
            fib_level=_to_decimal(row["reaction_fib_level_primary"]),
            score=_to_decimal(row["reaction_primary_score"]),
        )

    reaction_secondary = None
    if row["reaction_fib_level_secondary"] is not None:
        reaction_secondary = FibPreferenceLevel(
            fib_level=_to_decimal(row["reaction_fib_level_secondary"]),
            score=_to_decimal(row["reaction_secondary_score"]),
        )

    return FibPreferenceProfile(
        asset_id=int(row["asset_id"]),
        venue=str(row["venue"]),
        interval_code=str(row["interval_code"]),
        regime_label=str(row["regime_label"]),
        execution_primary=execution_primary,
        execution_secondary=execution_secondary,
        reaction_primary=reaction_primary,
        reaction_secondary=reaction_secondary,
    )


def apply_fib_preference_to_execution_context(
    *,
    execution_context: Any,
    fib_observation: Any,
    profile: FibPreferenceProfile | None,
    primary_bonus: Decimal = DEFAULT_PRIMARY_BONUS,
    secondary_bonus: Decimal = DEFAULT_SECONDARY_BONUS,
    distance_cap_bps: Decimal = DEFAULT_DISTANCE_CAP_BPS,
) -> tuple[Any, AppliedFibOverlay | None]:
    if profile is None:
        return execution_context, None

    entry_low = getattr(execution_context, "expected_entry_zone_low", None)
    entry_high = getattr(execution_context, "expected_entry_zone_high", None)
    entry_mid = None
    if entry_low is not None and entry_high is not None:
        entry_mid = (_to_decimal(entry_low) + _to_decimal(entry_high)) / Decimal("2")
    elif entry_low is not None:
        entry_mid = _to_decimal(entry_low)
    elif entry_high is not None:
        entry_mid = _to_decimal(entry_high)

    primary_fib_price = None
    secondary_fib_price = None

    if profile.execution_primary is not None:
        level = profile.execution_primary.fib_level
        if level == Decimal("0.500000"):
            primary_fib_price = getattr(fib_observation, "fib_0500_price", None)
        elif level == Decimal("0.618000"):
            primary_fib_price = getattr(fib_observation, "fib_0618_price", None)
        elif level == Decimal("0.786000"):
            primary_fib_price = getattr(fib_observation, "fib_0786_price", None)

    if profile.execution_secondary is not None:
        level = profile.execution_secondary.fib_level
        if level == Decimal("0.500000"):
            secondary_fib_price = getattr(fib_observation, "fib_0500_price", None)
        elif level == Decimal("0.618000"):
            secondary_fib_price = getattr(fib_observation, "fib_0618_price", None)
        elif level == Decimal("0.786000"):
            secondary_fib_price = getattr(fib_observation, "fib_0786_price", None)

    primary_distance_bps = _distance_bps(
        entry_mid,
        None if primary_fib_price is None else _to_decimal(primary_fib_price),
    )
    secondary_distance_bps = _distance_bps(
        entry_mid,
        None if secondary_fib_price is None else _to_decimal(secondary_fib_price),
    )

    applied_primary_bonus = _bonus_from_distance(
        distance_bps=primary_distance_bps,
        max_bonus=primary_bonus,
        cap_bps=distance_cap_bps,
    )
    applied_secondary_bonus = _bonus_from_distance(
        distance_bps=secondary_distance_bps,
        max_bonus=secondary_bonus,
        cap_bps=distance_cap_bps,
    )
    total_bonus = applied_primary_bonus + applied_secondary_bonus

    current_confidence = _to_decimal(getattr(execution_context, "zone_confidence_score", None), "0")
    current_alignment = _to_decimal(getattr(execution_context, "zone_alignment_score", None), "0")

    current_notes = getattr(execution_context, "notes", None) or ""
    note_suffix = (
        f" fib_pref_regime={profile.regime_label}"
        f" exec_primary={profile.execution_primary.fib_level if profile.execution_primary else ''}"
        f" exec_secondary={profile.execution_secondary.fib_level if profile.execution_secondary else ''}"
        f" fib_bonus={total_bonus}"
    )
    new_notes = (current_notes + note_suffix).strip()

    source_ref_json_raw = getattr(execution_context, "source_ref_json", None)
    source_ref = _safe_json_loads(source_ref_json_raw)
    source_ref["fib_overlay"] = {
        "profile_regime_label": profile.regime_label,
        "execution_primary_fib": None if profile.execution_primary is None else str(profile.execution_primary.fib_level),
        "execution_secondary_fib": None if profile.execution_secondary is None else str(profile.execution_secondary.fib_level),
        "execution_primary_score": None if profile.execution_primary is None else str(profile.execution_primary.score),
        "execution_secondary_score": None if profile.execution_secondary is None else str(profile.execution_secondary.score),
        "entry_fib_distance_bps_primary": None if primary_distance_bps is None else str(primary_distance_bps),
        "entry_fib_distance_bps_secondary": None if secondary_distance_bps is None else str(secondary_distance_bps),
        "applied_bonus_primary": str(applied_primary_bonus),
        "applied_bonus_secondary": str(applied_secondary_bonus),
        "total_bonus": str(total_bonus),
        "base_zone_confidence_score": str(current_confidence),
        "new_zone_confidence_score": str(current_confidence + total_bonus),
        "base_zone_alignment_score": str(current_alignment),
        "new_zone_alignment_score": str(current_alignment + (total_bonus / Decimal("2"))),
    }
    new_source_ref_json = json.dumps(source_ref, ensure_ascii=False, separators=(",", ":"))

    new_context = replace(
        execution_context,
        zone_confidence_score=current_confidence + total_bonus,
        zone_alignment_score=current_alignment + (total_bonus / Decimal("2")),
        source_ref_json=new_source_ref_json,
        notes=new_notes,
    )

    overlay = AppliedFibOverlay(
        regime_label=profile.regime_label,
        execution_primary_fib=None if profile.execution_primary is None else profile.execution_primary.fib_level,
        execution_secondary_fib=None if profile.execution_secondary is None else profile.execution_secondary.fib_level,
        execution_primary_score=None if profile.execution_primary is None else profile.execution_primary.score,
        execution_secondary_score=None if profile.execution_secondary is None else profile.execution_secondary.score,
        entry_fib_distance_bps_primary=primary_distance_bps,
        entry_fib_distance_bps_secondary=secondary_distance_bps,
        applied_bonus_primary=applied_primary_bonus,
        applied_bonus_secondary=applied_secondary_bonus,
        total_bonus=total_bonus,
    )
    return new_context, overlay
