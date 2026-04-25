"""
execution_context_policy.py

Purpose:
Translate market context (regime, fib, volatility) into
execution preferences for the execution planner.

This layer is:
- market-only (no account info)
- deterministic
- stateless

Input:
- regime_label (TREND_UP / RANGE / TREND_DOWN)
- fib value (string or None)
- volatility_bucket (LOW / MID / HIGH)

Output:
- effective_fib_primary
- effective_fib_secondary
- execution_profile
- adjusted_score_multiplier
"""

from typing import Optional, Dict


def resolve_execution_context(
    regime: str,
    fib: Optional[str],
    volatility: Optional[str],
) -> Dict:
    """
    Main policy resolver
    """

    regime = (regime or "").upper()
    volatility = (volatility or "MID").upper()
    fib = fib or None

    # --- REGIME DEFAULTS ---

    if regime == "TREND_UP":
        primary_fib = "0.500000"
        secondary_fib = "0.786000"
        discouraged = {"0.618000"}

    elif regime == "RANGE":
        primary_fib = "0.786000"
        secondary_fib = "0.500000"
        discouraged = {"0.618000"}

    elif regime == "TREND_DOWN":
        return {
            "enabled": False,
            "execution_profile": "DEFENSIVE_SKIP",
            "effective_fib_primary": None,
            "effective_fib_secondary": None,
            "score_multiplier": 0.35,
        }

    else:
        return {
            "enabled": False,
            "execution_profile": "UNKNOWN",
            "effective_fib_primary": None,
            "effective_fib_secondary": None,
            "score_multiplier": 0.0,
        }

    # --- FIB SCORING ---

    fib_bonus = 0.0

    if fib == primary_fib:
        fib_bonus += 0.12
    elif fib == secondary_fib:
        fib_bonus += 0.06
    elif fib in discouraged:
        fib_bonus -= 0.05

    # --- VOLATILITY PROFILE ---

    if regime == "TREND_UP":

        if volatility == "LOW":
            execution_profile = "TREND_UP_LOW_VOL"
            vol_multiplier = 0.95

        elif volatility == "MID":
            execution_profile = "TREND_UP_MID_VOL"
            vol_multiplier = 1.00

        else:  # HIGH
            execution_profile = "TREND_UP_HIGH_VOL"
            vol_multiplier = 0.90

    elif regime == "RANGE":

        if volatility == "LOW":
            execution_profile = "RANGE_LOW_VOL"
            vol_multiplier = 0.95

        elif volatility == "MID":
            execution_profile = "RANGE_MID_VOL"
            vol_multiplier = 1.00

        else:  # HIGH
            execution_profile = "RANGE_HIGH_VOL"
            vol_multiplier = 0.90

    else:
        execution_profile = "UNKNOWN"
        vol_multiplier = 0.0

    # --- FINAL SCORE MULTIPLIER ---

    regime_weight = {
        "TREND_UP": 1.0,
        "RANGE": 0.85,
    }.get(regime, 0.0)

    score_multiplier = regime_weight * vol_multiplier + fib_bonus

    return {
        "enabled": True,
        "execution_profile": execution_profile,
        "effective_fib_primary": primary_fib,
        "effective_fib_secondary": secondary_fib,
        "score_multiplier": round(score_multiplier, 4),
    }
