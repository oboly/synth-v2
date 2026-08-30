from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class WalletBalanceRow:
    currency_code: str
    available_amount: Decimal
    reserved_amount: Decimal
    total_amount: Decimal


@dataclass(frozen=True)
class WalletOpenOrderRow:
    market: str
    side: str
    order_type: str
    broker_order_id: str
    client_order_id: str | None
    limit_price: Decimal | None
    quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal
    broker_status: str


@dataclass(frozen=True)
class AccountAssetUpsertResult:
    market: str
    action: str  # INSERTED | EXISTING


@dataclass(frozen=True)
class WalletRefreshResult:
    profile: str
    account_code: str
    trading_account_id: int
    venue: str
    snapshot_ts_utc: datetime
    balance_count: int
    order_count: int
    account_asset_inserted: int
    account_asset_existing: int


@dataclass(frozen=True)
class ExactAccountStateRefreshResult:
    trading_account_id: int
    account_code: str
    venue: str
    account_mode: str
    snapshot_ts_utc: datetime
    balance_count: int
    order_count: int
    position_count: int | None
    account_asset_inserted: int
    account_asset_existing: int


@dataclass(frozen=True)
class MarketSyncRow:
    market: str
    base: str
    quote: str
    status: str
    is_tradeable: bool
    price_precision: int | None
    qty_precision: int | None


@dataclass(frozen=True)
class MarketSyncResult:
    venue: str
    total_markets: int
    asset_inserted: int
    asset_existing: int
    venue_market_inserted: int
    venue_market_updated: int
    unsupported_count: int
