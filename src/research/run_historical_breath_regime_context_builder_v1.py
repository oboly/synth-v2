from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


REPORT_NAME = "historical_breath_regime_context_builder_v1"
REPORT_VERSION = "1.0"

DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL = "4h"
DEFAULT_OUTPUT_DIR = Path("data/research/historical_breath_regime_context_builder_v1")
DEFAULT_MARKET_BREATH_ROWS = Path("data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl")
DEFAULT_ENRICHED_MARKET_BREATH_ROWS = Path(
    "data/research/historical_market_breath_source_enrichment_v1/historical_market_breath_source_enriched_rows_v1.csv"
)
DEFAULT_APLUS_GLOB = "data/research/aplus_canonical_table1_v1/*.jsonl"

ROWS_CSV = "historical_breath_regime_context_rows_v1.csv"
ROWS_JSONL = "historical_breath_regime_context_rows_v1.jsonl"
MANIFEST_JSON = "manifest_v1.json"

INTERVAL_DELTAS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}

MAX_STALENESS = {
    "15m": timedelta(hours=8),
    "1h": timedelta(hours=24),
    "4h": timedelta(hours=48),
    "1d": timedelta(days=7),
}

SAFETY_MARKERS = {
    "research_only": True,
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "executor": "none",
    "db_writes": 0,
}

UNKNOWN_FIELDS = {
    "breath_phase": "UNKNOWN",
    "breath_alignment": "UNKNOWN",
    "market_regime": "UNKNOWN",
    "btc_context": "UNKNOWN",
    "symbol_regime": "UNKNOWN",
    "fibo_context": "UNKNOWN",
    "aplus_context_state": "UNKNOWN",
    "martee_context_state": "UNKNOWN",
    "relative_strength_bucket": "UNKNOWN",
    "momentum_bucket": "UNKNOWN",
    "quality_state": "UNKNOWN",
    "confidence_bucket": "UNKNOWN",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build historical Breath/Regime context rows from existing research sources "
            "(research-only, market-only, file-output only)."
        )
    )
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--start-ts", default=None)
    parser.add_argument("--end-ts", default=None)
    parser.add_argument("--enriched-market-breath-rows", default=None)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def parse_symbols_arg(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [piece.strip().upper() for piece in str(value).split(",") if piece.strip()]
    return list(dict.fromkeys(items))


def parse_ts(value: str | datetime | None) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
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
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def latest_matching(glob_pattern: str) -> Path | None:
    matches = sorted(Path().glob(glob_pattern))
    return matches[-1] if matches else None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = line.strip()
            if not payload:
                continue
            item = json.loads(payload)
            if isinstance(item, dict):
                rows.append(item)
    return rows


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
    csv_rows: list[dict[str, Any]] = []
    for row in rows:
        converted: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, (list, dict)):
                converted[key] = json.dumps(value, sort_keys=True, ensure_ascii=True)
            else:
                converted[key] = value
        csv_rows.append(converted)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0].keys()))
        writer.writeheader()
        writer.writerows(csv_rows)


def canonical_breath_phase(raw_phase: Any) -> str:
    phase = str(raw_phase or "").strip().upper()
    mapping = {
        "EXHALE_EXPANSION": "EXPANSION",
        "HOLD_COMPRESSION": "CONTRACTION",
        "INHALE_ACCUMULATION": "RELOAD",
        "OVERBREATH_EXTENSION": "POST_SPIKE",
        "COLLAPSE_RESET": "IGNITION",
        "NEUTRAL_TRANSITION": "UNKNOWN",
        "INSUFFICIENT_DATA": "UNKNOWN",
    }
    return mapping.get(phase, "UNKNOWN")


def canonical_breath_alignment(raw_state: Any) -> str:
    state = str(raw_state or "").strip().upper()
    mapping = {
        "CONFIRMED": "ALIGNED",
        "EARLY": "EARLY",
        "FORMING": "EARLY",
        "LATE": "LATE",
        "RESET": "INCOHERENT",
        "UNKNOWN": "UNKNOWN",
    }
    return mapping.get(state, "UNKNOWN")


def band_label(value: float | None, *, weak: float, strong: float, neg_prefix: str, pos_prefix: str) -> str:
    if value is None:
        return "UNKNOWN"
    if value <= weak:
        return neg_prefix
    if value >= strong:
        return pos_prefix
    return "NEUTRAL"


def market_regime_from_scores(row: dict[str, Any]) -> str:
    explicit = str(row.get("market_regime") or row.get("global_regime") or "").strip().upper()
    if explicit:
        if "RISK_ON" in explicit:
            return "RISK_ON"
        if "BREAKDOWN" in explicit or "MILD_DECLINE" in explicit or "DAMAGE" in explicit:
            return "BTC_DAMAGE"
        if "ROTATION" in explicit or "ALT" in explicit:
            return "ALT_STRENGTH"
        if "NEUTRAL" in explicit:
            return "MIXED"
    momentum = as_float(row.get("momentum_score"))
    relative_strength = as_float(row.get("relative_strength_score"))
    btc_alignment = as_float(row.get("btc_alignment_score"))
    breadth_alignment = as_float(row.get("breadth_alignment_score"))
    if btc_alignment is not None and btc_alignment <= -25.0:
        return "BTC_DAMAGE"
    if momentum is not None and breadth_alignment is not None and momentum <= -15.0 and breadth_alignment <= 0.0:
        return "RISK_OFF"
    if momentum is not None and relative_strength is not None and momentum >= 20.0 and relative_strength >= 20.0:
        return "ALT_STRENGTH"
    if momentum is not None and btc_alignment is not None and momentum >= 10.0 and btc_alignment >= 0.0:
        return "RISK_ON"
    if any(value is not None for value in (momentum, relative_strength, btc_alignment, breadth_alignment)):
        return "MIXED"
    return "UNKNOWN"


def btc_context_from_scores(row: dict[str, Any]) -> str:
    explicit = str(row.get("btc_context") or "").strip().upper()
    if explicit:
        return explicit
    btc_alignment = as_float(row.get("btc_alignment_score"))
    global_regime = str(row.get("global_regime") or "").strip().upper()
    if "BREAKDOWN" in global_regime:
        return "BTC_DAMAGE_HARD"
    if "MILD_DECLINE" in global_regime or "DAMAGE" in global_regime:
        return "BTC_DAMAGE_CAUTION"
    if btc_alignment is None:
        return "UNKNOWN"
    if btc_alignment <= -25.0:
        return "BTC_DAMAGE_HARD"
    if btc_alignment < 0.0:
        return "BTC_DAMAGE_CAUTION"
    return "BTC_OK"


def symbol_regime_from_scores(row: dict[str, Any]) -> str:
    explicit = str(row.get("symbol_regime") or row.get("asset_class_regime") or "").strip().upper()
    if explicit:
        if "LEADERSHIP" in explicit or "REL_STRENGTH" in explicit:
            return "REL_STRENGTH"
        if "LAGGARD" in explicit or "STRESS" in explicit or "RISK_OFF" in explicit:
            return "LAGGARD"
    relative_strength = as_float(row.get("relative_strength_score"))
    momentum = as_float(row.get("momentum_score"))
    if relative_strength is None and momentum is None:
        return "UNKNOWN"
    if relative_strength is not None and relative_strength >= 20.0:
        return "REL_STRENGTH"
    if relative_strength is not None and relative_strength <= -20.0:
        return "LAGGARD"
    if momentum is not None and abs(momentum) >= 45.0:
        return "HIGH_BETA"
    if momentum is not None and abs(momentum) <= 10.0:
        return "LOW_BETA"
    return "UNKNOWN"


def relative_strength_bucket(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value >= 50.0:
        return "LEADER"
    if value >= 20.0:
        return "STRONG"
    if value <= -20.0:
        return "WEAK"
    return "NEUTRAL"


def momentum_bucket(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value >= 50.0:
        return "MOMENTUM_HIGH"
    if value >= 20.0:
        return "MOMENTUM_POSITIVE"
    if value <= -25.0:
        return "MOMENTUM_NEGATIVE"
    return "MOMENTUM_FLAT"


def confidence_bucket(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value >= 70.0:
        return "HIGH"
    if value >= 40.0:
        return "MEDIUM"
    return "LOW"


def quality_state_from_row(row: dict[str, Any]) -> str:
    populated = sum(
        1
        for key in (
            "breath_phase",
            "breath_alignment",
            "market_regime",
            "btc_context",
            "symbol_regime",
            "aplus_context_state",
        )
        if str(row.get(key) or "UNKNOWN").upper() != "UNKNOWN"
    )
    if populated >= 5:
        return "HIGH"
    if populated >= 3:
        return "MEDIUM"
    if populated >= 1:
        return "LOW"
    return "UNKNOWN"


def load_market_breath_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    rows = read_jsonl(path)
    out: list[dict[str, Any]] = []
    for row in rows:
        asof_ts = parse_ts(row.get("asof_ts_utc"))
        symbol = str(row.get("symbol") or "").strip().upper()
        if asof_ts is None or not symbol:
            continue
        out.append(
            {
                "source_name": "market_breath_outcome_validation_v1",
                "symbol": symbol,
                "venue": str(row.get("venue") or DEFAULT_VENUE).strip().lower(),
                "interval": str(row.get("interval_code") or DEFAULT_INTERVAL).strip(),
                "asof_ts_utc": asof_ts,
                "source_event_ts_utc": asof_ts,
                "breath_phase": canonical_breath_phase(row.get("market_breath_phase")),
                "breath_alignment": canonical_breath_alignment(row.get("market_breath_state")),
                "market_regime": market_regime_from_scores(row),
                "btc_context": btc_context_from_scores(row),
                "symbol_regime": symbol_regime_from_scores(row),
                "fibo_context": "UNKNOWN",
                "aplus_context_state": "UNKNOWN",
                "martee_context_state": "UNKNOWN",
                "relative_strength_bucket": relative_strength_bucket(as_float(row.get("relative_strength_score"))),
                "momentum_bucket": momentum_bucket(as_float(row.get("momentum_score"))),
                "confidence_bucket": confidence_bucket(as_float(row.get("market_breath_confidence"))),
                "source_refs": [
                    {
                        "source": "market_breath_outcome_validation_v1",
                        "path": str(path),
                        "asof_ts_utc": fmt_ts(asof_ts),
                    }
                ],
                "raw_row": row,
            }
        )
    return out


def parse_json_field(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return None


def load_enriched_market_breath_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    if not path.exists():
        raise FileNotFoundError(f"Enriched market breath rows file not found: {path}")

    rows: list[dict[str, Any]]
    if path.suffix.lower() == ".jsonl":
        rows = read_jsonl(path)
    elif path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    else:
        raise ValueError(f"Unsupported enriched market breath rows format: {path}")

    out: list[dict[str, Any]] = []
    for row in rows:
        asof_ts = parse_ts(row.get("asof_ts_utc"))
        symbol = str(row.get("symbol") or "").strip().upper()
        if asof_ts is None or not symbol:
            continue
        source_event_ts = parse_ts(row.get("source_event_ts_utc")) or asof_ts
        source_refs = parse_json_field(row.get("source_refs"))
        out.append(
            {
                "source_name": "historical_market_breath_source_enrichment_v1",
                "symbol": symbol,
                "venue": str(row.get("venue") or DEFAULT_VENUE).strip().lower(),
                "interval": str(row.get("interval") or DEFAULT_INTERVAL).strip(),
                "asof_ts_utc": asof_ts,
                "source_event_ts_utc": source_event_ts,
                "breath_phase": str(row.get("breath_phase") or "UNKNOWN").strip().upper(),
                "breath_alignment": str(row.get("breath_alignment") or "UNKNOWN").strip().upper(),
                "market_regime": str(row.get("market_regime") or "UNKNOWN").strip().upper(),
                "btc_context": str(row.get("btc_context") or "UNKNOWN").strip().upper(),
                "symbol_regime": str(row.get("symbol_regime") or "UNKNOWN").strip().upper(),
                "fibo_context": "UNKNOWN",
                "aplus_context_state": "UNKNOWN",
                "martee_context_state": "UNKNOWN",
                "relative_strength_bucket": str(row.get("relative_strength_bucket") or "UNKNOWN").strip().upper(),
                "momentum_bucket": str(row.get("momentum_bucket") or "UNKNOWN").strip().upper(),
                "quality_state": str(row.get("quality_state") or "UNKNOWN").strip().upper(),
                "confidence_bucket": str(row.get("confidence_bucket") or "UNKNOWN").strip().upper(),
                "source_refs": list(source_refs) if isinstance(source_refs, list) else [
                    {
                        "source": "historical_market_breath_source_enrichment_v1",
                        "path": str(path),
                        "asof_ts_utc": fmt_ts(asof_ts),
                    }
                ],
                "raw_row": row,
            }
        )
    return out


def load_aplus_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    rows = read_jsonl(path)
    out: list[dict[str, Any]] = []
    for row in rows:
        asof_ts = parse_ts(row.get("prediction_ts_utc"))
        symbol = str(row.get("token") or row.get("symbol") or "").strip().upper()
        if asof_ts is None or not symbol:
            continue
        state_parts = [
            str(row.get("strategic_bias") or "").strip().upper(),
            str(row.get("structural_role") or "").strip().upper(),
            str(row.get("phase") or "").strip().upper(),
        ]
        state = "_".join(part for part in state_parts if part) or "UNKNOWN"
        out.append(
            {
                "source_name": "aplus_canonical_table1_v1",
                "symbol": symbol,
                "asof_ts_utc": asof_ts,
                "aplus_context_state": state,
                "source_refs": [
                    {
                        "source": "aplus_canonical_table1_v1",
                        "path": str(path),
                        "prediction_ts_utc": fmt_ts(asof_ts),
                    }
                ],
            }
        )
    return out


def build_time_spine(
    *,
    symbols: list[str],
    venue: str,
    interval: str,
    start_ts: datetime,
    end_ts: datetime,
    max_rows: int = 0,
) -> list[dict[str, Any]]:
    step = INTERVAL_DELTAS.get(interval)
    if step is None:
        raise ValueError(f"Unsupported interval: {interval}")
    rows: list[dict[str, Any]] = []
    current = start_ts
    while current <= end_ts:
        for symbol in symbols:
            rows.append(
                {
                    "symbol": symbol.upper(),
                    "venue": venue.lower(),
                    "interval": interval,
                    "asof_ts_utc": current,
                }
            )
            if max_rows > 0 and len(rows) >= max_rows:
                return rows
        current += step
    return rows


def nearest_row_at_or_before(
    rows_by_symbol: dict[str, list[dict[str, Any]]],
    *,
    symbol: str,
    asof_ts_utc: datetime,
    max_staleness: timedelta,
) -> dict[str, Any] | None:
    candidates = rows_by_symbol.get(symbol.upper(), [])
    matched: dict[str, Any] | None = None
    for row in candidates:
        row_ts = row["asof_ts_utc"]
        if row_ts > asof_ts_utc:
            break
        matched = row
    if matched is None:
        return None
    if asof_ts_utc - matched["asof_ts_utc"] > max_staleness:
        return None
    return matched


def matching_rows_at_or_before(
    rows_by_symbol: dict[str, list[dict[str, Any]]],
    *,
    symbol: str,
    asof_ts_utc: datetime,
    max_staleness: timedelta,
) -> list[dict[str, Any]]:
    candidates = rows_by_symbol.get(symbol.upper(), [])
    matched: list[dict[str, Any]] = []
    latest_ts: datetime | None = None
    for row in candidates:
        row_ts = row["asof_ts_utc"]
        if row_ts > asof_ts_utc:
            break
        if latest_ts is None or row_ts > latest_ts:
            latest_ts = row_ts
            matched = [row]
        elif row_ts == latest_ts:
            matched.append(row)
    if latest_ts is None or asof_ts_utc - latest_ts > max_staleness:
        return []
    return matched


def build_lookup(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(rows, key=lambda item: (str(item.get("symbol") or "").upper(), item["asof_ts_utc"])):
        grouped[str(row.get("symbol") or "").upper()].append(row)
    return dict(grouped)


def merge_context_row(
    spine_row: dict[str, Any],
    *,
    symbol_lookup: dict[str, list[dict[str, Any]]],
    enriched_symbol_lookup: dict[str, list[dict[str, Any]]] | None,
    market_lookup: dict[str, list[dict[str, Any]]],
    aplus_lookup: dict[str, list[dict[str, Any]]],
    max_staleness: timedelta,
) -> dict[str, Any]:
    symbol = str(spine_row.get("symbol") or "").upper()
    venue = str(spine_row.get("venue") or DEFAULT_VENUE).lower()
    interval = str(spine_row.get("interval") or DEFAULT_INTERVAL)
    asof_ts = spine_row["asof_ts_utc"]

    merged: dict[str, Any] = {
        "symbol": symbol,
        "venue": venue,
        "interval": interval,
        "asof_ts_utc": fmt_ts(asof_ts),
        "source_event_ts_utc": None,
        **UNKNOWN_FIELDS,
        "source_refs": [],
        "research_only": True,
    }

    symbol_row = nearest_row_at_or_before(
        symbol_lookup,
        symbol=symbol,
        asof_ts_utc=asof_ts,
        max_staleness=max_staleness,
    )
    if symbol_row:
        for key in (
            "breath_phase",
            "breath_alignment",
            "market_regime",
            "btc_context",
            "symbol_regime",
            "fibo_context",
            "relative_strength_bucket",
            "momentum_bucket",
            "confidence_bucket",
        ):
            value = symbol_row.get(key)
            if value not in (None, "", "UNKNOWN"):
                merged[key] = value
        merged["source_event_ts_utc"] = fmt_ts(symbol_row.get("source_event_ts_utc") or symbol_row.get("asof_ts_utc"))
        merged["source_refs"].extend(list(symbol_row.get("source_refs") or []))

    if enriched_symbol_lookup:
        enriched_rows = matching_rows_at_or_before(
            enriched_symbol_lookup,
            symbol=symbol,
            asof_ts_utc=asof_ts,
            max_staleness=max_staleness,
        )
        for enriched_row in enriched_rows:
            for key in (
                "breath_phase",
                "breath_alignment",
                "market_regime",
                "btc_context",
                "symbol_regime",
                "relative_strength_bucket",
                "momentum_bucket",
                "quality_state",
                "confidence_bucket",
                "source_refs",
            ):
                if key == "source_refs":
                    merged["source_refs"].extend(list(enriched_row.get("source_refs") or []))
                    continue
                value = enriched_row.get(key)
                if value not in (None, "", "UNKNOWN"):
                    merged[key] = value
            if enriched_row.get("source_event_ts_utc") is not None:
                merged["source_event_ts_utc"] = fmt_ts(
                    enriched_row.get("source_event_ts_utc") or enriched_row.get("asof_ts_utc")
                )

    market_row = nearest_row_at_or_before(
        market_lookup,
        symbol="*",
        asof_ts_utc=asof_ts,
        max_staleness=max_staleness,
    )
    if market_row:
        for key in ("market_regime", "btc_context", "breath_phase", "breath_alignment"):
            if merged.get(key) == "UNKNOWN" and market_row.get(key) not in (None, "", "UNKNOWN"):
                merged[key] = market_row[key]
        merged["source_refs"].extend(list(market_row.get("source_refs") or []))

    aplus_row = nearest_row_at_or_before(
        aplus_lookup,
        symbol=symbol,
        asof_ts_utc=asof_ts,
        max_staleness=timedelta(days=7),
    )
    if aplus_row and aplus_row.get("aplus_context_state") not in (None, ""):
        merged["aplus_context_state"] = str(aplus_row["aplus_context_state"]).upper()
        merged["source_refs"].extend(list(aplus_row.get("source_refs") or []))

    merged["quality_state"] = quality_state_from_row(merged)
    return merged


def build_context_rows(
    *,
    breath_rows: list[dict[str, Any]],
    enriched_breath_rows: list[dict[str, Any]] | None = None,
    aplus_rows: list[dict[str, Any]] | None = None,
    market_context_rows: list[dict[str, Any]] | None = None,
    symbols: list[str] | None = None,
    venue: str = DEFAULT_VENUE,
    interval: str = DEFAULT_INTERVAL,
    start_ts: datetime | None = None,
    end_ts: datetime | None = None,
    max_rows: int = 0,
) -> list[dict[str, Any]]:
    filtered_breath = [row for row in breath_rows if str(row.get("interval") or interval) == interval]
    if symbols:
        wanted = {symbol.upper() for symbol in symbols}
        filtered_breath = [row for row in filtered_breath if str(row.get("symbol") or "").upper() in wanted]

    spine_rows: list[dict[str, Any]] = [
        {
            "symbol": str(row["symbol"]).upper(),
            "venue": str(row.get("venue") or venue).lower(),
            "interval": str(row.get("interval") or interval),
            "asof_ts_utc": row["asof_ts_utc"],
        }
        for row in filtered_breath
    ]

    if not spine_rows and symbols and start_ts and end_ts:
        spine_rows = build_time_spine(
            symbols=symbols,
            venue=venue,
            interval=interval,
            start_ts=start_ts,
            end_ts=end_ts,
            max_rows=max_rows,
        )

    if max_rows > 0:
        spine_rows = spine_rows[:max_rows]

    symbol_lookup = build_lookup(filtered_breath)
    enriched_symbol_lookup = build_lookup(list(enriched_breath_rows or []))
    market_lookup = build_lookup(list(market_context_rows or []))
    aplus_lookup = build_lookup(list(aplus_rows or []))
    max_staleness = MAX_STALENESS.get(interval, timedelta(days=2))

    rows = [
        merge_context_row(
            row,
            symbol_lookup=symbol_lookup,
            enriched_symbol_lookup=enriched_symbol_lookup,
            market_lookup=market_lookup,
            aplus_lookup=aplus_lookup,
            max_staleness=max_staleness,
        )
        for row in spine_rows
    ]

    rows.sort(key=lambda row: (row["symbol"], row["asof_ts_utc"]))
    return rows


def build_manifest(*, rows: list[dict[str, Any]], output_dir: Path, source_paths: dict[str, str | None]) -> dict[str, Any]:
    unknown_rows = sum(
        1
        for row in rows
        if all(str(row.get(field) or "UNKNOWN").upper() == "UNKNOWN" for field in ("breath_phase", "market_regime", "btc_context", "symbol_regime"))
    )
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "row_count": len(rows),
        "unknown_context_rows": unknown_rows,
        "output_dir": str(output_dir),
        "output_files": {
            "rows_csv": str(output_dir / ROWS_CSV),
            "rows_jsonl": str(output_dir / ROWS_JSONL),
            "manifest_json": str(output_dir / MANIFEST_JSON),
        },
        "source_paths": source_paths,
        "safety_markers": SAFETY_MARKERS,
        "research_only": True,
    }


def print_summary(*, rows: list[dict[str, Any]], manifest: dict[str, Any], output_mode: str) -> None:
    if output_mode == "json":
        print(json.dumps({"rows": rows, "manifest": manifest}, indent=2, sort_keys=True, ensure_ascii=True))
        return
    symbols = sorted({row["symbol"] for row in rows})
    quality_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        quality_counts[str(row["quality_state"])] += 1
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(f"row_count={len(rows)} symbols={','.join(symbols[:12]) if symbols else 'none'}")
    print("quality_state " + " ; ".join(f"{key}:{quality_counts[key]}" for key in sorted(quality_counts)))
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
    interval = str(args.interval)
    venue = str(args.venue).lower()
    output_dir = Path(args.output_dir)
    start_ts = parse_ts(args.start_ts)
    end_ts = parse_ts(args.end_ts)

    market_breath_path = DEFAULT_MARKET_BREATH_ROWS if DEFAULT_MARKET_BREATH_ROWS.exists() else None
    enriched_market_breath_path = (
        Path(args.enriched_market_breath_rows)
        if args.enriched_market_breath_rows
        else None
    )
    aplus_path = latest_matching(DEFAULT_APLUS_GLOB)

    breath_rows = load_market_breath_rows(market_breath_path)
    enriched_breath_rows = load_enriched_market_breath_rows(enriched_market_breath_path)
    aplus_rows = load_aplus_rows(aplus_path)
    rows = build_context_rows(
        breath_rows=breath_rows,
        enriched_breath_rows=enriched_breath_rows,
        aplus_rows=aplus_rows,
        symbols=symbols,
        venue=venue,
        interval=interval,
        start_ts=start_ts,
        end_ts=end_ts,
        max_rows=int(args.max_rows or 0),
    )

    manifest = build_manifest(
        rows=rows,
        output_dir=output_dir,
        source_paths={
            "market_breath_rows": None if market_breath_path is None else str(market_breath_path),
            "enriched_market_breath_rows": (
                None if enriched_market_breath_path is None else str(enriched_market_breath_path)
            ),
            "aplus_rows": None if aplus_path is None else str(aplus_path),
        },
    )

    if args.write_files:
        write_csv(output_dir / ROWS_CSV, rows)
        write_jsonl(output_dir / ROWS_JSONL, rows)
        write_json(output_dir / MANIFEST_JSON, manifest)

    print_summary(rows=rows, manifest=manifest, output_mode=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
