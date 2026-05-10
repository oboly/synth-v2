from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from src.strategy_runtime.runtime_snapshot_writer import (
    default_market_chain_components,
    write_strategy_runtime_snapshot,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write a strategy runtime snapshot for the market-only chain."
    )

    parser.add_argument(
        "--venue",
        default="bitvavo",
        help="Venue code. Default: bitvavo.",
    )

    parser.add_argument(
        "--interval",
        required=True,
        help="Interval code, e.g. 1h, 4h, 1d.",
    )

    parser.add_argument(
        "--chain-name",
        required=True,
        help="Chain script name, e.g. run_chain_1h.",
    )

    parser.add_argument(
        "--notes",
        default=None,
        help="Optional snapshot notes.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print component list without writing to DB.",
    )

    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()

    interval_code = str(args.interval).strip().lower()
    venue = str(args.venue).strip().lower()
    chain_name = str(args.chain_name).strip()

    if args.dry_run:
        components = default_market_chain_components(
            venue=venue,
            interval_code=interval_code,
            chain_name=chain_name,
        )
        for component in components:
            print(
                ",".join(
                    [
                        component.component_layer,
                        component.component_name,
                        component.component_version,
                        component.component_mode or "",
                        str(int(component.enabled)),
                    ]
                )
            )
        print(f"[DONE] dry-run components={len(components)}")
        return 0

    try:
        snapshot_id = write_strategy_runtime_snapshot(
            venue=venue,
            interval_code=interval_code,
            chain_name=chain_name,
            notes=args.notes,
            live_trading_enabled=False,
            decision_gate_enabled=False,
            execution_enabled=False,
        )
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(
        "[DONE] strategy_runtime_snapshot "
        f"id={snapshot_id} interval={interval_code} chain={chain_name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
