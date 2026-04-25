from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import yaml


QUALITY_PENALTY_DEFAULTS: dict[str, dict[str, Decimal]] = {
    "1d": {
        "TRUSTED": Decimal("0.00"),
        "NEW": Decimal("0.05"),
        "DEGRADED": Decimal("0.08"),
        "BLOCKED": Decimal("1.00"),
    },
    "4h": {
        "TRUSTED": Decimal("0.00"),
        "NEW": Decimal("0.00"),
        "DEGRADED": Decimal("0.05"),
        "BLOCKED": Decimal("1.00"),
    },
    "1h": {
        "TRUSTED": Decimal("0.00"),
        "NEW": Decimal("0.00"),
        "DEGRADED": Decimal("0.00"),
        "BLOCKED": Decimal("0.00"),
    },
}

WEIGHT_DEFAULTS: dict[str, Decimal] = {
    "context_score": Decimal("0.35"),
    "pullback_quality_score": Decimal("0.20"),
    "expansion_position_score": Decimal("0.20"),
    "signal_confidence": Decimal("0.15"),
    "relative_strength_score": Decimal("0.10"),
}

BUY_READY_MIN_SCORE_DEFAULT = Decimal("0.60")
PREPARE_MIN_SCORE_DEFAULT = Decimal("0.52")
BUY_READY_MAX_RANK_DEFAULT = 5
UNIVERSE_LIMIT_DEFAULT = 30

REFINEMENT_BONUS_DEFAULT = Decimal("0.03")
REFINEMENT_PENALTY_DEFAULT = Decimal("-0.05")


@dataclass(frozen=True)
class SelectionCandidate:
    asset_id: int
    symbol: str
    venue: str

    quality_status_1d: str
    quality_status_4h: str
    quality_status_1h: str

    trend_score_1d: Decimal
    setup_score_1d: Decimal
    signal_confidence_1d: Decimal
    risk_score_1d: Decimal

    volume_score_4h: Decimal
    compass_score_4h: Decimal
    setup_score_4h: Decimal
    relative_score_4h: Decimal
    signal_confidence_4h: Decimal
    expansion_position_score_4h: Decimal
    pullback_quality_score_4h: Decimal
    risk_score_4h: Decimal

    setup_score_1h: Decimal
    signal_confidence_1h: Decimal
    risk_score_1h: Decimal

    latest_quality_asof_ts_utc: str | None = None
    advice_ts_1h_utc: str | None = None
    advice_ts_4h_utc: str | None = None


@dataclass(frozen=True)
class SelectionRow:
    asset_id: int
    symbol: str
    venue: str
    asof_ts_utc: str | None

    advice_ts_1h_utc: str | None
    advice_ts_4h_utc: str | None

    quality_status_1d: str
    quality_status_4h: str
    quality_status_1h: str

    selection_state: str
    selection_bias: str
    selection_score: Decimal
    priority_rank: int | None

    allow_trade_flag: int
    allowed_sleeves: str
    blocked_reason: str | None
    summary: str

    trade_quality_score: Decimal
    relative_rank_score: Decimal
    timing_refinement_score: Decimal
    quality_penalty: Decimal


def _to_decimal(value: Any, default: str = "0.0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def load_selection_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ValueError("selection config root must be a mapping")

    return raw


def _penalty_for(interval_code: str, quality_status: str, config: dict[str, Any]) -> Decimal:
    penalties = config.get("quality", {}).get("penalties", {})
    interval_map = penalties.get(interval_code, {})
    if quality_status in interval_map:
        return _to_decimal(interval_map[quality_status])

    return QUALITY_PENALTY_DEFAULTS.get(interval_code, {}).get(
        quality_status,
        Decimal("0.0"),
    )


def _weights(config: dict[str, Any]) -> dict[str, Decimal]:
    weights_raw = config.get("weights", {})
    out = dict(WEIGHT_DEFAULTS)

    for key in WEIGHT_DEFAULTS:
        if key in weights_raw:
            out[key] = _to_decimal(weights_raw[key])

    return out


def _threshold_min_score(config: dict[str, Any], state_name: str) -> Decimal:
    thresholds = config.get("thresholds", {})
    state_cfg = thresholds.get(state_name, {})
    if state_name == "buy_ready":
        return _to_decimal(state_cfg.get("min_score", BUY_READY_MIN_SCORE_DEFAULT))
    if state_name == "prepare":
        return _to_decimal(state_cfg.get("min_score", PREPARE_MIN_SCORE_DEFAULT))
    raise ValueError(f"Unsupported threshold state: {state_name}")


def _buy_ready_max_rank(config: dict[str, Any]) -> int:
    thresholds = config.get("thresholds", {})
    buy_ready_cfg = thresholds.get("buy_ready", {})
    return int(buy_ready_cfg.get("max_rank", BUY_READY_MAX_RANK_DEFAULT))


def _universe_limit(config: dict[str, Any]) -> int:
    ranking = config.get("ranking", {})
    return int(ranking.get("universe_limit", UNIVERSE_LIMIT_DEFAULT))


def _refinement_bonus(config: dict[str, Any]) -> Decimal:
    return _to_decimal(
        config.get("refinement", {}).get("1h", {}).get("bonus", REFINEMENT_BONUS_DEFAULT)
    )


def _refinement_penalty(config: dict[str, Any]) -> Decimal:
    return _to_decimal(
        config.get("refinement", {}).get("1h", {}).get("penalty", REFINEMENT_PENALTY_DEFAULT)
    )


def _is_constructive_1d(candidate: SelectionCandidate) -> bool:
    if candidate.quality_status_1d == "BLOCKED":
        return False

    if candidate.quality_status_1d == "NEW":
        return True

    score_signals = 0
    if candidate.trend_score_1d >= Decimal("0.45"):
        score_signals += 1
    if candidate.setup_score_1d >= Decimal("0.45"):
        score_signals += 1
    if candidate.signal_confidence_1d >= Decimal("0.45"):
        score_signals += 1

    if candidate.risk_score_1d > Decimal("0.90"):
        return False

    return score_signals >= 1


def _is_bullish_1d(candidate: SelectionCandidate) -> bool:
    return (
        candidate.trend_score_1d >= Decimal("0.55")
        and candidate.setup_score_1d >= Decimal("0.50")
        and candidate.signal_confidence_1d >= Decimal("0.50")
        and candidate.risk_score_1d <= Decimal("0.80")
    )


def _is_constructive_4h(candidate: SelectionCandidate) -> bool:
    return (
        candidate.setup_score_4h >= Decimal("0.50")
        or candidate.signal_confidence_4h >= Decimal("0.52")
        or candidate.pullback_quality_score_4h >= Decimal("0.55")
        or candidate.compass_score_4h >= Decimal("0.55")
    )


def _context_proxy(candidate: SelectionCandidate) -> Decimal:
    return (
        candidate.compass_score_4h
        + candidate.setup_score_4h
        + candidate.volume_score_4h
    ) / Decimal("3.0")


def _trade_quality_score(candidate: SelectionCandidate, config: dict[str, Any]) -> Decimal:
    weights = _weights(config)

    context_score = _context_proxy(candidate)
    relative_strength_score = candidate.relative_score_4h

    score = (
        weights["context_score"] * context_score
        + weights["pullback_quality_score"] * candidate.pullback_quality_score_4h
        + weights["expansion_position_score"] * candidate.expansion_position_score_4h
        + weights["signal_confidence"] * candidate.signal_confidence_4h
        + weights["relative_strength_score"] * relative_strength_score
    )
    return score.quantize(Decimal("0.000001"))


def _timing_refinement_score(candidate: SelectionCandidate, config: dict[str, Any]) -> Decimal:
    if candidate.quality_status_1h == "BLOCKED":
        return Decimal("0.00")

    if (
        candidate.setup_score_1h >= Decimal("0.60")
        and candidate.signal_confidence_1h >= Decimal("0.55")
        and candidate.risk_score_1h <= Decimal("0.70")
    ):
        return _refinement_bonus(config)

    if (
        candidate.setup_score_1h < Decimal("0.40")
        or candidate.risk_score_1h > Decimal("0.80")
    ):
        return _refinement_penalty(config)

    if candidate.quality_status_1h == "DEGRADED":
        return Decimal("-0.01")

    return Decimal("0.00")


def _quality_penalty(candidate: SelectionCandidate, config: dict[str, Any]) -> Decimal:
    penalty = Decimal("0.00")
    penalty += _penalty_for("1d", candidate.quality_status_1d, config)
    penalty += _penalty_for("4h", candidate.quality_status_4h, config)
    return penalty


def _blocked_reason(candidate: SelectionCandidate) -> str | None:
    if candidate.quality_status_1d == "BLOCKED":
        return "BLOCKED_1D_QUALITY"
    if candidate.quality_status_4h == "BLOCKED":
        return "BLOCKED_4H_QUALITY"
    return None


def _selection_bias(candidate: SelectionCandidate, trade_quality_score: Decimal) -> str:
    if candidate.quality_status_1d == "BLOCKED" or candidate.quality_status_4h == "BLOCKED":
        return "AVOID"
    if _is_bullish_1d(candidate) and trade_quality_score >= Decimal("0.58"):
        return "BULLISH"
    if _is_constructive_1d(candidate) and trade_quality_score >= Decimal("0.48"):
        return "NEUTRAL_POSITIVE"
    if _is_constructive_1d(candidate):
        return "WATCH"
    return "DEFENSIVE"


def _max_state_for_new_assets(config: dict[str, Any]) -> str:
    return str(
        config.get("states", {})
        .get("new_asset_rules", {})
        .get("max_state", "PREPARE")
    ).upper()


def _clamp_state_for_new_asset(
    state_name: str,
    candidate: SelectionCandidate,
    config: dict[str, Any],
) -> str:
    if candidate.quality_status_1d != "NEW":
        return state_name

    max_state = _max_state_for_new_assets(config)
    order = ["AVOID", "NEUTRAL", "WATCHLIST", "PREPARE", "BUY_READY"]
    target_idx = order.index(state_name)
    max_idx = order.index(max_state) if max_state in order else order.index("PREPARE")
    return order[min(target_idx, max_idx)]


def _prepare_context_ok(candidate: SelectionCandidate) -> bool:
    if candidate.quality_status_1d == "BLOCKED":
        return False
    if candidate.quality_status_4h == "BLOCKED":
        return False
    if not _is_constructive_1d(candidate):
        return False
    if not _is_constructive_4h(candidate):
        return False
    return True


def _buy_ready_context_ok(candidate: SelectionCandidate) -> bool:
    if candidate.quality_status_1d != "TRUSTED":
        return False
    if candidate.quality_status_4h != "TRUSTED":
        return False
    if not _is_bullish_1d(candidate):
        return False
    if not _is_constructive_4h(candidate):
        return False
    return True


def _state_from_score(
    candidate: SelectionCandidate,
    selection_score: Decimal,
    blocked_reason: str | None,
    config: dict[str, Any],
) -> str:
    if blocked_reason is not None:
        return "AVOID"

    if not _is_constructive_1d(candidate):
        if selection_score >= Decimal("0.45"):
            return "WATCHLIST"
        if selection_score >= Decimal("0.30"):
            return "NEUTRAL"
        return "AVOID"

    if not _is_constructive_4h(candidate):
        if selection_score >= Decimal("0.45"):
            return _clamp_state_for_new_asset("WATCHLIST", candidate, config)
        if selection_score >= Decimal("0.30"):
            return "NEUTRAL"
        return "AVOID"

    buy_ready_min = _threshold_min_score(config, "buy_ready")
    prepare_min = _threshold_min_score(config, "prepare")

    if _buy_ready_context_ok(candidate) and selection_score >= buy_ready_min:
        state_name = "BUY_READY"
    elif _prepare_context_ok(candidate) and selection_score >= prepare_min:
        state_name = "PREPARE"
    elif selection_score >= Decimal("0.42"):
        state_name = "WATCHLIST"
    elif selection_score >= Decimal("0.30"):
        state_name = "NEUTRAL"
    else:
        state_name = "AVOID"

    return _clamp_state_for_new_asset(state_name, candidate, config)


def _allowed_sleeves(candidate: SelectionCandidate, state_name: str) -> str:
    sleeves: list[str] = []

    if (
        state_name in {"BUY_READY", "PREPARE"}
        and candidate.quality_status_1d == "TRUSTED"
        and candidate.quality_status_4h == "TRUSTED"
        and _is_bullish_1d(candidate)
    ):
        sleeves.append("CORE_STRUCTURAL")

    if (
        state_name in {"BUY_READY", "PREPARE", "WATCHLIST"}
        and candidate.quality_status_1d in {"TRUSTED", "NEW", "DEGRADED"}
        and candidate.quality_status_4h != "BLOCKED"
    ):
        sleeves.append("SWING_STRUCTURAL")

    if (
        state_name in {"BUY_READY", "PREPARE", "WATCHLIST"}
        and candidate.quality_status_4h != "BLOCKED"
    ):
        sleeves.append("TACTICAL_PULSE")

    if (
        state_name != "AVOID"
        and candidate.quality_status_1d != "BLOCKED"
        and candidate.quality_status_4h != "BLOCKED"
    ):
        sleeves.append("EXPERIMENTAL")

    return ",".join(sleeves)


def _summary(
    candidate: SelectionCandidate,
    state_name: str,
    selection_score: Decimal,
    priority_rank: int | None,
    allowed_sleeves: str,
    blocked_reason: str | None,
) -> str:
    parts = [
        f"1d={candidate.quality_status_1d}",
        f"4h={candidate.quality_status_4h}",
        f"1h={candidate.quality_status_1h}",
        f"state={state_name}",
        f"score={selection_score}",
    ]

    if priority_rank is not None:
        parts.append(f"rank={priority_rank}")
    if allowed_sleeves:
        parts.append(f"sleeves={allowed_sleeves}")
    if blocked_reason:
        parts.append(f"reason={blocked_reason}")

    return "; ".join(parts)


def rank_candidates(
    candidates: list[SelectionCandidate],
    config: dict[str, Any],
) -> list[SelectionRow]:
    staged_rows: list[dict[str, Any]] = []

    for candidate in candidates:
        trade_quality_score = _trade_quality_score(candidate, config)
        timing_refinement_score = _timing_refinement_score(candidate, config)
        quality_penalty = _quality_penalty(candidate, config)
        blocked_reason = _blocked_reason(candidate)

        selection_score = (
            trade_quality_score
            + timing_refinement_score
            - quality_penalty
        ).quantize(Decimal("0.000001"))

        state_name = _state_from_score(
            candidate=candidate,
            selection_score=selection_score,
            blocked_reason=blocked_reason,
            config=config,
        )

        staged_rows.append(
            {
                "candidate": candidate,
                "trade_quality_score": trade_quality_score,
                "timing_refinement_score": timing_refinement_score,
                "quality_penalty": quality_penalty,
                "selection_score": selection_score,
                "blocked_reason": blocked_reason,
                "state_name": state_name,
            }
        )

    staged_rows.sort(
        key=lambda item: (
            item["state_name"] == "AVOID",
            -item["selection_score"],
            item["candidate"].symbol,
        )
    )

    universe_limit = _universe_limit(config)
    buy_ready_max_rank = _buy_ready_max_rank(config)

    output: list[SelectionRow] = []
    rank_counter = 0

    for item in staged_rows:
        candidate = item["candidate"]
        state_name = item["state_name"]
        selection_score = item["selection_score"]
        blocked_reason = item["blocked_reason"]

        if state_name != "AVOID":
            rank_counter += 1
            priority_rank: int | None = rank_counter
        else:
            priority_rank = None

        relative_rank_score = Decimal("0.0")
        if priority_rank is not None and universe_limit > 0:
            relative_rank_score = (
                Decimal(universe_limit - min(priority_rank, universe_limit) + 1)
                / Decimal(universe_limit)
            ).quantize(Decimal("0.000001"))

        allow_trade_flag = 0
        if (
            state_name == "BUY_READY"
            and priority_rank is not None
            and priority_rank <= buy_ready_max_rank
            and selection_score >= _threshold_min_score(config, "buy_ready")
            and _buy_ready_context_ok(candidate)
        ):
            allow_trade_flag = 1
        elif (
            state_name == "PREPARE"
            and priority_rank is not None
            and priority_rank <= buy_ready_max_rank
            and selection_score >= _threshold_min_score(config, "prepare")
            and _prepare_context_ok(candidate)
        ):
            allow_trade_flag = 1

        allowed_sleeves = _allowed_sleeves(candidate, state_name)

        if allow_trade_flag == 0 and state_name == "BUY_READY":
            blocked_reason = blocked_reason or "BLOCKED_PRIORITY_TOO_LOW_OR_CONTEXT_INVALID"

        if allow_trade_flag == 0 and state_name == "PREPARE" and blocked_reason is None:
            if priority_rank is not None and priority_rank > buy_ready_max_rank:
                blocked_reason = "BLOCKED_PRIORITY_TOO_LOW"
            else:
                blocked_reason = "BLOCKED_CONTEXT_INVALID"

        selection_bias = _selection_bias(candidate, item["trade_quality_score"])
        summary = _summary(
            candidate=candidate,
            state_name=state_name,
            selection_score=selection_score,
            priority_rank=priority_rank,
            allowed_sleeves=allowed_sleeves,
            blocked_reason=blocked_reason,
        )

        output.append(
            SelectionRow(
                asset_id=candidate.asset_id,
                symbol=candidate.symbol,
                venue=candidate.venue,
                asof_ts_utc=candidate.latest_quality_asof_ts_utc,
                advice_ts_1h_utc=candidate.advice_ts_1h_utc,
                advice_ts_4h_utc=candidate.advice_ts_4h_utc,
                quality_status_1d=candidate.quality_status_1d,
                quality_status_4h=candidate.quality_status_4h,
                quality_status_1h=candidate.quality_status_1h,
                selection_state=state_name,
                selection_bias=selection_bias,
                selection_score=selection_score,
                priority_rank=priority_rank,
                allow_trade_flag=allow_trade_flag,
                allowed_sleeves=allowed_sleeves,
                blocked_reason=blocked_reason,
                summary=summary,
                trade_quality_score=item["trade_quality_score"],
                relative_rank_score=relative_rank_score,
                timing_refinement_score=item["timing_refinement_score"],
                quality_penalty=item["quality_penalty"],
            )
        )

    return output
