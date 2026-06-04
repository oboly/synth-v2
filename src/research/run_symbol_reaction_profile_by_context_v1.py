from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any


REPORT_NAME = "symbol_reaction_profile_by_context_v1"
REPORT_VERSION = "1.0"

DEFAULT_INPUT_ROWS = Path("data/research/position_lifecycle_outcome_validation_v1/outcome_rows_v1.jsonl")
DEFAULT_FIBO_ROWS = Path("data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv")
DEFAULT_CONTEXT_DIR = Path("data/research/historical_breath_regime_context_builder_v1")
DEFAULT_CONTEXT_ROWS_JSONL = DEFAULT_CONTEXT_DIR / "historical_breath_regime_context_rows_v1.jsonl"
DEFAULT_CONTEXT_ROWS_CSV = DEFAULT_CONTEXT_DIR / "historical_breath_regime_context_rows_v1.csv"
DEFAULT_OUTPUT_DIR = Path("data/research/symbol_reaction_profile_by_context_v1")

ROWS_CSV = "symbol_reaction_profile_by_context_rows_v1.csv"
ROWS_JSONL = "symbol_reaction_profile_by_context_rows_v1.jsonl"
MANIFEST_JSON = "manifest_v1.json"

MAX_STALENESS = timedelta(days=7)
DEFAULT_MIN_EVENTS = 5
HORIZONS = ("15m", "30m", "1h", "4h", "24h")
RELOAD_ZONE_PARTS = ("entry_low", "entry_mid", "entry_high")

SAFETY_MARKERS = {
    "research_only": True,
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "executor": "none",
    "db_writes": 0,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build per-symbol reaction profiles conditioned by historical context "
            "(research-only, market-only, no DB writes)."
        )
    )
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--input-rows", default=str(DEFAULT_INPUT_ROWS))
    parser.add_argument("--fibo-rows", default=str(DEFAULT_FIBO_ROWS))
    parser.add_argument("--context-rows", default=None)
    parser.add_argument("--min-events", type=int, default=DEFAULT_MIN_EVENTS)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def parse_symbols_arg(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {piece.strip().upper() for piece in str(value).split(",") if piece.strip()}


def parse_ts(value: Any) -> datetime | None:
    if value in ("", None):
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(tzinfo=None)


def fmt_ts(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    if isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = line.strip()
            if not payload:
                continue
            row = json.loads(payload)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    converted_rows: list[dict[str, Any]] = []
    for row in rows:
        converted: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, (list, dict)):
                converted[key] = json.dumps(value, sort_keys=True, ensure_ascii=True)
            else:
                converted[key] = value
        converted_rows.append(converted)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(converted_rows[0].keys()))
        writer.writeheader()
        writer.writerows(converted_rows)


def average_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(median(values)), 6)


def rate_or_none(flags: list[bool]) -> float | None:
    if not flags:
        return None
    return round(sum(1 for flag in flags if flag) / len(flags) * 100.0, 6)


def midpoint(low: float | None, high: float | None) -> float | None:
    if low is not None and high is not None:
        return (low + high) / 2.0
    return low if low is not None else high


def retrace_to_level_pct(event_price: float | None, level: float | None) -> float | None:
    if event_price is None or level is None or event_price <= 0:
        return None
    return round(abs((event_price / level) - 1.0) * 100.0, 6)


def boolish(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes"}:
        return True
    if text in {"0", "false", "no"}:
        return False
    return None


def choose_context_rows_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    if DEFAULT_CONTEXT_ROWS_JSONL.exists():
        return DEFAULT_CONTEXT_ROWS_JSONL
    return DEFAULT_CONTEXT_ROWS_CSV


def load_context_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".jsonl":
        rows = read_jsonl(path)
    else:
        rows = [dict(row) for row in read_csv_rows(path)]
    out: list[dict[str, Any]] = []
    for row in rows:
        asof_ts = parse_ts(row.get("asof_ts_utc"))
        symbol = str(row.get("symbol") or "").strip().upper()
        if asof_ts is None or not symbol:
            continue
        item = dict(row)
        item["symbol"] = symbol
        item["asof_ts_utc"] = asof_ts
        out.append(item)
    return out


def load_fibo_rows(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows = read_csv_rows(path)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        out[symbol] = dict(row)
    return out


def load_event_rows(path: Path, symbols: set[str] | None = None) -> list[dict[str, Any]]:
    rows = read_jsonl(path)
    out: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        event_ts = parse_ts(row.get("event_ts_utc"))
        if not symbol or event_ts is None:
            continue
        if symbols is not None and symbol not in symbols:
            continue
        item = dict(row)
        item["symbol"] = symbol
        item["event_ts_utc"] = event_ts
        out.append(item)
    return out


def build_context_lookup(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(rows, key=lambda item: (item["symbol"], item["asof_ts_utc"])):
        grouped[row["symbol"]].append(row)
    return dict(grouped)


def nearest_context_at_or_before(
    lookup: dict[str, list[dict[str, Any]]],
    *,
    symbol: str,
    event_ts_utc: datetime,
    max_staleness: timedelta = MAX_STALENESS,
) -> dict[str, Any] | None:
    matched: dict[str, Any] | None = None
    for row in lookup.get(symbol.upper(), []):
        if row["asof_ts_utc"] > event_ts_utc:
            break
        matched = row
    if matched is None:
        return None
    if event_ts_utc - matched["asof_ts_utc"] > max_staleness:
        return None
    return matched


def fibo_context_for_event(fibo_row: dict[str, Any] | None, event_price: float | None) -> str:
    if fibo_row is None or event_price is None or event_price <= 0:
        return "UNKNOWN"
    next_support = as_float(fibo_row.get("next_fibo_support_price"))
    next_target = as_float(fibo_row.get("next_target_price"))
    local_reaction = as_float(fibo_row.get("local_reaction_price"))
    if next_support is not None and abs((event_price / next_support) - 1.0) * 100.0 <= 3.0:
        return "NEAR_SUPPORT"
    if next_target is not None and abs((event_price / next_target) - 1.0) * 100.0 <= 3.0:
        return "NEAR_TARGET"
    if next_target is not None and event_price > next_target:
        return "EXTENSION"
    if local_reaction is not None:
        return "MID_RANGE"
    return "UNKNOWN"


def enrich_event(
    row: dict[str, Any],
    *,
    context_lookup: dict[str, list[dict[str, Any]]],
    fibo_by_symbol: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    symbol = row["symbol"]
    event_ts = row["event_ts_utc"]
    context = nearest_context_at_or_before(context_lookup, symbol=symbol, event_ts_utc=event_ts)
    current_price = as_float(row.get("current_price"))
    entry_low = as_float(row.get("entry_zone_low"))
    entry_high = as_float(row.get("entry_zone_high"))
    entry_mid = midpoint(entry_low, entry_high)
    context_row = context or {}
    fibo_row = fibo_by_symbol.get(symbol)
    fibo_context = str(context_row.get("fibo_context") or "UNKNOWN").upper()
    if fibo_context == "UNKNOWN":
        fibo_context = fibo_context_for_event(fibo_row, current_price)
    source_refs = context_row.get("source_refs") if isinstance(context_row.get("source_refs"), list) else []

    enriched = dict(row)
    enriched.update(
        {
            "breath_phase": str(context_row.get("breath_phase") or "UNKNOWN").upper(),
            "breath_alignment": str(context_row.get("breath_alignment") or "UNKNOWN").upper(),
            "market_regime": str(context_row.get("market_regime") or "UNKNOWN").upper(),
            "btc_context": str(context_row.get("btc_context") or "UNKNOWN").upper(),
            "symbol_regime": str(context_row.get("symbol_regime") or "UNKNOWN").upper(),
            "fibo_context": fibo_context,
            "context_asof_ts_utc": fmt_ts(context_row.get("asof_ts_utc")) if context else None,
            "context_join_status": "FOUND" if context else "UNKNOWN",
            "source_refs": source_refs,
            "retrace_to_entry_low_pct": retrace_to_level_pct(current_price, entry_low),
            "retrace_to_entry_mid_pct": retrace_to_level_pct(current_price, entry_mid),
            "retrace_to_entry_high_pct": retrace_to_level_pct(current_price, entry_high),
        }
    )
    return enriched


def event_bucket_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    return (
        row["symbol"],
        str(row.get("breath_phase") or "UNKNOWN").upper(),
        str(row.get("breath_alignment") or "UNKNOWN").upper(),
        str(row.get("market_regime") or "UNKNOWN").upper(),
        str(row.get("btc_context") or "UNKNOWN").upper(),
        str(row.get("symbol_regime") or "UNKNOWN").upper(),
        str(row.get("fibo_context") or "UNKNOWN").upper(),
    )


def bounce_for_horizon(row: dict[str, Any], horizon: str) -> float | None:
    if horizon in {"15m", "30m", "1h", "4h", "24h"}:
        return as_float((row.get("forward_returns") or {}).get(horizon))
    return None


def sample_quality(event_count: int, min_events: int) -> str:
    if event_count < min_events:
        return "INSUFFICIENT"
    if event_count < max(min_events * 2, 8):
        return "LOW"
    if event_count < max(min_events * 4, 16):
        return "MEDIUM"
    return "HIGH"


def best_reload_zone_part(rows: list[dict[str, Any]]) -> str:
    averages: dict[str, float | None] = {
        part: average_or_none(
            [
                value
                for value in [as_float(row.get(f"retrace_to_{part}_pct")) if False else row.get(f"retrace_to_{part}_pct") for row in rows]
                if isinstance(value, (int, float))
            ]
        )
        for part in RELOAD_ZONE_PARTS
    }
    best_part = min(
        RELOAD_ZONE_PARTS,
        key=lambda part: averages[part] if averages[part] is not None else 999999.0,
    )
    return best_part


def horizon_positive_rate(rows: list[dict[str, Any]], horizon: str) -> float | None:
    values = [bounce_for_horizon(row, horizon) for row in rows]
    filtered = [value for value in values if value is not None]
    if not filtered:
        return None
    return round(sum(1 for value in filtered if value > 0.0) / len(filtered) * 100.0, 6)


def best_hold_horizon(rows: list[dict[str, Any]]) -> str:
    averages = {
        horizon: average_or_none(
            [value for value in [bounce_for_horizon(row, horizon) for row in rows] if value is not None]
        )
        for horizon in HORIZONS
    }
    return max(HORIZONS, key=lambda horizon: averages[horizon] if averages[horizon] is not None else -999999.0)


def volatility_bucket(rows: list[dict[str, Any]]) -> str:
    values = [abs(as_float(row.get("max_adverse_excursion_pct")) or 0.0) for row in rows]
    avg_value = average_or_none(values)
    if avg_value is None:
        return "UNKNOWN"
    if avg_value >= 8.0:
        return "HIGH"
    if avg_value >= 4.0:
        return "MEDIUM"
    return "LOW"


def profile_label_for_row(row: dict[str, Any], min_events: int) -> str:
    if row["sample_quality"] == "INSUFFICIENT":
        return "INSUFFICIENT_SAMPLE"
    fakeout_rate = row.get("fakeout_rate") or 0.0
    retrace_high = row.get("avg_retrace_to_entry_high_pct") or 0.0
    bounce_15m = row.get("bounce_15m_pct") or 0.0
    bounce_4h = row.get("bounce_4h_pct") or 0.0
    bounce_24h = row.get("bounce_24h_pct") or 0.0
    mfe_mae_ratio = row.get("mfe_mae_ratio") or 0.0
    market_regime = str(row.get("market_regime") or "UNKNOWN").upper()
    btc_context = str(row.get("btc_context") or "UNKNOWN").upper()
    breath_phase = str(row.get("breath_phase") or "UNKNOWN").upper()

    if fakeout_rate >= 50.0 or btc_context == "BTC_DAMAGE_HARD" or market_regime == "BTC_DAMAGE":
        return "FAKEOUT_PRONE"
    if retrace_high >= 6.0 and bounce_24h >= 50.0:
        return "DEEP_RETRACER"
    if breath_phase == "RELOAD" and bounce_15m >= 60.0 and mfe_mae_ratio >= 1.5:
        return "FAST_REACTOR"
    if bounce_15m < 40.0 and bounce_24h >= 60.0 and bounce_4h >= 50.0:
        return "SLOW_GRINDER"
    if row["sample_quality"] in {"LOW", "MEDIUM"} and str(row.get("breath_phase") or "UNKNOWN") != "UNKNOWN":
        return "CONTEXT_DEPENDENT"
    return "MIXED"


def build_profile_rows(
    *,
    event_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    fibo_by_symbol: dict[str, dict[str, Any]],
    min_events: int,
) -> list[dict[str, Any]]:
    context_lookup = build_context_lookup(context_rows)
    enriched = [
        enrich_event(row, context_lookup=context_lookup, fibo_by_symbol=fibo_by_symbol)
        for row in event_rows
    ]
    grouped: dict[tuple[str, str, str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        grouped[event_bucket_key(row)].append(row)

    output: list[dict[str, Any]] = []
    for key, rows in sorted(grouped.items()):
        symbol, breath_phase, breath_alignment, market_regime, btc_context, symbol_regime, fibo_context = key
        eligible_flags = [boolish(row.get("hit_target_like_move")) for row in rows]
        reaction_touch_flags = [
            (as_float(row.get("retrace_to_entry_low_pct")) or 999999.0) <= 3.0
            for row in rows
        ]
        fakeout_flags = [boolish(row.get("broke_invalidation_like_move")) for row in rows]
        avg_mfe = average_or_none(
            [value for value in (as_float(row.get("max_favorable_excursion_pct")) for row in rows) if value is not None]
        )
        avg_mae = average_or_none(
            [value for value in (as_float(row.get("max_adverse_excursion_pct")) for row in rows) if value is not None]
        )
        row_out = {
            "symbol": symbol,
            "breath_phase": breath_phase,
            "breath_alignment": breath_alignment,
            "market_regime": market_regime,
            "btc_context": btc_context,
            "symbol_regime": symbol_regime,
            "fibo_context": fibo_context,
            "event_count": len(rows),
            "eligible_event_count": sum(1 for flag in eligible_flags if flag is not None),
            "avg_retrace_to_entry_low_pct": average_or_none(
                [value for value in (as_float(row.get("retrace_to_entry_low_pct")) for row in rows) if value is not None]
            ),
            "avg_retrace_to_entry_mid_pct": average_or_none(
                [value for value in (as_float(row.get("retrace_to_entry_mid_pct")) for row in rows) if value is not None]
            ),
            "avg_retrace_to_entry_high_pct": average_or_none(
                [value for value in (as_float(row.get("retrace_to_entry_high_pct")) for row in rows) if value is not None]
            ),
            "reaction_zone_touch_rate": rate_or_none(reaction_touch_flags),
            "bounce_15m_pct": horizon_positive_rate(rows, "15m"),
            "bounce_30m_pct": horizon_positive_rate(rows, "30m"),
            "bounce_1h_pct": horizon_positive_rate(rows, "1h"),
            "bounce_4h_pct": horizon_positive_rate(rows, "4h"),
            "bounce_24h_pct": horizon_positive_rate(rows, "24h"),
            "avg_mfe_pct": avg_mfe,
            "avg_mae_pct": avg_mae,
            "mfe_mae_ratio": None if avg_mfe is None or avg_mae in (None, 0.0) else round(avg_mfe / abs(avg_mae), 6),
            "fakeout_rate": rate_or_none([flag for flag in fakeout_flags if flag is not None]),
            "best_reload_zone_part": min(
                RELOAD_ZONE_PARTS,
                key=lambda part: average_or_none(
                    [value for value in (as_float(row.get(f"retrace_to_{part}_pct")) for row in rows) if value is not None]
                )
                if average_or_none(
                    [value for value in (as_float(row.get(f"retrace_to_{part}_pct")) for row in rows) if value is not None]
                )
                is not None
                else 999999.0,
            ),
            "best_hold_horizon": best_hold_horizon(rows),
            "volatility_bucket": volatility_bucket(rows),
            "sample_quality": sample_quality(len(rows), min_events),
            "source_refs": list(dict.fromkeys(json.dumps(ref, sort_keys=True) for row in rows for ref in (row.get("source_refs") or []))),
            "research_only": True,
        }
        row_out["source_refs"] = [json.loads(ref) for ref in row_out["source_refs"]]
        row_out["profile_label"] = profile_label_for_row(row_out, min_events)
        output.append(row_out)
    return output


def build_manifest(
    *,
    rows: list[dict[str, Any]],
    input_rows_path: Path,
    fibo_rows_path: Path,
    context_rows_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "row_count": len(rows),
        "input_rows_path": str(input_rows_path),
        "fibo_rows_path": str(fibo_rows_path),
        "context_rows_path": str(context_rows_path),
        "output_dir": str(output_dir),
        "output_files": {
            "rows_csv": str(output_dir / ROWS_CSV),
            "rows_jsonl": str(output_dir / ROWS_JSONL),
            "manifest_json": str(output_dir / MANIFEST_JSON),
        },
        "context_unknown_rows": sum(1 for row in rows if row["breath_phase"] == "UNKNOWN"),
        "safety_markers": SAFETY_MARKERS,
        "research_only": True,
    }


def print_summary(*, rows: list[dict[str, Any]], manifest: dict[str, Any], output_mode: str) -> None:
    if output_mode == "json":
        print(json.dumps({"rows": rows, "manifest": manifest}, indent=2, sort_keys=True, ensure_ascii=True))
        return
    labels: dict[str, int] = defaultdict(int)
    for row in rows:
        labels[str(row["profile_label"])] += 1
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(f"row_count={len(rows)} symbols={','.join(sorted({row['symbol'] for row in rows})) if rows else 'none'}")
    if labels:
        print("profile_label " + " ; ".join(f"{key}:{labels[key]}" for key in sorted(labels)))
    print(
        "safety "
        + " ".join(
            f"{key}={str(value).lower() if isinstance(value, bool) else value}"
            for key, value in SAFETY_MARKERS.items()
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = parse_symbols_arg(args.symbols)
    input_rows_path = Path(args.input_rows)
    fibo_rows_path = Path(args.fibo_rows)
    context_rows_path = choose_context_rows_path(args.context_rows)
    output_dir = Path(args.output_dir)

    event_rows = load_event_rows(input_rows_path, symbols=symbols)
    context_rows = load_context_rows(context_rows_path)
    fibo_by_symbol = load_fibo_rows(fibo_rows_path)
    profile_rows = build_profile_rows(
        event_rows=event_rows,
        context_rows=context_rows,
        fibo_by_symbol=fibo_by_symbol,
        min_events=int(args.min_events),
    )
    manifest = build_manifest(
        rows=profile_rows,
        input_rows_path=input_rows_path,
        fibo_rows_path=fibo_rows_path,
        context_rows_path=context_rows_path,
        output_dir=output_dir,
    )

    if args.write_files:
        write_csv(output_dir / ROWS_CSV, profile_rows)
        write_jsonl(output_dir / ROWS_JSONL, profile_rows)
        write_json(output_dir / MANIFEST_JSON, manifest)

    print_summary(rows=profile_rows, manifest=manifest, output_mode=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
