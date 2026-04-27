from __future__ import annotations

"""
Synth v2 - Trade Setup Filter V1 engine.

LAYER:
market-only setup/context filter

BOUNDARY:
Allowed:
- selection state
- ranking position
- BTC market context
- market-only asset suitability candidate

Forbidden:
- account balances
- positions
- open orders
- execution plans
- broker/order logic
"""

from decimal import Decimal

from src.trade_setup_filter.models import TradeSetupCandidate, TradeSetupDecision


DEFAULT_SELECTION_STATE = "WATCHLIST"
DEFAULT_RANK_MIN = 4
DEFAULT_RANK_MAX = 10
DEFAULT_BTC_PRIOR_MIN = Decimal("-0.015")
DEFAULT_BTC_PRIOR_MAX = Decimal("0.015")
DEFAULT_TARGET_HORIZON = "24H"

CANDIDATE_WEAK_SET = frozenset(
    {
        "HNT",
        "SOL",
        "XLM",
        "LTC",
        "ETH",
        "XRP",
        "CC",
        "NOT",
    }
)


def evaluate_trade_setup(
    candidate: TradeSetupCandidate,
    *,
    required_selection_state: str = DEFAULT_SELECTION_STATE,
    rank_min: int = DEFAULT_RANK_MIN,
    rank_max: int = DEFAULT_RANK_MAX,
    btc_prior_min: Decimal = DEFAULT_BTC_PRIOR_MIN,
    btc_prior_max: Decimal = DEFAULT_BTC_PRIOR_MAX,
    asset_suitability_mode: str = "off",
) -> TradeSetupDecision:
    setup_filter_state = "FAIL"
    setup_filter_reason = "UNKNOWN"

    if candidate.selection_state != required_selection_state:
        setup_filter_reason = "SELECTION_STATE_NOT_ELIGIBLE"

    elif candidate.priority_rank is None:
        setup_filter_reason = "PRIORITY_RANK_MISSING"

    elif candidate.priority_rank < rank_min or candidate.priority_rank > rank_max:
        setup_filter_reason = "RANK_OUTSIDE_SWEET_SPOT"

    elif candidate.btc_prior_24h is None:
        setup_filter_reason = "BTC_PRIOR_24H_MISSING"

    elif candidate.btc_prior_24h < btc_prior_min:
        setup_filter_reason = "MARKET_DAMAGE_RISK"

    elif candidate.btc_prior_24h > btc_prior_max:
        setup_filter_reason = "BTC_PRIOR_OVERHEAT_ZONE"

    elif (
        asset_suitability_mode == "candidate_weak_set"
        and candidate.symbol in CANDIDATE_WEAK_SET
    ):
        setup_filter_reason = "ASSET_SUITABILITY_WEAK_SET_CANDIDATE"

    else:
        setup_filter_state = "PASS"
        setup_filter_reason = "RANK_AND_MARKET_CONTEXT_OK"

    notes = (
        f"state={candidate.selection_state}; "
        f"rank={candidate.priority_rank}; "
        f"btc_prior_24h={candidate.btc_prior_24h}; "
        f"asset_suitability_mode={asset_suitability_mode}"
    )

    return TradeSetupDecision(
        asset_id=candidate.asset_id,
        symbol=candidate.symbol,
        venue=candidate.venue,
        asof_ts_utc=candidate.asof_ts_utc,
        context_ts_utc=candidate.context_ts_utc,
        selection_state=candidate.selection_state,
        selection_bias=candidate.selection_bias,
        selection_score=candidate.selection_score,
        priority_rank=candidate.priority_rank,
        allowed_sleeves=candidate.allowed_sleeves,
        btc_prior_24h=candidate.btc_prior_24h,
        setup_filter_state=setup_filter_state,
        setup_filter_reason=setup_filter_reason,
        target_horizon=DEFAULT_TARGET_HORIZON if setup_filter_state == "PASS" else "NONE",
        notes=notes,
    )
