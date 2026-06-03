from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from src.common.db import get_connection


SOURCE_WALLET_DISCOVERY = "WALLET_DISCOVERY"
SOURCE_OPEN_ORDER_DISCOVERY = "OPEN_ORDER_DISCOVERY"
SOURCE_MANUAL_ADD = "MANUAL_ADD"
ALLOWED_SOURCES = {
    SOURCE_WALLET_DISCOVERY,
    SOURCE_OPEN_ORDER_DISCOVERY,
    SOURCE_MANUAL_ADD,
}

ACTION_ADD_ASSET = "add_asset"
ACTION_HIDE_ASSET = "hide_asset"
ACTION_DISABLE_CANDIDATE = "disable_candidate"
ACTION_PAUSE_CANDIDATE_24H = "pause_candidate_24h"
ACTION_REENABLE_ASSET = "reenable_asset"
ALLOWED_ACTIONS = {
    ACTION_ADD_ASSET,
    ACTION_HIDE_ASSET,
    ACTION_DISABLE_CANDIDATE,
    ACTION_PAUSE_CANDIDATE_24H,
    ACTION_REENABLE_ASSET,
}

DISABLED_REASON_MANUAL = "MANUAL_DISABLE"
DISABLED_REASON_PAUSE_24H = "PAUSE_24H"
DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE_CURRENCY = "EUR"


@dataclass(frozen=True)
class AccountAssetActionResult:
    action: str
    status: str
    account_code: str
    trading_account_id: int
    venue: str
    market: str
    source: str | None
    message: str


class AccountAssetSettingsRepo(Protocol):
    def fetch_trading_account(self, *, account_code: str, venue: str) -> dict[str, Any] | None: ...
    def fetch_venue_market(self, *, venue: str, market: str) -> dict[str, Any] | None: ...
    def fetch_account_asset(self, *, trading_account_id: int, venue_market_id: int) -> dict[str, Any] | None: ...
    def insert_account_asset(
        self,
        *,
        trading_account_id: int,
        venue_market_id: int,
        source: str,
        now_utc: datetime,
    ) -> None: ...
    def update_account_asset(
        self,
        *,
        trading_account_id: int,
        venue_market_id: int,
        updates: dict[str, Any],
    ) -> None: ...


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_market(value: str) -> str:
    return str(value or "").strip().upper()


def _require_account(
    repo: AccountAssetSettingsRepo,
    *,
    account_code: str,
    venue: str,
) -> dict[str, Any]:
    row = repo.fetch_trading_account(account_code=account_code, venue=venue)
    if not row:
        raise RuntimeError(f"trading_account not found: account_code={account_code} venue={venue}")
    return row


def _require_venue_market(
    repo: AccountAssetSettingsRepo,
    *,
    venue: str,
    market: str,
    require_eur_quote: bool = True,
) -> dict[str, Any]:
    normalized_market = normalize_market(market)
    row = repo.fetch_venue_market(venue=venue, market=normalized_market)
    if not row:
        raise RuntimeError(f"venue_market not found: venue={venue} market={normalized_market}")
    quote_currency = str(row.get("quote_currency") or "").upper()
    if require_eur_quote and quote_currency and quote_currency != DEFAULT_QUOTE_CURRENCY:
        raise RuntimeError(
            f"manual add requires EUR market by default: venue={venue} market={normalized_market} quote={quote_currency}"
        )
    return row


def _require_account_asset(
    repo: AccountAssetSettingsRepo,
    *,
    trading_account_id: int,
    venue_market_id: int,
    venue: str,
    market: str,
) -> dict[str, Any]:
    row = repo.fetch_account_asset(
        trading_account_id=trading_account_id,
        venue_market_id=venue_market_id,
    )
    if not row:
        raise RuntimeError(
            f"account_asset not found: trading_account_id={trading_account_id} venue={venue} market={normalize_market(market)}"
        )
    return row


def add_asset_for_account(
    repo: AccountAssetSettingsRepo,
    *,
    account_code: str,
    venue: str,
    market: str,
    now_utc: datetime | None = None,
) -> AccountAssetActionResult:
    now_utc = now_utc or utc_now_naive()
    account = _require_account(repo, account_code=account_code, venue=venue)
    venue_market = _require_venue_market(repo, venue=venue, market=market, require_eur_quote=True)
    trading_account_id = int(account["trading_account_id"])
    venue_market_id = int(venue_market["venue_market_id"])
    existing = repo.fetch_account_asset(
        trading_account_id=trading_account_id,
        venue_market_id=venue_market_id,
    )
    if existing:
        return AccountAssetActionResult(
            action=ACTION_ADD_ASSET,
            status="EXISTING",
            account_code=account_code,
            trading_account_id=trading_account_id,
            venue=venue,
            market=normalize_market(market),
            source=str(existing.get("source") or SOURCE_MANUAL_ADD),
            message="account_asset already exists for this account and market",
        )
    repo.insert_account_asset(
        trading_account_id=trading_account_id,
        venue_market_id=venue_market_id,
        source=SOURCE_MANUAL_ADD,
        now_utc=now_utc,
    )
    return AccountAssetActionResult(
        action=ACTION_ADD_ASSET,
        status="INSERTED",
        account_code=account_code,
        trading_account_id=trading_account_id,
        venue=venue,
        market=normalize_market(market),
        source=SOURCE_MANUAL_ADD,
        message="account_asset created for this account only",
    )


def hide_asset_for_account(
    repo: AccountAssetSettingsRepo,
    *,
    account_code: str,
    venue: str,
    market: str,
) -> AccountAssetActionResult:
    account = _require_account(repo, account_code=account_code, venue=venue)
    venue_market = _require_venue_market(repo, venue=venue, market=market, require_eur_quote=False)
    trading_account_id = int(account["trading_account_id"])
    venue_market_id = int(venue_market["venue_market_id"])
    existing = _require_account_asset(
        repo,
        trading_account_id=trading_account_id,
        venue_market_id=venue_market_id,
        venue=venue,
        market=market,
    )
    repo.update_account_asset(
        trading_account_id=trading_account_id,
        venue_market_id=venue_market_id,
        updates={
            "is_hidden": 1,
            "is_visible": 0,
        },
    )
    return AccountAssetActionResult(
        action=ACTION_HIDE_ASSET,
        status="UPDATED",
        account_code=account_code,
        trading_account_id=trading_account_id,
        venue=venue,
        market=normalize_market(market),
        source=str(existing.get("source") or ""),
        message="asset hidden for this account only",
    )


def disable_candidate_for_account(
    repo: AccountAssetSettingsRepo,
    *,
    account_code: str,
    venue: str,
    market: str,
) -> AccountAssetActionResult:
    account = _require_account(repo, account_code=account_code, venue=venue)
    venue_market = _require_venue_market(repo, venue=venue, market=market, require_eur_quote=False)
    trading_account_id = int(account["trading_account_id"])
    venue_market_id = int(venue_market["venue_market_id"])
    existing = _require_account_asset(
        repo,
        trading_account_id=trading_account_id,
        venue_market_id=venue_market_id,
        venue=venue,
        market=market,
    )
    repo.update_account_asset(
        trading_account_id=trading_account_id,
        venue_market_id=venue_market_id,
        updates={
            "is_candidate_enabled": 0,
            "disabled_until_utc": None,
            "disabled_reason": DISABLED_REASON_MANUAL,
        },
    )
    return AccountAssetActionResult(
        action=ACTION_DISABLE_CANDIDATE,
        status="UPDATED",
        account_code=account_code,
        trading_account_id=trading_account_id,
        venue=venue,
        market=normalize_market(market),
        source=str(existing.get("source") or ""),
        message="candidate disabled for this account only",
    )


def pause_candidate_for_account(
    repo: AccountAssetSettingsRepo,
    *,
    account_code: str,
    venue: str,
    market: str,
    now_utc: datetime | None = None,
    hours: int = 24,
) -> AccountAssetActionResult:
    now_utc = now_utc or utc_now_naive()
    account = _require_account(repo, account_code=account_code, venue=venue)
    venue_market = _require_venue_market(repo, venue=venue, market=market, require_eur_quote=False)
    trading_account_id = int(account["trading_account_id"])
    venue_market_id = int(venue_market["venue_market_id"])
    existing = _require_account_asset(
        repo,
        trading_account_id=trading_account_id,
        venue_market_id=venue_market_id,
        venue=venue,
        market=market,
    )
    repo.update_account_asset(
        trading_account_id=trading_account_id,
        venue_market_id=venue_market_id,
        updates={
            "is_candidate_enabled": 0,
            "disabled_until_utc": now_utc + timedelta(hours=hours),
            "disabled_reason": DISABLED_REASON_PAUSE_24H,
        },
    )
    return AccountAssetActionResult(
        action=ACTION_PAUSE_CANDIDATE_24H,
        status="UPDATED",
        account_code=account_code,
        trading_account_id=trading_account_id,
        venue=venue,
        market=normalize_market(market),
        source=str(existing.get("source") or ""),
        message=f"candidate paused for {hours}h for this account only",
    )


def reenable_asset_for_account(
    repo: AccountAssetSettingsRepo,
    *,
    account_code: str,
    venue: str,
    market: str,
) -> AccountAssetActionResult:
    account = _require_account(repo, account_code=account_code, venue=venue)
    venue_market = _require_venue_market(repo, venue=venue, market=market, require_eur_quote=False)
    trading_account_id = int(account["trading_account_id"])
    venue_market_id = int(venue_market["venue_market_id"])
    existing = _require_account_asset(
        repo,
        trading_account_id=trading_account_id,
        venue_market_id=venue_market_id,
        venue=venue,
        market=market,
    )
    repo.update_account_asset(
        trading_account_id=trading_account_id,
        venue_market_id=venue_market_id,
        updates={
            "is_visible": 1,
            "is_hidden": 0,
            "is_candidate_enabled": 1,
            "disabled_until_utc": None,
            "disabled_reason": None,
        },
    )
    return AccountAssetActionResult(
        action=ACTION_REENABLE_ASSET,
        status="UPDATED",
        account_code=account_code,
        trading_account_id=trading_account_id,
        venue=venue,
        market=normalize_market(market),
        source=str(existing.get("source") or ""),
        message="asset re-enabled for this account only",
    )


def dispatch_account_asset_action(
    repo: AccountAssetSettingsRepo,
    *,
    action: str,
    account_code: str,
    venue: str,
    market: str,
    now_utc: datetime | None = None,
) -> AccountAssetActionResult:
    if action not in ALLOWED_ACTIONS:
        raise RuntimeError(f"unsupported account asset action: {action}")
    if action == ACTION_ADD_ASSET:
        return add_asset_for_account(repo, account_code=account_code, venue=venue, market=market, now_utc=now_utc)
    if action == ACTION_HIDE_ASSET:
        return hide_asset_for_account(repo, account_code=account_code, venue=venue, market=market)
    if action == ACTION_DISABLE_CANDIDATE:
        return disable_candidate_for_account(repo, account_code=account_code, venue=venue, market=market)
    if action == ACTION_PAUSE_CANDIDATE_24H:
        return pause_candidate_for_account(repo, account_code=account_code, venue=venue, market=market, now_utc=now_utc)
    return reenable_asset_for_account(repo, account_code=account_code, venue=venue, market=market)


class MySqlAccountAssetSettingsRepo:
    def __init__(self, conn: Any):
        self.conn = conn

    def fetch_trading_account(self, *, account_code: str, venue: str) -> dict[str, Any] | None:
        sql = """
        SELECT trading_account_id, account_code, venue
        FROM trading_account
        WHERE account_code = %s
          AND venue = %s
        LIMIT 1
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (account_code, venue))
            row = cur.fetchone()
        return None if not row else dict(row)

    def fetch_venue_market(self, *, venue: str, market: str) -> dict[str, Any] | None:
        sql = """
        SELECT vm.venue_market_id, vm.venue, vm.market, vm.quote_currency, vm.is_tradeable, a.symbol AS asset_symbol
        FROM venue_market vm
        JOIN asset a
          ON a.asset_id = vm.base_asset_id
        WHERE vm.venue = %s
          AND vm.market = %s
        LIMIT 1
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (venue, normalize_market(market)))
            row = cur.fetchone()
        return None if not row else dict(row)

    def fetch_account_asset(self, *, trading_account_id: int, venue_market_id: int) -> dict[str, Any] | None:
        sql = """
        SELECT
            account_asset_id,
            trading_account_id,
            venue_market_id,
            is_visible,
            is_candidate_enabled,
            is_order_proposal_enabled,
            is_hidden,
            disabled_until_utc,
            disabled_reason,
            source,
            first_seen_at_utc,
            last_seen_at_utc,
            created_ts,
            updated_ts
        FROM account_asset
        WHERE trading_account_id = %s
          AND venue_market_id = %s
        LIMIT 1
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (trading_account_id, venue_market_id))
            row = cur.fetchone()
        return None if not row else dict(row)

    def insert_account_asset(
        self,
        *,
        trading_account_id: int,
        venue_market_id: int,
        source: str,
        now_utc: datetime,
    ) -> None:
        if source not in ALLOWED_SOURCES:
            raise RuntimeError(f"unsupported account_asset source: {source}")
        sql = """
        INSERT INTO account_asset (
            trading_account_id,
            venue_market_id,
            is_visible,
            is_candidate_enabled,
            is_order_proposal_enabled,
            is_portfolio_member,
            is_hidden,
            disabled_until_utc,
            disabled_reason,
            source,
            first_seen_at_utc,
            last_seen_at_utc
        ) VALUES (
            %s,
            %s,
            1,
            1,
            0,
            0,
            0,
            NULL,
            NULL,
            %s,
            %s,
            %s
        )
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (trading_account_id, venue_market_id, source, now_utc, now_utc))

    def update_account_asset(
        self,
        *,
        trading_account_id: int,
        venue_market_id: int,
        updates: dict[str, Any],
    ) -> None:
        if not updates:
            return
        assignments: list[str] = []
        params: list[Any] = []
        for column, value in updates.items():
            assignments.append(f"{column} = %s")
            params.append(value)
        assignments.append("updated_ts = CURRENT_TIMESTAMP")
        sql = f"""
        UPDATE account_asset
        SET {", ".join(assignments)}
        WHERE trading_account_id = %s
          AND venue_market_id = %s
        """
        params.extend([trading_account_id, venue_market_id])
        with self.conn.cursor() as cur:
            cur.execute(sql, params)


def run_account_asset_action(
    *,
    action: str,
    account_code: str,
    venue: str,
    market: str,
) -> AccountAssetActionResult:
    conn = get_connection()
    try:
        repo = MySqlAccountAssetSettingsRepo(conn)
        result = dispatch_account_asset_action(
            repo,
            action=action,
            account_code=account_code,
            venue=venue,
            market=market,
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
