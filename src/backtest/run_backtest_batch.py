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


def _parse_symbols(symbols_raw: str) -> list[str]:
    out: list[str] = []
    for part in symbols_raw.split(","):
        symbol = part.strip().upper()
        if symbol:
            out.append(symbol)
    return out


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
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols, e.g. BTC,ETH,SOL")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--starting-cash", type=Decimal, default=Decimal("1000"))
    parser.add_argument("--fee-bps", type=Decimal, default=Decimal("25"))
    parser.add_argument("--strategy", default="pullback_reclaim_atr_v2")
    parser.add_argument("--atr-pct-min", type=float, default=1.0)
    parser.add_argument("--persist-scratch", default="1")
    parser.add_argument("--keep-flag", default="0")
    parser.add_argument("--notes-prefix", default="")
    parser.add_argument("--cleanup-scratch", default="1")
    parser.add_argument("--cleanup-days", type=int, default=3)
    args = parser.parse_args()

    symbols = _parse_symbols(args.symbols)
    if not symbols:
        print("No symbols parsed from --symbols.")
        return 1

    persist_scratch = _parse_bool_flag(args.persist_scratch)
    keep_flag = _parse_bool_flag(args.keep_flag)
    cleanup_scratch = _parse_bool_flag(args.cleanup_scratch)

    successes = 0
    failures = 0
    persisted_runs: list[tuple[str, int]] = []

    print("=== BACKTEST BATCH STARTED ===")
    print(
        f"symbols={','.join(symbols)} interval={args.interval} days={args.days} "
        f"strategy={args.strategy} atr_pct_min={args.atr_pct_min}"
    )
    print()

    for symbol in symbols:
        print(f"--- RUNNING {symbol} ---")

        try:
            metadata = fetch_asset_metadata(symbol)
            if not metadata:
                raise ValueError(f"Asset metadata not found for symbol={symbol}")

            asset_class = str(metadata.get("asset_class") or "MID_ALT").strip().upper()

            config = BacktestConfig(
                symbol=symbol,
                interval=args.interval,
                days=args.days,
                starting_cash=args.starting_cash,
                fee_bps=args.fee_bps,
            )

            strategy, overrides, resolved_strategy_name = _build_strategy(
                strategy_name=args.strategy,
                cli_atr_pct_min=args.atr_pct_min,
                symbol=symbol,
                asset_class=asset_class,
            )

            _df, result = run_backtest(config=config, strategy=strategy)
            print_backtest_report(config=config, result=result)
            print(f"resolved_strategy_name={resolved_strategy_name}")
            print(f"resolved_overrides={overrides}")

            if persist_scratch:
                note_parts = []
                if args.notes_prefix.strip():
                    note_parts.append(args.notes_prefix.strip())
                note_parts.append(f"{symbol} {args.days}d {args.interval} {strategy.name}")
                note_parts.append(f"asset_class={asset_class}")
                if args.strategy.strip().lower() in {"pullback_reclaim_atr_v1", "pullback_reclaim_atr_v2"}:
                    note_parts.append(f"atr_pct_min={getattr(strategy, 'atr_pct_min', args.atr_pct_min)}")

                bt_run_id = persist_backtest_run_scratch(
                    config=config,
                    strategy_name=strategy.name,
                    result=result,
                    notes=" | ".join(note_parts),
                    keep_flag=keep_flag,
                )
                persisted_runs.append((symbol, bt_run_id))
                print(f"persisted_bt_run_id={bt_run_id}")

            successes += 1

        except Exception as exc:
            failures += 1
            print(f"[FAILED] symbol={symbol} error={exc}")

        print()

    if cleanup_scratch:
        deleted_runs = cleanup_backtest_scratch(days_to_keep=args.cleanup_days)
        print(f"cleanup_deleted_runs={deleted_runs}")
    else:
        print("cleanup_deleted_runs=skipped")

    print()
    print("=== BACKTEST BATCH SUMMARY ===")
    print(f"successes={successes}")
    print(f"failures={failures}")

    if persisted_runs:
        print("persisted_runs=")
        for symbol, bt_run_id in persisted_runs:
            print(f"  {symbol}: bt_run_id={bt_run_id}")

    return 0 if successes > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
