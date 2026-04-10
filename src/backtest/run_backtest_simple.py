from __future__ import annotations

import argparse
from decimal import Decimal

from src.backtest.engine import fetch_asset_metadata, print_backtest_report, run_backtest
from src.backtest.param_repository import fetch_strategy_param_overrides
from src.backtest.repository import cleanup_backtest_scratch, persist_backtest_run_scratch
from src.backtest.strategies.pullback_reclaim_atr_strategy import PullbackReclaimAtrStrategy
from src.backtest.strategies.pullback_reclaim_strategy import PullbackReclaimStrategy
from src.backtest.types import BacktestConfig


def _parse_bool_flag(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_float(overrides: dict[str, str], key: str, fallback: float) -> float:
    raw = overrides.get(key)
    if raw is None:
        return float(fallback)
    return float(raw)


def _resolve_int(overrides: dict[str, str], key: str, fallback: int) -> int:
    raw = overrides.get(key)
    if raw is None:
        return int(fallback)
    return int(raw)


def _normalize_strategy_name(strategy_name: str) -> str:
    normalized = strategy_name.strip().lower()
    if normalized == "pullback_reclaim_atr_v1":
        return "pullback_reclaim_atr_v2"
    return normalized


def _build_strategy(
    strategy_name: str,
    cli_atr_pct_min: float,
    symbol: str,
    asset_class: str,
):
    normalized = _normalize_strategy_name(strategy_name)

    if normalized == "pullback_reclaim_v1":
        return PullbackReclaimStrategy(), {}, "pullback_reclaim_v1"

    if normalized == "pullback_reclaim_atr_v2":
        overrides = fetch_strategy_param_overrides(
            strategy_name="pullback_reclaim_atr_v2",
            symbol=symbol,
            asset_class=asset_class,
        )
        strategy = PullbackReclaimAtrStrategy(
            atr_pct_min=_resolve_float(overrides, "atr_pct_min", cli_atr_pct_min),
            asset_class=asset_class,
            ema200_slope_lookback=_resolve_int(overrides, "ema200_slope_lookback", 10),
        )
        return strategy, overrides, "pullback_reclaim_atr_v2"

    raise ValueError(f"Unknown strategy: {strategy_name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--starting-cash", type=Decimal, default=Decimal("1000"))
    parser.add_argument("--fee-bps", type=Decimal, default=Decimal("25"))
    parser.add_argument("--strategy", default="pullback_reclaim_atr_v2")
    parser.add_argument("--atr-pct-min", type=float, default=1.0)
    parser.add_argument("--persist-scratch", default="1")
    parser.add_argument("--keep-flag", default="0")
    parser.add_argument("--notes", default="")
    parser.add_argument("--cleanup-scratch", default="1")
    parser.add_argument("--cleanup-days", type=int, default=3)
    args = parser.parse_args()

    config = BacktestConfig(
        symbol=args.symbol,
        interval=args.interval,
        days=args.days,
        starting_cash=args.starting_cash,
        fee_bps=args.fee_bps,
    )

    metadata = fetch_asset_metadata(args.symbol)
    if not metadata:
        raise ValueError(f"Asset metadata not found for symbol={args.symbol}")

    asset_class = str(metadata.get("asset_class") or "MID_ALT").strip().upper()
    strategy, overrides, resolved_strategy_name = _build_strategy(
        strategy_name=args.strategy,
        cli_atr_pct_min=args.atr_pct_min,
        symbol=args.symbol,
        asset_class=asset_class,
    )

    _df, result = run_backtest(config=config, strategy=strategy)
    print_backtest_report(config=config, result=result)

    print()
    print(f"resolved_strategy_name={resolved_strategy_name}")

    if overrides:
        print(f"resolved_overrides={overrides}")
    else:
        print("resolved_overrides={}")

    if _parse_bool_flag(args.persist_scratch):
        bt_run_id = persist_backtest_run_scratch(
            config=config,
            strategy_name=strategy.name,
            result=result,
            notes=args.notes or None,
            keep_flag=_parse_bool_flag(args.keep_flag),
        )
        print()
        print(f"persisted_bt_run_id={bt_run_id}")

    if _parse_bool_flag(args.cleanup_scratch):
        deleted_runs = cleanup_backtest_scratch(days_to_keep=args.cleanup_days)
        print(f"cleanup_deleted_runs={deleted_runs}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
