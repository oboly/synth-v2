from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


REPORT_NAME = "xlm_event_level_context_overlap_audit_v1"
REPORT_VERSION = "1.0"

DEFAULT_SYMBOL = "XLM"
DEFAULT_RECOMPUTE_ROWS = Path(
    "data/research/historical_market_breath_source_recompute_v1/historical_market_breath_source_recomputed_rows_v1.csv"
)
DEFAULT_CONTEXT_ROWS = Path(
    "data/research/historical_breath_regime_context_builder_v1/historical_breath_regime_context_rows_v1.csv"
)
DEFAULT_PROFILE_ROWS = Path(
    "data/research/symbol_reaction_profile_by_context_v1/symbol_reaction_profile_by_context_rows_v1.csv"
)
DEFAULT_EVENT_ROWS = Path("data/research/position_lifecycle_outcome_validation_v1/outcome_rows_v1.jsonl")
DEFAULT_OUTPUT_DIR = Path("data/research/xlm_event_level_context_overlap_audit_v1")

ROWS_CSV = "xlm_event_level_context_overlap_rows_v1.csv"
MANIFEST_JSON = "manifest_v1.json"
MAX_STALENESS = timedelta(days=7)

CONTEXT_FIELDS = ("breath_phase", "breath_alignment", "market_regime", "btc_context", "symbol_regime")

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
        description="Audit XLM event-level overlap between recomputed context, context-builder rows, and aggregate profile buckets."
    )
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--recompute-rows", default=str(DEFAULT_RECOMPUTE_ROWS))
    parser.add_argument("--context-rows", default=str(DEFAULT_CONTEXT_ROWS))
    parser.add_argument("--profile-rows", default=str(DEFAULT_PROFILE_ROWS))
    parser.add_argument("--event-rows", default=str(DEFAULT_EVENT_ROWS))
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    converted_rows: list[dict[str, Any]] = []
    for row in rows:
        converted: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                converted[key] = json.dumps(value, sort_keys=True, ensure_ascii=True)
            else:
                converted[key] = value
        converted_rows.append(converted)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(converted_rows[0].keys()))
        writer.writeheader()
        writer.writerows(converted_rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def load_required_csv(path: Path, *, label: str) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing {label} file: {path}")
    rows = read_csv_rows(path)
    if not rows:
        raise ValueError(f"{label} file is empty: {path}")
    return rows


def load_required_jsonl(path: Path, *, label: str) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing {label} file: {path}")
    rows = read_jsonl(path)
    if not rows:
        raise ValueError(f"{label} file is empty: {path}")
    return rows


def is_unknown(value: Any) -> bool:
    return str(value or "").strip().upper() in {"", "UNKNOWN"}


def as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int:
    if value in ("", None):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


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


def context_key_from_values(
    symbol: str,
    breath_phase: str,
    breath_alignment: str,
    market_regime: str,
    btc_context: str,
    symbol_regime: str,
) -> tuple[str, str, str, str, str, str]:
    return (
        symbol.strip().upper(),
        breath_phase.strip().upper(),
        breath_alignment.strip().upper(),
        market_regime.strip().upper(),
        btc_context.strip().upper(),
        symbol_regime.strip().upper(),
    )


def profile_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return context_key_from_values(
        str(row.get("symbol") or ""),
        str(row.get("breath_phase") or "UNKNOWN"),
        str(row.get("breath_alignment") or "UNKNOWN"),
        str(row.get("market_regime") or "UNKNOWN"),
        str(row.get("btc_context") or "UNKNOWN"),
        str(row.get("symbol_regime") or "UNKNOWN"),
    )


def build_lookup(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda item: (str(item.get("symbol") or "").upper(), item["asof_ts_utc_dt"])):
        grouped.setdefault(str(row.get("symbol") or "").upper(), []).append(row)
    return grouped


def nearest_at_or_before(
    lookup: dict[str, list[dict[str, Any]]],
    *,
    symbol: str,
    event_ts_utc: datetime,
    max_staleness: timedelta = MAX_STALENESS,
) -> dict[str, Any] | None:
    matched: dict[str, Any] | None = None
    for row in lookup.get(symbol.upper(), []):
        if row["asof_ts_utc_dt"] > event_ts_utc:
            break
        matched = row
    if matched is None:
        return None
    if event_ts_utc - matched["asof_ts_utc_dt"] > max_staleness:
        return None
    return matched


def load_timestamped_csv_rows(path: Path, *, label: str, symbol: str) -> list[dict[str, Any]]:
    rows = load_required_csv(path, label=label)
    out: list[dict[str, Any]] = []
    for row in rows:
        row_symbol = str(row.get("symbol") or "").strip().upper()
        if row_symbol != symbol.upper():
            continue
        asof_ts = parse_ts(row.get("asof_ts_utc"))
        if asof_ts is None:
            continue
        item = dict(row)
        item["symbol"] = row_symbol
        item["asof_ts_utc_dt"] = asof_ts
        out.append(item)
    return out


def load_xlm_event_rows(path: Path, symbol: str) -> list[dict[str, Any]]:
    rows = load_required_jsonl(path, label="event rows")
    out: list[dict[str, Any]] = []
    for row in rows:
        row_symbol = str(row.get("symbol") or "").strip().upper()
        event_ts = parse_ts(row.get("event_ts_utc"))
        if row_symbol != symbol.upper() or event_ts is None:
            continue
        item = dict(row)
        item["symbol"] = row_symbol
        item["event_ts_utc_dt"] = event_ts
        out.append(item)
    return out


def known_context_from_recompute(row: dict[str, Any] | None) -> bool:
    if row is None:
        return False
    return any(not is_unknown(row.get(field)) for field in ("breath_phase", "breath_alignment", "symbol_regime"))


def build_event_rows(
    *,
    symbol: str,
    recompute_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    profile_rows: list[dict[str, str]],
    event_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    recompute_lookup = build_lookup(recompute_rows)
    context_lookup = build_lookup(context_rows)
    profile_keys = {profile_key(row) for row in profile_rows if str(row.get("symbol") or "").upper() == symbol.upper()}

    output: list[dict[str, Any]] = []
    for event_row in sorted(event_rows, key=lambda row: row["event_ts_utc_dt"]):
        event_ts = event_row["event_ts_utc_dt"]
        recompute = nearest_at_or_before(recompute_lookup, symbol=symbol, event_ts_utc=event_ts)
        context = nearest_at_or_before(context_lookup, symbol=symbol, event_ts_utc=event_ts)
        recompute_key = None
        if recompute is not None:
            recompute_key = context_key_from_values(
                symbol,
                str(recompute.get("breath_phase") or "UNKNOWN"),
                str(recompute.get("breath_alignment") or "UNKNOWN"),
                str(recompute.get("market_regime") or "UNKNOWN"),
                str(recompute.get("btc_context") or "UNKNOWN"),
                str(recompute.get("symbol_regime") or "UNKNOWN"),
            )
        aggregate_preserved = recompute_key in profile_keys if recompute_key is not None else False
        known_context = known_context_from_recompute(recompute)

        if recompute is None:
            issue = "NO_EVENT_OVERLAP"
        elif not known_context:
            issue = "EVENT_CONTEXT_UNKNOWN"
        elif aggregate_preserved:
            issue = "EVENT_HAS_KNOWN_CONTEXT"
        else:
            issue = "AGGREGATE_PROFILE_LOST_CONTEXT"

        output.append(
            {
                "symbol": symbol.upper(),
                "event_ts_utc": fmt_ts(event_ts),
                "source_candle_ts_utc": event_row.get("source_candle_ts_utc"),
                "recompute_asof_ts_utc": fmt_ts(recompute["asof_ts_utc_dt"]) if recompute else None,
                "context_asof_ts_utc": fmt_ts(context["asof_ts_utc_dt"]) if context else None,
                "breath_phase": None if recompute is None else str(recompute.get("breath_phase") or "UNKNOWN").upper(),
                "breath_alignment": None if recompute is None else str(recompute.get("breath_alignment") or "UNKNOWN").upper(),
                "market_regime": None if recompute is None else str(recompute.get("market_regime") or "UNKNOWN").upper(),
                "btc_context": None if recompute is None else str(recompute.get("btc_context") or "UNKNOWN").upper(),
                "symbol_regime": None if recompute is None else str(recompute.get("symbol_regime") or "UNKNOWN").upper(),
                "event_has_known_context": known_context,
                "aggregate_profile_preserved_context": aggregate_preserved,
                "max_favorable_excursion_pct": as_float(event_row.get("max_favorable_excursion_pct")),
                "max_adverse_excursion_pct": as_float(event_row.get("max_adverse_excursion_pct")),
                "drawdown_after_event_pct": as_float(event_row.get("drawdown_after_event_pct")),
                "issue_classification": issue,
                "research_only": True,
            }
        )
    return output


def build_manifest(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    issue_counts = {}
    for row in rows:
        issue = str(row.get("issue_classification") or "UNKNOWN")
        issue_counts[issue] = issue_counts.get(issue, 0) + 1
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "symbol": args.symbol.upper(),
        "row_count": len(rows),
        "issue_distribution": dict(sorted(issue_counts.items())),
        "recompute_rows_path": str(args.recompute_rows),
        "context_rows_path": str(args.context_rows),
        "profile_rows_path": str(args.profile_rows),
        "event_rows_path": str(args.event_rows),
        "output_dir": str(output_dir),
        "output_files": {
            "rows_csv": str(output_dir / ROWS_CSV),
            "manifest_json": str(output_dir / MANIFEST_JSON),
        },
        "safety_markers": SAFETY_MARKERS,
        "research_only": True,
    }


def print_summary(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    known_context_count = sum(1 for row in rows if row["event_has_known_context"])
    aggregate_loss_count = sum(1 for row in rows if row["issue_classification"] == "AGGREGATE_PROFILE_LOST_CONTEXT")
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(f"symbol={manifest['symbol']} event_count={len(rows)}")
    print(f"known_context_event_count={known_context_count}")
    print(f"aggregate_loss_event_count={aggregate_loss_count}")
    print(
        "issue_distribution "
        + " ; ".join(f"{key}:{value}" for key, value in manifest["issue_distribution"].items())
    )
    print(
        "safety "
        + " ".join(
            f"{key}={str(value).lower() if isinstance(value, bool) else value}"
            for key, value in SAFETY_MARKERS.items()
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbol = str(args.symbol).upper()
    output_dir = Path(args.output_dir)

    recompute_rows = load_timestamped_csv_rows(Path(args.recompute_rows), label="recompute rows", symbol=symbol)
    context_rows = load_timestamped_csv_rows(Path(args.context_rows), label="context rows", symbol=symbol)
    profile_rows = load_required_csv(Path(args.profile_rows), label="profile rows")
    event_rows = load_xlm_event_rows(Path(args.event_rows), symbol)

    rows = build_event_rows(
        symbol=symbol,
        recompute_rows=recompute_rows,
        context_rows=context_rows,
        profile_rows=profile_rows,
        event_rows=event_rows,
    )
    manifest = build_manifest(args=args, output_dir=output_dir, rows=rows)

    if args.write_files:
        write_csv(output_dir / ROWS_CSV, rows)
        write_json(output_dir / MANIFEST_JSON, manifest)

    if args.output == "json":
        print(json.dumps({"rows": rows, "manifest": manifest}, indent=2, sort_keys=True))
    else:
        print_summary(rows, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
