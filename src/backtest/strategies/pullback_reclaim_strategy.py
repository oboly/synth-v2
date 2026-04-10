from __future__ import annotations

import pandas as pd


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def _atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high_low = df["high_price"] - df["low_price"]
    high_close = (df["high_price"] - df["close_price"].shift(1)).abs()
    low_close = (df["low_price"] - df["close_price"].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


class PullbackReclaimStrategy:
    name = "pullback_reclaim_v1"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()

        out["ema20"] = _ema(out["close_price"], 20)
        out["ema50"] = _ema(out["close_price"], 50)
        out["ema200"] = _ema(out["close_price"], 200)
        out["atr14"] = _atr(out, 14)
        out["atr_pct"] = (out["atr14"] / out["close_price"]) * 100.0
        out["ema200_slope"] = out["ema200"] - out["ema200"].shift(10)

        out["trend_up"] = (
            (out["close_price"] > out["ema200"])
            & (out["ema20"] > out["ema50"])
            & (out["ema200_slope"] > 0)
        )

        out["pullback_seen"] = (
            out["trend_up"]
            & (out["close_price"] < out["ema20"])
            & (out["close_price"] > out["ema50"])
        )

        out["entry_long"] = (
            out["pullback_seen"].shift(1).fillna(False)
            & out["trend_up"]
            & (out["close_price"] > out["ema20"])
        )

        out["exit_long"] = (
            (out["close_price"] < out["ema50"])
            & (out["ema20"] < out["ema50"])
        )

        return out

    def should_enter_long(self, row: pd.Series) -> bool:
        return bool(row["entry_long"])

    def should_exit_long(self, row: pd.Series) -> tuple[bool, str]:
        if bool(row["exit_long"]):
            return True, "close_below_ema50_and_ema20_below_ema50"
        return False, ""
