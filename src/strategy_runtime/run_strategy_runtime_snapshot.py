from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from src.strategy_runtime.runtime_snapshot_writer import write_market_chain_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write a strategy runtime snapshot for a completed market chain."
    )

    parser.add_argument(
        "--interval",
        required=True,
        choices=["1h", "4h", "1d"],
        help="Market interval code.",
    )

    parser.add_argument(
        "--chain-name",
        required=True,
        help="Chain script name, e.g. run_chain_1h.",
    )

    parser.add_argument(
        "--venue",
        default="bitvavo",
        help="Venue code. Default: bitvavo.",
    )

    parser.add_argument(
        "--runtime-scope",
        default="market_chain",
        help="Runtime scope label. Default: market_chain.",
    )

    parser.add_argument(
        "--notes",
        default=None,
        help="Optional snapshot notes.",
    )

    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()

    try:
        snapshot_id = write_market_chain_snapshot(
            interval_code=args.interval,
            chain_name=args.chain_name,
            runtime_scope=args.runtime_scope,
            venue=args.venue,
            notes=args.notes,
        )
        print(
            "[DONE] strategy_runtime_snapshot "
            f"id={snapshot_id} interval={args.interval} chain={args.chain_name}"
        )
        return 0

    except Exception as exc:
        print(f"[ERROR] strategy_runtime_snapshot failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
