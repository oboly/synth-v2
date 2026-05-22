from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.advice.run_paper_advice_policy_v1 import (
    build_output_rows,
    fetch_latest_inputs,
    parse_aplus_table1,
    write_rows,
)
from src.common.db import get_connection
from src.market_data.market_price_snapshot_v1 import fetch_latest_prices_by_symbol
from src.reporting.run_fast_recompute_lifecycle_v1 import (
    RecomputeLifecycleRow,
    build_recompute_rows,
    fetch_latest_advice_rows,
)
from src.zone.engine_v1 import build_zone_engine_result
from src.zone.repository import ZoneRepository


REPORT_NAME = "fast_recompute_lifecycle_refresh_v1"
REPORT_VERSION = "0.1"

ENABLED_SCOPES = {"ZONE_AND_ADVICE_RECOMPUTE"}

SAFETY_LINE = (
    "broker_private_calls=0 broker_calls=0 broker_writes=0 order_submission=0 "
    "live_orders=0 decision_gate_changes=0 execution_planner_changes=0 "
    "executor=none account_awareness=0"
)


@dataclass(frozen=True)
class RefreshResultRow:
    symbol: str
    asset_id: int | None
    recommended_refresh_scope: str
    lifecycle_state: str
    recompute_reason: str
    old_leg_direction: str
    current_price: Decimal | None
    old_next_zone_state: str
    action_taken: str
    zone_result_state: str
    new_zone_asof_ts_utc: datetime | None
    paper_advice_refreshed: str
    post_refresh_state: str
    cooldown_label: str
    latest_zone_asof: str
    latest_advice_asof: datetime | None
    display_severity: str
    previous_refresh_count_for_asof: int


@dataclass(frozen=True)
class CooldownMarker:
    symbol: str
    asset_id: int
    advice_asof_ts_utc: datetime | None
    refreshed_zone_asof_ts_utc: str | None
    refresh_scope: str | None
    cooldown_state: str
    refreshed_at_utc: datetime | None
    refresh_count_for_asof: int
    current_price: Decimal | None
    lifecycle_state: str | None
    reason: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Consume the fast recompute lifecycle worklist and refresh market-only zones/advice."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--quote", default="EUR")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--sleeve-code", default="SWING_STRUCTURAL")
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--max-assets", type=int, default=6)
    parser.add_argument("--lookback-candles", type=int, default=120)
    parser.add_argument("--swing-window", type=int, default=5)
    parser.add_argument("--sr-tolerance-bps", default="60")
    parser.add_argument("--include-advice-only-review", action="store_true")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("summary", "table", "json"), default="table")
    parser.add_argument(
        "--cooldown-minutes",
        type=Decimal,
        default=Decimal(os.getenv("SYNTH_FAST_RECOMPUTE_COOLDOWN_MINUTES", "15")),
    )
    parser.add_argument(
        "--allow-intrabar-repeat",
        type=int,
        default=int(os.getenv("SYNTH_FAST_RECOMPUTE_ALLOW_INTRABAR_REPEAT", "1")),
    )
    parser.add_argument(
        "--max-per-asset-per-4h",
        type=int,
        default=int(os.getenv("SYNTH_FAST_RECOMPUTE_MAX_PER_ASSET_PER_4H", "3")),
    )
    return parser.parse_args()


def dec_text(value: Decimal | None, places: str = "0.000000") -> str:
    if value is None:
        return ""
    try:
        return str(value.quantize(Decimal(places)))
    except Exception:
        return str(value)


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="microseconds")
    return str(value)


def _json_loads_dict(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _asof_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="microseconds")
    return str(value)


def _parse_dt(value: Any) -> datetime | None:
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


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _price_move_pct(old: Decimal | None, new: Decimal | None) -> Decimal | None:
    if old is None or new is None or old <= 0:
        return None
    return abs((new / old) - Decimal("1")) * Decimal("100")


def cooldown_applies(
    row: RecomputeLifecycleRow,
    marker: CooldownMarker | None,
    *,
    cooldown_minutes: Decimal = Decimal("15"),
    allow_intrabar_repeat: bool = True,
    max_per_asset_per_4h: int = 3,
) -> bool:
    if marker is None:
        return False
    if _asof_text(row.asof_ts_utc) != _asof_text(marker.advice_asof_ts_utc):
        return False
    if not allow_intrabar_repeat:
        return True
    if marker.refresh_count_for_asof >= max_per_asset_per_4h:
        return True
    refreshed_at = marker.refreshed_at_utc
    if refreshed_at is None:
        return True
    age_minutes = Decimal(str((datetime.now(UTC).replace(tzinfo=None) - refreshed_at).total_seconds())) / Decimal("60")
    if age_minutes < cooldown_minutes:
        return True
    lifecycle_changed = (
        (marker.lifecycle_state or "") != row.lifecycle_state
        or (marker.reason or "") != row.recompute_reason
    )
    price_moved = (_price_move_pct(marker.current_price, row.current_price) or Decimal("0")) >= Decimal("0.25")
    return not (lifecycle_changed or price_moved)


def resolve_asset_ids(conn: Any, symbols: list[str]) -> dict[str, int]:
    normalized = sorted({symbol.upper() for symbol in symbols if symbol})
    if not normalized:
        return {}
    placeholders = []
    params: dict[str, Any] = {}
    for idx, symbol in enumerate(normalized):
        key = f"symbol_{idx}"
        placeholders.append(f"%({key})s")
        params[key] = symbol
    sql = f"""
    SELECT asset_id, symbol
    FROM asset
    WHERE UPPER(symbol) IN ({', '.join(placeholders)})
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    return {str(row["symbol"]).upper(): int(row["asset_id"]) for row in rows}


def fetch_cooldown_markers(
    conn: Any,
    *,
    venue: str,
    interval: str,
    symbols: list[str],
) -> dict[str, CooldownMarker]:
    normalized = sorted({symbol.upper() for symbol in symbols if symbol})
    if not normalized:
        return {}

    placeholders = []
    params: dict[str, Any] = {
        "venue": venue,
        "interval": interval,
    }
    for idx, symbol in enumerate(normalized):
        key = f"symbol_{idx}"
        placeholders.append(f"%({key})s")
        params[key] = symbol

    sql = f"""
    WITH ranked_advice AS (
        SELECT
            asset_id,
            symbol,
            asof_ts_utc,
            source_ref_json,
            ROW_NUMBER() OVER (
                PARTITION BY asset_id
                ORDER BY asof_ts_utc DESC, updated_ts_utc DESC
            ) AS rn
        FROM paper_advice_observation
        WHERE venue = %(venue)s
          AND interval_code = %(interval)s
          AND UPPER(symbol) IN ({', '.join(placeholders)})
    )
    SELECT
        asset_id,
        symbol,
        asof_ts_utc,
        source_ref_json
    FROM ranked_advice
    WHERE rn = 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())

    markers: dict[str, CooldownMarker] = {}
    for row in rows:
        source_ref = _json_loads_dict(row.get("source_ref_json"))
        refresh_ref = _json_loads_dict(source_ref.get("fast_recompute_refresh"))
        if refresh_ref.get("refreshed_by") != REPORT_NAME:
            continue
        marker_interval = refresh_ref.get("interval_code")
        if marker_interval is not None and str(marker_interval) != interval:
            continue
        refreshed_zone_asof = refresh_ref.get("zone_asof_ts_utc")
        if not refreshed_zone_asof:
            continue
        symbol = str(row["symbol"]).upper()
        markers[symbol] = CooldownMarker(
            symbol=symbol,
            asset_id=int(row["asset_id"]),
            advice_asof_ts_utc=row.get("asof_ts_utc"),
            refreshed_zone_asof_ts_utc=str(refreshed_zone_asof),
            refresh_scope=(
                None
                if refresh_ref.get("refresh_scope") is None
                else str(refresh_ref.get("refresh_scope"))
            ),
            cooldown_state="COOLDOWN_ALREADY_REFRESHED_THIS_CANDLE",
            refreshed_at_utc=_parse_dt(refresh_ref.get("refreshed_at_utc")),
            refresh_count_for_asof=int(refresh_ref.get("refresh_count_for_asof") or 1),
            current_price=_optional_decimal(refresh_ref.get("current_price")),
            lifecycle_state=(
                None if refresh_ref.get("lifecycle") is None else str(refresh_ref.get("lifecycle"))
            ),
            reason=None if refresh_ref.get("reason") is None else str(refresh_ref.get("reason")),
        )
    return markers


def selected_worklist_rows(
    rows: list[RecomputeLifecycleRow],
    *,
    max_assets: int,
    include_advice_only_review: bool,
    cooldown_by_symbol: dict[str, CooldownMarker],
    cooldown_minutes: Decimal = Decimal("15"),
    allow_intrabar_repeat: bool = True,
    max_per_asset_per_4h: int = 3,
) -> list[RecomputeLifecycleRow]:
    enabled = set(ENABLED_SCOPES)
    if include_advice_only_review:
        enabled.add("ADVICE_ONLY_REVIEW")
    selected = [
        row
        for row in rows
        if row.recommended_refresh_scope in enabled
        and not cooldown_applies(
            row,
            cooldown_by_symbol.get(row.symbol.upper()),
            cooldown_minutes=cooldown_minutes,
            allow_intrabar_repeat=allow_intrabar_repeat,
            max_per_asset_per_4h=max_per_asset_per_4h,
        )
    ]
    return selected[:max_assets]


def refresh_zone_for_asset(
    *,
    repo: ZoneRepository,
    asset_id: int,
    symbol: str,
    venue: str,
    interval: str,
    sleeve_code: str,
    lookback_candles: int,
    swing_window: int,
    sr_tolerance_bps: Decimal,
    write_db: bool,
) -> tuple[str, datetime | None]:
    candles = repo.fetch_recent_candles(
        asset_id=asset_id,
        symbol=symbol,
        venue=venue,
        interval_code=interval,
        limit=lookback_candles,
    )
    if len(candles) < 20:
        return "SKIPPED_ZONE_RESULT_MISSING", None

    result = build_zone_engine_result(
        repo=repo,
        candles=candles,
        swing_window=swing_window,
        sr_tolerance_bps=sr_tolerance_bps,
        sleeve_code=sleeve_code,
    )
    if result is None or result.execution_context is None:
        return "SKIPPED_ZONE_RESULT_MISSING", None

    if write_db:
        repo.upsert_fib_observation(result.fib_observation)
        for zone in result.zones:
            repo.upsert_zone_observation(zone)
        repo.delete_execution_zone_context_scope(
            venue=venue,
            interval_code=interval,
            sleeve_code=sleeve_code,
            asset_id=asset_id,
        )
        repo.upsert_execution_zone_context(result.execution_context)

    return "ZONE_RECOMPUTED", result.execution_context.asof_ts_utc


def refresh_paper_advice_for_assets(
    *,
    conn: Any,
    asset_ids: list[int],
    refresh_context_by_asset_id: dict[int, RefreshResultRow],
    venue: str,
    interval: str,
    write_db: bool,
) -> int:
    if not asset_ids or not write_db:
        return 0
    conn.rollback()
    aplus_prediction_ts, aplus_rows = parse_aplus_table1(Path("db://latest"))
    input_rows = fetch_latest_inputs(
        conn,
        venue=venue,
        interval_code=interval,
        limit=None,
        asset_ids=asset_ids,
    )
    output_rows = build_output_rows(
        input_rows,
        aplus_rows=aplus_rows,
        interval_code=interval,
        aplus_raw_path=Path("db://latest"),
        aplus_prediction_ts=aplus_prediction_ts,
    )
    refresh_ts = datetime.now(UTC).replace(tzinfo=None)
    for output_row in output_rows:
        asset_id = int(output_row["asset_id"])
        refresh_context = refresh_context_by_asset_id.get(asset_id)
        if refresh_context is None:
            continue
        source_ref = _json_loads_dict(output_row.get("source_ref_json"))
        zone_asof = None if refresh_context.new_zone_asof_ts_utc is None else str(refresh_context.new_zone_asof_ts_utc)
        source_ref["fast_recompute_refresh"] = {
            "refreshed_by": REPORT_NAME,
            "version": REPORT_VERSION,
            "interval_code": interval,
            "recompute_asof_ts_utc": str(output_row.get("asof_ts_utc")),
            "zone_asof_ts_utc": zone_asof,
            "refreshed_at_utc": refresh_ts.isoformat(sep=" ", timespec="microseconds"),
            "refresh_count_for_asof": refresh_context.previous_refresh_count_for_asof + 1,
            "refresh_scope": refresh_context.recommended_refresh_scope,
            "lifecycle": refresh_context.lifecycle_state,
            "reason": refresh_context.recompute_reason,
            "current_price": (
                None if refresh_context.current_price is None else str(refresh_context.current_price)
            ),
            "old_next_zone_state": refresh_context.old_next_zone_state,
        }
        output_row["source_ref_json"] = json.dumps(source_ref, ensure_ascii=False, default=json_default)
    return write_rows(conn, output_rows)


def classify_refresh_result(
    *,
    row: RecomputeLifecycleRow,
    action: str,
    zone_state: str,
    cooldown: CooldownMarker | None,
    new_asof: datetime | None,
) -> tuple[str, str, str, str]:
    if action == "PAPER_ADVICE_REFRESHED":
        return "REFRESHED_THIS_RUN", "", "DISPLAY_CONTEXT", _asof_text(new_asof)
    if action == "ZONE_RECOMPUTED":
        return "REFRESHED_THIS_RUN", "", "DISPLAY_CONTEXT", _asof_text(new_asof)
    if action == "SKIPPED_ALREADY_REFRESHED_THIS_ASOF":
        cooldown_label = "" if cooldown is None else cooldown.cooldown_state
        if row.lifecycle_state == "INVALIDATION_TOUCHED":
            return "RECOMPUTED_BUT_STILL_TRIGGERING", cooldown_label, "DISPLAY_CRITICAL", (
                "" if cooldown is None else str(cooldown.refreshed_zone_asof_ts_utc or "")
            )
        if row.recompute_needed or row.recommended_refresh_scope == "ZONE_AND_ADVICE_RECOMPUTE":
            return "COOLDOWN_MONITOR", cooldown_label, "DISPLAY_WATCH", (
                "" if cooldown is None else str(cooldown.refreshed_zone_asof_ts_utc or "")
            )
        return "REFRESHED_RECENTLY", cooldown_label, "DISPLAY_MUTED", (
            "" if cooldown is None else str(cooldown.refreshed_zone_asof_ts_utc or "")
        )
    if action in {"FAILED_SAFE", "SKIPPED_ZONE_RESULT_MISSING"} or zone_state in {
        "FAILED_SAFE",
        "SKIPPED_ZONE_RESULT_MISSING",
    }:
        return "REFRESH_FAILED_OR_STALE", "", "DISPLAY_CRITICAL", ""
    if action in {"SKIPPED_MAX_ASSETS_THROTTLE", "DRY_RUN_ZONE_AND_ADVICE_RECOMPUTE"}:
        return "REFRESH_NEEDED", "", "DISPLAY_CRITICAL", ""
    if row.recommended_refresh_scope == "SKIP_ACTIVE_MAP":
        return "NO_REFRESH_NEEDED", "", "DISPLAY_CONTEXT", ""
    return "NO_REFRESH_NEEDED", "", "DISPLAY_MUTED", ""


def build_refresh_rows(
    *,
    worklist_rows: list[RecomputeLifecycleRow],
    asset_by_symbol: dict[str, int],
    cooldown_by_symbol: dict[str, CooldownMarker],
    args: argparse.Namespace,
) -> tuple[list[RefreshResultRow], list[int]]:
    repo = ZoneRepository()
    output: list[RefreshResultRow] = []
    refreshed_asset_ids: list[int] = []
    selected = selected_worklist_rows(
        worklist_rows,
        max_assets=int(args.max_assets),
        include_advice_only_review=bool(args.include_advice_only_review),
        cooldown_by_symbol=cooldown_by_symbol,
        cooldown_minutes=Decimal(str(args.cooldown_minutes)),
        allow_intrabar_repeat=bool(int(args.allow_intrabar_repeat)),
        max_per_asset_per_4h=int(args.max_per_asset_per_4h),
    )
    selected_symbols = {row.symbol for row in selected}
    enabled_scopes = set(ENABLED_SCOPES)
    if bool(args.include_advice_only_review):
        enabled_scopes.add("ADVICE_ONLY_REVIEW")

    for row in worklist_rows:
        asset_id = asset_by_symbol.get(row.symbol)
        cooldown = cooldown_by_symbol.get(row.symbol.upper())
        if cooldown_applies(
            row,
            cooldown,
            cooldown_minutes=Decimal(str(args.cooldown_minutes)),
            allow_intrabar_repeat=bool(int(args.allow_intrabar_repeat)),
            max_per_asset_per_4h=int(args.max_per_asset_per_4h),
        ) and row.recommended_refresh_scope in enabled_scopes:
            action = "SKIPPED_ALREADY_REFRESHED_THIS_ASOF"
            zone_state = cooldown.cooldown_state
            new_asof = None
            paper_refreshed = "NO"
        elif row.symbol not in selected_symbols and row.recommended_refresh_scope in enabled_scopes:
            action = "SKIPPED_MAX_ASSETS_THROTTLE"
            zone_state = "WAITING_MAX_ASSETS_THROTTLE"
            new_asof = None
            paper_refreshed = "NO"
        elif row.symbol not in selected_symbols:
            action = "SKIPPED_SCOPE_NOT_ENABLED"
            zone_state = "NOT_SELECTED"
            new_asof = None
            paper_refreshed = "NO"
        elif asset_id is None:
            action = "SKIPPED_ASSET_NOT_FOUND"
            zone_state = "ASSET_NOT_FOUND"
            new_asof = None
            paper_refreshed = "NO"
        elif row.recommended_refresh_scope not in ENABLED_SCOPES:
            action = "SKIPPED_SCOPE_NOT_ENABLED"
            zone_state = "SCOPE_NOT_ENABLED"
            new_asof = None
            paper_refreshed = "NO"
        elif not args.write_db:
            action = "DRY_RUN_ZONE_AND_ADVICE_RECOMPUTE"
            zone_state = "DRY_RUN"
            new_asof = None
            paper_refreshed = "NO"
        else:
            try:
                zone_state, new_asof = refresh_zone_for_asset(
                    repo=repo,
                    asset_id=asset_id,
                    symbol=row.symbol,
                    venue=str(args.venue),
                    interval=str(args.interval),
                    sleeve_code=str(args.sleeve_code),
                    lookback_candles=int(args.lookback_candles),
                    swing_window=int(args.swing_window),
                    sr_tolerance_bps=Decimal(str(args.sr_tolerance_bps)),
                    write_db=True,
                )
                if zone_state == "ZONE_RECOMPUTED":
                    action = "ZONE_RECOMPUTED"
                    refreshed_asset_ids.append(asset_id)
                else:
                    action = zone_state
                paper_refreshed = "NO"
            except Exception:
                action = "FAILED_SAFE"
                zone_state = "FAILED_SAFE"
                new_asof = None
                paper_refreshed = "NO"

        post_refresh_state, cooldown_label, display_severity, latest_zone_asof = classify_refresh_result(
            row=row,
            action=action,
            zone_state=zone_state,
            cooldown=cooldown,
            new_asof=new_asof,
        )
        previous_refresh_count = 0 if cooldown is None else int(cooldown.refresh_count_for_asof)
        output.append(
            RefreshResultRow(
                symbol=row.symbol,
                asset_id=asset_id,
                recommended_refresh_scope=row.recommended_refresh_scope,
                lifecycle_state=row.lifecycle_state,
                recompute_reason=row.recompute_reason,
                old_leg_direction=row.leg_direction,
                current_price=row.current_price,
                old_next_zone_state=row.next_zone_state,
                action_taken=action,
                zone_result_state=zone_state,
                new_zone_asof_ts_utc=new_asof,
                paper_advice_refreshed=paper_refreshed,
                post_refresh_state=post_refresh_state,
                cooldown_label=cooldown_label,
                latest_zone_asof=latest_zone_asof,
                latest_advice_asof=row.asof_ts_utc,
                display_severity=display_severity,
                previous_refresh_count_for_asof=previous_refresh_count,
            )
        )

    return output, list(dict.fromkeys(refreshed_asset_ids))


def mark_paper_refreshed(rows: list[RefreshResultRow], refreshed_asset_ids: set[int]) -> list[RefreshResultRow]:
    output: list[RefreshResultRow] = []
    for row in rows:
        if row.asset_id in refreshed_asset_ids and row.action_taken == "ZONE_RECOMPUTED":
            output.append(
                RefreshResultRow(
                    **{
                        **asdict(row),
                        "action_taken": "PAPER_ADVICE_REFRESHED",
                        "paper_advice_refreshed": "YES",
                        "post_refresh_state": "REFRESHED_THIS_RUN",
                        "display_severity": "DISPLAY_CONTEXT",
                    }
                )
            )
        else:
            output.append(row)
    return output


def build_refresh_context_by_asset_id(rows: list[RefreshResultRow]) -> dict[int, RefreshResultRow]:
    contexts: dict[int, RefreshResultRow] = {}
    for row in rows:
        if row.asset_id is None or row.action_taken != "ZONE_RECOMPUTED":
            continue
        contexts[int(row.asset_id)] = row
    return contexts


def print_table(rows: list[RefreshResultRow]) -> None:
    headers = [
        "symbol",
        "asset_id",
        "scope",
        "lifecycle",
        "reason",
        "old_leg",
        "price",
        "old_next_zone",
        "action",
        "zone_state",
        "post_refresh_state",
        "cooldown",
        "display_severity",
        "latest_zone_asof",
        "latest_advice_asof",
        "new_zone_asof",
        "paper_advice",
    ]
    print(" | ".join(headers))
    print("-+-".join("-" * len(header) for header in headers))
    for row in rows:
        print(
            " | ".join(
                [
                    row.symbol,
                    "" if row.asset_id is None else str(row.asset_id),
                    row.recommended_refresh_scope,
                    row.lifecycle_state,
                    row.recompute_reason,
                    row.old_leg_direction,
                    dec_text(row.current_price),
                    row.old_next_zone_state,
                    row.action_taken,
                    row.zone_result_state,
                    row.post_refresh_state,
                    row.cooldown_label,
                    row.display_severity,
                    row.latest_zone_asof,
                    "" if row.latest_advice_asof is None else str(row.latest_advice_asof),
                    "" if row.new_zone_asof_ts_utc is None else str(row.new_zone_asof_ts_utc),
                    row.paper_advice_refreshed,
                ]
            )
        )


def summary_counts(rows: list[RefreshResultRow], *, total_recompute_candidates: int) -> dict[str, int]:
    state_counts = Counter(row.post_refresh_state for row in rows)
    action_counts = Counter(row.action_taken for row in rows)
    return {
        "total_recompute_candidates": int(total_recompute_candidates),
        "refreshed_this_run": int(state_counts.get("REFRESHED_THIS_RUN", 0)),
        "cooldown_monitor": int(state_counts.get("COOLDOWN_MONITOR", 0)),
        "recomputed_but_still_triggering": int(
            state_counts.get("RECOMPUTED_BUT_STILL_TRIGGERING", 0)
        ),
        "skipped_max_assets_throttle": int(action_counts.get("SKIPPED_MAX_ASSETS_THROTTLE", 0)),
        "refresh_failed_or_stale": int(state_counts.get("REFRESH_FAILED_OR_STALE", 0)),
        "no_refresh_needed": int(state_counts.get("NO_REFRESH_NEEDED", 0)),
    }


def main() -> int:
    args = parse_args()

    conn = get_connection()
    try:
        _, advice_rows = fetch_latest_advice_rows(
            conn,
            venue=str(args.venue),
            interval=str(args.interval),
            limit=int(args.limit),
        )
        price_by_symbol = fetch_latest_prices_by_symbol(
            conn,
            venue=str(args.venue),
            quote_currency=str(args.quote),
            symbols=[str(row.get("symbol") or "").upper() for row in advice_rows],
        )
        worklist_rows = build_recompute_rows(
            advice_rows,
            venue=str(args.venue),
            interval=str(args.interval),
            price_by_symbol=price_by_symbol,
        )
        asset_by_symbol = resolve_asset_ids(conn, [row.symbol for row in worklist_rows])
        cooldown_by_symbol = fetch_cooldown_markers(
            conn,
            venue=str(args.venue),
            interval=str(args.interval),
            symbols=[row.symbol for row in worklist_rows],
        )
        result_rows, refreshed_asset_ids = build_refresh_rows(
            worklist_rows=worklist_rows,
            asset_by_symbol=asset_by_symbol,
            cooldown_by_symbol=cooldown_by_symbol,
            args=args,
        )
        advice_written = refresh_paper_advice_for_assets(
            conn=conn,
            asset_ids=refreshed_asset_ids,
            refresh_context_by_asset_id=build_refresh_context_by_asset_id(result_rows),
            venue=str(args.venue),
            interval=str(args.interval),
            write_db=bool(args.write_db),
        )
        if advice_written:
            result_rows = mark_paper_refreshed(result_rows, set(refreshed_asset_ids))
    finally:
        conn.close()

    if args.output == "summary":
        counts = summary_counts(result_rows, total_recompute_candidates=len(worklist_rows))
        print(f"report={REPORT_NAME} version={REPORT_VERSION}")
        print(f"write_db={bool(args.write_db)} candidates={len(worklist_rows)} rows={len(result_rows)}")
        print(f"zone_refreshed_assets={len(refreshed_asset_ids)} paper_advice_rows_written={advice_written}")
        print("counts=" + " ".join(f"{key}={value}" for key, value in counts.items()))
        print(
            "cadence="
            f"cooldown_minutes={args.cooldown_minutes} "
            f"allow_intrabar_repeat={int(args.allow_intrabar_repeat)} "
            f"max_per_asset_per_4h={int(args.max_per_asset_per_4h)}"
        )
        print(SAFETY_LINE)
    elif args.output == "json":
        print(
            json.dumps(
                {
                    "report": REPORT_NAME,
                    "version": REPORT_VERSION,
                    "write_db": bool(args.write_db),
                    "summary_counts": summary_counts(
                        result_rows,
                        total_recompute_candidates=len(worklist_rows),
                    ),
                    "rows": [asdict(row) for row in result_rows],
                    "paper_advice_rows_written": advice_written,
                    "cooldown_minutes": str(args.cooldown_minutes),
                    "allow_intrabar_repeat": int(args.allow_intrabar_repeat),
                    "max_per_asset_per_4h": int(args.max_per_asset_per_4h),
                    "broker_private_calls": 0,
                    "broker_calls": 0,
                    "broker_writes": 0,
                    "order_submission": 0,
                    "live_orders": 0,
                    "decision_gate_changes": 0,
                    "execution_planner_changes": 0,
                    "executor": "none",
                    "account_awareness": 0,
                },
                indent=2,
                sort_keys=True,
                default=json_default,
            )
        )
    else:
        print_table(result_rows)
        print(SAFETY_LINE)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
