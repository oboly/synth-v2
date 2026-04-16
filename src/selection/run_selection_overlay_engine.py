"""
CLI entrypoint for Synth v2 Selection Overlay Engine v1.
"""

from __future__ import annotations

import argparse

from src.selection.selection_overlay_engine import run_selection_overlay_engine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run selection overlay engine and write selection_enriched_overlays."
    )
    parser.add_argument(
        "--venue",
        required=True,
        help="Venue code, for example: bitvavo",
    )
    parser.add_argument(
        "--asof-ts",
        dest="asof_ts",
        required=False,
        default=None,
        help='Optional UTC timestamp, for example: "2026-04-08 12:00:00"',
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_selection_overlay_engine(
        venue=args.venue,
        asof_ts_utc=args.asof_ts,
    )


if __name__ == "__main__":
    main()
