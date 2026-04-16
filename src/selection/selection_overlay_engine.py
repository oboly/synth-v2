"""
Synth v2 - Selection Overlay Engine v1

Purpose:
- Read latest or specified selection_state rows
- Apply HTF overlay rules
- Persist enriched overlay outputs to selection_enriched_overlays

Notes:
- UTC only
- Minimal v1 implementation based on currently available selection_state fields
- Failed breakout source fields are not yet available in selection_state, so failed breakout
  columns remain prepared but inactive unless future source inputs are added
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional

from src.common.db import get_connection


BULLISH_BIASES = {"BULLISH", "LONG", "BUY", "LONG_BIAS"}
BULLISH_SELECTION_STATES = {"PREPARE", "BUY_READY", "STRONG_CANDIDATE"}

HTF_BEAR_REGIMES = {"RISK_OFF", "RESET_DAMAGE"}
HTF_PREPARE_REGIMES = {"NEUTRAL_TRANSITION", "RANGE_CHOP", "COMPRESSION_BUILD"}
HTF_BULL_REGIMES = {"TREND_EXPANSION", "ROTATION_OPENING"}

HTF_BEAR_CAP = Decimal("0.35")
HTF_PREPARE_CAP = Decimal("0.60")
FAILED_BREAKOUT_FIXED_PENALTY = Decimal("0.10")
DECIMAL_5 = Decimal("0.00001")


@dataclass(frozen=True)
class SelectionRow:
    asset_id: int
    venue: str
    asof_ts_utc: object
    selection_state: str
    selection_bias: str
    selection_score: Decimal
    advice_state_4h: Optional[str]
    regime_label_4h: Optional[str]
    opportunity_score_4h: Decimal
    risk_score_4h: Decimal


@dataclass(frozen=True)
class OverlayRow:
    asset_id: int
    venue: str
    asof_ts_utc: object
    failed_breakout_flag_4h: int
    avoid_long_overlay_flag: int
    breakout_failure_state: Optional[str]
    htf_rule_state: str
    htf_recommendation: str
    htf_score_cap: Optional[Decimal]
    bullish_structure_conflict_flag: int
    overlay_conflict_severity: Decimal
    selection_score_after_overlay: Decimal
    advice_overlay_reason: Optional[str]


def _to_decimal(value: object, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _q5(value: Decimal) -> Decimal:
    return value.quantize(DECIMAL_5, rounding=ROUND_HALF_UP)


def _normalize_text(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _is_bullish_bias(selection_bias: Optional[str]) -> bool:
    return (selection_bias or "").upper() in BULLISH_BIASES


def _is_bullish_state(selection_state: Optional[str]) -> bool:
    return (selection_state or "").upper() in BULLISH_SELECTION_STATES


def classify_htf_rule_state(row: SelectionRow) -> str:
    regime = (row.regime_label_4h or "").upper()
    advice = (row.advice_state_4h or "").upper()
    risk = row.risk_score_4h

    if regime in HTF_BEAR_REGIMES:
        return "BEAR"

    if regime in HTF_PREPARE_REGIMES:
        return "PREPARE"

    if regime in HTF_BULL_REGIMES:
        if risk >= Decimal("0.70"):
            return "PREPARE"
        if advice in {"NO_ACTION", "WATCH"} and risk >= Decimal("0.45"):
            return "PREPARE"
        return "BULL"

    if risk >= Decimal("0.75"):
        return "BEAR"

    if risk >= Decimal("0.45"):
        return "PREPARE"

    return "BULL"


def classify_htf_recommendation(htf_rule_state: str) -> str:
    if htf_rule_state == "BEAR":
        return "NO_TRADE"
    if htf_rule_state == "PREPARE":
        return "WATCH"
    return "ALLOW"


def determine_htf_score_cap(htf_rule_state: str) -> Optional[Decimal]:
    if htf_rule_state == "BEAR":
        return HTF_BEAR_CAP
    if htf_rule_state == "PREPARE":
        return HTF_PREPARE_CAP
    return None


def infer_failed_breakout_flag_4h(row: SelectionRow) -> int:
    """
    v1 intentionally conservative:
    failed breakout is not inferred from current selection_state-only data because that would
    create false confidence. Keep it inactive until explicit source fields exist.
    """
    _ = row
    return 0


def infer_breakout_failure_state(row: SelectionRow, failed_breakout_flag_4h: int) -> Optional[str]:
    _ = row
    if failed_breakout_flag_4h == 1:
        return "FAILED_UPSIDE_BREAKOUT"
    return None


def compute_avoid_long_overlay_flag(
    row: SelectionRow,
    failed_breakout_flag_4h: int,
    htf_rule_state: str,
) -> int:
    if not _is_bullish_bias(row.selection_bias):
        return 0
    if failed_breakout_flag_4h == 1:
        return 1
    if htf_rule_state == "BEAR":
        return 1
    return 0


def compute_bullish_structure_conflict_flag(row: SelectionRow, htf_rule_state: str) -> int:
    if _is_bullish_bias(row.selection_bias) and htf_rule_state in {"BEAR", "PREPARE"}:
        if _is_bullish_state(row.selection_state):
            return 1
    return 0


def compute_overlay_conflict_severity(
    row: SelectionRow,
    htf_rule_state: str,
    failed_breakout_flag_4h: int,
    bullish_structure_conflict_flag: int,
) -> Decimal:
    if failed_breakout_flag_4h == 1 and _is_bullish_bias(row.selection_bias):
        return Decimal("0.85")

    if bullish_structure_conflict_flag == 1 and htf_rule_state == "BEAR":
        return Decimal("0.85")

    if bullish_structure_conflict_flag == 1 and htf_rule_state == "PREPARE":
        if row.selection_state.upper() == "BUY_READY":
            return Decimal("0.60")
        return Decimal("0.45")

    if htf_rule_state == "PREPARE" and (row.selection_bias or "").upper() == "NEUTRAL_POSITIVE":
        return Decimal("0.15")

    return Decimal("0.00")


def compute_selection_score_after_overlay(
    row: SelectionRow,
    failed_breakout_flag_4h: int,
    avoid_long_overlay_flag: int,
    htf_score_cap: Optional[Decimal],
) -> Decimal:
    score = row.selection_score

    if failed_breakout_flag_4h == 1 and avoid_long_overlay_flag == 1 and _is_bullish_bias(row.selection_bias):
        score -= FAILED_BREAKOUT_FIXED_PENALTY

    if htf_score_cap is not None and score > htf_score_cap:
        score = htf_score_cap

    if score < Decimal("0.0"):
        score = Decimal("0.0")

    return _q5(score)


def build_advice_overlay_reason(
    row: SelectionRow,
    failed_breakout_flag_4h: int,
    bullish_structure_conflict_flag: int,
    htf_rule_state: str,
) -> Optional[str]:
    reasons: list[str] = []

    if failed_breakout_flag_4h == 1:
        reasons.append("FAILED_UPSIDE_BREAKOUT")

    if bullish_structure_conflict_flag == 1 and htf_rule_state == "BEAR":
        reasons.append("HTF_BEAR_CONFLICT")

    if bullish_structure_conflict_flag == 1 and htf_rule_state == "PREPARE":
        reasons.append("HTF_PREPARE_CAP")

    if not reasons:
        return None

    return ",".join(reasons)


def row_to_selection_row(raw: dict) -> SelectionRow:
    return SelectionRow(
        asset_id=int(raw["asset_id"]),
        venue=str(raw["venue"]),
        asof_ts_utc=raw["asof_ts_utc"],
        selection_state=str(raw["selection_state"]),
        selection_bias=str(raw["selection_bias"]),
        selection_score=_to_decimal(raw["selection_score"]),
        advice_state_4h=_normalize_text(raw.get("advice_state_4h")),
        regime_label_4h=_normalize_text(raw.get("regime_label_4h")),
        opportunity_score_4h=_to_decimal(raw.get("opportunity_score_4h"), "0"),
        risk_score_4h=_to_decimal(raw.get("risk_score_4h"), "0"),
    )


def build_overlay_row(row: SelectionRow) -> OverlayRow:
    failed_breakout_flag_4h = infer_failed_breakout_flag_4h(row)
    breakout_failure_state = infer_breakout_failure_state(row, failed_breakout_flag_4h)

    htf_rule_state = classify_htf_rule_state(row)
    htf_recommendation = classify_htf_recommendation(htf_rule_state)
    htf_score_cap = determine_htf_score_cap(htf_rule_state)

    avoid_long_overlay_flag = compute_avoid_long_overlay_flag(
        row=row,
        failed_breakout_flag_4h=failed_breakout_flag_4h,
        htf_rule_state=htf_rule_state,
    )

    bullish_structure_conflict_flag = compute_bullish_structure_conflict_flag(
        row=row,
        htf_rule_state=htf_rule_state,
    )

    overlay_conflict_severity = _q5(
        compute_overlay_conflict_severity(
            row=row,
            htf_rule_state=htf_rule_state,
            failed_breakout_flag_4h=failed_breakout_flag_4h,
            bullish_structure_conflict_flag=bullish_structure_conflict_flag,
        )
    )

    selection_score_after_overlay = compute_selection_score_after_overlay(
        row=row,
        failed_breakout_flag_4h=failed_breakout_flag_4h,
        avoid_long_overlay_flag=avoid_long_overlay_flag,
        htf_score_cap=htf_score_cap,
    )

    advice_overlay_reason = build_advice_overlay_reason(
        row=row,
        failed_breakout_flag_4h=failed_breakout_flag_4h,
        bullish_structure_conflict_flag=bullish_structure_conflict_flag,
        htf_rule_state=htf_rule_state,
    )

    return OverlayRow(
        asset_id=row.asset_id,
        venue=row.venue,
        asof_ts_utc=row.asof_ts_utc,
        failed_breakout_flag_4h=failed_breakout_flag_4h,
        avoid_long_overlay_flag=avoid_long_overlay_flag,
        breakout_failure_state=breakout_failure_state,
        htf_rule_state=htf_rule_state,
        htf_recommendation=htf_recommendation,
        htf_score_cap=htf_score_cap,
        bullish_structure_conflict_flag=bullish_structure_conflict_flag,
        overlay_conflict_severity=overlay_conflict_severity,
        selection_score_after_overlay=selection_score_after_overlay,
        advice_overlay_reason=advice_overlay_reason,
    )


def fetch_selection_rows(venue: str, asof_ts_utc: Optional[str] = None) -> list[SelectionRow]:
    sql = """
    SELECT
        se.asset_id,
        se.venue,
        se.asof_ts_utc,
        se.selection_state,
        se.selection_bias,
        se.selection_score,
        se.advice_state_4h,
        se.regime_label_4h,
        se.opportunity_score_4h,
        se.risk_score_4h
    FROM selection_state se
    WHERE se.venue = %s
      AND se.asof_ts_utc = COALESCE(
            %s,
            (
                SELECT MAX(se2.asof_ts_utc)
                FROM selection_state se2
                WHERE se2.venue = se.venue
            )
      )
    ORDER BY se.selection_score DESC, se.asset_id ASC
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (venue, asof_ts_utc))
            rows = cur.fetchall()
    finally:
        conn.close()

    return [row_to_selection_row(raw=row) for row in rows]


def upsert_overlay_rows(rows: Iterable[OverlayRow]) -> int:
    payload = [
        (
            row.asset_id,
            row.venue,
            row.asof_ts_utc,
            row.failed_breakout_flag_4h,
            row.avoid_long_overlay_flag,
            row.breakout_failure_state,
            row.htf_rule_state,
            row.htf_recommendation,
            str(row.htf_score_cap) if row.htf_score_cap is not None else None,
            row.bullish_structure_conflict_flag,
            str(row.overlay_conflict_severity),
            str(row.selection_score_after_overlay),
            row.advice_overlay_reason,
        )
        for row in rows
    ]

    if not payload:
        return 0

    sql = """
    INSERT INTO selection_enriched_overlays (
        asset_id,
        venue,
        asof_ts_utc,
        failed_breakout_flag_4h,
        avoid_long_overlay_flag,
        breakout_failure_state,
        htf_rule_state,
        htf_recommendation,
        htf_score_cap,
        bullish_structure_conflict_flag,
        overlay_conflict_severity,
        selection_score_after_overlay,
        advice_overlay_reason
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    ON DUPLICATE KEY UPDATE
        failed_breakout_flag_4h = VALUES(failed_breakout_flag_4h),
        avoid_long_overlay_flag = VALUES(avoid_long_overlay_flag),
        breakout_failure_state = VALUES(breakout_failure_state),
        htf_rule_state = VALUES(htf_rule_state),
        htf_recommendation = VALUES(htf_recommendation),
        htf_score_cap = VALUES(htf_score_cap),
        bullish_structure_conflict_flag = VALUES(bullish_structure_conflict_flag),
        overlay_conflict_severity = VALUES(overlay_conflict_severity),
        selection_score_after_overlay = VALUES(selection_score_after_overlay),
        advice_overlay_reason = VALUES(advice_overlay_reason),
        updated_ts_utc = CURRENT_TIMESTAMP
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, payload)
        conn.commit()
    finally:
        conn.close()

    return len(payload)


def run_selection_overlay_engine(venue: str, asof_ts_utc: Optional[str] = None) -> int:
    selection_rows = fetch_selection_rows(venue=venue, asof_ts_utc=asof_ts_utc)

    if not selection_rows:
        print("[DONE] selection_enriched_overlays rows=0")
        return 0

    overlay_rows = [build_overlay_row(row) for row in selection_rows]
    written = upsert_overlay_rows(overlay_rows)

    bear_conflicts = sum(1 for row in overlay_rows if row.bullish_structure_conflict_flag == 1)
    hard_avoid = sum(1 for row in overlay_rows if row.htf_recommendation == "NO_TRADE")

    print(f"[DONE] selection_enriched_overlays rows={written}")
    print(f"[INFO] bullish_structure_conflicts={bear_conflicts}")
    print(f"[INFO] htf_no_trade_rows={hard_avoid}")

    return written
