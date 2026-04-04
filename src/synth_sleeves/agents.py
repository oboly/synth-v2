"""
SYNTH v2
Module: synth_sleeves.agents
Purpose:
    Default sleeve agents using canonical selection semantics, relative strength,
    momentum persistence, and size modulation for PREPARE / ENTER states.
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
    # Typical observed range is roughly 0..20+, so divide by 20 and clamp.
    if raw_score <= DECIMAL_ZERO:
        return DECIMAL_ZERO
    return _clamp_0_1(raw_score / Decimal("20"))


def _rs_ok_prepare(row: AgentSignalRow) -> bool:
    return _d(row, "rs_rank_pct_7d") >= Decimal("0.40") or _d(row, "rs_rank_pct_14d") >= Decimal("0.40")


def _rs_ok_enter(row: AgentSignalRow) -> bool:
    return _d(row, "rs_rank_pct_7d") >= Decimal("0.55") or _d(row, "rs_rank_pct_14d") >= Decimal("0.55")


def _mp_ok_prepare(row: AgentSignalRow) -> bool:
    return _d(row, "mp_green_ratio_7d") >= Decimal("0.43") or _d(row, "mp_green_ratio_14d") >= Decimal("0.43")


def _mp_ok_enter(row: AgentSignalRow) -> bool:
    return _d(row, "mp_green_ratio_7d") >= Decimal("0.50") or _d(row, "mp_green_ratio_14d") >= Decimal("0.50")


def _prepare_quality_score(row: AgentSignalRow) -> Decimal:
    """
    PREPARE quality:
    - selection_score already captures a lot of upstream structure
    - 14d RS adds medium-horizon competitive strength
    - 14d persistence adds movement quality
    """
    selection_component = _clamp_0_1(row.selection_score)
    rs_component = _clamp_0_1(_d(row, "rs_rank_pct_14d"))
    persistence_component = _normalize_persistence_score(_d(row, "mp_persistence_score_14d"))

    score = (
        selection_component * Decimal("0.55")
        + rs_component * Decimal("0.25")
        + persistence_component * Decimal("0.20")
    )
    return _clamp_0_1(score)


def _enter_quality_score(row: AgentSignalRow) -> Decimal:
    """
    ENTER quality:
    - selection_score still dominant
    - 7d RS matters more for active entry timing
    - 7d persistence matters more for current movement quality
    """
    selection_component = _clamp_0_1(row.selection_score)
    rs_component = _clamp_0_1(_d(row, "rs_rank_pct_7d"))
    persistence_component = _normalize_persistence_score(_d(row, "mp_persistence_score_7d"))

    score = (
        selection_component * Decimal("0.50")
        + rs_component * Decimal("0.30")
        + persistence_component * Decimal("0.20")
    )
    return _clamp_0_1(score)


def _scale_prepare_fraction(base_fraction: Decimal, quality_score: Decimal) -> Decimal:
    """
    PREPARE sizing:
    - strong prepare: full base
    - medium prepare: 2/3 base
    - weak-but-allowed prepare: 1/3 base
    """
    if quality_score >= Decimal("0.70"):
        return base_fraction
    if quality_score >= Decimal("0.50"):
        return base_fraction * Decimal("0.66")
    return base_fraction * Decimal("0.33")


def _scale_enter_fraction(base_fraction: Decimal, quality_score: Decimal) -> Decimal:
    """
    ENTER sizing:
    - strong enter: full base
    - acceptable but not top-tier enter: 80% base
    """
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
    ):
        quality = _enter_quality_score(row)
        requested_fraction = _scale_enter_fraction(Decimal("0.15"), quality)

        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.CORE,
            strategy_name="core_trend",
            desired_action=DecisionAction.ENTER_LONG,
            requested_fraction=requested_fraction,
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="CORE enter-ready structural alignment with acceptable relative strength and persistence.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.ENTER_LONG,
        )

    if (
        row.selection_state == "PRE_ALIGNMENT"
        and row.regime_ok
        and row.selection_score >= Decimal("0.50")
        and _rs_ok_prepare(row)
        and _mp_ok_prepare(row)
    ):
        quality = _prepare_quality_score(row)
        requested_fraction = _scale_prepare_fraction(Decimal("0.20"), quality)

        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.CORE,
            strategy_name="core_trend",
            desired_action=DecisionAction.PREPARE,
            requested_fraction=requested_fraction,
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="CORE prepare: early structural alignment with quality-scaled sizing.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.PREPARE,
        )

    if (
        row.selection_state == "EARLY_WATCH"
        and row.regime_ok
        and row.selection_score >= Decimal("0.60")
        and _rs_ok_prepare(row)
        and _mp_ok_prepare(row)
    ):
        quality = _prepare_quality_score(row)
        requested_fraction = _scale_prepare_fraction(Decimal("0.20"), quality)

        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.CORE,
            strategy_name="core_trend",
            desired_action=DecisionAction.PREPARE,
            requested_fraction=requested_fraction,
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="CORE prepare: softer early structural alignment with quality-scaled sizing.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.PREPARE,
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
    ):
        quality = _enter_quality_score(row)
        requested_fraction = _scale_enter_fraction(Decimal("0.05"), quality)

        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.SWING,
            strategy_name="swing_rotation",
            desired_action=DecisionAction.ENTER_LONG,
            requested_fraction=requested_fraction,
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="SWING enter-ready rotation setup with acceptable relative strength and persistence.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.ENTER_LONG,
        )

    if (
        row.selection_state == "PRE_ALIGNMENT"
        and row.regime_ok
        and row.selection_score >= Decimal("0.45")
        and _rs_ok_prepare(row)
        and _mp_ok_prepare(row)
    ):
        quality = _prepare_quality_score(row)
        requested_fraction = _scale_prepare_fraction(Decimal("0.05"), quality)

        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.SWING,
            strategy_name="swing_rotation",
            desired_action=DecisionAction.PREPARE,
            requested_fraction=requested_fraction,
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="SWING prepare: constructive multi-day setup with quality-scaled sizing.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.PREPARE,
        )

    if (
        row.selection_state == "EARLY_WATCH"
        and row.regime_ok
        and row.selection_score >= Decimal("0.55")
        and _rs_ok_prepare(row)
        and _mp_ok_prepare(row)
    ):
        quality = _prepare_quality_score(row)
        requested_fraction = _scale_prepare_fraction(Decimal("0.05"), quality)

        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.SWING,
            strategy_name="swing_rotation",
            desired_action=DecisionAction.PREPARE,
            requested_fraction=requested_fraction,
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="SWING prepare: early watch state with quality-scaled sizing.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.PREPARE,
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
            reasoning="TACTICAL momentum burst with acceptable relative strength and persistence.",
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
            reasoning="EXPERIMENTAL enter-ready candidate with strong relative strength and persistence.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.ENTER_LONG,
        )

    if (
        row.selection_state == "PRE_ALIGNMENT"
        and row.selection_score >= Decimal("0.65")
        and _rs_ok_enter(row)
        and _mp_ok_enter(row)
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
            reasoning="EXPERIMENTAL prepare candidate with strong relative strength and persistence.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.PREPARE,
        )

    if (
        row.selection_state == "TACTICAL"
        and row.selection_score >= Decimal("0.60")
        and _rs_ok_enter(row)
        and _mp_ok_enter(row)
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
            reasoning="EXPERIMENTAL tactical candidate with strong relative strength and persistence.",
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
