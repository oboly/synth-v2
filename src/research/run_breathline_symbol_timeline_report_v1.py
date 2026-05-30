from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.research.run_aplus_prime17_opportunity_report_v1 import (
    fetch_asset_ids,
    fetch_optional_context,
    parse_focus_table1,
    parse_focus_table2,
)
from src.research.run_aplus_vs_synth_comparison_outcome_validation_v1 import (
    MAX_HORIZON,
    OutcomeRow,
    build_outcome_rows,
    fetch_candles,
    parse_snapshot_ts_from_path,
)
from src.research.run_aplus_vs_synth_comparison_report_v1 import (
    ComparisonRow,
    build_rows,
    fetch_additional_context,
    tokens_in_both,
)


REPORT_NAME = "breathline_symbol_timeline_report_v1"
REPORT_VERSION = "1.0"
DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE = "EUR"
DEFAULT_INTERVAL = "1d"
DEFAULT_CANDLE_INTERVAL = "15m"


@dataclass(frozen=True)
class TimelineRow:
    symbol: str
    snapshot_ts_utc: str
    aplus_phase: str
    aplus_field: str
    aplus_role: str
    aplus_bias: str
    harmonic_phase: str
    phase_state: str
    offset_band: str
    drift_direction: str
    quality: str
    extension_risk: str
    estimated_window_utc: str
    estimated_duration_days: str
    comparison_bucket: str
    synth_bucket: str
    selection_state: str
    setup_state: str
    zone_context_summary: str
    reload_context_summary: str
    volume_context_summary: str
    return_15m: float | None
    return_1h: float | None
    return_4h: float | None
    return_24h: float | None
    phase_read: str
    interpretation: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only breathline symbol timeline report for selected symbols, "
            "combining raw A+ posture, harmonic phase, Synth comparison context, "
            "reload context, and observed forward returns."
        )
    )
    parser.add_argument("--table1-raw", required=True)
    parser.add_argument("--table2-raw", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--candle-interval", default=DEFAULT_CANDLE_INTERVAL)
    parser.add_argument("--reload-selected-events", default="data/research/reload_reaction_scalp_parameter_sweep_v1/reload_reaction_scalp_selected_events_v1.jsonl")
    parser.add_argument("--output", choices=("table", "timeline", "json"), default="table")
    return parser.parse_args(argv)


def fmt_ts(value: datetime | None) -> str:
    if value is None:
        return "unavailable"
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def window_for_phase(snapshot_ts_utc: datetime, phase_state: str, harmonic_phase: str) -> tuple[str, str, str]:
    state = phase_state.strip().lower()
    harmonic = harmonic_phase.strip().lower()
    if state in {"early", "forming"} or harmonic.startswith("forming"):
        start = snapshot_ts_utc
        end = snapshot_ts_utc + timedelta(days=2)
        return f"{fmt_ts(start)} -> {fmt_ts(end)} (estimated)", "2.0", "estimated early/forming window"
    if state == "confirmed" or harmonic.startswith("confirmed"):
        start = snapshot_ts_utc - timedelta(days=1)
        end = snapshot_ts_utc + timedelta(days=3)
        return f"{fmt_ts(start)} -> {fmt_ts(end)} (estimated)", "4.0", "estimated confirmed window"
    if state in {"late", "exhausted"} or harmonic in {"late_extension", "reset"}:
        start = snapshot_ts_utc - timedelta(days=2)
        end = snapshot_ts_utc + timedelta(days=1)
        return f"{fmt_ts(start)} -> {fmt_ts(end)} (estimated)", "3.0", "estimated late/exhausted window"
    return "unknown window", "unavailable", "window unknown"


def positive(value: float | None) -> bool:
    return value is not None and value > 0


def build_interpretation(
    *,
    comparison_bucket: str,
    synth_bucket: str,
    aplus_bucket: str,
    return_4h: float | None,
    return_24h: float | None,
) -> str:
    aplus_caution = aplus_bucket == "CAUTION_DETERIORATION"
    aplus_constructive = aplus_bucket in {"A_PLUS_CORE_CONTINUATION", "WATCH_ONLY_NEEDS_SYNTH_CONFIRMATION"}
    synth_raw = synth_bucket == "SYNTH_RAW_EDGE_CONTEXT"
    synth_blocked = comparison_bucket == "APLUS_CONSTRUCTIVE_SYNTH_BLOCKED"
    any_positive = positive(return_4h) or positive(return_24h)

    if aplus_caution and any_positive:
        return "DIRTY_SQUEEZE"
    if aplus_constructive and synth_raw and any_positive:
        return "CONSTRUCTIVE_CURVE_WINDOW"
    if aplus_constructive and synth_blocked:
        return "BREATH_POSITIVE_TIMING_BLOCKED"
    if synth_raw and aplus_caution:
        return "CURVE_AGAINST_BREATH_CAUTION"
    if comparison_bucket in {"BOTH_CAUTION", "CONFLICT_SYNTH_BULL_A_PLUS_BEAR"}:
        return "WEAK_OR_LATE_PHASE"
    if comparison_bucket == "BOTH_AGREE_UP":
        return "ALIGNED_CONSTRUCTIVE_WINDOW"
    if comparison_bucket == "A_PLUS_ONLY_WAIT":
        return "BREATH_POSITIVE_SYNTH_WAIT"
    return "MIXED_OR_UNCLEAR"


def build_phase_read(row: ComparisonRow) -> str:
    return (
        f"A+ {row.aplus_phase}/{row.aplus_field}/{row.aplus_bias}; "
        f"harmonic {row.harmonic_phase} {row.phase_state} / {row.extension_risk}; "
        f"Synth {row.synth_bucket}"
    )


def build_timeline_rows(
    *,
    comparison_rows: list[ComparisonRow],
    outcome_rows: list[OutcomeRow],
    snapshot_ts_utc: datetime,
) -> list[TimelineRow]:
    outcomes_by_symbol = {row.token: row for row in outcome_rows}
    rows: list[TimelineRow] = []
    for row in comparison_rows:
        outcome = outcomes_by_symbol.get(row.token)
        estimated_window_utc, estimated_duration_days, _window_note = window_for_phase(
            snapshot_ts_utc,
            row.phase_state,
            row.harmonic_phase,
        )
        interpretation = build_interpretation(
            comparison_bucket=row.comparison_bucket,
            synth_bucket=row.synth_bucket,
            aplus_bucket=row.aplus_bucket,
            return_4h=None if outcome is None else outcome.return_4h,
            return_24h=None if outcome is None else outcome.return_24h,
        )
        rows.append(
            TimelineRow(
                symbol=row.token,
                snapshot_ts_utc=fmt_ts(snapshot_ts_utc),
                aplus_phase=row.aplus_phase,
                aplus_field=row.aplus_field,
                aplus_role=row.aplus_role,
                aplus_bias=row.aplus_bias,
                harmonic_phase=row.harmonic_phase,
                phase_state=row.phase_state,
                offset_band=row.offset_band,
                drift_direction=row.drift_direction,
                quality=row.quality,
                extension_risk=row.extension_risk,
                estimated_window_utc=estimated_window_utc,
                estimated_duration_days=estimated_duration_days,
                comparison_bucket=row.comparison_bucket,
                synth_bucket=row.synth_bucket,
                selection_state=row.selection_state,
                setup_state=row.setup_state,
                zone_context_summary=row.zone_context_summary,
                reload_context_summary=row.reload_context_summary,
                volume_context_summary=row.volume_context_summary,
                return_15m=None if outcome is None else outcome.return_15m,
                return_1h=None if outcome is None else outcome.return_1h,
                return_4h=None if outcome is None else outcome.return_4h,
                return_24h=None if outcome is None else outcome.return_24h,
                phase_read=build_phase_read(row),
                interpretation=interpretation,
            )
        )
    return rows


def print_table(rows: list[TimelineRow], *, meta: dict[str, Any]) -> None:
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print("scope=research-only read-only breathline symbol timeline")
    print("broker_calls=0 broker_writes=0 order_submission=0 executor=none live_trading=false")
    if meta.get("db_error"):
        print(f"db_error={meta['db_error']}")
    print()
    columns = [
        "symbol",
        "snapshot_ts_utc",
        "aplus_phase",
        "aplus_field",
        "aplus_role",
        "aplus_bias",
        "harmonic_phase",
        "phase_state",
        "offset_band",
        "drift_direction",
        "quality",
        "extension_risk",
        "estimated_window_utc",
        "estimated_duration_days",
        "comparison_bucket",
        "synth_bucket",
        "selection_state",
        "setup_state",
        "zone_context_summary",
        "reload_context_summary",
        "volume_context_summary",
        "return_15m",
        "return_1h",
        "return_4h",
        "return_24h",
        "phase_read",
        "interpretation",
    ]
    print("\t".join(columns))
    for row in rows:
        payload = asdict(row)
        print("\t".join(str(payload[col]) for col in columns))


def _fmt_return(value: float | None) -> str:
    return "None" if value is None else f"{value:.3f}%"


def _clip(text: str, limit: int = 34) -> str:
    clean = str(text or "unavailable").replace("\n", " ").strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


def print_timeline(rows: list[TimelineRow], *, meta: dict[str, Any]) -> None:
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print("scope=research-only read-only breathline symbol timeline")
    print("broker_calls=0 broker_writes=0 order_submission=0 executor=none live_trading=false")
    if meta.get("db_error"):
        print(f"db_error={meta['db_error']}")
    print()
    for row in rows:
        print(f"SYMBOL {row.symbol}")
        print(f"snapshot: {row.snapshot_ts_utc}")
        print(f"window:   {row.estimated_window_utc}")
        print()
        print("time        | -24h | snapshot | +4h | +24h | +72h |")
        print(
            "A+ posture  |      | "
            f"{_clip(f'{row.aplus_phase}/{row.aplus_field}/{row.aplus_bias}', 34)}"
        )
        print(
            "harmonic    |      | "
            f"{_clip(f'{row.harmonic_phase} {row.phase_state} / {row.extension_risk}', 34)}"
        )
        print(
            "Synth curve |      | "
            f"{_clip(f'{row.synth_bucket}; {row.reload_context_summary}', 34)}"
        )
        print(
            "returns     |      | "
            f"15m {_fmt_return(row.return_15m)} | 4h {_fmt_return(row.return_4h)} | 24h {_fmt_return(row.return_24h)} |"
        )
        print(f"read        | {row.interpretation}: {_clip(row.phase_read, 72)}")
        print()


def print_json(rows: list[TimelineRow], *, meta: dict[str, Any]) -> None:
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
        "meta": meta,
        "rows": [asdict(row) for row in rows],
    }
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    table1_path = Path(args.table1_raw)
    table2_path = Path(args.table2_raw)
    table1 = parse_focus_table1(table1_path.read_text(encoding="utf-8"))
    table2 = parse_focus_table2(table2_path.read_text(encoding="utf-8"))
    requested_symbols = [symbol.upper() for symbol in args.symbols]
    tokens = [token for token in tokens_in_both(table1, table2) if token in requested_symbols]
    snapshot_ts_utc = min(parse_snapshot_ts_from_path(table1_path), parse_snapshot_ts_from_path(table2_path))

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
    comparison_rows = build_rows(
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

    db_error: str | None = None
    candles_by_symbol: dict[str, list[Any]] = {}
    try:
        conn = get_connection()
    except Exception as exc:
        db_error = f"{type(exc).__name__}: {exc}"
    else:
        try:
            asset_ids = fetch_asset_ids(conn, tokens)
            candles_by_symbol = fetch_candles(
                conn,
                asset_ids=asset_ids,
                venue=args.venue,
                interval_code=args.candle_interval,
                start_ts=snapshot_ts_utc - timedelta(days=1),
                end_ts=snapshot_ts_utc + MAX_HORIZON + timedelta(hours=1),
            )
        except Exception as exc:
            db_error = f"{type(exc).__name__}: {exc}"
            candles_by_symbol = {}
        finally:
            conn.close()

    outcome_rows = build_outcome_rows(
        comparison_rows,
        snapshot_ts_utc=snapshot_ts_utc,
        candles_by_symbol=candles_by_symbol,
    )
    timeline_rows = build_timeline_rows(
        comparison_rows=comparison_rows,
        outcome_rows=outcome_rows,
        snapshot_ts_utc=snapshot_ts_utc,
    )
    meta = {
        "symbols_requested": requested_symbols,
        "symbols_used": tokens,
        "venue": args.venue,
        "quote": args.quote,
        "interval": args.interval,
        "candle_interval": args.candle_interval,
        "reload_selected_events": str(args.reload_selected_events),
        "missing_candles_handled_gracefully": True,
        **base_meta,
        **extra_meta,
    }
    if db_error is not None:
        meta["db_error"] = db_error

    if args.output == "json":
        print_json(timeline_rows, meta=meta)
    elif args.output == "timeline":
        print_timeline(timeline_rows, meta=meta)
    else:
        print_table(timeline_rows, meta=meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
