# -*- coding: utf-8 -*-

"""
range_state.py

Range State v1
--------------

Objectieve meting van:
- is markt in range?
- waar zit prijs binnen die range?
- is range aan het breken?

Geen trading logica. Pure measurement.
"""

from typing import List, Dict, Tuple, Optional

def compute_range_state(
    candles: List[Dict[str, float]],
    lookback: int = 20
) -> Tuple[Optional[str], Optional[float]]:
    """
    candles: lijst van dicts met keys:
        - high
        - low
        - close

    returns:
        (range_state, range_score)
    """

    if not candles or len(candles) < lookback:
        return None, None

    window = candles[-lookback:]

    highs = [c["high"] for c in window]
    lows = [c["low"] for c in window]
    closes = [c["close"] for c in window]

    range_high = max(highs)
    range_low = min(lows)
    range_width = range_high - range_low

    if range_width <= 0:
        return "NO_RANGE", 0.0

    current_close = closes[-1]

    # --- ATR (simple v1)
    trs = []
    for i in range(1, len(window)):
        h = window[i]["high"]
        l = window[i]["low"]
        pc = window[i - 1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)

    atr = sum(trs) / len(trs) if trs else 0

    if atr == 0:
        return "NO_RANGE", 0.0

    range_width_atr_ratio = range_width / atr

    # --- positie binnen range
    close_pos = (current_close - range_low) / range_width

    # --- BREAK detectie
    if current_close > range_high + 0.25 * atr:
        return "RANGE_BREAKING", 0.5

    if current_close < range_low - 0.25 * atr:
        return "RANGE_BREAKING", 0.5

    # --- NO_RANGE heuristiek
    if range_width_atr_ratio < 1.5:
        return "NO_RANGE", 0.2

    # --- positie classificatie
    if close_pos <= 0.20:
        state = "RANGE_LOW_EDGE"
    elif close_pos >= 0.80:
        state = "RANGE_HIGH_EDGE"
    else:
        state = "IN_RANGE"

    # --- simpele confidence score
    score = min(1.0, range_width_atr_ratio / 6.0)

    return state, round(score, 6)


# simpele test
if __name__ == "__main__":
    test_candles = [
        {"high": 10, "low": 9, "close": 9.5},
        {"high": 10.2, "low": 9.1, "close": 9.8},
        {"high": 10.1, "low": 9.2, "close": 9.7},
        {"high": 10.3, "low": 9.0, "close": 9.6},
        {"high": 10.4, "low": 9.3, "close": 9.9},
        {"high": 10.2, "low": 9.1, "close": 9.7},
        {"high": 10.3, "low": 9.2, "close": 9.8},
        {"high": 10.1, "low": 9.0, "close": 9.6},
        {"high": 10.2, "low": 9.1, "close": 9.7},
        {"high": 10.3, "low": 9.2, "close": 9.8},
        {"high": 10.1, "low": 9.0, "close": 9.6},
        {"high": 10.2, "low": 9.1, "close": 9.7},
        {"high": 10.3, "low": 9.2, "close": 9.8},
        {"high": 10.1, "low": 9.0, "close": 9.6},
        {"high": 10.2, "low": 9.1, "close": 9.7},
        {"high": 10.3, "low": 9.2, "close": 9.8},
        {"high": 10.1, "low": 9.0, "close": 9.6},
        {"high": 10.2, "low": 9.1, "close": 9.7},
        {"high": 10.3, "low": 9.2, "close": 9.8},
        {"high": 10.1, "low": 9.0, "close": 9.6},
    ]

    state, score = compute_range_state(test_candles)
    print("state:", state, "score:", score)
