#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os

import pandas as pd
import pymysql
from dotenv import load_dotenv


RULE_NAME_TAO = "tao_reversal_v1"
TAO_SYMBOL = "TAO"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extended live advice report with HTF rule override integration."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args()


def get_connection() -> pymysql.connections.Connection:
    load_dotenv()
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=(os.getenv("DB_PASSWORD") or os.getenv("DB_PASS") or ""),
        database=os.getenv("DB_NAME"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def query_df(
    conn: pymysql.connections.Connection,
    sql: str,
    params: list[object] | tuple[object, ...] | None = None,
) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql, params or [])
        rows = cur.fetchall()
    return pd.DataFrame(rows)


def fmt_score(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.4f}"


def htf_rule_meaning(state_code: object) -> str:
    state = str(state_code or "").upper()
    if state == "BEAR":
        return "HTF structure remains bearish. Treat rallies as relief until reversal confirmed."
    if state == "PREPARE":
        return "Early reversal watch active. Wait for pullback or stronger confirmation."
    if state == "BULL":
        return "HTF reversal confirmed. Trend-following entries allowed."
    return "-"


def normalize_recommendation(value: str) -> str:
    text = str(value or "").strip().upper()

    if text in {"BUY", "BUY_NOW", "ENTER_LONG", "TREND"}:
        return "BUY"
    if text in {"WATCH", "WATCH_BUY", "PULLBACK_WATCH"}:
        return "WATCH"
    if text in {"TACTICAL_ONLY", "SCALP_ONLY"}:
        return "TACTICAL_ONLY"
    if text in {"NO_TRADE", "AVOID"}:
        return "NO_TRADE"

    return "NO_TRADE"


def recommendation_rank(rec: str) -> int:
    order = {
        "NO_TRADE": 0,
        "TACTICAL_ONLY": 1,
        "WATCH": 2,
        "BUY": 3,
    }
    return order.get(normalize_recommendation(rec), 0)


def clamp_recommendation(base_rec: str, cap_rec: str) -> str:
    base_norm = normalize_recommendation(base_rec)
    cap_norm = normalize_recommendation(cap_rec)
    return base_norm if recommendation_rank(base_norm) <= recommendation_rank(cap_norm) else cap_norm


def derive_base_recommendation(row: pd.Series) -> str:
    selection_state = str(row.get("selection_state") or "").upper()
    selection_bias = str(row.get("selection_bias") or "").upper()
    score = float(row.get("selection_score") or 0.0)

    if selection_state == "BUY_READY":
        return "BUY"

    if selection_state in {"PREPARE", "WATCHLIST", "PRE_ALIGNMENT"}:
        return "WATCH"

    if selection_state in {"TACTICAL_ONLY"}:
        return "TACTICAL_ONLY"

    if selection_state in {"AVOID", "REJECTED_HTF", "REJECTED_LTF", "LOW_PRIORITY"}:
        return "NO_TRADE"

    if selection_bias in {"BULLISH", "BUY", "LONG", "LONG_BIAS"}:
        if score >= 0.60:
            return "BUY"
        if score >= 0.45:
            return "WATCH"

    if selection_bias in {"WATCH", "NEUTRAL_POSITIVE"}:
        return "WATCH"

    if selection_bias in {"TACTICAL"}:
        return "TACTICAL_ONLY"

    return "NO_TRADE"


def apply_htf_override(row: pd.Series) -> dict[str, object]:
    has_selection = bool(row.get("has_selection_row", True))

    if has_selection:
        base_score = float(row.get("selection_score") or 0.0)
        base_recommendation = derive_base_recommendation(row)
    else:
        base_score = None
        base_recommendation = "NO_TRADE"

    symbol = str(row.get("symbol") or "").upper()
    rule_name = str(row.get("htf_rule_name") or "")
    state_code = str(row.get("htf_rule_state") or "").upper() or None
    htf_rule_score = row.get("htf_rule_score")

    result = {
        "base_score": base_score,
        "base_recommendation": base_recommendation if has_selection else "-",
        "final_score": base_score,
        "final_recommendation": base_recommendation,
        "override_applied": False,
        "override_reason": None,
    }

    if symbol != TAO_SYMBOL:
        return result

    if rule_name != RULE_NAME_TAO or not state_code:
        return result

    if not has_selection:
        if state_code == "BEAR":
            result["final_score"] = htf_rule_score
            result["final_recommendation"] = "NO_TRADE"
            result["override_applied"] = True
            result["override_reason"] = "HTF-only fallback: TAO has rule state but no selection row."
            return result

        if state_code == "PREPARE":
            result["final_score"] = htf_rule_score
            result["final_recommendation"] = "WATCH"
            result["override_applied"] = True
            result["override_reason"] = "HTF-only fallback: early reversal watch without selection row."
            return result

        if state_code == "BULL":
            result["final_score"] = htf_rule_score
            result["final_recommendation"] = "WATCH"
            result["override_applied"] = True
            result["override_reason"] = "HTF-only fallback: bullish rule exists but no selection row yet."
            return result

    if state_code == "BEAR":
        result["final_score"] = min(float(base_score or 0.0), 0.35)
        result["final_recommendation"] = clamp_recommendation(base_recommendation, "NO_TRADE")
        result["override_applied"] = True
        result["override_reason"] = "HTF BEAR caps score and blocks bullish recommendation."
        return result

    if state_code == "PREPARE":
        result["final_score"] = min(float(base_score or 0.0), 0.60)
        result["final_recommendation"] = clamp_recommendation(base_recommendation, "WATCH")
        result["override_applied"] = True
        result["override_reason"] = "HTF PREPARE allows watch state but blocks aggressive buy."
        return result

    return result


def normalize_df_types(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    for col in [
        "asof_ts_utc",
        "advice_ts_1h_utc",
        "advice_ts_4h_utc",
    ]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    for col in [
        "selection_score",
        "priority_rank",
        "opportunity_score_1h",
        "opportunity_score_4h",
        "risk_score_1h",
        "risk_score_4h",
        "htf_rule_score",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def fetch_selection_rows(
    conn: pymysql.connections.Connection,
    venue: str,
    symbol: str | None,
    limit: int,
) -> pd.DataFrame:
    filters = ["ss.venue = %s"]
    params: list[object] = [RULE_NAME_TAO, venue]

    if symbol:
        filters.append("UPPER(a.symbol) = %s")
        params.append(symbol.upper())

    where_sql = " AND ".join(filters)

    sql = f"""
    SELECT
        1 AS has_selection_row,
        ss.asset_id,
        a.symbol,
        ss.venue,
        ss.asof_ts_utc,
        ss.advice_ts_1h_utc,
        ss.advice_ts_4h_utc,
        ss.selection_state,
        ss.selection_bias,
        ss.selection_score,
        ss.priority_rank,
        ss.regime_label_1h,
        ss.regime_label_4h,
        ss.advice_state_1h,
        ss.advice_state_4h,
        ss.opportunity_score_1h,
        ss.opportunity_score_4h,
        ss.risk_score_1h,
        ss.risk_score_4h,
        ss.summary_text,
        rs.rule_name AS htf_rule_name,
        rs.state_code AS htf_rule_state,
        rs.rule_score AS htf_rule_score,
        rs.notes AS htf_rule_notes
    FROM selection_state ss
    JOIN asset a
      ON a.asset_id = ss.asset_id
    LEFT JOIN v_signal_rule_state_latest rs
      ON rs.asset_id = ss.asset_id
     AND rs.rule_name = %s
    WHERE {where_sql}
      AND ss.asof_ts_utc = (
          SELECT MAX(ss2.asof_ts_utc)
          FROM selection_state ss2
          WHERE ss2.asset_id = ss.asset_id
            AND ss2.venue = ss.venue
      )
    ORDER BY
        ss.selection_score DESC,
        ss.priority_rank ASC,
        a.symbol ASC
    LIMIT {int(limit)}
    """

    return normalize_df_types(query_df(conn, sql, params))


def fetch_tao_rule_only_fallback(
    conn: pymysql.connections.Connection,
    venue: str,
    symbol: str | None,
) -> pd.DataFrame:
    if symbol and symbol.upper() != TAO_SYMBOL:
        return pd.DataFrame()

    sql = """
    SELECT
        0 AS has_selection_row,
        a.asset_id,
        a.symbol,
        %s AS venue,
        NULL AS asof_ts_utc,
        NULL AS advice_ts_1h_utc,
        NULL AS advice_ts_4h_utc,
        NULL AS selection_state,
        NULL AS selection_bias,
        NULL AS selection_score,
        NULL AS priority_rank,
        NULL AS regime_label_1h,
        NULL AS regime_label_4h,
        NULL AS advice_state_1h,
        NULL AS advice_state_4h,
        NULL AS opportunity_score_1h,
        NULL AS opportunity_score_4h,
        NULL AS risk_score_1h,
        NULL AS risk_score_4h,
        NULL AS summary_text,
        rs.rule_name AS htf_rule_name,
        rs.state_code AS htf_rule_state,
        rs.rule_score AS htf_rule_score,
        rs.notes AS htf_rule_notes
    FROM v_signal_rule_state_latest rs
    JOIN asset a
      ON a.asset_id = rs.asset_id
    WHERE UPPER(a.symbol) = %s
      AND rs.rule_name = %s
    LIMIT 1
    """

    return normalize_df_types(query_df(conn, sql, [venue, TAO_SYMBOL, RULE_NAME_TAO]))


def fetch_report_rows(
    conn: pymysql.connections.Connection,
    venue: str,
    symbol: str | None,
    limit: int,
) -> pd.DataFrame:
    selection_df = fetch_selection_rows(conn=conn, venue=venue, symbol=symbol, limit=limit)

    if not selection_df.empty:
        return selection_df

    return fetch_tao_rule_only_fallback(conn=conn, venue=venue, symbol=symbol)


def print_report(df: pd.DataFrame) -> None:
    print()
    print("LIVE ADVICE REPORT — EXTENDED (HTF OVERRIDE ENABLED)")
    print("====================================================")

    for _, row in df.iterrows():
        override = apply_htf_override(row)

        print()
        print("---")
        print(f"Asset: {row['symbol']}")
        print(f"As of: {row['asof_ts_utc'] if pd.notna(row['asof_ts_utc']) else '-'}")
        print(f"Selection State: {row['selection_state'] if pd.notna(row['selection_state']) else '-'}")
        print(f"Selection Bias:  {row['selection_bias'] if pd.notna(row['selection_bias']) else '-'}")
        print(f"Priority Rank:   {int(row['priority_rank']) if pd.notna(row['priority_rank']) else '-'}")
        print(f"Base Score:      {fmt_score(override['base_score'])}")
        print(f"Final Score:     {fmt_score(override['final_score'])}")
        print(f"Base Rec:        {override['base_recommendation']}")
        print(f"Final Rec:       {override['final_recommendation']}")

        if override["override_applied"]:
            print(f"Override:        {override['override_reason']}")

        if pd.notna(row.get("htf_rule_state")) and row.get("htf_rule_name") == RULE_NAME_TAO:
            print()
            print("HTF Rule:")
            print(
                f"- {row['htf_rule_name']} = {row['htf_rule_state']} "
                f"({fmt_score(row['htf_rule_score'])})"
            )
            print(f"- Meaning: {htf_rule_meaning(row['htf_rule_state'])}")
            if pd.notna(row.get("htf_rule_notes")):
                print(f"- Notes:   {row['htf_rule_notes']}")

        print()
        print("Context:")
        print(f"- Regime 1h:     {row['regime_label_1h'] if pd.notna(row['regime_label_1h']) else '-'}")
        print(f"- Regime 4h:     {row['regime_label_4h'] if pd.notna(row['regime_label_4h']) else '-'}")
        print(f"- Advice 1h:     {row['advice_state_1h'] if pd.notna(row['advice_state_1h']) else '-'}")
        print(f"- Advice 4h:     {row['advice_state_4h'] if pd.notna(row['advice_state_4h']) else '-'}")
        print(f"- Opp score 1h:  {fmt_score(row['opportunity_score_1h'])}")
        print(f"- Opp score 4h:  {fmt_score(row['opportunity_score_4h'])}")
        print(f"- Risk score 1h: {fmt_score(row['risk_score_1h'])}")
        print(f"- Risk score 4h: {fmt_score(row['risk_score_4h'])}")

        print()
        print("Summary:")
        print(row["summary_text"] if pd.notna(row["summary_text"]) else "-")


def main() -> int:
    args = parse_args()
    connection = get_connection()

    try:
        df = fetch_report_rows(
            conn=connection,
            venue=args.venue,
            symbol=args.symbol,
            limit=args.limit,
        )

        if df.empty:
            print("No rows found.")
            return 0

        print_report(df)
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
