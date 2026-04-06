from __future__ import annotations

from src.market_structure.context_builder import build_strategy_context_from_volume_and_zones
from src.market_structure.fib_engine import build_fib_observations
from src.market_structure.repository import MarketStructureRepository
from src.market_structure.zone_engine import build_zone_observations


def main() -> int:
    repo = MarketStructureRepository()

    zone_rows = build_zone_observations(intervals=["4h", "1d"])
    fib_rows = build_fib_observations(intervals=["4h", "1d"])
    ctx_rows = build_strategy_context_from_volume_and_zones()

    summary = {
        "zones_written": repo.upsert_zone_observations(zone_rows),
        "fibs_written": repo.upsert_fib_observations(fib_rows),
        "contexts_written": repo.upsert_strategy_signal_context(ctx_rows),
    }

    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
