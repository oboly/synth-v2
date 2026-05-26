from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.research.live_like_vertical_slice_contract_v1 import (
    NEAR_INTRADAY_RETEST_RECLAIM_V1,
    StrategyCandidate,
    StrategyInstanceConfig,
)


REPORT_NAME = "intraday_retest_reclaim_candidate_v1"
REPORT_VERSION = "1.0"
DEFAULT_BASE_URL = "https://api.bitvavo.com/v2"
DEFAULT_OUTPUT_ROOT = "data/research/intraday_retest_reclaim_candidate_v1"
DEFAULT_RUN_DIR_PREFIX = "run_"

STRATEGY_CANDIDATE_JSON = "strategy_candidate_v1.json"
STRATEGY_CANDIDATE_JSONL = "strategy_candidate_v1.jsonl"
MANIFEST_JSON = "manifest_v1.json"

WATCHER_STATES = {
    "IMPULSE_CONTINUATION",
    "WICK_REJECTION_PULLBACK",
    "SHALLOW_PULLBACK_STRONG",
    "NORMAL_RETEST_ZONE",
    "DEEP_RETEST_ZONE",
    "NO_CLEAN_ENTRY",
}
ENTRY_RETEST_STATES = {"SHALLOW_PULLBACK_STRONG", "NORMAL_RETEST_ZONE", "DEEP_RETEST_ZONE"}


@dataclass(frozen=True)
class Candle:
    open_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass(frozen=True)
class TimeframeContext:
    interval: str
    state: str
    recent_low: Decimal
    recent_high: Decimal
    shallow_level: Decimal
    normal_level: Decimal
    deep_level: Decimal
    last_candle_open_ts_utc: datetime
    range_size: Decimal


@dataclass(frozen=True)
class OutputPaths:
    strategy_candidate_json: Path
    strategy_candidate_jsonl: Path
    manifest_json: Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Emit one market-only StrategyCandidate preview row for "
            "INTRADAY_RETEST_RECLAIM_V1 using public Bitvavo candles only."
        )
    )
    parser.add_argument("--market", default="NEAR-EUR")
    parser.add_argument("--symbol", default="NEAR")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--quote", default="EUR")
    parser.add_argument("--strategy-instance-id", default="near_intraday_retest_reclaim_v1")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def fmt_ts(value: datetime) -> str:
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_run_id(now_utc: datetime) -> str:
    return now_utc.strftime("%Y%m%dT%H%M%SZ")


def dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def fmt_decimal(value: Decimal | float, places: str = "0.000000") -> str:
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    return str(decimal_value.quantize(Decimal(places)))


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return fmt_ts(value)
    if isinstance(value, Decimal):
        return str(value)
    return value


def resolve_output_dir(*, output_root: str, run_id: str) -> Path:
    return Path(output_root) / f"{DEFAULT_RUN_DIR_PREFIX}{run_id}"


def output_paths(output_dir: Path) -> OutputPaths:
    return OutputPaths(
        strategy_candidate_json=output_dir / STRATEGY_CANDIDATE_JSON,
        strategy_candidate_jsonl=output_dir / STRATEGY_CANDIDATE_JSONL,
        manifest_json=output_dir / MANIFEST_JSON,
    )


def http_json(url: str) -> Any:
    request = Request(url, method="GET", headers={"User-Agent": REPORT_NAME})
    with urlopen(request, timeout=20) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def fetch_price(*, base_url: str, market: str) -> Decimal:
    query = urlencode({"market": market})
    payload = http_json(f"{base_url}/ticker/price?{query}")
    if isinstance(payload, list):
        if not payload:
            raise RuntimeError(f"No ticker price returned for {market}")
        payload = payload[0]
    return dec(payload["price"])


def fetch_candles(*, base_url: str, market: str, interval: str, limit: int) -> list[Candle]:
    query = urlencode({"interval": interval, "limit": limit})
    payload = http_json(f"{base_url}/{market}/candles?{query}")
    candles: list[Candle] = []
    for row in reversed(payload):
        open_ts_ms, open_px, high_px, low_px, close_px, _volume = row
        candles.append(
            Candle(
                open_ts_utc=datetime.fromtimestamp(int(open_ts_ms) / 1000, tz=UTC),
                open_price=dec(open_px),
                high_price=dec(high_px),
                low_price=dec(low_px),
                close_price=dec(close_px),
            )
        )
    if not candles:
        raise RuntimeError(f"No {interval} candles returned for {market}")
    return candles


def classify_timeframe(interval: str, candles: list[Candle], current_price: Decimal) -> TimeframeContext:
    if len(candles) < 8:
        raise RuntimeError(f"Not enough {interval} candles to classify state")

    window = candles[-24:] if interval == "1h" else candles[-16:]
    recent_low = min(candle.low_price for candle in window)
    recent_high = max(candle.high_price for candle in window)
    if recent_high <= recent_low:
        raise RuntimeError(f"Invalid range for {interval}: low={recent_low} high={recent_high}")

    range_size = recent_high - recent_low
    shallow_level = recent_high - (range_size * Decimal("0.382"))
    normal_level = recent_high - (range_size * Decimal("0.500"))
    deep_level = recent_high - (range_size * Decimal("0.618"))

    last_close = window[-1].close_price
    prev_close = window[-2].close_price
    last_high = window[-1].high_price
    last_low = window[-1].low_price

    if current_price >= recent_high * Decimal("0.995") and last_close >= prev_close:
        state = "IMPULSE_CONTINUATION"
    elif last_high >= shallow_level and current_price > shallow_level and current_price < last_high:
        state = "WICK_REJECTION_PULLBACK"
    elif current_price >= shallow_level:
        state = "SHALLOW_PULLBACK_STRONG"
    elif current_price >= normal_level:
        state = "NORMAL_RETEST_ZONE"
    elif current_price >= deep_level and current_price >= recent_low:
        state = "DEEP_RETEST_ZONE"
    else:
        state = "NO_CLEAN_ENTRY"

    if current_price < recent_low or last_low < recent_low:
        state = "NO_CLEAN_ENTRY"

    return TimeframeContext(
        interval=interval,
        state=state,
        recent_low=recent_low,
        recent_high=recent_high,
        shallow_level=shallow_level,
        normal_level=normal_level,
        deep_level=deep_level,
        last_candle_open_ts_utc=window[-1].open_ts_utc,
        range_size=range_size,
    )


def candidate_state_from_context(context_15m: TimeframeContext, context_1h: TimeframeContext) -> str:
    if context_15m.state in ENTRY_RETEST_STATES:
        return {
            "SHALLOW_PULLBACK_STRONG": "SHALLOW_RETEST_ACTIVE",
            "NORMAL_RETEST_ZONE": "NORMAL_RETEST_ACTIVE",
            "DEEP_RETEST_ZONE": "DEEP_RETEST_ACTIVE",
        }[context_15m.state]
    if context_15m.state == "WICK_REJECTION_PULLBACK":
        return "WAIT_RETEST"
    if context_15m.state == "IMPULSE_CONTINUATION":
        return "IMPULSE_ACTIVE" if context_1h.state == "IMPULSE_CONTINUATION" else "WAIT_RETEST"
    return "NO_CANDIDATE"


def freshness_state(*, now_utc: datetime, context_15m: TimeframeContext, max_candidate_age_seconds: int) -> tuple[str, int]:
    age_seconds = max(0, int((now_utc - context_15m.last_candle_open_ts_utc).total_seconds()))
    return ("FRESH" if age_seconds <= max_candidate_age_seconds else "STALE", age_seconds)


def confidence_score(context_15m: TimeframeContext, context_1h: TimeframeContext) -> float:
    score = Decimal("0.20")
    if context_15m.state == "SHALLOW_PULLBACK_STRONG":
        score += Decimal("0.36")
    elif context_15m.state == "NORMAL_RETEST_ZONE":
        score += Decimal("0.32")
    elif context_15m.state == "DEEP_RETEST_ZONE":
        score += Decimal("0.24")
    elif context_15m.state == "IMPULSE_CONTINUATION":
        score += Decimal("0.18")
    elif context_15m.state == "WICK_REJECTION_PULLBACK":
        score += Decimal("0.12")

    if context_1h.state == "IMPULSE_CONTINUATION":
        score += Decimal("0.22")
    elif context_1h.state in {"SHALLOW_PULLBACK_STRONG", "NORMAL_RETEST_ZONE"}:
        score += Decimal("0.16")
    elif context_1h.state == "DEEP_RETEST_ZONE":
        score += Decimal("0.10")
    elif context_1h.state == "WICK_REJECTION_PULLBACK":
        score += Decimal("0.08")
    else:
        score -= Decimal("0.12")

    if context_15m.state == context_1h.state and context_15m.state in WATCHER_STATES:
        score += Decimal("0.08")

    return max(0.0, min(1.0, float(score)))


def risk_severity_score(context_15m: TimeframeContext, context_1h: TimeframeContext, current_price: Decimal) -> float:
    score = Decimal("0.12")

    if context_15m.state == "DEEP_RETEST_ZONE":
        score += Decimal("0.20")
    elif context_15m.state == "NORMAL_RETEST_ZONE":
        score += Decimal("0.12")
    elif context_15m.state == "SHALLOW_PULLBACK_STRONG":
        score += Decimal("0.08")
    elif context_15m.state == "WICK_REJECTION_PULLBACK":
        score += Decimal("0.15")
    elif context_15m.state == "NO_CLEAN_ENTRY":
        score += Decimal("0.42")

    if context_1h.state == "NO_CLEAN_ENTRY":
        score += Decimal("0.28")
    elif context_1h.state == "DEEP_RETEST_ZONE":
        score += Decimal("0.10")
    elif context_1h.state == "WICK_REJECTION_PULLBACK":
        score += Decimal("0.06")

    if current_price <= context_15m.deep_level:
        score += Decimal("0.08")

    return max(0.0, min(1.0, float(score)))


def direction_pressure(context_15m: TimeframeContext, context_1h: TimeframeContext) -> float:
    if context_1h.state == "IMPULSE_CONTINUATION":
        return 0.80
    if context_15m.state in ENTRY_RETEST_STATES:
        return 0.65
    if context_15m.state == "WICK_REJECTION_PULLBACK":
        return 0.45
    return 0.20


def exposure_delta_pressure(candidate_state: str, confidence: float, risk: float) -> float:
    if candidate_state == "ENTRY_CANDIDATE":
        return round(max(0.0, min(1.0, confidence - (risk * 0.50))), 6)
    if candidate_state in {"SHALLOW_RETEST_ACTIVE", "NORMAL_RETEST_ACTIVE", "DEEP_RETEST_ACTIVE"}:
        return round(max(0.0, min(1.0, confidence - (risk * 0.65))), 6)
    if candidate_state in {"WAIT_RETEST", "IMPULSE_ACTIVE"}:
        return round(max(0.0, min(1.0, confidence - (risk * 0.80))), 6)
    return 0.0


def entry_quality_score(context_15m: TimeframeContext, current_price: Decimal) -> float:
    if context_15m.range_size == 0:
        return 0.0
    normalized = float((current_price - context_15m.recent_low) / context_15m.range_size)
    return round(max(0.0, min(1.0, 1.0 - normalized)), 6)


def resolve_instance_config(args: argparse.Namespace) -> StrategyInstanceConfig:
    if (
        args.strategy_instance_id == NEAR_INTRADAY_RETEST_RECLAIM_V1.strategy_instance_id
        and args.symbol.upper() == NEAR_INTRADAY_RETEST_RECLAIM_V1.symbol
        and args.venue == NEAR_INTRADAY_RETEST_RECLAIM_V1.venue
        and args.quote.upper() == NEAR_INTRADAY_RETEST_RECLAIM_V1.quote
    ):
        return NEAR_INTRADAY_RETEST_RECLAIM_V1

    return StrategyInstanceConfig(
        strategy_instance_id=str(args.strategy_instance_id),
        strategy_family=NEAR_INTRADAY_RETEST_RECLAIM_V1.strategy_family,
        symbol=str(args.symbol).upper(),
        venue=str(args.venue),
        quote=str(args.quote).upper(),
        enabled=True,
        mode="shadow",
        capital_bucket=NEAR_INTRADAY_RETEST_RECLAIM_V1.capital_bucket,
        primary_tf=NEAR_INTRADAY_RETEST_RECLAIM_V1.primary_tf,
        entry_tf=NEAR_INTRADAY_RETEST_RECLAIM_V1.entry_tf,
        context_tf=NEAR_INTRADAY_RETEST_RECLAIM_V1.context_tf,
        max_candidate_age_seconds=NEAR_INTRADAY_RETEST_RECLAIM_V1.max_candidate_age_seconds,
        min_confidence_score=NEAR_INTRADAY_RETEST_RECLAIM_V1.min_confidence_score,
        max_risk_severity_score=NEAR_INTRADAY_RETEST_RECLAIM_V1.max_risk_severity_score,
        execution_profile=NEAR_INTRADAY_RETEST_RECLAIM_V1.execution_profile,
    )


def build_candidate(
    *,
    instance_config: StrategyInstanceConfig,
    market: str,
    current_price: Decimal,
    context_15m: TimeframeContext,
    context_1h: TimeframeContext,
    now_utc: datetime,
) -> StrategyCandidate:
    base_candidate_state = candidate_state_from_context(context_15m, context_1h)
    fresh_state, age_seconds = freshness_state(
        now_utc=now_utc,
        context_15m=context_15m,
        max_candidate_age_seconds=instance_config.max_candidate_age_seconds,
    )
    confidence = confidence_score(context_15m, context_1h)
    risk = risk_severity_score(context_15m, context_1h, current_price)

    if fresh_state != "FRESH":
        candidate_state = "STALE"
        entry_state = "ENTRY_NOT_READY_STALE"
    elif context_1h.state == "NO_CLEAN_ENTRY":
        candidate_state = "INVALIDATED"
        entry_state = "ENTRY_BLOCKED_PRIMARY_INVALIDATION"
    elif (
        context_15m.state in ENTRY_RETEST_STATES
        and risk <= instance_config.max_risk_severity_score
        and confidence >= instance_config.min_confidence_score
    ):
        candidate_state = "ENTRY_CANDIDATE"
        entry_state = "ENTRY_RETEST_READY"
    else:
        candidate_state = base_candidate_state
        if context_15m.state in ENTRY_RETEST_STATES:
            entry_state = "ENTRY_RETEST_REVIEW"
        elif context_15m.state == "WICK_REJECTION_PULLBACK":
            entry_state = "ENTRY_WAIT_PULLBACK"
        elif context_15m.state == "IMPULSE_CONTINUATION":
            entry_state = "ENTRY_WAIT_RETEST"
        else:
            entry_state = "ENTRY_NOT_READY"

    candidate_id = (
        f"{instance_config.strategy_instance_id}__"
        f"{now_utc.strftime('%Y%m%dT%H%M%SZ')}__{instance_config.entry_tf}"
    )
    direction = direction_pressure(context_15m, context_1h)
    exposure = exposure_delta_pressure(candidate_state, confidence, risk)
    quality = entry_quality_score(context_15m, current_price)

    source_context = {
        "market": market,
        "price_at_emit": str(current_price),
        "market_state_15m": context_15m.state,
        "market_state_1h": context_1h.state,
        "thresholds": {
            "min_confidence_score": instance_config.min_confidence_score,
            "max_risk_severity_score": instance_config.max_risk_severity_score,
            "max_candidate_age_seconds": instance_config.max_candidate_age_seconds,
        },
        "context_15m": {
            "recent_low": str(context_15m.recent_low),
            "recent_high": str(context_15m.recent_high),
            "shallow_level": str(context_15m.shallow_level),
            "normal_level": str(context_15m.normal_level),
            "deep_level": str(context_15m.deep_level),
            "last_candle_open_ts_utc": fmt_ts(context_15m.last_candle_open_ts_utc),
        },
        "context_1h": {
            "recent_low": str(context_1h.recent_low),
            "recent_high": str(context_1h.recent_high),
            "shallow_level": str(context_1h.shallow_level),
            "normal_level": str(context_1h.normal_level),
            "deep_level": str(context_1h.deep_level),
            "last_candle_open_ts_utc": fmt_ts(context_1h.last_candle_open_ts_utc),
        },
        "freshness_age_seconds": age_seconds,
    }
    safety_markers = {
        "broker_private_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "decision_gate_changes": 0,
        "execution_planner_changes": 0,
        "executor": "none",
        "account_tables_used": False,
        "mode": instance_config.mode,
    }

    return StrategyCandidate(
        strategy_candidate_id=candidate_id,
        strategy_instance_id=instance_config.strategy_instance_id,
        strategy_family=instance_config.strategy_family,
        symbol=instance_config.symbol,
        venue=instance_config.venue,
        quote=instance_config.quote,
        horizon_bucket="intraday",
        primary_timeframe=instance_config.primary_tf,
        entry_timeframe=instance_config.entry_tf,
        candidate_state=candidate_state,
        entry_state=entry_state,
        direction_pressure=round(direction, 6),
        exposure_delta_pressure=round(exposure, 6),
        entry_quality_score=quality,
        risk_severity_score=round(risk, 6),
        confidence_score=round(confidence, 6),
        freshness_state=fresh_state,
        created_at_utc=fmt_ts(now_utc),
        source_context=source_context,
        safety_markers=safety_markers,
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(row, sort_keys=True, ensure_ascii=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def build_manifest(
    *,
    args: argparse.Namespace,
    run_id: str,
    output_dir: Path,
    instance_config: StrategyInstanceConfig,
    candidate: StrategyCandidate,
    output_paths_map: OutputPaths,
    run_started_at: datetime,
    run_finished_at: datetime,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "run_started_at_utc": fmt_ts(run_started_at),
        "run_finished_at_utc": fmt_ts(run_finished_at),
        "run_duration_sec": round((run_finished_at - run_started_at).total_seconds(), 6),
        "market": str(args.market).upper(),
        "symbol": instance_config.symbol,
        "venue": instance_config.venue,
        "quote": instance_config.quote,
        "strategy_instance_id": instance_config.strategy_instance_id,
        "strategy_family": instance_config.strategy_family,
        "mode": instance_config.mode,
        "wrote_files": bool(args.write_files),
        "candidate_state": candidate.candidate_state,
        "entry_state": candidate.entry_state,
        "confidence_score": candidate.confidence_score,
        "risk_severity_score": candidate.risk_severity_score,
        "output_paths": {
            "strategy_candidate_json": str(output_paths_map.strategy_candidate_json),
            "strategy_candidate_jsonl": str(output_paths_map.strategy_candidate_jsonl),
            "manifest_json": str(output_paths_map.manifest_json),
        },
        "db_writes": 0,
        "broker_private_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "decision_gate_changes": 0,
        "execution_planner_changes": 0,
        "executor": "none",
        "account_tables_used": False,
        "notes": [
            "Market-only candidate generation only.",
            "This output does not create permission or execution intent.",
            "Downstream path remains StrategyCandidate -> DecisionPreview -> ExecutionPlanPreview -> ShadowEvent.",
        ],
    }


def print_summary(
    *,
    args: argparse.Namespace,
    candidate: StrategyCandidate,
    output_dir: Path | None,
) -> None:
    payload = {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "market": str(args.market).upper(),
        "symbol": candidate.symbol,
        "candidate_state": candidate.candidate_state,
        "entry_state": candidate.entry_state,
        "confidence_score": candidate.confidence_score,
        "risk_severity_score": candidate.risk_severity_score,
        "broker_writes": 0,
        "order_submission": 0,
        "executor": "none",
    }
    if output_dir is not None:
        payload["output_dir"] = str(output_dir)
    if args.output == "json":
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))
        return

    print(f"report={payload['report']} version={payload['version']}")
    print(f"market={payload['market']} symbol={payload['symbol']}")
    print(
        "candidate_state="
        f"{payload['candidate_state']} entry_state={payload['entry_state']}"
    )
    print(
        "confidence_score="
        f"{payload['confidence_score']:.6f} risk_severity_score={payload['risk_severity_score']:.6f}"
    )
    if output_dir is not None:
        print(f"output_dir={output_dir}")
    print("broker_writes=0 order_submission=0 executor=none")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_started_at = utc_now()
    run_id = utc_run_id(run_started_at)
    output_dir = resolve_output_dir(output_root=str(args.output_root), run_id=run_id)
    paths = output_paths(output_dir)

    market = str(args.market).upper()
    instance_config = resolve_instance_config(args)
    base_url = str(args.base_url).rstrip("/")

    current_price = fetch_price(base_url=base_url, market=market)
    candles_15m = fetch_candles(base_url=base_url, market=market, interval="15m", limit=64)
    candles_1h = fetch_candles(base_url=base_url, market=market, interval="1h", limit=64)
    context_15m = classify_timeframe("15m", candles_15m, current_price)
    context_1h = classify_timeframe("1h", candles_1h, current_price)
    candidate = build_candidate(
        instance_config=instance_config,
        market=market,
        current_price=current_price,
        context_15m=context_15m,
        context_1h=context_1h,
        now_utc=run_started_at,
    )

    run_finished_at = utc_now()
    manifest = build_manifest(
        args=args,
        run_id=run_id,
        output_dir=output_dir,
        instance_config=instance_config,
        candidate=candidate,
        output_paths_map=paths,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
    )

    if args.write_files:
        candidate_payload = asdict(candidate)
        write_json(paths.strategy_candidate_json, candidate_payload)
        write_jsonl(paths.strategy_candidate_jsonl, candidate_payload)
        write_json(paths.manifest_json, manifest)

    print_summary(args=args, candidate=candidate, output_dir=output_dir if args.write_files else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
