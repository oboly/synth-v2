from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from src.market_data.market_price_snapshot_v1 import MarketPriceSnapshot


DEFAULT_CURRENT_PRICE_FRESH_AFTER = timedelta(minutes=15)


@dataclass(frozen=True)
class CurrentPriceDisplay:
    status: str
    safe_price: Decimal | None
    observed_ts_utc: datetime | None
    age_min: Decimal | None


def _naive_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _age_minutes(
    observed_ts_utc: datetime | None,
    *,
    now_utc: datetime,
) -> Decimal | None:
    if observed_ts_utc is None:
        return None
    age_seconds = Decimal(str((_naive_utc(now_utc) - _naive_utc(observed_ts_utc)).total_seconds()))
    return age_seconds / Decimal("60")


def _canonical_market(snapshot: MarketPriceSnapshot) -> str:
    return f"{snapshot.symbol.strip().upper()}-{snapshot.quote_currency.strip().upper()}"


def classify_current_price_snapshot(
    snapshot: MarketPriceSnapshot | None,
    *,
    now_utc: datetime,
    fresh_after: timedelta = DEFAULT_CURRENT_PRICE_FRESH_AFTER,
    expected_market: str | None = None,
) -> CurrentPriceDisplay:
    if snapshot is None:
        return CurrentPriceDisplay(
            status="MISSING_CURRENT_PRICE",
            safe_price=None,
            observed_ts_utc=None,
            age_min=None,
        )

    observed_ts_utc = snapshot.observed_ts_utc
    age_min = _age_minutes(observed_ts_utc, now_utc=now_utc)
    if observed_ts_utc is None or age_min is None:
        return CurrentPriceDisplay(
            status="STALE_CURRENT_PRICE",
            safe_price=None,
            observed_ts_utc=observed_ts_utc,
            age_min=None,
        )

    fresh_after_min = Decimal(str(fresh_after.total_seconds() / 60))
    if age_min < 0 or age_min > fresh_after_min:
        return CurrentPriceDisplay(
            status="STALE_CURRENT_PRICE",
            safe_price=None,
            observed_ts_utc=observed_ts_utc,
            age_min=age_min,
        )

    snapshot_market = snapshot.market.strip().upper()
    if snapshot_market != _canonical_market(snapshot):
        return CurrentPriceDisplay(
            status="INCONSISTENT_CURRENT_PRICE",
            safe_price=None,
            observed_ts_utc=observed_ts_utc,
            age_min=age_min,
        )
    if expected_market is not None and snapshot_market != expected_market.strip().upper():
        return CurrentPriceDisplay(
            status="INCONSISTENT_CURRENT_PRICE",
            safe_price=None,
            observed_ts_utc=observed_ts_utc,
            age_min=age_min,
        )

    # `observed_ts_utc` says when Synth saw the row; when a provider supplied an
    # event timestamp, that timestamp must also be fresh. Otherwise repeatedly
    # observing an old provider value would incorrectly make it look current.
    if snapshot.source_ts_utc is not None:
        source_age_min = _age_minutes(snapshot.source_ts_utc, now_utc=now_utc)
        if source_age_min is None or source_age_min < 0 or source_age_min > fresh_after_min:
            return CurrentPriceDisplay(
                status="INCONSISTENT_CURRENT_PRICE",
                safe_price=None,
                observed_ts_utc=observed_ts_utc,
                age_min=age_min,
            )

    return CurrentPriceDisplay(
        status="FRESH_CURRENT_PRICE",
        safe_price=snapshot.price,
        observed_ts_utc=observed_ts_utc,
        age_min=age_min,
    )
