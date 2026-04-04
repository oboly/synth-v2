"""
SYNTH v2
Module: synth_sleeves.equity
Purpose:
    Compute paper wallet equity from cash + market value of open lots.
Boundary:
    - Pure helpers
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from src.synth_sleeves.models import OpenLot


DECIMAL_ZERO = Decimal("0")


def compute_open_market_value_eur(open_lots: Iterable[OpenLot]) -> Decimal:
    total = DECIMAL_ZERO
    for lot in open_lots:
        total += lot.quantity_units * lot.latest_price_eur
    return total


def compute_wallet_equity_eur(*, paper_cash_eur: Decimal, open_lots: Iterable[OpenLot]) -> Decimal:
    return paper_cash_eur + compute_open_market_value_eur(open_lots)
