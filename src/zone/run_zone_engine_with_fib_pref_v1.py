from __future__ import annotations

import argparse
from dataclasses import fields, is_dataclass
from decimal import Decimal
from typing import Any

from src.zone.engine_v1 import build_zone_engine_result
from src.zone.fib_preference_overlay_v1 import (
    DEFAULT_DISTANCE_CAP_BPS,
    DEFAULT_MIN_EXECUTION_SCORE,
    DEFAULT_PRIMARY_BONUS,
    DEFAULT_SECONDARY_BONUS,
    apply_fib_preference_to_execution_context,
    fetch_latest_fib_preference_profile,
    infer_regime_candidates,
)
from src.zone.repository import ZoneRepository


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run zone engine with fib preference execution overlay.")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--sleeve-code", required=True)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--limit-assets", type=int, default=40)
    parser.add_argument("--lookback-candles", type=int, default=300)
    parser.add_argument("--swing-window", type=int, default=2)
    parser.add_argument("--sr-tolerance-bps", default="60")
    parser.add_argument("--fib-primary-bonus", default=str(DEFAULT_PRIMARY_BONUS))
    parser.add_argument("--fib-secondary-bonus", default=str(DEFAULT_SECONDARY_BONUS))
    parser.add_argument("--fib-distance-cap-bps", default=str(DEFAULT_DISTANCE_CAP_BPS))
    parser.add_argument("--fib-min-execution-score", default=str(DEFAULT_MIN_EXECUTION_SCORE))
    parser.add_argument("--asof-ts", default=None)
    parser.add_argument("--write-db", action="store_true")
    return parser.parse_args()


def _print_header() -> None:
    headers = [
        "asset_id",
        "symbol",
        "interval_code",
        "asof_ts_utc",
        "base_conf",
        "new_conf",
        "fib_regime",
        "exec_primary",
        "exec_secondary",
        "fib_bonus",
        "fib_overlay_in_json",
        "entry_zone_low",
        "entry_zone_high",
        "zones_written",
    ]
    print(" | ".join(headers))
    print("-+-".join("-" * len(h) for h in headers))


def _print_row(row: list[str]) -> None:
    print(" | ".join(row))


def _extract_zone_inputs(result: Any) -> list[Any]:
    candidate_names = [
        "zone_observations",
        "zones",
        "zone_inputs",
        "zone_rows",
        "zone_results",
        "zone_observation",
        "zone",
    ]

    for name in candidate_names:
        if not hasattr(result, name):
            continue
        value = getattr(result, name)
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        return [value]

    if is_dataclass(result):
        for f in fields(result):
            name = f.name.lower()
            if "zone" not in name:
                continue
            value = getattr(result, f.name)
            if value is None:
                continue
            if isinstance(value, list):
                return value
            if isinstance(value, tuple):
                return list(value)
            return [value]

    return []


def main() -> int:
    args = parse_args()
    repo = ZoneRepository()

    assets = repo.fetch_assets(asset_id=args.asset_id, limit=args.limit_assets)
    sr_tolerance_bps = _to_decimal(args.sr_tolerance_bps)
    fib_primary_bonus = _to_decimal(args.fib_primary_bonus)
    fib_secondary_bonus = _to_decimal(args.fib_secondary_bonus)
    fib_distance_cap_bps = _to_decimal(args.fib_distance_cap_bps)
    fib_min_execution_score = _to_decimal(args.fib_min_execution_score)

    _print_header()

    processed_assets = 0
    results_count = 0

    for asset in assets:
        candles = repo.fetch_recent_candles(
            asset_id=int(asset["asset_id"]),
            symbol=str(asset["symbol"]),
            venue=args.venue,
            interval_code=args.interval,
            limit=args.lookback_candles,
            asof_ts_utc=args.asof_ts,
        )
        if len(candles) < 20:
            continue

        result = build_zone_engine_result(
            repo=repo,
            candles=candles,
            swing_window=args.swing_window,
            sr_tolerance_bps=sr_tolerance_bps,
            sleeve_code=args.sleeve_code,
        )
        processed_assets += 1

        if result is None:
            continue

        base_context = result.execution_context
        regime_candidates = infer_regime_candidates(getattr(result.fib_observation, "leg_direction", None))
        profile = fetch_latest_fib_preference_profile(
            asset_id=result.fib_observation.asset_id,
            venue=args.venue,
            interval_code=args.interval,
            regime_candidates=regime_candidates,
            min_execution_score=fib_min_execution_score,
        )

        new_context, overlay = apply_fib_preference_to_execution_context(
            execution_context=base_context,
            fib_observation=result.fib_observation,
            profile=profile,
            primary_bonus=fib_primary_bonus,
            secondary_bonus=fib_secondary_bonus,
            distance_cap_bps=fib_distance_cap_bps,
        )

        zone_inputs = _extract_zone_inputs(result)
        zones_written = 0

        source_ref_json = getattr(new_context, "source_ref_json", None) or ""
        fib_overlay_in_json = "fib_overlay" in source_ref_json

        if args.write_db:
            repo.upsert_fib_observation(result.fib_observation)
            for zone in zone_inputs:
                repo.upsert_zone_observation(zone)
                zones_written += 1
            repo.upsert_execution_zone_context(new_context)

        results_count += 1
        _print_row(
            [
                str(new_context.asset_id),
                str(new_context.symbol),
                str(new_context.interval_code),
                str(new_context.asof_ts_utc),
                str(base_context.zone_confidence_score),
                str(new_context.zone_confidence_score),
                "" if overlay is None else str(overlay.regime_label),
                "" if overlay is None or overlay.execution_primary_fib is None else str(overlay.execution_primary_fib),
                "" if overlay is None or overlay.execution_secondary_fib is None else str(overlay.execution_secondary_fib),
                "" if overlay is None else str(overlay.total_bonus),
                str(int(fib_overlay_in_json)),
                "" if new_context.expected_entry_zone_low is None else str(new_context.expected_entry_zone_low),
                "" if new_context.expected_entry_zone_high is None else str(new_context.expected_entry_zone_high),
                str(zones_written),
            ]
        )

    print(
        f"processed_assets={processed_assets} "
        f"results={results_count} "
        f"write_db={args.write_db}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
