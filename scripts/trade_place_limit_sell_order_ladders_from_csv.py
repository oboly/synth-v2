from decimal import Decimal
from src.execution.limit_sell_ladder_v1 import (
    LimitSellLadderLevel,
    build_limit_sell_ladder_orders,
    preview_limit_sell_ladder_orders,
)

levels = [
    LimitSellLadderLevel(Decimal("0.3260"), Decimal("0.35"), Decimal("25"), "FFGRV TP1"),
    LimitSellLadderLevel(Decimal("0.3820"), Decimal("0.35"), Decimal("25"), "FFGRV TP2"),
    LimitSellLadderLevel(Decimal("0.4600"), Decimal("0.50"), Decimal("50"), "FFGRV TP3"),
]

orders = build_limit_sell_ladder_orders(
    market="WLD-EUR",
    available_qty=Decimal("123.456"),
    levels=levels,
)

print(preview_limit_sell_ladder_orders(orders))

# Direct broker placement is disabled; live execution prerequisites are not
# implemented.
