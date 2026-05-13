from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


REPORT_NAME = "breath_curve_symbol_regime_validation_v1"
VERSION = "0.1"

POLICY_NAMES = (
    "0618_selected_minus8_v1",
    "0618_selected_minus7_v1",
    "0618_selected_early_band_v1",
)


@dataclass(frozen=True)
class PolicySpec:
    policy_name: str
    purpose: str


def policy_specs() -> list[PolicySpec]:
    return [
        PolicySpec(
            policy_name="0618_selected_minus8_v1",
            purpose="primary 0.618 selected -8 early pulse-to-1.000 candidate",
        ),
        PolicySpec(
            policy_name="0618_selected_minus7_v1",
            purpose="secondary/demoted 0.618 selected -7 candidate",
        ),
        PolicySpec(
            policy_name="0618_selected_early_band_v1",
            purpose="broader 0.618 selected -7/-8 recall candidate",
        ),
    ]


def parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def as_float(value: Any) -> float | None:
    if value is None:
        return None

    text = str(value).strip()
    if text == "" or text.lower() in {"none", "null", "nan"}:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def fmt(value: Any, places: int = 4) -> str:
    parsed = as_float(value)
    if parsed is None:
        return ""

    text = f"{parsed:.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print("(no rows)")
        return

    widths = [len(header) for header in headers]

    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    print(" | ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers))))
    print("-+-".join("-" * width for width in widths))

    for row in rows:
        print(" | ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))


def latest_input_csv(default_dir: str) -> Path:
    paths = sorted(
        Path(default_dir).glob("breath_curve_random_anchor_baseline_v2_*_all_rows.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not paths:
        raise RuntimeError(f"No random-anchor all_rows CSV found under {default_dir}")

    return paths[0]


def load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fields = sorted({key for row in rows for key in row.keys()})

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def policy_matches(row: dict[str, Any], policy_name: str) -> bool:
    if row.get("status") != "OK":
        return False

    if str(row.get("checkpoint_ratio")) != "0.618":
        return False

    selected_band = str(row.get("selected_band_w1_0"))

    if policy_name == "0618_selected_minus8_v1":
        return selected_band == "-8"

    if policy_name == "0618_selected_minus7_v1":
        return selected_band == "-7"

    if policy_name == "0618_selected_early_band_v1":
        return selected_band in {"-8", "-7"}

    raise RuntimeError(f"Unknown policy_name={policy_name}")


def values(rows: list[dict[str, Any]], key: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        value = as_float(row.get(key))
        if value is not None:
            out.append(value)
    return out


def summarize(evaluated_rows: list[dict[str, Any]], selected_rows: list[dict[str, Any]]) -> dict[str, Any]:
    ret1000 = values(selected_rows, "return_to_1000_pct")
    ret1272 = values(selected_rows, "return_to_1272_pct")
    partial = values(selected_rows, "selected_partial_score")

    def avg(items: list[float]) -> float | None:
        if not items:
            return None
        return round(sum(items) / len(items), 4)

    def med(items: list[float]) -> float | None:
        if not items:
            return None
        return round(float(median(items)), 4)

    def positive_rate(items: list[float]) -> float | None:
        if not items:
            return None
        return round(sum(1 for item in items if item > 0.0) / len(items) * 100.0, 4)

    evaluated = len(evaluated_rows)
    eligible = len(selected_rows)

    return {
        "evaluated_rows": evaluated,
        "eligible_rows": eligible,
        "selection_rate_pct": round(eligible / evaluated * 100.0, 4) if evaluated else None,
        "avg_partial_score": avg(partial),
        "avg_return_to_1000_pct": avg(ret1000),
        "median_return_to_1000_pct": med(ret1000),
        "positive_to_1000_pct": positive_rate(ret1000),
        "best_return_to_1000_pct": max(ret1000) if ret1000 else None,
        "worst_return_to_1000_pct": min(ret1000) if ret1000 else None,
        "avg_return_to_1272_pct": avg(ret1272),
        "median_return_to_1272_pct": med(ret1272),
        "positive_to_1272_pct": positive_rate(ret1272),
        "best_return_to_1272_pct": max(ret1272) if ret1272 else None,
        "worst_return_to_1272_pct": min(ret1272) if ret1272 else None,
    }


def table_cols(conn: Any, table_name: str) -> set[str]:
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
            """,
            (table_name,),
        )
        return {str(row["COLUMN_NAME"]) for row in cur.fetchall()}


def choose(cols: set[str], options: list[str], required: bool = True) -> str | None:
    for option in options:
        if option in cols:
            return option

    if required:
        raise RuntimeError(f"Missing expected column. Tried: {options}")

    return None


def resolve_asset_id(conn: Any, symbol: str) -> int | None:
    cols = table_cols(conn, "asset")
    id_col = choose(cols, ["asset_id", "id"], required=False)
    symbol_col = choose(cols, ["symbol", "asset_code", "code", "base_symbol", "ticker"], required=False)

    if not id_col or not symbol_col:
        return None

    candidates = sorted(
        {
            symbol,
            symbol.upper(),
            symbol.replace("-EUR", "").upper(),
            symbol.replace("/EUR", "").upper(),
            symbol.replace("USDT", "").upper(),
        }
    )

    placeholders = ",".join(["%s"] * len(candidates))
    sql = f"SELECT `{id_col}` AS asset_id FROM asset WHERE `{symbol_col}` IN ({placeholders}) LIMIT 1"

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, tuple(candidates))
        row = cur.fetchone()

    if not row:
        return None

    return int(row["asset_id"])


def classify_trend(row: dict[str, Any]) -> str:
    p20 = as_float(row.get("price_vs_ema20"))
    p50 = as_float(row.get("price_vs_ema50"))
    spread = as_float(row.get("ema_spread"))

    if p20 is None and p50 is None and spread is None:
        return "TREND_UNKNOWN"

    bullish_votes = 0
    bearish_votes = 0

    for value in (p20, p50, spread):
        if value is None:
            continue
        if value > 0:
            bullish_votes += 1
        elif value < 0:
            bearish_votes += 1

    if bullish_votes >= 2:
        return "TREND_BULL"
    if bearish_votes >= 2:
        return "TREND_BEAR"
    return "TREND_MIXED"


def classify_rsi(row: dict[str, Any]) -> str:
    rsi = as_float(row.get("rsi_14"))
    if rsi is None:
        return "RSI_UNKNOWN"
    if rsi < 40:
        return "RSI_LOW"
    if rsi < 55:
        return "RSI_MID"
    if rsi < 70:
        return "RSI_HIGH"
    return "RSI_EXTREME"


def classify_volume(row: dict[str, Any]) -> str:
    z = as_float(row.get("volume_zscore_20"))
    ratio = as_float(row.get("dollar_volume_ratio_20")) or as_float(row.get("volume_ratio_20"))

    if z is None and ratio is None:
        return "VOLUME_UNKNOWN"

    if (z is not None and z >= 1.0) or (ratio is not None and ratio >= 1.5):
        return "VOLUME_EXPANSION"

    if (z is not None and z <= -0.75) or (ratio is not None and ratio < 0.75):
        return "VOLUME_THIN"

    return "VOLUME_NORMAL"


def classify_atr(row: dict[str, Any]) -> str:
    atr_pct = as_float(row.get("atr_pct"))
    if atr_pct is None:
        return "ATR_UNKNOWN"
    if atr_pct < 3:
        return "ATR_LOW"
    if atr_pct < 7:
        return "ATR_NORMAL"
    return "ATR_HIGH"


def classify_context(row: dict[str, Any]) -> dict[str, str]:
    return {
        "trend_bucket": classify_trend(row),
        "rsi_bucket": classify_rsi(row),
        "volume_bucket": classify_volume(row),
        "atr_bucket": classify_atr(row),
    }


def fetch_feature_row(
    conn: Any,
    *,
    symbol: str,
    venue: str,
    interval_code: str,
    as_of: datetime,
    cache: dict[tuple[str, str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    key = (symbol, venue, interval_code, iso(as_of))
    if key in cache:
        return cache[key]

    cols = table_cols(conn, "feat_candle")

    asset_col = choose(cols, ["asset_id"], required=False)
    ts_col = choose(cols, ["asof_ts_utc", "open_ts_utc", "close_ts_utc", "ts_utc", "timestamp_utc"], required=False)
    venue_col = choose(cols, ["venue"], required=False)
    interval_col = choose(cols, ["interval_code", "timeframe"], required=False)

    if not asset_col or not ts_col:
        cache[key] = {}
        return {}

    asset_id = resolve_asset_id(conn, symbol)
    if asset_id is None:
        cache[key] = {}
        return {}

    wanted = [
        "rsi_14",
        "price_vs_ema20",
        "price_vs_ema50",
        "ema_spread",
        "volume_zscore_20",
        "volume_ratio_20",
        "dollar_volume_ratio_20",
        "atr_pct",
    ]

    select_cols = [col for col in wanted if col in cols]
    if not select_cols:
        cache[key] = {}
        return {}

    where = [f"`{asset_col}` = %s", f"`{ts_col}` <= %s"]
    params: list[Any] = [asset_id, iso(as_of)]

    if venue_col:
        where.append(f"`{venue_col}` = %s")
        params.append(venue)

    if interval_col:
        where.append(f"`{interval_col}` = %s")
        params.append(interval_code)

    sql = f"""
        SELECT
            `{ts_col}` AS feature_ts_utc,
            {", ".join(f"`{col}`" for col in select_cols)}
        FROM feat_candle
        WHERE {" AND ".join(where)}
        ORDER BY `{ts_col}` DESC
        LIMIT 1
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, tuple(params))
        row = cur.fetchone()

    cache[key] = dict(row or {})
    return cache[key]


def enrich_with_db_context(rows: list[dict[str, Any]], *, venue: str, interval_code: str) -> list[dict[str, Any]]:
    load_dotenv(dotenv_path=".env", override=False)

    conn = get_db_connection()
    cache: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    try:
        out: list[dict[str, Any]] = []

        for row in rows:
            as_of = parse_dt(row.get("as_of_ts_utc"))
            symbol = str(row.get("symbol", "")).strip()

            enriched = dict(row)

            if as_of is None or not symbol:
                enriched.update(
                    {
                        "symbol_trend_bucket": "TREND_UNKNOWN",
                        "symbol_rsi_bucket": "RSI_UNKNOWN",
                        "symbol_volume_bucket": "VOLUME_UNKNOWN",
                        "symbol_atr_bucket": "ATR_UNKNOWN",
                        "btc_trend_bucket": "TREND_UNKNOWN",
                        "eth_trend_bucket": "TREND_UNKNOWN",
                        "btc_eth_context_bucket": "BTC_ETH_UNKNOWN",
                    }
                )
                out.append(enriched)
                continue

            symbol_feature = fetch_feature_row(
                conn,
                symbol=symbol,
                venue=venue,
                interval_code=interval_code,
                as_of=as_of,
                cache=cache,
            )
            btc_feature = fetch_feature_row(
                conn,
                symbol="BTC",
                venue=venue,
                interval_code=interval_code,
                as_of=as_of,
                cache=cache,
            )
            eth_feature = fetch_feature_row(
                conn,
                symbol="ETH",
                venue=venue,
                interval_code=interval_code,
                as_of=as_of,
                cache=cache,
            )

            symbol_context = classify_context(symbol_feature)
            btc_context = classify_context(btc_feature)
            eth_context = classify_context(eth_feature)

            btc_trend = btc_context["trend_bucket"]
            eth_trend = eth_context["trend_bucket"]

            if btc_trend == "TREND_BULL" and eth_trend == "TREND_BULL":
                btc_eth_context = "BTC_ETH_BULL"
            elif btc_trend == "TREND_BEAR" and eth_trend == "TREND_BEAR":
                btc_eth_context = "BTC_ETH_BEAR"
            elif "UNKNOWN" in {btc_trend.split("_")[-1], eth_trend.split("_")[-1]}:
                btc_eth_context = "BTC_ETH_UNKNOWN"
            else:
                btc_eth_context = "BTC_ETH_MIXED"

            enriched.update(
                {
                    "symbol_feature_ts_utc": str(symbol_feature.get("feature_ts_utc", "")),
                    "btc_feature_ts_utc": str(btc_feature.get("feature_ts_utc", "")),
                    "eth_feature_ts_utc": str(eth_feature.get("feature_ts_utc", "")),
                    "symbol_trend_bucket": symbol_context["trend_bucket"],
                    "symbol_rsi_bucket": symbol_context["rsi_bucket"],
                    "symbol_volume_bucket": symbol_context["volume_bucket"],
                    "symbol_atr_bucket": symbol_context["atr_bucket"],
                    "btc_trend_bucket": btc_context["trend_bucket"],
                    "btc_rsi_bucket": btc_context["rsi_bucket"],
                    "btc_volume_bucket": btc_context["volume_bucket"],
                    "eth_trend_bucket": eth_context["trend_bucket"],
                    "eth_rsi_bucket": eth_context["rsi_bucket"],
                    "eth_volume_bucket": eth_context["volume_bucket"],
                    "btc_eth_context_bucket": btc_eth_context,
                }
            )
            out.append(enriched)

        return out
    finally:
        conn.close()


def add_unknown_context(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for row in rows:
        enriched = dict(row)
        enriched.update(
            {
                "symbol_trend_bucket": "TREND_UNKNOWN",
                "symbol_rsi_bucket": "RSI_UNKNOWN",
                "symbol_volume_bucket": "VOLUME_UNKNOWN",
                "symbol_atr_bucket": "ATR_UNKNOWN",
                "btc_trend_bucket": "TREND_UNKNOWN",
                "btc_rsi_bucket": "RSI_UNKNOWN",
                "btc_volume_bucket": "VOLUME_UNKNOWN",
                "eth_trend_bucket": "TREND_UNKNOWN",
                "eth_rsi_bucket": "RSI_UNKNOWN",
                "eth_volume_bucket": "VOLUME_UNKNOWN",
                "btc_eth_context_bucket": "BTC_ETH_UNKNOWN",
            }
        )
        out.append(enriched)

    return out


def policy_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for spec in policy_specs():
        for row in rows:
            if policy_matches(row, spec.policy_name):
                out.append(
                    {
                        **row,
                        "policy_name": spec.policy_name,
                        "policy_purpose": spec.purpose,
                    }
                )

    return out


def grouped_policy_summary(
    rows: list[dict[str, Any]],
    group_keys: list[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for spec in policy_specs():
        for source in ("real", "random"):
            evaluated_base = [
                row
                for row in rows
                if row.get("status") == "OK"
                and row.get("source") == source
            ]

            group_values = sorted(
                {
                    tuple(str(row.get(group_key, "")) for group_key in group_keys)
                    for row in evaluated_base
                }
            )

            for group_value in group_values:
                group_dict = {
                    group_keys[idx]: group_value[idx]
                    for idx in range(len(group_keys))
                }

                evaluated = [
                    row
                    for row in evaluated_base
                    if all(str(row.get(key, "")) == group_dict[key] for key in group_keys)
                ]
                selected = [
                    row
                    for row in evaluated
                    if policy_matches(row, spec.policy_name)
                ]

                out.append(
                    {
                        "policy_name": spec.policy_name,
                        "source": source,
                        **group_dict,
                        **summarize(evaluated, selected),
                    }
                )

    return out


def policy_source_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for spec in policy_specs():
        for source in ("real", "random"):
            evaluated = [row for row in rows if row.get("source") == source and row.get("status") == "OK"]
            selected = [row for row in evaluated if policy_matches(row, spec.policy_name)]
            out.append(
                {
                    "policy_name": spec.policy_name,
                    "source": source,
                    **summarize(evaluated, selected),
                }
            )

    return out


def policy_symbol_comparison(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    symbols = sorted({str(row.get("symbol")) for row in rows if row.get("status") == "OK"})
    out: list[dict[str, Any]] = []

    for spec in policy_specs():
        for symbol in symbols:
            real_eval = [
                row
                for row in rows
                if row.get("status") == "OK"
                and row.get("source") == "real"
                and row.get("symbol") == symbol
            ]
            random_eval = [
                row
                for row in rows
                if row.get("status") == "OK"
                and row.get("source") == "random"
                and row.get("symbol") == symbol
            ]
            real_selected = [row for row in real_eval if policy_matches(row, spec.policy_name)]
            random_selected = [row for row in random_eval if policy_matches(row, spec.policy_name)]

            real = summarize(real_eval, real_selected)
            random_summary = summarize(random_eval, random_selected)

            real_avg = real.get("avg_return_to_1000_pct")
            random_avg = random_summary.get("avg_return_to_1000_pct")
            real_sel = real.get("selection_rate_pct")
            random_sel = random_summary.get("selection_rate_pct")

            out.append(
                {
                    "policy_name": spec.policy_name,
                    "symbol": symbol,
                    "real_evaluated": real["evaluated_rows"],
                    "real_eligible": real["eligible_rows"],
                    "real_selection_rate_pct": real_sel,
                    "real_avg_return_to_1000_pct": real_avg,
                    "real_positive_to_1000_pct": real["positive_to_1000_pct"],
                    "real_worst_return_to_1000_pct": real["worst_return_to_1000_pct"],
                    "random_evaluated": random_summary["evaluated_rows"],
                    "random_eligible": random_summary["eligible_rows"],
                    "random_selection_rate_pct": random_sel,
                    "random_avg_return_to_1000_pct": random_avg,
                    "random_positive_to_1000_pct": random_summary["positive_to_1000_pct"],
                    "random_worst_return_to_1000_pct": random_summary["worst_return_to_1000_pct"],
                    "edge_avg_return_to_1000_pct": round(real_avg - random_avg, 4)
                    if real_avg is not None and random_avg is not None
                    else None,
                    "selection_rate_delta_pct": round(real_sel - random_sel, 4)
                    if real_sel is not None and random_sel is not None
                    else None,
                }
            )

    return out


def print_source_summary(rows: list[dict[str, Any]]) -> None:
    print("--- policy source summary ---")
    print_table(
        [
            "policy",
            "source",
            "eval",
            "eligible",
            "sel_rate",
            "avg1000",
            "pos1000",
            "worst1000",
            "avg1272",
            "pos1272",
        ],
        [
            [
                str(row["policy_name"]),
                str(row["source"]),
                str(row["evaluated_rows"]),
                str(row["eligible_rows"]),
                fmt(row["selection_rate_pct"], 2),
                fmt(row["avg_return_to_1000_pct"]),
                fmt(row["positive_to_1000_pct"], 2),
                fmt(row["worst_return_to_1000_pct"]),
                fmt(row["avg_return_to_1272_pct"]),
                fmt(row["positive_to_1272_pct"], 2),
            ]
            for row in rows
        ],
    )


def print_symbol_comparison(rows: list[dict[str, Any]]) -> None:
    print()
    print("--- policy symbol comparison ---")
    print_table(
        [
            "policy",
            "symbol",
            "real_elig",
            "real_sel",
            "real_avg1000",
            "rand_elig",
            "rand_sel",
            "rand_avg1000",
            "edge1000",
            "sel_delta",
        ],
        [
            [
                str(row["policy_name"]),
                str(row["symbol"]),
                str(row["real_eligible"]),
                fmt(row["real_selection_rate_pct"], 2),
                fmt(row["real_avg_return_to_1000_pct"]),
                str(row["random_eligible"]),
                fmt(row["random_selection_rate_pct"], 2),
                fmt(row["random_avg_return_to_1000_pct"]),
                fmt(row["edge_avg_return_to_1000_pct"]),
                fmt(row["selection_rate_delta_pct"], 2),
            ]
            for row in rows
            if row["real_eligible"] > 0 or row["random_eligible"] > 0
        ],
    )


def print_group_summary(title: str, group_keys: list[str], rows: list[dict[str, Any]], limit: int) -> None:
    print()
    print(title)
    print_table(
        group_keys
        + [
            "eval",
            "eligible",
            "sel_rate",
            "avg1000",
            "pos1000",
            "worst1000",
            "avg1272",
            "pos1272",
        ],
        [
            [
                *[str(row.get(key, "")) for key in group_keys],
                str(row["evaluated_rows"]),
                str(row["eligible_rows"]),
                fmt(row["selection_rate_pct"], 2),
                fmt(row["avg_return_to_1000_pct"]),
                fmt(row["positive_to_1000_pct"], 2),
                fmt(row["worst_return_to_1000_pct"]),
                fmt(row["avg_return_to_1272_pct"]),
                fmt(row["positive_to_1272_pct"], 2),
            ]
            for row in rows[:limit]
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only symbol/regime validation for Breath Curve random-anchor baseline rows."
    )
    parser.add_argument("--input-csv", default=None)
    parser.add_argument("--default-dir", default="data/research/breath_curve_random_anchor_baseline_v2")
    parser.add_argument("--out-dir", default="data/research/breath_curve_symbol_regime_validation_v1")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", dest="interval_code", default="1d")
    parser.add_argument("--db-context", action="store_true")
    parser.add_argument("--limit-print", type=int, default=80)
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_csv = Path(args.input_csv) if args.input_csv else latest_input_csv(args.default_dir)
    raw_rows = load_rows(input_csv)
    ok_rows = [row for row in raw_rows if row.get("status") == "OK"]

    if args.db_context:
        enriched_rows = enrich_with_db_context(ok_rows, venue=args.venue, interval_code=args.interval_code)
        context_mode = "db"
    else:
        enriched_rows = add_unknown_context(ok_rows)
        context_mode = "csv_only"

    selected_policy_rows = policy_rows(enriched_rows)
    source_summary = policy_source_summary(enriched_rows)
    symbol_comparison = policy_symbol_comparison(enriched_rows)

    symbol_bucket_summary = grouped_policy_summary(
        enriched_rows,
        ["symbol"],
    )
    symbol_trend_summary = grouped_policy_summary(
        enriched_rows,
        ["symbol_trend_bucket"],
    )
    btc_eth_summary = grouped_policy_summary(
        enriched_rows,
        ["btc_eth_context_bucket"],
    )
    volume_summary = grouped_policy_summary(
        enriched_rows,
        ["symbol_volume_bucket"],
    )
    rsi_summary = grouped_policy_summary(
        enriched_rows,
        ["symbol_rsi_bucket"],
    )

    out_dir = Path(args.out_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    enriched_path = out_dir / f"breath_curve_symbol_regime_validation_v1_{stamp}_enriched_rows.csv"
    policy_path = out_dir / f"breath_curve_symbol_regime_validation_v1_{stamp}_policy_rows.csv"
    source_path = out_dir / f"breath_curve_symbol_regime_validation_v1_{stamp}_source_summary.csv"
    symbol_path = out_dir / f"breath_curve_symbol_regime_validation_v1_{stamp}_symbol_comparison.csv"
    symbol_bucket_path = out_dir / f"breath_curve_symbol_regime_validation_v1_{stamp}_symbol_bucket_summary.csv"
    trend_path = out_dir / f"breath_curve_symbol_regime_validation_v1_{stamp}_symbol_trend_summary.csv"
    btc_eth_path = out_dir / f"breath_curve_symbol_regime_validation_v1_{stamp}_btc_eth_context_summary.csv"
    volume_path = out_dir / f"breath_curve_symbol_regime_validation_v1_{stamp}_volume_summary.csv"
    rsi_path = out_dir / f"breath_curve_symbol_regime_validation_v1_{stamp}_rsi_summary.csv"

    write_csv(enriched_path, enriched_rows)
    write_csv(policy_path, selected_policy_rows)
    write_csv(source_path, source_summary)
    write_csv(symbol_path, symbol_comparison)
    write_csv(symbol_bucket_path, symbol_bucket_summary)
    write_csv(trend_path, symbol_trend_summary)
    write_csv(btc_eth_path, btc_eth_summary)
    write_csv(volume_path, volume_summary)
    write_csv(rsi_path, rsi_summary)

    if args.output == "table":
        print(f"report={REPORT_NAME} version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
        print("selection_engine=none decision_gate=none execution_planner=none executor=none")
        print("post_hoc_fields_used_as_filters=0")
        print(f"input_csv={input_csv}")
        print(f"context_mode={context_mode}")
        print(f"ok_rows={len(enriched_rows)} policy_rows={len(selected_policy_rows)}")
        print()

        print_source_summary(source_summary)
        print_symbol_comparison(symbol_comparison)
        print_group_summary(
            "--- policy/source/symbol buckets ---",
            ["policy_name", "source", "symbol"],
            symbol_bucket_summary,
            args.limit_print,
        )
        print_group_summary(
            "--- policy/source/symbol trend buckets ---",
            ["policy_name", "source", "symbol_trend_bucket"],
            symbol_trend_summary,
            args.limit_print,
        )
        print_group_summary(
            "--- policy/source/BTC-ETH context buckets ---",
            ["policy_name", "source", "btc_eth_context_bucket"],
            btc_eth_summary,
            args.limit_print,
        )
        print_group_summary(
            "--- policy/source/volume buckets ---",
            ["policy_name", "source", "symbol_volume_bucket"],
            volume_summary,
            args.limit_print,
        )
        print_group_summary(
            "--- policy/source/RSI buckets ---",
            ["policy_name", "source", "symbol_rsi_bucket"],
            rsi_summary,
            args.limit_print,
        )

        print()
        print(f"wrote_enriched_rows={enriched_path}")
        print(f"wrote_policy_rows={policy_path}")
        print(f"wrote_source_summary={source_path}")
        print(f"wrote_symbol_comparison={symbol_path}")
        print(f"wrote_symbol_bucket_summary={symbol_bucket_path}")
        print(f"wrote_symbol_trend_summary={trend_path}")
        print(f"wrote_btc_eth_context_summary={btc_eth_path}")
        print(f"wrote_volume_summary={volume_path}")
        print(f"wrote_rsi_summary={rsi_path}")
        print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
