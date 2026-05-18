from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_db_connection


REPORT = "trade_setup_fail_reason_diagnostic_v1"
VERSION = "0.1"
DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL = "4h"
DEFAULT_LIMIT = 80
LIFECYCLE_INTERVAL = "15m"

RANK_MIN = 4
RANK_MAX = 10
BTC_PRIOR_MIN = Decimal("-0.015")
BTC_PRIOR_MAX = Decimal("0.015")
REQUIRED_SELECTION_STATE = "WATCHLIST"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose why latest paper advice rows show setup filter FAIL."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--output", choices=("table", "jsonl"), default="table")
    return parser.parse_args()


def parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip().replace("T", " ").removesuffix("Z")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def latest_ts(conn: Any, table: str, where_sql: str, params: dict[str, Any], column: str = "asof_ts_utc") -> datetime | None:
    sql = f"SELECT MAX({column}) AS latest_ts FROM {table} WHERE {where_sql}"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone() or {}
    return parse_ts(row.get("latest_ts"))


def fetch_latest_paper_rows(
    conn: Any,
    *,
    venue: str,
    interval: str,
    limit: int,
    symbol: str | None,
) -> tuple[datetime | None, list[dict[str, Any]]]:
    latest_asof = latest_ts(
        conn,
        "paper_advice_observation",
        "venue = %(venue)s AND interval_code = %(interval)s",
        {"venue": venue, "interval": interval},
    )

    if latest_asof is None:
        return None, []

    sql = """
    SELECT
        paper_advice_observation_id,
        asset_id,
        symbol,
        venue,
        interval_code,
        asof_ts_utc,
        context_ts_utc,
        selection_state,
        selection_bias,
        selection_score,
        priority_rank,
        setup_filter_state,
        setup_filter_reason,
        current_target_horizon,
        policy_decision,
        suggested_horizon,
        allowed_now,
        leg_direction,
        entry_zone_low,
        entry_zone_high,
        tp_zone_low,
        tp_zone_high,
        invalidation_price,
        zone_confidence_score,
        zone_alignment_score,
        advice_state,
        advice_action,
        confidence_score,
        risk_label,
        reason_codes_json,
        source_ref_json
    FROM paper_advice_observation
    WHERE venue = %(venue)s
      AND interval_code = %(interval)s
      AND asof_ts_utc = %(latest_asof)s
    """

    params: dict[str, Any] = {"venue": venue, "interval": interval, "latest_asof": latest_asof}
    if symbol:
        sql += " AND UPPER(symbol) = %(symbol)s"
        params["symbol"] = symbol.upper()

    sql += """
    ORDER BY
        priority_rank IS NULL,
        priority_rank ASC,
        confidence_score DESC,
        symbol ASC
    LIMIT %(limit)s
    """
    params["limit"] = int(limit)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return latest_asof, list(cur.fetchall())


def fetch_latest_table_rows(
    conn: Any,
    *,
    table: str,
    venue: str,
    interval: str | None = None,
) -> tuple[datetime | None, dict[int, dict[str, Any]], dict[str, dict[str, Any]]]:
    clauses = ["venue = %(venue)s"]
    params: dict[str, Any] = {"venue": venue}
    if interval is not None:
        clauses.append("interval_code = %(interval)s")
        params["interval"] = interval

    latest_asof = latest_ts(conn, table, " AND ".join(clauses), params)
    if latest_asof is None:
        return None, {}, {}

    clauses.append("asof_ts_utc = %(latest_asof)s")
    params["latest_asof"] = latest_asof

    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {table} WHERE {' AND '.join(clauses)}", params)
        rows = list(cur.fetchall())

    by_asset = {int(row["asset_id"]): row for row in rows if row.get("asset_id") is not None}
    by_symbol = {str(row["symbol"]).upper(): row for row in rows if row.get("symbol") is not None}
    return latest_asof, by_asset, by_symbol


def parse_reason_codes(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return [str(raw)]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    if isinstance(parsed, dict):
        return [f"{key}={value}" for key, value in parsed.items()]
    return [str(parsed)]


def parse_source_ref(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def zone_asof_from_row(row: dict[str, Any] | None) -> datetime | None:
    if not row:
        return None
    source_ref = parse_source_ref(row.get("source_ref_json"))
    return parse_ts(source_ref.get("zone_asof_ts_utc"))


def latest_candles_by_asset(
    conn: Any,
    *,
    venue: str,
    interval: str,
    asset_ids: list[int],
) -> dict[int, dict[str, Any]]:
    if not asset_ids:
        return {}
    placeholders = ",".join(["%s"] * len(asset_ids))
    params: list[Any] = [venue, interval, *asset_ids, venue, interval]
    sql = f"""
    SELECT
        c.asset_id,
        c.close_ts_utc,
        c.close_price,
        c.high_price,
        c.low_price
    FROM obs_market_candle c
    JOIN (
        SELECT asset_id, MAX(close_ts_utc) AS max_close_ts_utc
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND asset_id IN ({placeholders})
        GROUP BY asset_id
    ) latest
      ON latest.asset_id = c.asset_id
     AND latest.max_close_ts_utc = c.close_ts_utc
    WHERE c.venue = %s
      AND c.interval_code = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    return {int(row["asset_id"]): row for row in rows}


def previous_paper_rows_by_asset(
    conn: Any,
    *,
    venue: str,
    interval: str,
    latest_asof: datetime | None,
    asset_ids: list[int],
) -> dict[int, dict[str, Any]]:
    if latest_asof is None or not asset_ids:
        return {}

    placeholders = ",".join(["%s"] * len(asset_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT p.*
            FROM paper_advice_observation p
            JOIN (
                SELECT asset_id, MAX(asof_ts_utc) AS previous_asof_ts_utc
                FROM paper_advice_observation
                WHERE venue = %s
                  AND interval_code = %s
                  AND asof_ts_utc < %s
                  AND asset_id IN ({placeholders})
                GROUP BY asset_id
            ) previous
              ON previous.asset_id = p.asset_id
             AND previous.previous_asof_ts_utc = p.asof_ts_utc
            WHERE p.venue = %s
              AND p.interval_code = %s
            """,
            [venue, interval, latest_asof, *asset_ids, venue, interval],
        )
        rows = list(cur.fetchall())

    return {int(row["asset_id"]): row for row in rows if row.get("asset_id") is not None}


def lifecycle_badges_by_asset(
    conn: Any,
    *,
    venue: str,
    rows: list[dict[str, Any]],
) -> dict[int, str]:
    result: dict[int, str] = {}
    down_rows = [
        row for row in rows
        if str(row.get("leg_direction") or "").upper() == "DOWN" and row.get("asset_id") is not None
    ]
    if not down_rows:
        return result

    starts: dict[int, datetime] = {}
    for row in down_rows:
        source_ref = parse_source_ref(row.get("source_ref_json"))
        start = parse_ts(source_ref.get("zone_asof_ts_utc")) or parse_ts(row.get("context_ts_utc")) or parse_ts(row.get("asof_ts_utc"))
        if start is None:
            continue
        asset_id = int(row["asset_id"])
        starts[asset_id] = min(starts.get(asset_id, start), start)

    if not starts:
        return result

    asset_ids = sorted(starts)
    latest = latest_candles_by_asset(
        conn,
        venue=venue,
        interval=LIFECYCLE_INTERVAL,
        asset_ids=asset_ids,
    )
    min_start = min(starts.values())
    placeholders = ",".join(["%s"] * len(asset_ids))

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT asset_id, close_ts_utc, high_price, low_price
            FROM obs_market_candle
            WHERE venue = %s
              AND interval_code = %s
              AND asset_id IN ({placeholders})
              AND close_ts_utc >= %s
            ORDER BY asset_id, close_ts_utc
            """,
            [venue, LIFECYCLE_INTERVAL, *asset_ids, min_start],
        )
        candles = list(cur.fetchall())

    candles_by_asset: dict[int, list[dict[str, Any]]] = {}
    for candle in candles:
        candles_by_asset.setdefault(int(candle["asset_id"]), []).append(candle)

    for row in down_rows:
        asset_id = int(row["asset_id"])
        start = starts.get(asset_id)
        latest_row = latest.get(asset_id)
        if start is None or latest_row is None:
            result[asset_id] = "PULLBACK WATCH"
            continue

        invalidation = as_decimal(row.get("invalidation_price"))
        entry_low = as_decimal(row.get("entry_zone_low"))
        entry_high = as_decimal(row.get("entry_zone_high"))
        tp_values = [value for value in (as_decimal(row.get("tp_zone_low")), as_decimal(row.get("tp_zone_high"))) if value is not None]
        tp_low = min(tp_values) if tp_values else None
        tp_high = max(tp_values) if tp_values else None
        latest_close = as_decimal(latest_row.get("close_price"))

        invalidated = False
        downside_reached = False
        for candle in candles_by_asset.get(asset_id, []):
            close_ts = parse_ts(candle.get("close_ts_utc"))
            if close_ts is None or close_ts < start:
                continue
            high = as_decimal(candle.get("high_price"))
            low = as_decimal(candle.get("low_price"))
            if invalidation is not None and high is not None and high >= invalidation:
                invalidated = True
            if tp_low is not None and tp_high is not None and low is not None and high is not None and low <= tp_high and high >= tp_low:
                downside_reached = True

        if invalidated:
            result[asset_id] = "INVALIDATED | EXPIRED MAP | RECOMPUTE NEEDED | NOT ACTIONABLE"
        elif downside_reached and latest_close is not None and entry_high is not None and latest_close > entry_high:
            result[asset_id] = "REACTION RETEST AFTER ENTRY"
        elif downside_reached and latest_close is not None and tp_high is not None and latest_close > tp_high:
            result[asset_id] = "POST-ENTRY BOUNCE"
        elif downside_reached:
            result[asset_id] = "DOWNSIDE ENTRY REACHED"
        elif latest_close is not None and entry_low is not None and entry_high is not None and entry_low <= latest_close <= entry_high:
            result[asset_id] = "REACTION ZONE ACTIVE"
        elif latest_close is not None and tp_high is not None and entry_low is not None and tp_high < latest_close < entry_low:
            result[asset_id] = "PULLBACK IN PROGRESS"
        else:
            result[asset_id] = "PULLBACK WATCH"

    return result


def reason_diagnostic(row: dict[str, Any], filter_row: dict[str, Any] | None) -> dict[str, Any]:
    setup_state = str(row.get("setup_filter_state") or "").upper()
    reason = str(row.get("setup_filter_reason") or (filter_row or {}).get("setup_filter_reason") or "").upper()
    source = filter_row or row

    if setup_state != "FAIL":
        return {
            "fail_primary_reason": "",
            "fail_reason_codes": [],
            "failed_guard_name": "",
            "failed_guard_detail": "",
            "relevant_metric": "",
            "threshold": "",
            "observed_value": "",
            "source_table": "trade_setup_filter_observation" if filter_row else "paper_advice_observation",
            "source_ts_utc": source.get("asof_ts_utc"),
        }

    if not reason:
        return {
            "fail_primary_reason": "INSUFFICIENT_REASON_DETAIL",
            "fail_reason_codes": ["missing setup_filter_reason"],
            "failed_guard_name": "unknown",
            "failed_guard_detail": "setup_filter_state=FAIL but no setup_filter_reason is stored",
            "relevant_metric": "",
            "threshold": "",
            "observed_value": "",
            "source_table": "paper_advice_observation",
            "source_ts_utc": row.get("asof_ts_utc"),
        }

    mapping: dict[str, dict[str, str]] = {
        "SELECTION_STATE_NOT_ELIGIBLE": {
            "guard": "selection_state_required",
            "detail": "candidate selection_state must match setup-filter required state",
            "metric": "selection_state",
            "threshold": REQUIRED_SELECTION_STATE,
            "observed": fmt(source.get("selection_state")),
        },
        "PRIORITY_RANK_MISSING": {
            "guard": "priority_rank_present",
            "detail": "candidate must have a priority_rank",
            "metric": "priority_rank",
            "threshold": "not null",
            "observed": fmt(source.get("priority_rank")),
        },
        "RANK_OUTSIDE_SWEET_SPOT": {
            "guard": "rank_sweet_spot",
            "detail": "priority_rank must be inside configured sweet spot",
            "metric": "priority_rank",
            "threshold": f"{RANK_MIN}..{RANK_MAX}",
            "observed": fmt(source.get("priority_rank")),
        },
        "BTC_PRIOR_24H_MISSING": {
            "guard": "btc_prior_available",
            "detail": "BTC 24h prior return must be available",
            "metric": "btc_prior_24h",
            "threshold": "not null",
            "observed": fmt(source.get("btc_prior_24h")),
        },
        "MARKET_DAMAGE_RISK": {
            "guard": "btc_prior_lower_bound",
            "detail": "BTC 24h prior return is below lower bound",
            "metric": "btc_prior_24h",
            "threshold": f">= {BTC_PRIOR_MIN}",
            "observed": fmt(source.get("btc_prior_24h")),
        },
        "BTC_PRIOR_OVERHEAT_ZONE": {
            "guard": "btc_prior_upper_bound",
            "detail": "BTC 24h prior return is above upper bound",
            "metric": "btc_prior_24h",
            "threshold": f"<= {BTC_PRIOR_MAX}",
            "observed": fmt(source.get("btc_prior_24h")),
        },
        "ASSET_SUITABILITY_WEAK_SET_CANDIDATE": {
            "guard": "asset_suitability_candidate_weak_set",
            "detail": "symbol is in the current candidate_weak_set blocklist",
            "metric": "symbol",
            "threshold": "not in candidate_weak_set",
            "observed": fmt(source.get("symbol")),
        },
        "UNKNOWN": {
            "guard": "unknown",
            "detail": "setup filter stored UNKNOWN; richer reason persistence is needed",
            "metric": "",
            "threshold": "",
            "observed": "",
        },
    }
    info = mapping.get(reason)
    if info is None:
        return {
            "fail_primary_reason": "INSUFFICIENT_REASON_DETAIL",
            "fail_reason_codes": [reason],
            "failed_guard_name": "unknown",
            "failed_guard_detail": f"unmapped setup_filter_reason={reason}",
            "relevant_metric": "",
            "threshold": "",
            "observed_value": "",
            "source_table": "trade_setup_filter_observation" if filter_row else "paper_advice_observation",
            "source_ts_utc": source.get("asof_ts_utc"),
        }

    return {
        "fail_primary_reason": reason,
        "fail_reason_codes": [reason],
        "failed_guard_name": info["guard"],
        "failed_guard_detail": info["detail"],
        "relevant_metric": info["metric"],
        "threshold": info["threshold"],
        "observed_value": info["observed"],
        "source_table": "trade_setup_filter_observation" if filter_row else "paper_advice_observation",
        "source_ts_utc": source.get("asof_ts_utc"),
    }


def build_rows(
    *,
    paper_rows: list[dict[str, Any]],
    filter_by_asset: dict[int, dict[str, Any]],
    policy_by_asset: dict[int, dict[str, Any]],
    selection_by_asset: dict[int, dict[str, Any]],
    zone_by_asset: dict[int, dict[str, Any]],
    latest_candles: dict[int, dict[str, Any]],
    lifecycle_badges: dict[int, str],
    previous_paper_by_asset: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in paper_rows:
        asset_id = int(row["asset_id"])
        filter_row = filter_by_asset.get(asset_id)
        policy_row = policy_by_asset.get(asset_id)
        selection_row = selection_by_asset.get(asset_id)
        zone_row = zone_by_asset.get(asset_id)
        latest_candle = latest_candles.get(asset_id)
        previous_paper = previous_paper_by_asset.get(asset_id)
        diagnostic = reason_diagnostic(row, filter_row)
        current_zone_asof = zone_asof_from_row(row)
        previous_zone_asof = zone_asof_from_row(previous_paper)
        current_invalidation = as_decimal(row.get("invalidation_price"))
        previous_invalidation = as_decimal((previous_paper or {}).get("invalidation_price"))
        zone_changed_from_previous = (
            previous_paper is not None
            and (
                current_zone_asof != previous_zone_asof
                or current_invalidation != previous_invalidation
                or as_decimal(row.get("entry_zone_low")) != as_decimal(previous_paper.get("entry_zone_low"))
                or as_decimal(row.get("entry_zone_high")) != as_decimal(previous_paper.get("entry_zone_high"))
                or as_decimal(row.get("tp_zone_low")) != as_decimal(previous_paper.get("tp_zone_low"))
                or as_decimal(row.get("tp_zone_high")) != as_decimal(previous_paper.get("tp_zone_high"))
            )
        )

        out.append(
            {
                "symbol": row.get("symbol"),
                "advice_state": row.get("advice_state"),
                "action": row.get("advice_action"),
                "confidence_score": row.get("confidence_score"),
                "leg_direction": row.get("leg_direction"),
                "selection_state": row.get("selection_state") or (selection_row or {}).get("selection_state"),
                "setup_filter_state": row.get("setup_filter_state"),
                "policy_decision": row.get("policy_decision") or (policy_row or {}).get("policy_decision"),
                "risk_label": row.get("risk_label"),
                "reason_codes": parse_reason_codes(row.get("reason_codes_json")),
                "entry_zone_low": row.get("entry_zone_low") if row.get("entry_zone_low") is not None else (zone_row or {}).get("entry_zone_low"),
                "entry_zone_high": row.get("entry_zone_high") if row.get("entry_zone_high") is not None else (zone_row or {}).get("entry_zone_high"),
                "tp_zone_low": row.get("tp_zone_low") if row.get("tp_zone_low") is not None else (zone_row or {}).get("tp_zone_low"),
                "tp_zone_high": row.get("tp_zone_high") if row.get("tp_zone_high") is not None else (zone_row or {}).get("tp_zone_high"),
                "invalidation_price": row.get("invalidation_price") if row.get("invalidation_price") is not None else (zone_row or {}).get("invalidation_price"),
                "lifecycle_badge": lifecycle_badges.get(asset_id, ""),
                "latest_close_ts_utc": (latest_candle or {}).get("close_ts_utc"),
                "latest_close_price": (latest_candle or {}).get("close_price"),
                "priority_rank": row.get("priority_rank") if row.get("priority_rank") is not None else (selection_row or {}).get("priority_rank"),
                "selection_score": row.get("selection_score") if row.get("selection_score") is not None else (selection_row or {}).get("selection_score"),
                "btc_prior_24h": (filter_row or {}).get("btc_prior_24h"),
                "trade_setup_filter_asof_ts_utc": (filter_row or {}).get("asof_ts_utc"),
                "trade_setup_filter_reason": row.get("setup_filter_reason") or (filter_row or {}).get("setup_filter_reason"),
                "trade_setup_filter_notes": (filter_row or {}).get("notes"),
                "policy_reason": (policy_row or {}).get("policy_reason"),
                "current_zone_asof_ts_utc": current_zone_asof,
                "previous_paper_advice_asof_ts_utc": (previous_paper or {}).get("asof_ts_utc"),
                "previous_zone_asof_ts_utc": previous_zone_asof,
                "previous_invalidation_price": previous_invalidation,
                "zone_changed_from_previous_snapshot": zone_changed_from_previous,
                **diagnostic,
            }
        )
    return out


def counter_dict(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(Counter(str(row.get(key) or "") for row in rows))


def print_summary(rows: list[dict[str, Any]], *, symbol: str | None, latest_paper_asof: datetime | None) -> None:
    setup_counts = Counter(str(row.get("setup_filter_state") or "") for row in rows)
    fail_rows = [row for row in rows if str(row.get("setup_filter_state") or "").upper() == "FAIL"]
    watch_setup_fail = [
        row["symbol"]
        for row in rows
        if str(row.get("selection_state") or "").upper() in {"WATCH", "WATCHLIST", "WATCH_CORE"}
        and str(row.get("setup_filter_state") or "").upper() == "FAIL"
    ]
    interesting_lifecycle_fail = [
        row["symbol"]
        for row in rows
        if str(row.get("setup_filter_state") or "").upper() == "FAIL"
        and any(token in str(row.get("lifecycle_badge") or "") for token in ("ENTRY", "RETEST", "BOUNCE", "INVALIDATED"))
    ]

    print(f"report={REPORT} version={VERSION}")
    print("scope=read-only diagnostic")
    print("broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    print("selection_engine_changes=0 policy_changes=0 decision_gate_changes=0 execution_planner_changes=0 executor_changes=0")
    print(f"latest_paper_advice_asof_ts_utc={fmt(latest_paper_asof)}")
    print(f"row_count={len(rows)}")
    print(f"setup_pass_count={setup_counts.get('PASS', 0)}")
    print(f"setup_fail_count={setup_counts.get('FAIL', 0)}")
    print(f"by_selection_state={json.dumps(counter_dict(rows, 'selection_state'), sort_keys=True)}")
    print(f"by_advice_state={json.dumps(counter_dict(rows, 'advice_state'), sort_keys=True)}")
    print(f"by_policy_decision={json.dumps(counter_dict(rows, 'policy_decision'), sort_keys=True)}")
    print(f"by_fail_primary_reason={json.dumps(counter_dict(fail_rows, 'fail_primary_reason'), sort_keys=True)}")
    print(f"top_fail_reasons={json.dumps(Counter(row.get('fail_primary_reason') for row in fail_rows).most_common(10), default=json_default)}")
    print(f"selection_watch_but_setup_fail={','.join(watch_setup_fail)}")
    print(f"interesting_lifecycle_but_setup_fail={','.join(interesting_lifecycle_fail)}")
    if symbol:
        print(f"focused_symbol={symbol.upper()}")
    print()


def print_table(rows: list[dict[str, Any]], *, symbol: str | None, latest_paper_asof: datetime | None) -> None:
    print_summary(rows, symbol=symbol, latest_paper_asof=latest_paper_asof)
    headers = [
        "symbol",
        "advice",
        "action",
        "dir",
        "selection",
        "setup",
        "policy",
        "lifecycle",
        "fail_primary_reason",
        "failed_guard_name",
        "metric",
        "threshold",
        "observed",
        "latest_close",
    ]
    table_rows: list[list[str]] = []
    for row in rows:
        table_rows.append(
            [
                fmt(row.get("symbol")),
                fmt(row.get("advice_state")),
                fmt(row.get("action")),
                fmt(row.get("leg_direction")),
                fmt(row.get("selection_state")),
                fmt(row.get("setup_filter_state")),
                fmt(row.get("policy_decision")),
                fmt(row.get("lifecycle_badge")),
                fmt(row.get("fail_primary_reason")),
                fmt(row.get("failed_guard_name")),
                fmt(row.get("relevant_metric")),
                fmt(row.get("threshold")),
                fmt(row.get("observed_value")),
                fmt(row.get("latest_close_price")),
            ]
        )

    widths = [len(header) for header in headers]
    for row_values in table_rows:
        for idx, value in enumerate(row_values):
            widths[idx] = min(max(widths[idx], len(value)), 42)

    def clip(value: str, width: int) -> str:
        if len(value) <= width:
            return value
        return value[: max(0, width - 1)] + "…"

    def line(values: list[str]) -> str:
        return " | ".join(clip(values[idx], widths[idx]).ljust(widths[idx]) for idx in range(len(values)))

    print(line(headers))
    print("-+-".join("-" * width for width in widths))
    for row_values in table_rows:
        print(line(row_values))

    hype_rows = [row for row in rows if str(row.get("symbol") or "").upper() == "HYPE"]
    if hype_rows:
        row = hype_rows[0]
        print()
        print("--- HYPE focused diagnostic ---")
        for key in (
            "symbol",
            "advice_state",
            "action",
            "selection_state",
            "setup_filter_state",
            "policy_decision",
            "leg_direction",
            "entry_zone_low",
            "entry_zone_high",
            "tp_zone_low",
            "tp_zone_high",
            "invalidation_price",
            "lifecycle_badge",
            "fail_primary_reason",
            "failed_guard_name",
            "failed_guard_detail",
            "relevant_metric",
            "threshold",
            "observed_value",
            "trade_setup_filter_reason",
            "trade_setup_filter_notes",
            "latest_close_ts_utc",
            "latest_close_price",
            "current_zone_asof_ts_utc",
            "previous_paper_advice_asof_ts_utc",
            "previous_zone_asof_ts_utc",
            "previous_invalidation_price",
            "zone_changed_from_previous_snapshot",
        ):
            print(f"{key}={fmt(row.get(key))}")
        print(f"newer_4h_snapshot_reset_old_invalidation={fmt(row.get('zone_changed_from_previous_snapshot'))}")
        print("reaction_retest_with_setup_fail_consistency=consistent if lifecycle path is interesting but setup filter guard remains FAIL")


def main() -> int:
    args = parse_args()
    venue = str(args.venue)
    interval = str(args.interval)
    symbol = None if args.symbol is None else str(args.symbol).upper()

    load_dotenv(dotenv_path=Path(".env"))
    conn = get_db_connection()
    try:
        latest_paper_asof, paper_rows = fetch_latest_paper_rows(
            conn,
            venue=venue,
            interval=interval,
            limit=int(args.limit),
            symbol=symbol,
        )
        asset_ids = [int(row["asset_id"]) for row in paper_rows if row.get("asset_id") is not None]
        _, filter_by_asset, _ = fetch_latest_table_rows(conn, table="trade_setup_filter_observation", venue=venue)
        _, policy_by_asset, _ = fetch_latest_table_rows(conn, table="trade_setup_policy_preview_observation", venue=venue)
        _, selection_by_asset, _ = fetch_latest_table_rows(conn, table="selection_state", venue=venue)
        _, zone_by_asset, _ = fetch_latest_table_rows(conn, table="vw_paper_advice_execution_zone_context_v1", venue=venue, interval=interval)
        latest_candles = latest_candles_by_asset(conn, venue=venue, interval=LIFECYCLE_INTERVAL, asset_ids=asset_ids)
        lifecycle_badges = lifecycle_badges_by_asset(conn, venue=venue, rows=paper_rows)
        previous_paper_by_asset = previous_paper_rows_by_asset(
            conn,
            venue=venue,
            interval=interval,
            latest_asof=latest_paper_asof,
            asset_ids=asset_ids,
        )
    finally:
        conn.close()

    rows = build_rows(
        paper_rows=paper_rows,
        filter_by_asset=filter_by_asset,
        policy_by_asset=policy_by_asset,
        selection_by_asset=selection_by_asset,
        zone_by_asset=zone_by_asset,
        latest_candles=latest_candles,
        lifecycle_badges=lifecycle_badges,
        previous_paper_by_asset=previous_paper_by_asset,
    )

    if args.output == "jsonl":
        for row in rows:
            print(json.dumps(row, ensure_ascii=False, default=json_default, sort_keys=True))
    else:
        print_table(rows, symbol=symbol, latest_paper_asof=latest_paper_asof)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
