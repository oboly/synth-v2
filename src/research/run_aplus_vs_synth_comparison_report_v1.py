from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.research.run_aplus_prime17_opportunity_report_v1 import (
    PRIME17_TOKENS,
    Table1FocusRecord,
    Table2FocusRecord,
    classify_bucket,
    fetch_asset_ids,
    fetch_optional_context,
    format_volume_summary,
    format_zone_summary,
    parse_focus_table1,
    parse_focus_table2,
    safe_decimal_text,
    selection_confirmed,
    selection_is_constructive,
    table_exists,
    volume_confirmed,
    zone_valid,
)


REPORT_NAME = "aplus_vs_synth_comparison_report_v1"
REPORT_VERSION = "1.0"
DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE = "EUR"
DEFAULT_INTERVAL = "1d"
DEFAULT_RELOAD_SELECTED_EVENTS = Path(
    "data/research/reload_reaction_scalp_parameter_sweep_v1/reload_reaction_scalp_selected_events_v1.jsonl"
)
RELOAD_ROLE_PRIORITY = {"ROBUST": 0, "RAW_EDGE": 1, "LOW_MAE": 2, "APLUS": 3, "WICK_TOUCH": 4}
SETUP_FAIL_BEARISH_REASONS = {
    "MARKET_DAMAGE_RISK",
    "MARKET_DAMAGE_CAUTION",
    "SELECTION_STATE_NOT_ELIGIBLE",
    "BTC_PRIOR_OVERHEAT_ZONE",
}


@dataclass(frozen=True)
class ComparisonRow:
    token: str
    aplus_bucket: str
    aplus_phase: str
    aplus_coherence: str
    aplus_field: str
    aplus_role: str
    aplus_bias: str
    harmonic_phase: str
    phase_state: str
    offset_band: str
    drift_direction: str
    quality: str
    extension_risk: str
    selection_state: str
    selection_score: str
    setup_state: str
    setup_reason: str
    zone_context_summary: str
    reload_context_summary: str
    reload_context_role: str
    reload_context_promotable: str
    volume_context_summary: str
    synth_confirmation_strength: str
    synth_bucket: str
    comparison_bucket: str
    reason: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only comparison of A+ Prime-17 posture versus existing Synth context "
            "(selection/setup/zone/reload/volume), with explicit comparison buckets."
        )
    )
    parser.add_argument("--table1-raw", required=True)
    parser.add_argument("--table2-raw", required=True)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--reload-selected-events", default=str(DEFAULT_RELOAD_SELECTED_EVENTS))
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = line.strip()
            if not payload:
                continue
            loaded = json.loads(payload)
            if isinstance(loaded, dict):
                rows.append(loaded)
    return rows


def parse_ts(value: Any) -> datetime:
    text = str(value or "").strip()
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def tokens_in_both(
    table1: dict[str, Table1FocusRecord],
    table2: dict[str, Table2FocusRecord],
) -> list[str]:
    both = set(table1) & set(table2)
    return [token for token in PRIME17_TOKENS if token in both]


def fetch_latest_setup_context(conn: Any, *, tokens: list[str], venue: str) -> dict[str, dict[str, Any]]:
    if not tokens or not table_exists(conn, "trade_setup_filter_observation"):
        return {}
    placeholders = ", ".join(["%s"] * len(tokens))
    sql = f"""
        SELECT symbol, asof_ts_utc, setup_filter_state, setup_filter_reason, selection_score
        FROM trade_setup_filter_observation
        WHERE venue = %s
          AND symbol IN ({placeholders})
        ORDER BY symbol ASC, asof_ts_utc DESC, trade_setup_filter_observation_id DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql, [venue, *tokens])
        rows = cur.fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row["symbol"]).upper()
        if symbol not in out:
            out[symbol] = row
    return out


def fetch_latest_paper_advice_context(
    conn: Any,
    *,
    tokens: list[str],
    venue: str,
    interval: str,
) -> dict[str, dict[str, Any]]:
    if not tokens or not table_exists(conn, "paper_advice_observation"):
        return {}
    placeholders = ", ".join(["%s"] * len(tokens))
    sql = f"""
        SELECT
            symbol,
            asof_ts_utc,
            advice_state,
            advice_action,
            confidence_score,
            risk_label,
            setup_filter_state,
            setup_filter_reason,
            current_target_horizon
        FROM paper_advice_observation
        WHERE venue = %s
          AND interval_code = %s
          AND symbol IN ({placeholders})
        ORDER BY symbol ASC, asof_ts_utc DESC, paper_advice_observation_id DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql, [venue, interval, *tokens])
        rows = cur.fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row["symbol"]).upper()
        if symbol not in out:
            out[symbol] = row
    return out


def load_reload_selected_event_context(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        priority = RELOAD_ROLE_PRIORITY.get(str(row.get("candidate_role") or "").upper(), 99)
        ts_text = str(row.get("event_ts_utc") or "")
        try:
            ts = parse_ts(ts_text)
        except Exception:
            ts = datetime.min.replace(tzinfo=UTC)
        current_best = out.get(symbol)
        if current_best is None:
            out[symbol] = {"priority": priority, "ts": ts, "row": row}
            continue
        if priority < int(current_best["priority"]):
            out[symbol] = {"priority": priority, "ts": ts, "row": row}
            continue
        if priority == int(current_best["priority"]) and ts > current_best["ts"]:
            out[symbol] = {"priority": priority, "ts": ts, "row": row}
    return {symbol: payload["row"] for symbol, payload in out.items()}


def fetch_additional_context(
    *,
    tokens: list[str],
    venue: str,
    interval: str,
    reload_selected_events: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    meta = {
        "setup_context": "unavailable",
        "paper_advice_context": "unavailable",
        "reload_selected_events": "available" if reload_selected_events.exists() else "unavailable",
        "db_error": None,
    }
    reload_selected_map = load_reload_selected_event_context(reload_selected_events)
    try:
        conn = get_connection()
    except Exception as exc:
        meta["db_error"] = f"{type(exc).__name__}: {exc}"
        return {}, {}, reload_selected_map, meta
    try:
        setup_map = fetch_latest_setup_context(conn, tokens=tokens, venue=venue)
        paper_advice_map = fetch_latest_paper_advice_context(conn, tokens=tokens, venue=venue, interval=interval)
        meta["setup_context"] = "available" if setup_map else "unavailable"
        meta["paper_advice_context"] = "available" if paper_advice_map else "unavailable"
        return setup_map, paper_advice_map, reload_selected_map, meta
    except Exception as exc:
        meta["db_error"] = f"{type(exc).__name__}: {exc}"
        return {}, {}, reload_selected_map, meta
    finally:
        conn.close()


def format_reload_summary(selected_event: dict[str, Any] | None, paper_advice_row: dict[str, Any] | None) -> str:
    if selected_event:
        return (
            f"role={selected_event.get('candidate_role')}; "
            f"parameter={selected_event.get('parameter_key')}; "
            f"bucket={selected_event.get('reason_bucket')}; "
            f"ret15m={selected_event.get('forward_return_15m_pct')}; "
            f"mfe={selected_event.get('max_favorable_excursion_pct')}"
        )
    if paper_advice_row:
        return (
            f"advice_state={paper_advice_row.get('advice_state')}; "
            f"advice_action={paper_advice_row.get('advice_action')}; "
            f"risk={paper_advice_row.get('risk_label')}; "
            f"horizon={paper_advice_row.get('current_target_horizon')}"
        )
    return "unavailable"


def parse_reload_context(selected_event: dict[str, Any] | None, paper_advice_row: dict[str, Any] | None) -> tuple[str, str]:
    if selected_event:
        role = str(selected_event.get("candidate_role") or "UNKNOWN").upper()
        promotable = "true" if role == "ROBUST" else "false"
        return role, promotable
    if paper_advice_row:
        return "UNKNOWN", "unknown"
    return "UNAVAILABLE", "unknown"


def aplus_constructive_state(t1: Table1FocusRecord, t2: Table2FocusRecord) -> tuple[bool, bool]:
    constructive = (
        t1.aplus_phase in {"forming", "confirmed"}
        and t1.aplus_coherence in {"high", "moderate"}
        and t1.aplus_bias in {"accumulation", "continuation"}
        and t2.quality in {"clean", "mixed"}
        and t2.extension_risk in {"low", "moderate"}
        and t2.harmonic_phase not in {"late_extension", "reset", "unclear"}
        and t2.phase_state not in {"late", "exhausted"}
    )
    caution = (
        t1.aplus_phase in {"late", "exhaustion", "reset"}
        or t1.aplus_bias in {"caution", "avoid"}
        or t2.harmonic_phase in {"late_extension", "reset"}
        or t2.phase_state in {"late", "exhausted"}
        or t2.quality == "dirty"
        or t2.extension_risk == "high"
    )
    return constructive, caution


def synth_flags(
    *,
    selection_row: dict[str, Any] | None,
    setup_row: dict[str, Any] | None,
    zone_summary: str,
    reload_summary: str,
    volume_row: dict[str, Any] | None,
    paper_advice_row: dict[str, Any] | None,
) -> dict[str, Any]:
    selection_state = str(selection_row.get("selection_state") if selection_row else "unavailable").upper()
    setup_state = str(setup_row.get("setup_filter_state") if setup_row else "unavailable").upper()
    setup_reason = str(setup_row.get("setup_filter_reason") if setup_row else "unavailable").upper()
    advice_state = str(paper_advice_row.get("advice_state") if paper_advice_row else "unavailable").upper()
    advice_action = str(paper_advice_row.get("advice_action") if paper_advice_row else "unavailable").upper()
    selection_yes = selection_confirmed(selection_row)
    setup_yes = setup_state == "PASS"
    zone_yes = zone_valid(zone_summary)
    volume_yes = volume_confirmed(volume_row)
    reload_role = "UNAVAILABLE"
    reload_promotable = "unknown"
    reload_yes = False
    reload_hard = False
    reload_raw_only = False
    upper_reload_summary = reload_summary.upper()
    if reload_summary != "unavailable":
        reload_yes = (
            "ROLE=" in upper_reload_summary
            or "ADVICE_ACTION=RELOAD_REVIEW" in upper_reload_summary
            or "ADVICE_ACTION=BUY_REVIEW" in upper_reload_summary
        )
        if "ROLE=ROBUST" in upper_reload_summary:
            reload_role = "ROBUST"
            reload_promotable = "true"
            reload_hard = True
        elif "ROLE=RAW_EDGE" in upper_reload_summary:
            reload_role = "RAW_EDGE"
            reload_promotable = "false"
            reload_raw_only = True
        elif "ROLE=LOW_MAE" in upper_reload_summary:
            reload_role = "LOW_MAE"
            reload_promotable = "false"
            reload_raw_only = True
        elif "ROLE=APLUS" in upper_reload_summary:
            reload_role = "APLUS"
            reload_promotable = "false"
            reload_raw_only = True
        elif "ROLE=WICK_TOUCH" in upper_reload_summary:
            reload_role = "WICK_TOUCH"
            reload_promotable = "false"
            reload_raw_only = True
        elif "ADVICE_ACTION=RELOAD_REVIEW" in upper_reload_summary or "ADVICE_ACTION=BUY_REVIEW" in upper_reload_summary:
            reload_role = "UNKNOWN"
            reload_promotable = "unknown"
    hard_confirm = selection_yes or setup_yes or (zone_yes and reload_hard)
    soft_context = zone_yes or volume_yes
    raw_edge_only = reload_raw_only and not hard_confirm
    synth_any_positive = hard_confirm or soft_context or reload_yes
    synth_bear = (
        selection_state == "AVOID"
        or (setup_state == "FAIL" and setup_reason in SETUP_FAIL_BEARISH_REASONS)
        or advice_state in {"INVALIDATED", "AVOID", "WAIT"}
        or advice_action in {"AVOID", "INVALIDATED"}
    )
    unavailable_count = sum(
        1
        for value in [selection_row, setup_row, volume_row]
        if value in (None, {})
    )
    return {
        "selection_yes": selection_yes,
        "setup_yes": setup_yes,
        "zone_yes": zone_yes,
        "volume_yes": volume_yes,
        "reload_yes": reload_yes,
        "reload_role": reload_role,
        "reload_promotable": reload_promotable,
        "reload_hard": reload_hard,
        "reload_raw_only": reload_raw_only,
        "hard_confirm": hard_confirm,
        "soft_context": soft_context,
        "raw_edge_only": raw_edge_only,
        "synth_any_positive": synth_any_positive,
        "synth_bear": synth_bear,
        "mostly_unavailable": unavailable_count >= 2 and zone_summary == "unavailable" and reload_summary == "unavailable",
    }


def classify_synth_bucket(
    *,
    selection_row: dict[str, Any] | None,
    setup_row: dict[str, Any] | None,
    zone_summary: str,
    reload_summary: str,
    volume_row: dict[str, Any] | None,
    paper_advice_row: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    flags = synth_flags(
        selection_row=selection_row,
        setup_row=setup_row,
        zone_summary=zone_summary,
        reload_summary=reload_summary,
        volume_row=volume_row,
        paper_advice_row=paper_advice_row,
    )
    if flags["hard_confirm"]:
        return "SYNTH_CONFIRMED_UP", flags
    if flags["raw_edge_only"]:
        return "SYNTH_RAW_EDGE_CONTEXT", flags
    if flags["synth_any_positive"]:
        return "SYNTH_REVIEW_UP", flags
    if flags["synth_bear"]:
        return "SYNTH_AVOID_OR_FAIL", flags
    if flags["mostly_unavailable"]:
        return "SYNTH_UNAVAILABLE", flags
    return "SYNTH_MIXED_WAIT", flags


def classify_comparison_bucket(
    *,
    aplus_constructive: bool,
    aplus_caution: bool,
    synth_bucket: str,
    synth_confirmation_strength: str,
) -> tuple[str, str]:
    synth_constructive = synth_bucket in {"SYNTH_CONFIRMED_UP", "SYNTH_REVIEW_UP"}
    synth_bear = synth_bucket == "SYNTH_AVOID_OR_FAIL"
    synth_raw = synth_bucket == "SYNTH_RAW_EDGE_CONTEXT"
    if aplus_constructive and synth_confirmation_strength == "HARD_CONFIRM":
        return "BOTH_AGREE_UP", "aplus_constructive_and_synth_confirms"
    if aplus_constructive and synth_confirmation_strength == "SOFT_CONTEXT":
        return "APLUS_CONSTRUCTIVE_SYNTH_SOFT_CONTEXT", "aplus_constructive_but_synth_only_has_soft_context"
    if aplus_constructive and synth_raw:
        return "APLUS_CONSTRUCTIVE_SYNTH_RAW_CONTEXT", "aplus_constructive_but_synth_only_has_raw_edge_context"
    if aplus_constructive and (synth_bear or synth_confirmation_strength == "NO_CONFIRM"):
        return "APLUS_CONSTRUCTIVE_SYNTH_BLOCKED", "aplus_constructive_but_synth_is_explicitly_blocked"
    if aplus_constructive:
        return "A_PLUS_ONLY_WAIT", "aplus_constructive_but_synth_confirmation_missing"
    if aplus_caution and synth_bucket == "SYNTH_CONFIRMED_UP":
        return "CONFLICT_SYNTH_BULL_A_PLUS_BEAR", "synth_strong_but_aplus_caution"
    if aplus_caution and synth_raw:
        return "SYNTH_RAW_CONTEXT_A_PLUS_CAUTION", "synth_has_only_raw_edge_context_while_aplus_is_caution"
    if aplus_caution:
        return "BOTH_CAUTION", "aplus_caution_and_synth_weak_or_bearish"
    if synth_constructive:
        return "SYNTH_ONLY_REVIEW", "synth_constructive_without_aplus_constructive_alignment"
    return "INSUFFICIENT_CONTEXT", "not_enough_shared_signal_context"


def build_rows(
    *,
    tokens: list[str],
    table1: dict[str, Table1FocusRecord],
    table2: dict[str, Table2FocusRecord],
    selection_map: dict[str, dict[str, Any]],
    setup_map: dict[str, dict[str, Any]],
    zone_map: dict[str, dict[str, Any]],
    volume_map: dict[str, dict[str, Any]],
    paper_advice_map: dict[str, dict[str, Any]],
    reload_selected_map: dict[str, dict[str, Any]],
) -> list[ComparisonRow]:
    rows: list[ComparisonRow] = []
    for token in tokens:
        t1 = table1[token]
        t2 = table2[token]
        selection_row = selection_map.get(token)
        setup_row = setup_map.get(token)
        zone_summary = format_zone_summary(zone_map.get(token))
        volume_summary = format_volume_summary(volume_map.get(token))
        paper_advice_row = paper_advice_map.get(token)
        reload_selected_row = reload_selected_map.get(token)
        reload_summary = format_reload_summary(reload_selected_row, paper_advice_row)
        reload_context_role, reload_context_promotable = parse_reload_context(reload_selected_row, paper_advice_row)
        aplus_bucket, _ = classify_bucket(
            token=token,
            t1=t1,
            t2=t2,
            selection_row=selection_row,
            zone_summary=zone_summary,
            volume_row=volume_map.get(token),
        )
        synth_bucket, flags = classify_synth_bucket(
            selection_row=selection_row,
            setup_row=setup_row,
            zone_summary=zone_summary,
            reload_summary=reload_summary,
            volume_row=volume_map.get(token),
            paper_advice_row=paper_advice_row,
        )
        synth_confirmation_strength = (
            "HARD_CONFIRM"
            if flags["hard_confirm"]
            else "RAW_EDGE_ONLY"
            if flags["raw_edge_only"]
            else "SOFT_CONTEXT"
            if flags["soft_context"]
            else "NO_CONFIRM"
        )
        aplus_constructive, aplus_caution = aplus_constructive_state(t1, t2)
        comparison_bucket, comparison_reason = classify_comparison_bucket(
            aplus_constructive=aplus_constructive,
            aplus_caution=aplus_caution,
            synth_bucket=synth_bucket,
            synth_confirmation_strength=synth_confirmation_strength,
        )
        reason = (
            f"{comparison_reason}; aplus_bucket={aplus_bucket}; synth_bucket={synth_bucket}; "
            f"confirmation_strength={synth_confirmation_strength}; "
            f"selection={'yes' if flags['selection_yes'] else 'no'}; "
            f"setup={'yes' if flags['setup_yes'] else 'no'}; "
            f"zone={'yes' if flags['zone_yes'] else 'no'}; "
            f"reload={'yes' if flags['reload_yes'] else 'no'}; "
            f"reload_role={reload_context_role}; "
            f"reload_promotable={reload_context_promotable}; "
            f"volume={'yes' if flags['volume_yes'] else 'no'}"
        )
        rows.append(
            ComparisonRow(
                token=token,
                aplus_bucket=aplus_bucket,
                aplus_phase=t1.aplus_phase,
                aplus_coherence=t1.aplus_coherence,
                aplus_field=t1.aplus_field,
                aplus_role=t1.aplus_role,
                aplus_bias=t1.aplus_bias,
                harmonic_phase=t2.harmonic_phase,
                phase_state=t2.phase_state,
                offset_band=t2.offset_band,
                drift_direction=t2.drift_direction,
                quality=t2.quality,
                extension_risk=t2.extension_risk,
                selection_state=str(selection_row.get("selection_state")) if selection_row else "unavailable",
                selection_score=safe_decimal_text(selection_row.get("selection_score") if selection_row else None),
                setup_state=str(setup_row.get("setup_filter_state")) if setup_row else "unavailable",
                setup_reason=str(setup_row.get("setup_filter_reason")) if setup_row else "unavailable",
                zone_context_summary=zone_summary,
                reload_context_summary=reload_summary,
                reload_context_role=reload_context_role,
                reload_context_promotable=reload_context_promotable,
                volume_context_summary=volume_summary,
                synth_confirmation_strength=synth_confirmation_strength,
                synth_bucket=synth_bucket,
                comparison_bucket=comparison_bucket,
                reason=reason,
            )
        )
    return rows


def print_table(rows: list[ComparisonRow]) -> None:
    columns = [
        "token",
        "aplus_bucket",
        "aplus_phase",
        "aplus_coherence",
        "aplus_field",
        "aplus_role",
        "aplus_bias",
        "harmonic_phase",
        "phase_state",
        "offset_band",
        "drift_direction",
        "quality",
        "extension_risk",
        "selection_state",
        "selection_score",
        "setup_state",
        "setup_reason",
        "zone_context_summary",
        "reload_context_summary",
        "reload_context_role",
        "reload_context_promotable",
        "volume_context_summary",
        "synth_confirmation_strength",
        "synth_bucket",
        "comparison_bucket",
        "reason",
    ]
    print("\t".join(columns))
    for row in rows:
        payload = asdict(row)
        print("\t".join(str(payload[col]) for col in columns))


def print_json(rows: list[ComparisonRow], *, meta: dict[str, Any]) -> None:
    payload = {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "row_count": len(rows),
        "safety": {
            "db_writes": 0,
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "selection_engine_changes": 0,
            "decision_gate_changes": 0,
            "execution_planner_changes": 0,
            "executor_changes": 0,
        },
        "context_meta": meta,
        "rows": [asdict(row) for row in rows],
    }
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    table1 = parse_focus_table1(Path(args.table1_raw).read_text(encoding="utf-8"))
    table2 = parse_focus_table2(Path(args.table2_raw).read_text(encoding="utf-8"))
    tokens = tokens_in_both(table1, table2)
    selection_map, zone_map, volume_map, base_meta = fetch_optional_context(
        tokens=tokens,
        venue=args.venue,
        interval=args.interval,
    )
    setup_map, paper_advice_map, reload_selected_map, extra_meta = fetch_additional_context(
        tokens=tokens,
        venue=args.venue,
        interval=args.interval,
        reload_selected_events=Path(args.reload_selected_events),
    )
    rows = build_rows(
        tokens=tokens,
        table1=table1,
        table2=table2,
        selection_map=selection_map,
        setup_map=setup_map,
        zone_map=zone_map,
        volume_map=volume_map,
        paper_advice_map=paper_advice_map,
        reload_selected_map=reload_selected_map,
    )
    meta = {
        "tokens_used": tokens,
        "venue": args.venue,
        "quote": args.quote,
        "interval": args.interval,
        "reload_selected_events": str(args.reload_selected_events),
        **base_meta,
        **extra_meta,
    }
    if args.output == "json":
        print_json(rows, meta=meta)
    else:
        print_table(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
