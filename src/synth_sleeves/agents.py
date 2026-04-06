"""
SYNTH v2
Module: synth_sleeves.agents
Purpose:
    Default sleeve agents using canonical selection semantics, relative strength,
    momentum persistence, volume confirmation, and size modulation.
Boundary:
    - No DB I/O
    - No external API I/O
    - Input = normalized selection rows
    - Output = proposals only
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from src.synth_sleeves.models import (
    AgentProposal,
    AgentSignalRow,
    DecisionAction,
    EntryState,
    SleeveCode,
)


ENTER_STATES = {
    "LONG_READY",
    "CONFIRMED_LONG",
    "ENTER_LONG",
}

TACTICAL_STATES = {
    "TACTICAL",
    "SCALP_ONLY",
}

DECIMAL_ZERO = Decimal("0")
DECIMAL_ONE = Decimal("1")
DECIMAL_TWO = Decimal("2")

DECIMAL_05 = Decimal("0.05")
DECIMAL_07 = Decimal("0.7")
DECIMAL_08 = Decimal("0.8")
DECIMAL_11 = Decimal("1.1")
DECIMAL_12 = Decimal("1.2")
DECIMAL_15 = Decimal("1.5")
DECIMAL_20 = Decimal("20")


def apply_core_volume_modifier(
    action: str,
    target_fraction: Decimal,
    vol_ratio: Decimal | None,
    vol_z: Decimal | None,
) -> tuple[str, Decimal]:
    if vol_ratio is None:
        return action, target_fraction

    if action == "ENTER_LONG" and vol_ratio < DECIMAL_08:
        return "PREPARE", target_fraction * DECIMAL_07

    if action == "ENTER_LONG" and vol_ratio > DECIMAL_15 and (vol_z or DECIMAL_ZERO) > DECIMAL_ZERO:
        return action, target_fraction * DECIMAL_12

    if action == "PREPARE" and vol_ratio > DECIMAL_12 and (vol_z or DECIMAL_ZERO) > DECIMAL_ZERO:
        return "ENTER_LONG", target_fraction * DECIMAL_11

    return action, target_fraction


def apply_swing_volume_modifier(
    action: str,
    target_fraction: Decimal,
    vol_ratio: Decimal | None,
    vol_z: Decimal | None,
) -> tuple[str, Decimal]:
    if vol_ratio is None:
        return action, target_fraction

    # SWING blijft opportunistisch:
    # zwak volume → kleinere positie, GEEN downgrade
    if action == "ENTER_LONG" and vol_ratio < Decimal("0.8"):
        return action, target_fraction * DECIMAL_07

    # lichte boost bij goed volume
    if action == "ENTER_LONG" and vol_ratio > DECIMAL_12:
        return action, target_fraction * DECIMAL_11

    # PREPARE → sneller promoten dan CORE
    if action == "PREPARE" and vol_ratio > Decimal("1.0") and (vol_z or DECIMAL_ZERO) > Decimal("-0.2"):
        return "ENTER_LONG", target_fraction * DECIMAL_11

    return action, target_fraction

def _has_valid_price(row: AgentSignalRow) -> bool:
    return row.latest_price_eur > DECIMAL_ZERO


def _d(row: AgentSignalRow, key: str) -> Decimal:
    return Decimal(str(row.extra.get(key, Decimal("0"))))


def _clamp_0_1(value: Decimal) -> Decimal:
    if value < DECIMAL_ZERO:
        return DECIMAL_ZERO
    if value > DECIMAL_ONE:
        return DECIMAL_ONE
    return value


def _normalize_persistence_score(raw_score: Decimal) -> Decimal:
    if raw_score <= DECIMAL_ZERO:
        return DECIMAL_ZERO
    return _clamp_0_1(raw_score / DECIMAL_20)


def _normalize_volume_ratio(raw_ratio: Decimal) -> Decimal:
    if raw_ratio <= DECIMAL_ZERO:
        return DECIMAL_ZERO
    return _clamp_0_1(raw_ratio / DECIMAL_TWO)


def _normalize_volume_zscore(raw_zscore: Decimal) -> Decimal:
    if raw_zscore <= Decimal("-1"):
        return DECIMAL_ZERO
    return _clamp_0_1((raw_zscore + DECIMAL_ONE) / Decimal("3"))


def _volume_ok_prepare(row: AgentSignalRow) -> bool:
    return _d(row, "vc_volume_ratio_7d") >= Decimal("0.90") or _d(row, "vc_volume_zscore_7d") >= DECIMAL_ZERO


def _volume_ok_enter(row: AgentSignalRow) -> bool:
    return _d(row, "vc_volume_ratio_7d") >= DECIMAL_ONE or _d(row, "vc_volume_zscore_7d") >= Decimal("0.20")


def _rs_ok_prepare(row: AgentSignalRow) -> bool:
    return _d(row, "rs_rank_pct_7d") >= Decimal("0.40") or _d(row, "rs_rank_pct_14d") >= Decimal("0.40")


def _rs_ok_enter(row: AgentSignalRow) -> bool:
    return _d(row, "rs_rank_pct_7d") >= Decimal("0.55") or _d(row, "rs_rank_pct_14d") >= Decimal("0.55")


def _mp_ok_prepare(row: AgentSignalRow) -> bool:
    return _d(row, "mp_green_ratio_7d") >= Decimal("0.43") or _d(row, "mp_green_ratio_14d") >= Decimal("0.43")


def _mp_ok_enter(row: AgentSignalRow) -> bool:
    return _d(row, "mp_green_ratio_7d") >= Decimal("0.50") or _d(row, "mp_green_ratio_14d") >= Decimal("0.50")


def _prepare_quality_score(row: AgentSignalRow) -> Decimal:
    selection_component = _clamp_0_1(row.selection_score)
    rs_component = _clamp_0_1(_d(row, "rs_rank_pct_14d"))
    persistence_component = _normalize_persistence_score(_d(row, "mp_persistence_score_14d"))
    volume_component = max(
        _normalize_volume_ratio(_d(row, "vc_volume_ratio_14d")),
        _normalize_volume_zscore(_d(row, "vc_volume_zscore_14d")),
    )

    score = (
        selection_component * Decimal("0.45")
        + rs_component * Decimal("0.20")
        + persistence_component * Decimal("0.20")
        + volume_component * Decimal("0.15")
    )
    return _clamp_0_1(score)


def _enter_quality_score(row: AgentSignalRow) -> Decimal:
    selection_component = _clamp_0_1(row.selection_score)
    rs_component = _clamp_0_1(_d(row, "rs_rank_pct_7d"))
    persistence_component = _normalize_persistence_score(_d(row, "mp_persistence_score_7d"))
    volume_component = max(
        _normalize_volume_ratio(_d(row, "vc_volume_ratio_7d")),
        _normalize_volume_zscore(_d(row, "vc_volume_zscore_7d")),
    )

    score = (
        selection_component * Decimal("0.40")
        + rs_component * Decimal("0.25")
        + persistence_component * Decimal("0.20")
        + volume_component * Decimal("0.15")
    )
    return _clamp_0_1(score)


def _scale_prepare_fraction(base_fraction: Decimal, quality_score: Decimal) -> Decimal:
    if quality_score >= Decimal("0.70"):
        return base_fraction
    if quality_score >= Decimal("0.50"):
        return base_fraction * Decimal("0.66")
    return base_fraction * Decimal("0.33")


def _scale_enter_fraction(base_fraction: Decimal, quality_score: Decimal) -> Decimal:
    if quality_score >= Decimal("0.75"):
        return base_fraction
    return base_fraction * Decimal("0.80")


def core_trend(run_ts_utc: datetime, row: AgentSignalRow) -> AgentProposal | None:
    if row.htf_reject or not row.liquidity_ok or not _has_valid_price(row):
        return None

    if (
        row.selection_state in ENTER_STATES
        and row.regime_ok
        and row.selection_score >= Decimal("0.55")
        and _rs_ok_enter(row)
        and _mp_ok_enter(row)
        and _volume_ok_enter(row)
    ):
        quality = _enter_quality_score(row)
        requested_fraction = _scale_enter_fraction(Decimal("0.15"), quality)

        desired_action = "ENTER_LONG"
        desired_action, requested_fraction = apply_core_volume_modifier(
            desired_action,
            requested_fraction,
            _d(row, "vc_volume_ratio_7d"),
            _d(row, "vc_volume_zscore_7d"),
        )

        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.CORE,
            strategy_name="core_trend",
            desired_action=DecisionAction(desired_action),
            requested_fraction=requested_fraction,
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="CORE action after structure, persistence, RS, and volume modulation.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.ENTER_LONG if desired_action == "ENTER_LONG" else EntryState.PREPARE,
        )

    if (
        row.selection_state == "PRE_ALIGNMENT"
        and row.regime_ok
        and row.selection_score >= Decimal("0.50")
        and _rs_ok_prepare(row)
        and _mp_ok_prepare(row)
        and _volume_ok_prepare(row)
    ):
        quality = _prepare_quality_score(row)
        requested_fraction = _scale_prepare_fraction(Decimal("0.20"), quality)

        desired_action = "PREPARE"
        desired_action, requested_fraction = apply_core_volume_modifier(
            desired_action,
            requested_fraction,
            _d(row, "vc_volume_ratio_7d"),
            _d(row, "vc_volume_zscore_7d"),
        )

        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.CORE,
            strategy_name="core_trend",
            desired_action=DecisionAction(desired_action),
            requested_fraction=requested_fraction,
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="CORE prepare with quality-scaled sizing and volume modulation.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.PREPARE if desired_action == "PREPARE" else EntryState.ENTER_LONG,
        )

    if (
        row.selection_state == "EARLY_WATCH"
        and row.regime_ok
        and row.selection_score >= Decimal("0.60")
        and _rs_ok_prepare(row)
        and _mp_ok_prepare(row)
        and _volume_ok_prepare(row)
    ):
        quality = _prepare_quality_score(row)
        requested_fraction = _scale_prepare_fraction(Decimal("0.20"), quality)

        desired_action = "PREPARE"
        desired_action, requested_fraction = apply_core_volume_modifier(
            desired_action,
            requested_fraction,
            _d(row, "vc_volume_ratio_7d"),
            _d(row, "vc_volume_zscore_7d"),
        )

        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.CORE,
            strategy_name="core_trend",
            desired_action=DecisionAction(desired_action),
            requested_fraction=requested_fraction,
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="CORE early-watch prepare with quality-scaled sizing and volume modulation.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.PREPARE if desired_action == "PREPARE" else EntryState.ENTER_LONG,
        )

    return None


def swing_rotation(run_ts_utc: datetime, row: AgentSignalRow) -> AgentProposal | None:
    if row.htf_reject or not row.liquidity_ok or not _has_valid_price(row):
        return None

    if (
        row.selection_state in ENTER_STATES
        and row.regime_ok
        and row.selection_score >= Decimal("0.52")
        and _rs_ok_prepare(row)
        and _mp_ok_prepare(row)
        and _volume_ok_prepare(row)
    ):
        quality = _enter_quality_score(row)
        requested_fraction = _scale_enter_fraction(Decimal("0.05"), quality)

        desired_action = "ENTER_LONG"
        desired_action, requested_fraction = apply_swing_volume_modifier(
            desired_action,
            requested_fraction,
            _d(row, "vc_volume_ratio_7d"),
            _d(row, "vc_volume_zscore_7d"),
        )

        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.SWING,
            strategy_name="swing_rotation",
            desired_action=DecisionAction(desired_action),
            requested_fraction=requested_fraction,
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="SWING enter-ready rotation setup with sleeve-specific volume modulation.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.ENTER_LONG if desired_action == "ENTER_LONG" else EntryState.PREPARE,
        )

    if (
        row.selection_state == "PRE_ALIGNMENT"
        and row.regime_ok
        and row.selection_score >= Decimal("0.45")
        and _rs_ok_prepare(row)
        and _mp_ok_prepare(row)
        and _volume_ok_prepare(row)
    ):
        quality = _prepare_quality_score(row)
        requested_fraction = _scale_prepare_fraction(Decimal("0.05"), quality)

        desired_action = "PREPARE"
        desired_action, requested_fraction = apply_swing_volume_modifier(
            desired_action,
            requested_fraction,
            _d(row, "vc_volume_ratio_7d"),
            _d(row, "vc_volume_zscore_7d"),
        )

        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.SWING,
            strategy_name="swing_rotation",
            desired_action=DecisionAction(desired_action),
            requested_fraction=requested_fraction,
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="SWING prepare with sleeve-specific volume modulation.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.PREPARE if desired_action == "PREPARE" else EntryState.ENTER_LONG,
        )

    if (
        row.selection_state == "EARLY_WATCH"
        and row.regime_ok
        and row.selection_score >= Decimal("0.55")
        and _rs_ok_prepare(row)
        and _mp_ok_prepare(row)
        and _volume_ok_prepare(row)
    ):
        quality = _prepare_quality_score(row)
        requested_fraction = _scale_prepare_fraction(Decimal("0.05"), quality)

        desired_action = "PREPARE"
        desired_action, requested_fraction = apply_swing_volume_modifier(
            desired_action,
            requested_fraction,
            _d(row, "vc_volume_ratio_7d"),
            _d(row, "vc_volume_zscore_7d"),
        )

        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.SWING,
            strategy_name="swing_rotation",
            desired_action=DecisionAction(desired_action),
            requested_fraction=requested_fraction,
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="SWING early-watch prepare with sleeve-specific volume modulation.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.PREPARE if desired_action == "PREPARE" else EntryState.ENTER_LONG,
        )

    return None


def tactical_momentum(run_ts_utc: datetime, row: AgentSignalRow) -> AgentProposal | None:
    if not row.liquidity_ok or not _has_valid_price(row):
        return None

    if (
        row.selection_state in TACTICAL_STATES
        and row.selection_score >= Decimal("0.55")
        and _rs_ok_prepare(row)
        and _mp_ok_prepare(row)
        and _volume_ok_enter(row)
    ):
        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.TACTICAL,
            strategy_name="tactical_momentum",
            desired_action=DecisionAction.SCALP_ONLY,
            requested_fraction=Decimal("0.08"),
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="TACTICAL momentum burst with acceptable relative strength, persistence, and volume confirmation.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.SCALP_ONLY,
        )

    return None


def experimental_misc(run_ts_utc: datetime, row: AgentSignalRow) -> AgentProposal | None:
    if row.htf_reject or not _has_valid_price(row):
        return None

    if (
        row.selection_state in ENTER_STATES
        and row.selection_score >= Decimal("0.65")
        and _rs_ok_enter(row)
        and _mp_ok_enter(row)
        and _volume_ok_enter(row)
    ):
        quality = _enter_quality_score(row)
        requested_fraction = _scale_enter_fraction(Decimal("0.05"), quality)

        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.EXPERIMENTAL,
            strategy_name="experimental_misc",
            desired_action=DecisionAction.ENTER_LONG,
            requested_fraction=requested_fraction,
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="EXPERIMENTAL enter-ready candidate with strong relative strength, persistence, and volume confirmation.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.ENTER_LONG,
        )

    if (
        row.selection_state == "PRE_ALIGNMENT"
        and row.selection_score >= Decimal("0.65")
        and _rs_ok_enter(row)
        and _mp_ok_enter(row)
        and _volume_ok_enter(row)
    ):
        quality = _prepare_quality_score(row)
        requested_fraction = _scale_prepare_fraction(Decimal("0.05"), quality)

        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.EXPERIMENTAL,
            strategy_name="experimental_misc",
            desired_action=DecisionAction.PREPARE,
            requested_fraction=requested_fraction,
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="EXPERIMENTAL prepare candidate with strong relative strength, persistence, and volume confirmation.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.PREPARE,
        )

    if (
        row.selection_state == "TACTICAL"
        and row.selection_score >= Decimal("0.60")
        and _rs_ok_enter(row)
        and _mp_ok_enter(row)
        and _volume_ok_enter(row)
    ):
        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.EXPERIMENTAL,
            strategy_name="experimental_misc",
            desired_action=DecisionAction.SCALP_ONLY,
            requested_fraction=Decimal("0.05"),
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="EXPERIMENTAL tactical candidate with strong relative strength, persistence, and volume confirmation.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.SCALP_ONLY,
        )

    return None


AGENT_REGISTRY = {
    "core_trend": core_trend,
    "swing_rotation": swing_rotation,
    "tactical_momentum": tactical_momentum,
    "experimental_misc": experimental_misc,
}
