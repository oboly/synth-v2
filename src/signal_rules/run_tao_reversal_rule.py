from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from src.common.db import get_connection


RULE_NAME = "tao_reversal_v1"


@dataclass
class CandleColumns:
    open_ts: str
    close_ts: str
    close_px: str
    high_px: str
    low_px: str
    volume_q: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TAO reversal state rule.")
    parser.add_argument("--symbol", default="TAO")
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--floor-eur", type=float, default=150.0)
    parser.add_argument("--breakout-eur", type=float, default=300.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def choose_first(existing: set[str], candidates: Iterable[str]) -> str:
    for name in candidates:
        if name in existing:
            return name
    raise RuntimeError(f"Could not find any of expected columns: {list(candidates)}")


def detect_candle_columns(conn) -> CandleColumns:
    query = """
    SELECT COLUMN_NAME
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'obs_market_candle'
    """
    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()

    existing = {row["COLUMN_NAME"] for row in rows}
    return CandleColumns(
        open_ts=choose_first(existing, ["open_ts_utc"]),
        close_ts=choose_first(existing, ["close_ts_utc"]),
        close_px=choose_first(existing, ["close_price_eur", "close_eur", "close_price", "close"]),
        high_px=choose_first(existing, ["high_price_eur", "high_eur", "high_price", "high"]),
        low_px=choose_first(existing, ["low_price_eur", "low_eur", "low_price", "low"]),
        volume_q=choose_first(existing, ["volume_quote_eur", "volume_quote", "quote_volume", "volume"]),
    )


def resolve_asset_id(conn, symbol: str, asset_id: int | None) -> int:
    if asset_id is not None:
        return asset_id

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT asset_id
            FROM asset
            WHERE symbol = %s
            ORDER BY asset_id
            LIMIT 1
            """,
            (symbol,),
        )
        row = cur.fetchone()

    if not row:
        raise RuntimeError(
            f"Could not resolve asset_id for symbol={symbol}. "
            "Pass --asset-id explicitly."
        )
    return int(row["asset_id"])


def load_candles(
    conn,
    cols: CandleColumns,
    asset_id: int,
    venue: str,
    interval_code: str,
    limit_rows: int,
) -> pd.DataFrame:
    query = f"""
    SELECT
        {cols.open_ts} AS open_ts_utc,
        {cols.close_ts} AS close_ts_utc,
        {cols.close_px} AS close_eur,
        {cols.high_px} AS high_eur,
        {cols.low_px} AS low_eur,
        {cols.volume_q} AS volume_quote_eur
    FROM obs_market_candle
    WHERE asset_id = %s
      AND venue = %s
      AND interval_code = %s
    ORDER BY open_ts_utc DESC
    LIMIT %s
    """

    with conn.cursor() as cur:
        cur.execute(query, (asset_id, venue, interval_code, limit_rows))
        rows = cur.fetchall()

    if not rows:
        raise RuntimeError(f"No candles found for asset_id={asset_id} interval={interval_code}")

    df = pd.DataFrame(rows)

    required_cols = [
        "open_ts_utc",
        "close_ts_utc",
        "close_eur",
        "high_eur",
        "low_eur",
        "volume_quote_eur",
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise RuntimeError(
            f"Missing expected columns after fetch for interval={interval_code}: {missing}. "
            f"Columns present: {list(df.columns)}"
        )

    for col in ["close_eur", "high_eur", "low_eur", "volume_quote_eur"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["open_ts_utc"] = pd.to_datetime(df["open_ts_utc"], errors="coerce")
    df["close_ts_utc"] = pd.to_datetime(df["close_ts_utc"], errors="coerce")

    bad_rows = df[
        df["open_ts_utc"].isna()
        | df["close_ts_utc"].isna()
        | df["close_eur"].isna()
        | df["high_eur"].isna()
        | df["low_eur"].isna()
    ]
    if not bad_rows.empty:
        sample = bad_rows.head(5).to_dict(orient="records")
        raise RuntimeError(
            f"Failed to normalize candle rows for interval={interval_code}. "
            f"Sample bad rows: {sample}"
        )

    df = df.sort_values("open_ts_utc").reset_index(drop=True)
    return df


def find_pivots(series: pd.Series, left: int = 2, right: int = 2, mode: str = "high") -> list[tuple[int, float]]:
    values = series.to_numpy(dtype=float)
    pivots: list[tuple[int, float]] = []
    for i in range(left, len(values) - right):
        window = values[i - left : i + right + 1]
        center = values[i]
        if mode == "high":
            if center == np.max(window) and np.sum(window == center) == 1:
                pivots.append((i, center))
        else:
            if center == np.min(window) and np.sum(window == center) == 1:
                pivots.append((i, center))
    return pivots


def has_hh_hl(df: pd.DataFrame) -> bool:
    highs = find_pivots(df["high_eur"], mode="high")
    lows = find_pivots(df["low_eur"], mode="low")
    if len(highs) < 2 or len(lows) < 2:
        return False
    last_two_highs = highs[-2:]
    last_two_lows = lows[-2:]
    return (last_two_highs[-1][1] > last_two_highs[-2][1]) and (last_two_lows[-1][1] > last_two_lows[-2][1])


def holds_above_ema(series: pd.Series, ema: pd.Series, candles: int) -> bool:
    if len(series) < candles or len(ema) < candles:
        return False
    return bool((series.iloc[-candles:] > ema.iloc[-candles:]).all())


def detect_volume_signal(df_1d: pd.DataFrame) -> str:
    if len(df_1d) < 8:
        return "UNKNOWN"

    recent = df_1d.iloc[-6:].copy()
    recent["delta"] = recent["close_eur"].diff().fillna(0.0)

    up = recent.loc[recent["delta"] > 0, "volume_quote_eur"].sum()
    down = recent.loc[recent["delta"] <= 0, "volume_quote_eur"].sum()

    if up > down * 1.20:
        return "STRONG_CONFIRMATION"
    if up > down:
        return "CONFIRMING"
    return "WEAK"


def detect_rejection_event_htf(df_1d: pd.DataFrame, breakout_eur: float) -> bool:
    if len(df_1d) < 2:
        return False

    row = df_1d.iloc[-1]
    prev = df_1d.iloc[-2]

    body = abs(float(row["close_eur"]) - float(prev["close_eur"]))
    upper_wick = float(row["high_eur"]) - float(row["close_eur"])

    return bool(float(row["high_eur"]) > breakout_eur and upper_wick > max(body, 0.0000001) * 1.5)


def compute_state(
    df_1d: pd.DataFrame,
    df_4h: pd.DataFrame,
    floor_eur: float,
    breakout_eur: float,
) -> dict:
    df_1d = df_1d.copy()
    df_4h = df_4h.copy()

    df_1d["ema50_1d"] = df_1d["close_eur"].ewm(span=50, adjust=False).mean()
    df_1d["ema200_1d"] = df_1d["close_eur"].ewm(span=200, adjust=False).mean()

    close_1d = float(df_1d.iloc[-1]["close_eur"])
    close_4h = float(df_4h.iloc[-1]["close_eur"])
    ema50_1d = float(df_1d.iloc[-1]["ema50_1d"])
    ema200_1d = float(df_1d.iloc[-1]["ema200_1d"])
    asof_ts_utc = pd.Timestamp(df_1d.iloc[-1]["close_ts_utc"]).to_pydatetime()

    hh_hl_1d = has_hh_hl(df_1d.iloc[-120:].reset_index(drop=True))
    hh_hl_4h = has_hh_hl(df_4h.iloc[-120:].reset_index(drop=True))
    hl_above_floor = bool(float(df_4h.iloc[-20:]["low_eur"].min()) >= floor_eur)
    above_ema50 = holds_above_ema(df_1d["close_eur"], df_1d["ema50_1d"], candles=3)
    breakout_above_300 = bool(close_1d > breakout_eur)
    volume_signal = detect_volume_signal(df_1d)
    rejection_event_htf = detect_rejection_event_htf(df_1d, breakout_eur)

    if (
        breakout_above_300
        and close_1d > ema200_1d
        and hh_hl_1d
        and hh_hl_4h
        and volume_signal in {"CONFIRMING", "STRONG_CONFIRMATION"}
        and not rejection_event_htf
    ):
        state_code = "BULL"
        rule_score = 1.0
    elif (
        hl_above_floor
        and above_ema50
        and hh_hl_4h
        and volume_signal in {"CONFIRMING", "STRONG_CONFIRMATION"}
    ):
        state_code = "PREPARE"
        rule_score = 0.60
    else:
        state_code = "BEAR"
        rule_score = 0.20

    notes = (
        f"close_1d={close_1d:.6f}; ema50_1d={ema50_1d:.6f}; ema200_1d={ema200_1d:.6f}; "
        f"hh_hl_1d={int(hh_hl_1d)}; hh_hl_4h={int(hh_hl_4h)}; "
        f"hl_above_floor={int(hl_above_floor)}; above_ema50={int(above_ema50)}; "
        f"breakout_above_300={int(breakout_above_300)}; volume_signal={volume_signal}; "
        f"rejection_event_htf={int(rejection_event_htf)}"
    )

    return {
        "asof_ts_utc": asof_ts_utc,
        "state_code": state_code,
        "rule_score": rule_score,
        "close_1d_eur": close_1d,
        "ema50_1d": ema50_1d,
        "ema200_1d": ema200_1d,
        "close_4h_eur": close_4h,
        "has_hh_hl_1d": int(hh_hl_1d),
        "has_hh_hl_4h": int(hh_hl_4h),
        "hl_above_floor": int(hl_above_floor),
        "holds_above_ema50_1d": int(above_ema50),
        "breakout_above_300": int(breakout_above_300),
        "volume_signal": volume_signal,
        "rejection_event_htf": int(rejection_event_htf),
        "notes": notes,
    }


def write_state(conn, asset_id: int, venue: str, state: dict) -> None:
    query = """
    INSERT INTO signal_rule_state (
        asset_id,
        venue,
        rule_name,
        asof_ts_utc,
        state_code,
        rule_score,
        close_1d_eur,
        ema50_1d,
        ema200_1d,
        close_4h_eur,
        has_hh_hl_1d,
        has_hh_hl_4h,
        hl_above_floor,
        holds_above_ema50_1d,
        breakout_above_300,
        volume_signal,
        rejection_event_htf,
        notes
    ) VALUES (
        %(asset_id)s,
        %(venue)s,
        %(rule_name)s,
        %(asof_ts_utc)s,
        %(state_code)s,
        %(rule_score)s,
        %(close_1d_eur)s,
        %(ema50_1d)s,
        %(ema200_1d)s,
        %(close_4h_eur)s,
        %(has_hh_hl_1d)s,
        %(has_hh_hl_4h)s,
        %(hl_above_floor)s,
        %(holds_above_ema50_1d)s,
        %(breakout_above_300)s,
        %(volume_signal)s,
        %(rejection_event_htf)s,
        %(notes)s
    )
    ON DUPLICATE KEY UPDATE
        state_code = VALUES(state_code),
        rule_score = VALUES(rule_score),
        close_1d_eur = VALUES(close_1d_eur),
        ema50_1d = VALUES(ema50_1d),
        ema200_1d = VALUES(ema200_1d),
        close_4h_eur = VALUES(close_4h_eur),
        has_hh_hl_1d = VALUES(has_hh_hl_1d),
        has_hh_hl_4h = VALUES(has_hh_hl_4h),
        hl_above_floor = VALUES(hl_above_floor),
        holds_above_ema50_1d = VALUES(holds_above_ema50_1d),
        breakout_above_300 = VALUES(breakout_above_300),
        volume_signal = VALUES(volume_signal),
        rejection_event_htf = VALUES(rejection_event_htf),
        notes = VALUES(notes)
    """
    payload = {
        "asset_id": asset_id,
        "venue": venue,
        "rule_name": RULE_NAME,
        **state,
    }
    with conn.cursor() as cur:
        cur.execute(query, payload)
    conn.commit()


def main() -> None:
    args = parse_args()
    conn = get_connection()
    try:
        cols = detect_candle_columns(conn)
        asset_id = resolve_asset_id(conn, args.symbol, args.asset_id)

        df_1d = load_candles(
            conn=conn,
            cols=cols,
            asset_id=asset_id,
            venue=args.venue,
            interval_code="1d",
            limit_rows=320,
        )
        df_4h = load_candles(
            conn=conn,
            cols=cols,
            asset_id=asset_id,
            venue=args.venue,
            interval_code="4h",
            limit_rows=320,
        )

        state = compute_state(
            df_1d=df_1d,
            df_4h=df_4h,
            floor_eur=args.floor_eur,
            breakout_eur=args.breakout_eur,
        )

        print(
            f"[TAO_RULE] asset_id={asset_id} venue={args.venue} "
            f"asof={state['asof_ts_utc']} state={state['state_code']} "
            f"score={state['rule_score']:.2f}"
        )
        print(f"[TAO_RULE] {state['notes']}")

        if not args.dry_run:
            write_state(conn, asset_id=asset_id, venue=args.venue, state=state)
            print("[TAO_RULE] state written to signal_rule_state")
        else:
            print("[TAO_RULE] dry-run; nothing written")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
