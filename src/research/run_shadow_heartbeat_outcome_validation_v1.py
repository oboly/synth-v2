from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "shadow_heartbeat_outcome_validation_v1"
REPORT_VERSION = "1.0"

DEFAULT_CHAIN_ROOT = Path("data/research/live_like_shadow_chain_v1")
DEFAULT_OUTPUT_DIR = Path("data/research/shadow_heartbeat_outcome_validation_v1")
DEFAULT_INTERVAL = "15m"
DEFAULT_VENUE = "bitvavo"

CHAIN_SUMMARY_JSON = "chain_summary_v1.json"
MANIFEST_JSON = "manifest_v1.json"
STRATEGY_CANDIDATE_JSON = "strategy_candidate_v1.json"
DECISION_PREVIEW_JSON = "decision_preview_v1.json"
SHADOW_EVENT_JSON = "shadow_event_v1.json"

OUTPUT_ROWS = "outcome_rows_v1.jsonl"
OUTPUT_SUMMARY = "outcome_summary_v1.json"

HORIZON_LABELS: list[tuple[str, timedelta]] = [
    ("15m", timedelta(minutes=15)),
    ("30m", timedelta(minutes=30)),
    ("1h", timedelta(hours=1)),
    ("2h", timedelta(hours=2)),
    ("4h", timedelta(hours=4)),
    ("8h", timedelta(hours=8)),
    ("24h", timedelta(hours=24)),
]
MAX_WINDOW = HORIZON_LABELS[-1][1]

WAIT_RETEST_COHORT_STATES = {
    "WAIT_RETEST",
    "SHALLOW_RETEST_ACTIVE",
    "NORMAL_RETEST_ACTIVE",
    "DEEP_RETEST_ACTIVE",
    "IMPULSE_ACTIVE",
}
BLOCKED_CANDIDATE_STATES = {"INVALIDATED", "STALE"}
COHORT_STATES = ("ENTRY_CANDIDATE", "WAIT_RETEST", "NO_CANDIDATE", "BLOCKED")

THRESHOLDS = (0.5, 1.0)


@dataclass(frozen=True)
class OutputPaths:
    outcome_rows_jsonl: Path
    outcome_summary_json: Path


@dataclass(frozen=True)
class Candle:
    close_ts_utc: datetime
    close_price: float
    high_price: float
    low_price: float


@dataclass(frozen=True)
class HeartbeatEvent:
    run_id: str
    run_dir: Path
    event_ts_utc: datetime
    symbol: str
    market: str
    venue: str
    interval_code: str
    candidate_state: str
    decision_state: str
    execution_plan_state: str
    validation_state: str
    permission_state: str | None
    entry_state: str | None
    label_state_15m: str | None
    label_state_1h: str | None
    reference_price: float | None
    reference_price_source: str
    transition_from_state: str | None
    transition_changed: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate live-like shadow heartbeat states against forward market outcomes "
            "(research-only, market-only, read-only, no executor)."
        )
    )
    parser.add_argument("--chain-root", default=str(DEFAULT_CHAIN_ROOT))
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--venue", default=None)
    parser.add_argument("--interval", default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    return parser.parse_args(argv)


def fmt_ts(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_ts(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Missing timestamp")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_artifact_path(raw_path: Any) -> Path | None:
    text = str(raw_path or "").strip()
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        return path
    return repo_root() / path


def load_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    return read_json(path)


def normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def normalize_state(value: Any) -> str:
    return str(value or "").strip().upper()


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def derive_validation_state(candidate_state: str, decision_state: str, execution_plan_state: str) -> str:
    candidate = normalize_state(candidate_state)
    decision = normalize_state(decision_state)
    execution = normalize_state(execution_plan_state)
    if candidate == "ENTRY_CANDIDATE":
        return "ENTRY_CANDIDATE"
    if candidate in WAIT_RETEST_COHORT_STATES:
        return "WAIT_RETEST"
    if candidate == "NO_CANDIDATE":
        return "NO_CANDIDATE"
    if candidate in BLOCKED_CANDIDATE_STATES or decision == "BLOCKED" or execution == "BLOCKED":
        return "BLOCKED"
    return "NO_CANDIDATE"


def build_output_paths(output_dir: Path) -> OutputPaths:
    return OutputPaths(
        outcome_rows_jsonl=output_dir / OUTPUT_ROWS,
        outcome_summary_json=output_dir / OUTPUT_SUMMARY,
    )


def find_event_timestamp(chain_summary: dict[str, Any], manifest: dict[str, Any], shadow_payload: dict[str, Any] | None) -> datetime:
    for candidate in (
        None if shadow_payload is None else shadow_payload.get("event_ts_utc"),
        manifest.get("run_finished_at_utc"),
        manifest.get("run_started_at_utc"),
        chain_summary.get("run_finished_at_utc"),
        chain_summary.get("run_started_at_utc"),
    ):
        if candidate:
            return parse_ts(candidate)
    raise ValueError("Unable to resolve heartbeat event timestamp")


def infer_interval(
    chain_summary: dict[str, Any],
    candidate_payload: dict[str, Any] | None,
    requested: str | None,
) -> str:
    if requested:
        return str(requested)
    for candidate in (
        None if candidate_payload is None else candidate_payload.get("entry_timeframe"),
        None if candidate_payload is None else candidate_payload.get("primary_timeframe"),
        chain_summary.get("interval_code"),
        chain_summary.get("interval"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return DEFAULT_INTERVAL


def infer_venue(chain_summary: dict[str, Any], candidate_payload: dict[str, Any] | None, requested: str | None) -> str:
    if requested:
        return str(requested)
    for candidate in (
        None if candidate_payload is None else candidate_payload.get("venue"),
        chain_summary.get("venue"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return DEFAULT_VENUE


def load_heartbeat_events(
    *,
    chain_root: Path,
    symbol_filter: str | None,
    venue_override: str | None,
    interval_override: str | None,
    max_events: int | None,
) -> list[HeartbeatEvent]:
    run_dirs = sorted(path for path in chain_root.glob("run_*") if path.is_dir())
    previous_state_by_symbol: dict[str, str] = {}
    events: list[HeartbeatEvent] = []
    for run_dir in run_dirs:
        summary_path = run_dir / CHAIN_SUMMARY_JSON
        manifest_path = run_dir / MANIFEST_JSON
        if not summary_path.exists() or not manifest_path.exists():
            continue
        chain_summary = read_json(summary_path)
        manifest = read_json(manifest_path)

        candidate_run_dir = resolve_artifact_path(chain_summary.get("candidate_run_dir") or manifest.get("candidate_run_dir"))
        decision_run_dir = resolve_artifact_path(chain_summary.get("decision_run_dir") or manifest.get("decision_run_dir"))
        shadow_run_dir = resolve_artifact_path(chain_summary.get("shadow_event_run_dir") or manifest.get("shadow_event_run_dir"))

        candidate_payload = load_optional_json(None if candidate_run_dir is None else candidate_run_dir / STRATEGY_CANDIDATE_JSON)
        decision_payload = load_optional_json(None if decision_run_dir is None else decision_run_dir / DECISION_PREVIEW_JSON)
        shadow_payload = load_optional_json(None if shadow_run_dir is None else shadow_run_dir / SHADOW_EVENT_JSON)

        symbol = normalize_symbol(
            chain_summary.get("symbol")
            or manifest.get("symbol")
            or (None if candidate_payload is None else candidate_payload.get("symbol"))
        )
        if symbol_filter and symbol != normalize_symbol(symbol_filter):
            continue
        if not symbol:
            continue

        event_ts = find_event_timestamp(chain_summary, manifest, shadow_payload)
        market = str(
            chain_summary.get("market")
            or manifest.get("market")
            or (None if candidate_payload is None else candidate_payload.get("source_context", {}).get("market"))
            or ""
        )
        candidate_state = str(
            chain_summary.get("candidate_state")
            or manifest.get("candidate_state")
            or (None if candidate_payload is None else candidate_payload.get("candidate_state"))
            or ""
        )
        decision_state = str(
            chain_summary.get("decision_state")
            or manifest.get("decision_state")
            or (None if decision_payload is None else decision_payload.get("decision_state"))
            or ""
        )
        execution_plan_state = str(
            chain_summary.get("execution_plan_state")
            or manifest.get("execution_plan_state")
            or ""
        )
        permission_state = None if decision_payload is None else str(decision_payload.get("permission_state") or "")
        if permission_state == "":
            permission_state = None
        entry_state = None if candidate_payload is None else str(candidate_payload.get("entry_state") or "")
        if entry_state == "":
            entry_state = None
        source_context = {} if candidate_payload is None else candidate_payload.get("source_context", {}) or {}
        label_state_15m = str(source_context.get("market_state_15m") or "") or None
        label_state_1h = str(source_context.get("market_state_1h") or "") or None
        reference_price = None
        reference_price_source = "unavailable"
        for key, source in (
            ("observed_price", "shadow_event_observed_price"),
            ("observed_price", "chain_summary_observed_price"),
            ("price_at_emit", "candidate_price_at_emit"),
            ("current_price", "candidate_current_price"),
            ("ticker_price", "candidate_ticker_price"),
        ):
            raw_value = (
                (None if shadow_payload is None else shadow_payload.get(key))
                if source.startswith("shadow_event")
                else chain_summary.get(key)
                if source.startswith("chain_summary")
                else source_context.get(key)
            )
            price = as_float(raw_value)
            if price is not None and price > 0:
                reference_price = price
                reference_price_source = source
                break

        validation_state = derive_validation_state(candidate_state, decision_state, execution_plan_state)
        previous_state = previous_state_by_symbol.get(symbol)
        transition_changed = previous_state is not None and previous_state != validation_state
        previous_state_by_symbol[symbol] = validation_state

        events.append(
            HeartbeatEvent(
                run_id=str(manifest.get("run_id") or run_dir.name.replace("run_", "")),
                run_dir=run_dir,
                event_ts_utc=event_ts,
                symbol=symbol,
                market=market,
                venue=infer_venue(chain_summary, candidate_payload, venue_override),
                interval_code=infer_interval(chain_summary, candidate_payload, interval_override),
                candidate_state=candidate_state,
                decision_state=decision_state,
                execution_plan_state=execution_plan_state,
                validation_state=validation_state,
                permission_state=permission_state,
                entry_state=entry_state,
                label_state_15m=label_state_15m,
                label_state_1h=label_state_1h,
                reference_price=reference_price,
                reference_price_source=reference_price_source,
                transition_from_state=previous_state,
                transition_changed=transition_changed,
            )
        )

    events.sort(key=lambda item: (item.event_ts_utc, item.run_id, item.run_dir.name))
    if max_events is not None:
        if max_events <= 0:
            raise ValueError("--max-events must be greater than zero")
        events = events[-max_events:]

    previous_state_by_symbol.clear()
    rebased: list[HeartbeatEvent] = []
    for event in events:
        previous_state = previous_state_by_symbol.get(event.symbol)
        rebased.append(
            HeartbeatEvent(
                run_id=event.run_id,
                run_dir=event.run_dir,
                event_ts_utc=event.event_ts_utc,
                symbol=event.symbol,
                market=event.market,
                venue=event.venue,
                interval_code=event.interval_code,
                candidate_state=event.candidate_state,
                decision_state=event.decision_state,
                execution_plan_state=event.execution_plan_state,
                validation_state=event.validation_state,
                permission_state=event.permission_state,
                entry_state=event.entry_state,
                label_state_15m=event.label_state_15m,
                label_state_1h=event.label_state_1h,
                reference_price=event.reference_price,
                reference_price_source=event.reference_price_source,
                transition_from_state=previous_state,
                transition_changed=previous_state is not None and previous_state != event.validation_state,
            )
        )
        previous_state_by_symbol[event.symbol] = event.validation_state
    return rebased


def infer_global_value(events: list[HeartbeatEvent], attr: str, fallback: str) -> str:
    values = sorted({str(getattr(event, attr) or "").strip() for event in events if str(getattr(event, attr) or "").strip()})
    if not values:
        return fallback
    if len(values) > 1:
        raise ValueError(f"Multiple {attr} values found in heartbeat history; pass --{attr.replace('_code', '').replace('_', '-')} explicitly")
    return values[0]


def fetch_asset_map(conn, symbols: list[str]) -> dict[str, int]:
    if not symbols:
        return {}
    placeholders = ", ".join(["%s"] * len(symbols))
    sql = f"SELECT asset_id, symbol FROM asset WHERE symbol IN ({placeholders})"
    with conn.cursor() as cur:
        cur.execute(sql, tuple(symbols))
        rows = cur.fetchall()
    return {normalize_symbol(row["symbol"]): int(row["asset_id"]) for row in rows}


def fetch_candles(
    conn,
    *,
    asset_ids: dict[str, int],
    venue: str,
    interval_code: str,
    start_ts: datetime,
    end_ts: datetime,
) -> dict[str, list[Candle]]:
    if not asset_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(asset_ids))
    sql = f"""
        SELECT asset_id, close_ts_utc, close_price, high_price, low_price
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND close_ts_utc >= %s
          AND close_ts_utc <= %s
          AND asset_id IN ({placeholders})
        ORDER BY asset_id, close_ts_utc
    """
    params: list[Any] = [venue, interval_code, to_naive_utc(start_ts), to_naive_utc(end_ts), *asset_ids.values()]
    reverse_asset = {asset_id: symbol for symbol, asset_id in asset_ids.items()}
    grouped: dict[str, list[Candle]] = {symbol: [] for symbol in asset_ids}
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    for row in rows:
        symbol = reverse_asset.get(int(row["asset_id"]))
        if symbol is None:
            continue
        close_ts = row["close_ts_utc"]
        if close_ts.tzinfo is None:
            close_ts = close_ts.replace(tzinfo=UTC)
        else:
            close_ts = close_ts.astimezone(UTC)
        close_price = as_float(row["close_price"])
        high_price = as_float(row["high_price"])
        low_price = as_float(row["low_price"])
        if close_price is None or high_price is None or low_price is None:
            continue
        grouped[symbol].append(
            Candle(
                close_ts_utc=close_ts,
                close_price=close_price,
                high_price=high_price,
                low_price=low_price,
            )
        )
    return grouped


def find_latest_candle_before_or_at(candles: list[Candle], ts: datetime) -> Candle | None:
    candidate: Candle | None = None
    for candle in candles:
        if candle.close_ts_utc <= ts:
            candidate = candle
            continue
        break
    return candidate


def find_first_candle_at_or_after(candles: list[Candle], ts: datetime) -> Candle | None:
    for candle in candles:
        if candle.close_ts_utc >= ts:
            return candle
    return None


def candles_in_window(candles: list[Candle], start_ts: datetime, end_ts: datetime) -> list[Candle]:
    return [candle for candle in candles if start_ts < candle.close_ts_utc <= end_ts]


def return_pct(reference_price: float | None, future_price: float | None) -> float | None:
    if reference_price is None or future_price is None or reference_price <= 0:
        return None
    return round((future_price / reference_price - 1.0) * 100.0, 6)


def median_or_none(values: list[float]) -> float | None:
    return round(float(median(values)), 6) if values else None


def average_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def hit_rate(values: list[bool]) -> float | None:
    if not values:
        return None
    return round(sum(1 for value in values if value) / len(values) * 100.0, 6)


def build_event_row(event: HeartbeatEvent, candles: list[Candle]) -> dict[str, Any]:
    base_candle = find_latest_candle_before_or_at(candles, event.event_ts_utc)
    reference_price = event.reference_price
    reference_price_source = event.reference_price_source
    if reference_price is None and base_candle is not None:
        reference_price = base_candle.close_price
        reference_price_source = "base_candle_close"

    window_candles = candles_in_window(candles, event.event_ts_utc, event.event_ts_utc + MAX_WINDOW)
    horizon_returns: dict[str, float | None] = {}
    horizon_prices: dict[str, float | None] = {}
    completeness_flags: dict[str, bool] = {}

    for label, delta in HORIZON_LABELS:
        target_ts = event.event_ts_utc + delta
        future_candle = find_first_candle_at_or_after(candles, target_ts)
        horizon_prices[label] = None if future_candle is None else future_candle.close_price
        horizon_returns[label] = return_pct(reference_price, horizon_prices[label])
        completeness_flags[label] = future_candle is not None

    close_returns_24h = [return_pct(reference_price, candle.close_price) for candle in window_candles]
    close_returns_24h = [value for value in close_returns_24h if value is not None]

    max_forward_return_pct = round(max(close_returns_24h), 6) if close_returns_24h else None
    min_forward_return_pct = round(min(close_returns_24h), 6) if close_returns_24h else None

    mfe_pct = None
    mae_pct = None
    if reference_price is not None and reference_price > 0 and window_candles:
        mfe_pct = round((max(candle.high_price for candle in window_candles) / reference_price - 1.0) * 100.0, 6)
        mae_pct = round((min(candle.low_price for candle in window_candles) / reference_price - 1.0) * 100.0, 6)

    full_window_complete = completeness_flags["24h"]
    row = {
        "event_ts": fmt_ts(event.event_ts_utc),
        "run_id": event.run_id,
        "symbol": event.symbol,
        "market": event.market,
        "venue": event.venue,
        "interval_code": event.interval_code,
        "state": event.validation_state,
        "candidate_state": event.candidate_state,
        "decision_state": event.decision_state,
        "execution_plan_state": event.execution_plan_state,
        "permission_state": event.permission_state,
        "entry_state": event.entry_state,
        "label_state_15m": event.label_state_15m,
        "label_state_1h": event.label_state_1h,
        "transition_from_state": event.transition_from_state,
        "transition_changed": event.transition_changed,
        "reference_price": reference_price,
        "reference_price_source": reference_price_source,
        "base_candle_ts": None if base_candle is None else fmt_ts(base_candle.close_ts_utc),
        "sample_complete_24h": full_window_complete,
        "sample_has_reference_price": reference_price is not None,
        "sample_window_candle_count_24h": len(window_candles),
        "max_forward_return_pct": max_forward_return_pct,
        "min_forward_return_pct": min_forward_return_pct,
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
        "hit_plus_0_5_pct": bool(mfe_pct is not None and mfe_pct >= 0.5),
        "hit_plus_1_0_pct": bool(mfe_pct is not None and mfe_pct >= 1.0),
        "hit_minus_0_5_pct": bool(mae_pct is not None and mae_pct <= -0.5),
        "hit_minus_1_0_pct": bool(mae_pct is not None and mae_pct <= -1.0),
        "sample_completeness_flags": {
            "has_reference_price": reference_price is not None,
            "complete_15m": completeness_flags["15m"],
            "complete_30m": completeness_flags["30m"],
            "complete_1h": completeness_flags["1h"],
            "complete_2h": completeness_flags["2h"],
            "complete_4h": completeness_flags["4h"],
            "complete_8h": completeness_flags["8h"],
            "complete_24h": completeness_flags["24h"],
        },
    }
    for label, _delta in HORIZON_LABELS:
        row[f"future_price_{label}"] = horizon_prices[label]
        row[f"return_pct_{label}"] = horizon_returns[label]
    return row


def build_event_rows(events: list[HeartbeatEvent], candles_by_symbol: dict[str, list[Candle]]) -> list[dict[str, Any]]:
    return [build_event_row(event, candles_by_symbol.get(event.symbol, [])) for event in events]


def values_for_state(rows: list[dict[str, Any]], state: str, field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        if row["state"] != state:
            continue
        value = row.get(field)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def bools_for_state(rows: list[dict[str, Any]], state: str, field: str) -> list[bool]:
    values: list[bool] = []
    for row in rows:
        if row["state"] != state:
            continue
        value = row.get(field)
        if isinstance(value, bool):
            values.append(value)
    return values


def build_state_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for state in COHORT_STATES:
        state_rows = [row for row in rows if row["state"] == state]
        summary: dict[str, Any] = {
            "count": len(state_rows),
            "complete_count": sum(1 for row in state_rows if row.get("sample_complete_24h")),
            "transition_changed_count": sum(1 for row in state_rows if row.get("transition_changed")),
            "transition_from_counts": {},
            "avg_mfe_pct": average_or_none(values_for_state(rows, state, "mfe_pct")),
            "median_mfe_pct": median_or_none(values_for_state(rows, state, "mfe_pct")),
            "avg_mae_pct": average_or_none(values_for_state(rows, state, "mae_pct")),
            "median_mae_pct": median_or_none(values_for_state(rows, state, "mae_pct")),
            "hit_rate_plus_0_5_pct": hit_rate(bools_for_state(rows, state, "hit_plus_0_5_pct")),
            "hit_rate_plus_1_0_pct": hit_rate(bools_for_state(rows, state, "hit_plus_1_0_pct")),
            "hit_rate_minus_0_5_pct": hit_rate(bools_for_state(rows, state, "hit_minus_0_5_pct")),
            "hit_rate_minus_1_0_pct": hit_rate(bools_for_state(rows, state, "hit_minus_1_0_pct")),
        }
        transition_from_counts: dict[str, int] = {}
        for row in state_rows:
            prev = str(row.get("transition_from_state") or "NONE")
            transition_from_counts[prev] = transition_from_counts.get(prev, 0) + 1
        summary["transition_from_counts"] = dict(sorted(transition_from_counts.items()))
        for label, _delta in HORIZON_LABELS:
            field = f"return_pct_{label}"
            values = values_for_state(rows, state, field)
            summary[f"avg_return_pct_{label}"] = average_or_none(values)
            summary[f"median_return_pct_{label}"] = median_or_none(values)
        output[state] = summary
    return output


def build_transition_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        current = str(row["state"])
        previous = str(row.get("transition_from_state") or "NONE")
        key = f"{previous}->{current}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def build_summary(
    *,
    events: list[HeartbeatEvent],
    rows: list[dict[str, Any]],
    chain_root: Path,
    output_paths: OutputPaths,
    wrote_files: bool,
) -> dict[str, Any]:
    if not events:
        raise ValueError("No heartbeat events available for validation")
    venues = sorted({event.venue for event in events})
    intervals = sorted({event.interval_code for event in events})
    symbols = sorted({event.symbol for event in events})
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "scope": "research-only market-only read-only heartbeat outcome validation no paper trading no live trading no executor",
        "chain_root": str(chain_root),
        "symbol_scope": symbols,
        "venue_scope": venues,
        "interval_scope": intervals,
        "event_count": len(events),
        "complete_count": sum(1 for row in rows if row.get("sample_complete_24h")),
        "first_event_ts": fmt_ts(events[0].event_ts_utc),
        "latest_event_ts": fmt_ts(events[-1].event_ts_utc),
        "state_counts": {state: sum(1 for row in rows if row["state"] == state) for state in COHORT_STATES},
        "state_summary": build_state_summary(rows),
        "transition_counts": build_transition_counts(rows),
        "transition_changed_count": sum(1 for row in rows if row.get("transition_changed")),
        "cohort_interpretation": {
            "ENTRY_CANDIDATE": "candidate-quality cohort",
            "WAIT_RETEST": "setup-maturation cohort",
            "NO_CANDIDATE": "baseline/noise cohort",
            "BLOCKED": "safety/control cohort, not bearish signal",
        },
        "interpretation": [
            "Outcome measurement only; do not convert these results into strategy rules yet.",
            "ENTRY_CANDIDATE is a candidate-quality cohort, not a trade permission.",
            "WAIT_RETEST is a setup-maturation cohort, not an execution queue.",
            "NO_CANDIDATE is the baseline/noise cohort.",
            "BLOCKED is the safety/control cohort and must not be read as a bearish signal.",
            "This runner does not enable executor, paper trading, or live trading.",
        ],
        "limitations": [
            "Forward outcomes are measured from heartbeat timestamps against market candles only.",
            "The study does not model fills, fees, slippage, sizing, portfolio context, or account state.",
            "Missing future candles reduce completeness for some heartbeat rows.",
            "Results are cohort diagnostics only and are not runtime policy changes.",
        ],
        "output_paths": {
            "outcome_rows_jsonl": str(output_paths.outcome_rows_jsonl),
            "outcome_summary_json": str(output_paths.outcome_summary_json),
        },
        "db_writes": 0,
        "broker_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "executor": "none",
        "account_awareness": 0,
        "decision_gate_changes": 0,
        "execution_planner_changes": 0,
        "strategy_changes": 0,
        "wrote_files": wrote_files,
    }


def print_summary(summary: dict[str, Any], output_mode: str) -> None:
    if output_mode == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True))
        return
    print(f"report={summary['report']} version={summary['version']}")
    print(
        f"events={summary['event_count']} complete={summary['complete_count']} "
        f"symbols={','.join(summary['symbol_scope'])} "
        f"venue={','.join(summary['venue_scope'])} interval={','.join(summary['interval_scope'])}"
    )
    print(f"first_event_ts={summary['first_event_ts']} latest_event_ts={summary['latest_event_ts']}")
    for state in COHORT_STATES:
        state_summary = summary["state_summary"][state]
        print(
            f"state={state} count={state_summary['count']} complete={state_summary['complete_count']} "
            f"avg_return_pct_24h={state_summary['avg_return_pct_24h']} "
            f"median_return_pct_24h={state_summary['median_return_pct_24h']} "
            f"avg_mfe_pct={state_summary['avg_mfe_pct']} avg_mae_pct={state_summary['avg_mae_pct']}"
        )
    print("broker_calls=0 broker_writes=0 order_submission=0 executor=none account_awareness=0")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    chain_root = Path(args.chain_root)
    output_dir = Path(args.output_dir)
    output_paths = build_output_paths(output_dir)

    events = load_heartbeat_events(
        chain_root=chain_root,
        symbol_filter=args.symbol,
        venue_override=args.venue,
        interval_override=args.interval,
        max_events=args.max_events,
    )
    if not events:
        raise FileNotFoundError(f"No heartbeat events found under {chain_root}")

    venue = normalize_symbol(infer_global_value(events, "venue", DEFAULT_VENUE)).lower()
    interval_code = infer_global_value(events, "interval_code", DEFAULT_INTERVAL)
    symbols = sorted({event.symbol for event in events})

    conn = get_connection()
    try:
        asset_map = fetch_asset_map(conn, symbols)
        start_ts = min(event.event_ts_utc for event in events) - timedelta(hours=2)
        end_ts = max(event.event_ts_utc for event in events) + MAX_WINDOW + timedelta(hours=1)
        candles_by_symbol = fetch_candles(
            conn,
            asset_ids=asset_map,
            venue=venue,
            interval_code=interval_code,
            start_ts=start_ts,
            end_ts=end_ts,
        )
    finally:
        conn.close()

    aligned_events = [
        HeartbeatEvent(
            run_id=event.run_id,
            run_dir=event.run_dir,
            event_ts_utc=event.event_ts_utc,
            symbol=event.symbol,
            market=event.market,
            venue=venue,
            interval_code=interval_code,
            candidate_state=event.candidate_state,
            decision_state=event.decision_state,
            execution_plan_state=event.execution_plan_state,
            validation_state=event.validation_state,
            permission_state=event.permission_state,
            entry_state=event.entry_state,
            label_state_15m=event.label_state_15m,
            label_state_1h=event.label_state_1h,
            reference_price=event.reference_price,
            reference_price_source=event.reference_price_source,
            transition_from_state=event.transition_from_state,
            transition_changed=event.transition_changed,
        )
        for event in events
    ]
    rows = build_event_rows(aligned_events, candles_by_symbol)
    summary = build_summary(
        events=aligned_events,
        rows=rows,
        chain_root=chain_root,
        output_paths=output_paths,
        wrote_files=args.write_files,
    )

    if args.write_files:
        write_jsonl(output_paths.outcome_rows_jsonl, rows)
        write_json(output_paths.outcome_summary_json, summary)

    print_summary(summary, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
