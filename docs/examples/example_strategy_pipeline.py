# =============================================================================
# File: example_usage.py
# Boundary: DEMO — replace data loader with your Bitvavo ETL.
# =============================================================================

import pandas as pd

from regime import compute_daily_regime, RegimeConfig
from signals import generate_signals_4h, SignalConfig4H


def main(ohlcv_1d: pd.DataFrame, ohlcv_4h: pd.DataFrame) -> None:
    # Both DataFrames must have UTC tz-aware DatetimeIndex and columns:
    # open, high, low, close, volume

    daily = compute_daily_regime(ohlcv_1d, RegimeConfig())
    sigs = generate_signals_4h(ohlcv_4h, daily, SignalConfig4H())

    print("Daily regime:", daily)
    for s in sigs:
        print(s)


# You’d call main(...) after your candle fetch + feature pipeline.
