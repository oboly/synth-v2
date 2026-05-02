from __future__ import annotations

DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL = "1h"

SUPPORTED_INTERVALS = ["1h", "4h", "1d"]

MAX_CANDLES_DEFAULT = 2500

PRICE_OVERLAYS = {
    "ema_20": "EMA 20",
    "ema_50": "EMA 50",
}

FEATURE_COLUMNS = [
    "ema_20",
    "ema_50",
    "rsi_14",
    "atr_14",
    "volume_ratio_20",
    "volume_zscore_20",
    "price_vs_ema20",
    "price_vs_ema50",
    "atr_pct",
    "ema_spread_pct",
    "wick_reversal_score",
]

SIGNAL_COLUMNS = [
    "trend_signal",
    "volume_signal",
    "phase_signal",
    "compass_signal",
    "rotation_signal",
    "relative_signal",
    "setup_signal",
    "risk_signal",
    "signal_confidence",
    "reason_code",
    "reason_text",
    "expansion_position_score",
    "pullback_quality_score",
    "late_trend_flag",
]

SELECTION_COLUMNS = [
    "selection_state",
    "selection_bias",
    "selection_score",
    "priority_rank",
    "regime_label_1h",
    "regime_label_4h",
    "advice_state_1h",
    "advice_state_4h",
    "summary_text",
]

PROFILE_COLUMNS = [
    "liquidity_score",
    "liquidity_class",
    "beta_to_market",
    "beta_profile",
    "realized_volatility",
    "sector_group_code",
    "sector_confidence",
    "coverage_ratio",
]
