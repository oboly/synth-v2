from __future__ import annotations

from decimal import Decimal

from src.execution_planner.planner import build_execution_plan
from src.market_structure.repository import MarketStructureRepository


def main() -> int:
    repo = MarketStructureRepository()

    plan = build_execution_plan(
        asset_id=1,
        sleeve_code="CORE",
        desired_action="ENTER_LONG",
        target_fraction=Decimal("0.10"),
        reference_price_eur=Decimal("100.0"),
    )

    summary = {
        "plans_written": repo.insert_execution_plans([plan]),
    }
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
