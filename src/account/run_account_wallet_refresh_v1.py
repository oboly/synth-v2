"""
run_account_wallet_refresh_v1 — Per-account wallet snapshot refresh.

Default credential source: encrypted DB credential (--credential-source db).
The active encrypted credential for the profile's primary linked trading account
is loaded using SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY and decrypted in memory.
The plaintext reference is discarded immediately after client construction.

Legacy file-based credentials are only loaded when --credential-source profile-env
is passed explicitly. This path is never an automatic fallback.

Safety:
  broker_private_calls=2 (get_balance + get_open_orders)
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from src.account.account_snapshot_models_v1 import (
    AccountAssetUpsertResult,
    WalletBalanceRow,
    WalletOpenOrderRow,
    WalletRefreshResult,
)
from src.account.linked_account_resolver_v1 import resolve_primary_linked_account
from src.account_provisioning.account_credential_loader_v1 import load_account_credential
from src.account_provisioning.credential_crypto_v1 import load_master_key_from_env
from src.account_provisioning.credential_repository_v1 import CredentialRepository
from src.common.db import get_db_connection
from src.execution.bitvavo_client import BitvavoClient


RUNNER_NAME = "account_wallet_refresh_v1"
RUNNER_VERSION = "0.2"
DEFAULT_VENUE = "bitvavo"
# Legacy profile-env path only — never used for the default db credential source.
CREDENTIAL_BASE_DIR = Path.home() / ".config/synth/accounts"

_PROFILE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


# ---------------------------------------------------------------------------
# Profile slug validation
# ---------------------------------------------------------------------------

def validate_profile_slug(profile: str) -> None:
    if not _PROFILE_SLUG_RE.match(profile):
        raise ValueError(
            f"Invalid profile slug {profile!r}. "
            "Must match [a-z0-9][a-z0-9_-]{{0,62}}."
        )
    if ".." in profile or "/" in profile:
        raise ValueError(f"Path traversal rejected in profile slug: {profile!r}")


# ---------------------------------------------------------------------------
# Legacy profile-env credential loading (explicit --credential-source profile-env only)
# ---------------------------------------------------------------------------

def get_account_env_dir(account_env_dir: str | Path | None = None) -> Path:
    if account_env_dir is not None:
        return Path(account_env_dir).expanduser()
    override = os.getenv("SYNTH_ACCOUNT_ENV_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config/synth/accounts"


def load_profile_credentials(
    profile: str,
    *,
    account_env_dir: str | Path | None = None,
) -> tuple[str, str]:
    """Load API key and secret from profile env file. Never returns empty strings.

    Only called when --credential-source profile-env is explicitly set.
    Never used as a fallback from the default db credential source.
    """
    validate_profile_slug(profile)
    env_path = get_account_env_dir(account_env_dir) / f"{profile}.env"
    if not env_path.exists():
        raise FileNotFoundError(
            f"Profile credential file not found: {env_path}. "
            "Create it with BITVAVO_API_KEY and BITVAVO_API_SECRET."
        )
    values = dotenv_values(str(env_path))
    api_key = values.get("BITVAVO_API_KEY", "")
    api_secret = values.get("BITVAVO_API_SECRET", "")
    if not api_key:
        raise ValueError(f"BITVAVO_API_KEY missing or empty in {env_path}")
    if not api_secret:
        raise ValueError(f"BITVAVO_API_SECRET missing or empty in {env_path}")
    return api_key, api_secret


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def decimal_value(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def fetch_trading_account(conn: Any, *, account_code: str, venue: str) -> dict[str, Any]:
    """Validate trading_account by account_code. Used for profile-env legacy path."""
    sql = (
        "SELECT trading_account_id, account_code, venue, account_mode, enabled, live_trading_enabled "
        "FROM trading_account WHERE account_code = %s AND venue = %s LIMIT 1"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (account_code, venue))
        row = cur.fetchone()
    if not row:
        raise RuntimeError(
            f"trading_account not found: account_code={account_code} venue={venue}"
        )
    if not int(row["enabled"]):
        raise RuntimeError(f"trading_account disabled: account_code={account_code}")
    if int(row["live_trading_enabled"]) != 0:
        raise RuntimeError(
            "Refusing wallet refresh for account with live_trading_enabled != 0."
        )
    return dict(row)


def normalize_balance_rows(raw_balances: list[dict[str, Any]]) -> list[WalletBalanceRow]:
    rows: list[WalletBalanceRow] = []
    for raw in raw_balances:
        currency_code = str(
            raw.get("symbol") or raw.get("currency") or raw.get("asset") or ""
        ).strip().upper()
        if not currency_code:
            continue
        available = decimal_value(raw.get("available"))
        reserved = decimal_value(
            raw.get("inOrder") if raw.get("inOrder") is not None else raw.get("reserved")
        )
        rows.append(
            WalletBalanceRow(
                currency_code=currency_code,
                available_amount=available,
                reserved_amount=reserved,
                total_amount=available + reserved,
            )
        )
    return sorted(rows, key=lambda r: r.currency_code)


def normalize_order_rows(
    raw_orders: list[dict[str, Any]],
    *,
    venue_quote: str = "EUR",
) -> list[WalletOpenOrderRow]:
    rows: list[WalletOpenOrderRow] = []
    for raw in raw_orders:
        market = str(raw.get("market") or "")
        if not market.endswith(f"-{venue_quote}"):
            continue
        broker_order_id = str(raw.get("orderId") or "")
        if not broker_order_id:
            continue
        quantity = decimal_value(raw.get("amount"))
        remaining = decimal_value(raw.get("amountRemaining"))
        filled = max(quantity - remaining, Decimal("0"))
        rows.append(
            WalletOpenOrderRow(
                market=market,
                side=str(raw.get("side") or "").upper(),
                order_type=str(raw.get("orderType") or "").upper(),
                broker_order_id=broker_order_id,
                client_order_id=raw.get("clientOrderId"),
                limit_price=optional_decimal(raw.get("price")),
                quantity=quantity,
                filled_quantity=filled,
                remaining_quantity=remaining,
                broker_status=str(raw.get("status") or "UNKNOWN").upper(),
            )
        )
    return rows


def fetch_venue_market_id(conn: Any, *, venue: str, market: str) -> int | None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT venue_market_id FROM venue_market WHERE venue = %s AND market = %s LIMIT 1",
                (venue, market),
            )
            row = cur.fetchone()
        return int(row["venue_market_id"]) if row else None
    except Exception:
        return None


def upsert_account_asset(
    conn: Any,
    *,
    trading_account_id: int,
    venue_market_id: int,
    source: str,
) -> AccountAssetUpsertResult:
    market_label = f"vm_id={venue_market_id}"
    sql = """
    INSERT INTO account_asset (
        trading_account_id, venue_market_id,
        is_visible, is_candidate_enabled, is_order_proposal_enabled,
        is_portfolio_member, is_hidden, source
    ) VALUES (
        %s, %s,
        1, 1, 0,
        0, 0, %s
    )
    ON DUPLICATE KEY UPDATE
        source = IF(source = 'MANUAL_ADD', VALUES(source), source),
        updated_ts = CURRENT_TIMESTAMP
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue_market_id, source))
        affected = cur.rowcount
    action = "INSERTED" if affected == 1 else "EXISTING"
    return AccountAssetUpsertResult(market=market_label, action=action)


def write_balance_snapshot(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    balances: list[WalletBalanceRow],
    snapshot_ts_utc: datetime,
    source_name: str,
) -> int:
    sql = (
        "INSERT INTO trading_account_balance_snapshot ("
        "snapshot_ts_utc, trading_account_id, venue, currency_code, "
        "available_amount, reserved_amount, total_amount, source_name, raw_json"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    written = 0
    with conn.cursor() as cur:
        for row in balances:
            raw = {
                "currency_code": row.currency_code,
                "available_amount": str(row.available_amount),
                "reserved_amount": str(row.reserved_amount),
                "total_amount": str(row.total_amount),
            }
            cur.execute(
                sql,
                (
                    snapshot_ts_utc,
                    trading_account_id,
                    venue,
                    row.currency_code,
                    row.available_amount,
                    row.reserved_amount,
                    row.total_amount,
                    source_name,
                    json.dumps(raw, sort_keys=True, separators=(",", ":")),
                ),
            )
            written += 1
    return written


def write_open_order_snapshot(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    orders: list[WalletOpenOrderRow],
    snapshot_ts_utc: datetime,
) -> int:
    # Gracefully skip if account_open_order_snapshot table does not exist yet.
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM account_open_order_snapshot LIMIT 0")
    except Exception:
        print(
            "[warn] account_open_order_snapshot table not found; "
            "run migration 20260603_account_open_order_snapshot_v1.sql",
            file=sys.stderr,
        )
        return 0

    sql = """
    INSERT INTO account_open_order_snapshot (
        snapshot_ts_utc, trading_account_id, venue, market,
        broker_order_id, client_order_id, side, order_type,
        limit_price, quantity, filled_quantity, remaining_quantity,
        broker_status
    ) VALUES (
        %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s
    )
    ON DUPLICATE KEY UPDATE
        broker_status = VALUES(broker_status),
        filled_quantity = VALUES(filled_quantity),
        remaining_quantity = VALUES(remaining_quantity)
    """
    written = 0
    with conn.cursor() as cur:
        for order in orders:
            cur.execute(
                sql,
                (
                    snapshot_ts_utc,
                    trading_account_id,
                    venue,
                    order.market,
                    order.broker_order_id,
                    order.client_order_id,
                    order.side,
                    order.order_type,
                    order.limit_price,
                    order.quantity,
                    order.filled_quantity,
                    order.remaining_quantity,
                    order.broker_status,
                ),
            )
            written += 1
    return written


def discover_account_assets(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    balances: list[WalletBalanceRow],
    orders: list[WalletOpenOrderRow],
    quote_currency: str = "EUR",
) -> tuple[int, int]:
    inserted = 0
    existing = 0

    # From wallet balances: skip quote currency itself (EUR)
    for row in balances:
        if row.currency_code == quote_currency:
            continue
        market = f"{row.currency_code}-{quote_currency}"
        venue_market_id = fetch_venue_market_id(conn, venue=venue, market=market)
        if venue_market_id is None:
            continue
        result = upsert_account_asset(
            conn,
            trading_account_id=trading_account_id,
            venue_market_id=venue_market_id,
            source="WALLET_DISCOVERY",
        )
        if result.action == "INSERTED":
            inserted += 1
        else:
            existing += 1

    # From open orders
    seen_order_markets: set[str] = set()
    for order in orders:
        if order.market in seen_order_markets:
            continue
        seen_order_markets.add(order.market)
        venue_market_id = fetch_venue_market_id(conn, venue=venue, market=order.market)
        if venue_market_id is None:
            continue
        result = upsert_account_asset(
            conn,
            trading_account_id=trading_account_id,
            venue_market_id=venue_market_id,
            source="OPEN_ORDER_DISCOVERY",
        )
        if result.action == "INSERTED":
            inserted += 1
        else:
            existing += 1

    return inserted, existing


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh per-account wallet snapshot from Bitvavo. "
            "Private read-only. No broker writes, no order submission."
        )
    )
    parser.add_argument(
        "--account-profile",
        required=True,
        metavar="PROFILE",
        help="Account profile slug [a-z0-9_-].",
    )
    parser.add_argument(
        "--credential-source",
        choices=["db", "profile-env"],
        default="db",
        help=(
            "Credential source. 'db' (default): load encrypted credential from DB "
            "using SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY. "
            "'profile-env': load from ~/.config/synth/accounts/<profile>.env "
            "(legacy, explicit only — never an automatic fallback)."
        ),
    )
    parser.add_argument(
        "--account-env-dir",
        default=None,
        help=(
            "Override credential directory for --credential-source profile-env. "
            "Ignored when --credential-source db is used."
        ),
    )
    parser.add_argument(
        "--account-code",
        default=None,
        metavar="CODE",
        help=(
            "trading_account.account_code. Only used with --credential-source profile-env. "
            "Ignored for --credential-source db (always resolved from DB)."
        ),
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument(
        "--write-db",
        action="store_true",
        default=False,
        help="Persist snapshots to DB. Dry-run if omitted.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=15)
    parser.add_argument(
        "--output",
        choices=("summary", "none"),
        default="summary",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        validate_profile_slug(args.account_profile)
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    conn = get_db_connection()
    try:
        if args.credential_source == "db":
            # Load master key from environment — never from profile .env files.
            try:
                _, master_key_bytes = load_master_key_from_env()
            except ValueError as exc:
                print(f"[error] master key: {exc}", file=sys.stderr)
                return 1

            # Resolve profile → primary linked trading account.
            try:
                identity = resolve_primary_linked_account(
                    conn,
                    profile_code=args.account_profile,
                    venue=args.venue,
                )
            except ValueError as exc:
                print(f"[error] account resolution: {exc}", file=sys.stderr)
                return 1

            trading_account_id = identity.trading_account_id
            account_code = identity.account_code

            # Decrypt the stored active credential.
            try:
                plain = load_account_credential(
                    conn,
                    trading_account_id=trading_account_id,
                    venue=args.venue,
                    master_key_bytes=master_key_bytes,
                    cred_repo_factory=CredentialRepository,
                )
            except ValueError as exc:
                print(f"[error] credential load: {exc}", file=sys.stderr)
                return 1

            client = BitvavoClient(
                api_key=plain.api_key,
                api_secret=plain.api_secret,
                timeout_seconds=args.timeout_seconds,
            )
            del plain  # discard plaintext reference immediately

        else:
            # profile-env: explicit legacy path only.
            account_code = args.account_code or f"bitvavo_{args.account_profile}_read"
            try:
                api_key, api_secret = load_profile_credentials(
                    args.account_profile,
                    account_env_dir=args.account_env_dir,
                )
            except (FileNotFoundError, ValueError) as exc:
                print(f"[error] credential load failed: {exc}", file=sys.stderr)
                return 1

            try:
                account = fetch_trading_account(conn, account_code=account_code, venue=args.venue)
                trading_account_id = int(account["trading_account_id"])
            except RuntimeError as exc:
                print(f"[error] {exc}", file=sys.stderr)
                return 1

            client = BitvavoClient(
                api_key=api_key,
                api_secret=api_secret,
                timeout_seconds=args.timeout_seconds,
            )

        print(f"runner={RUNNER_NAME} version={RUNNER_VERSION}")
        print(f"profile={args.account_profile} account_code={account_code}")
        print(f"trading_account_id={trading_account_id} venue={args.venue}")
        print(f"credential_source={args.credential_source}")
        print("[INFO] private read-only; no broker writes; no order submission")

        try:
            raw_balances = client.get_balance()
        except PermissionError as exc:
            print(f"[error] private read gate: {exc}", file=sys.stderr)
            return 1

        try:
            raw_orders = client.get_open_orders()
        except PermissionError as exc:
            print(f"[error] private read gate: {exc}", file=sys.stderr)
            return 1

        balances = normalize_balance_rows(raw_balances)
        orders = normalize_order_rows(raw_orders)
        snapshot_ts_utc = utc_now_naive()

        balance_writes = 0
        order_writes = 0
        aa_inserted = 0
        aa_existing = 0

        if args.write_db:
            aa_inserted, aa_existing = discover_account_assets(
                conn,
                trading_account_id=trading_account_id,
                venue=args.venue,
                balances=balances,
                orders=orders,
            )
            conn.commit()

            balance_writes = write_balance_snapshot(
                conn,
                trading_account_id=trading_account_id,
                venue=args.venue,
                balances=balances,
                snapshot_ts_utc=snapshot_ts_utc,
                source_name=RUNNER_NAME,
            )
            conn.commit()

            order_writes = write_open_order_snapshot(
                conn,
                trading_account_id=trading_account_id,
                venue=args.venue,
                orders=orders,
                snapshot_ts_utc=snapshot_ts_utc,
            )
            conn.commit()

        result = WalletRefreshResult(
            profile=args.account_profile,
            account_code=account_code,
            trading_account_id=trading_account_id,
            venue=args.venue,
            snapshot_ts_utc=snapshot_ts_utc,
            balance_count=len(balances),
            order_count=len(orders),
            account_asset_inserted=aa_inserted,
            account_asset_existing=aa_existing,
        )

        if args.output == "summary":
            print(f"snapshot_ts_utc={snapshot_ts_utc.isoformat(sep=' ')}")
            print(f"balance_count={result.balance_count}")
            print(f"order_count={result.order_count}")
            if args.write_db:
                print(f"account_asset_inserted={result.account_asset_inserted}")
                print(f"account_asset_existing={result.account_asset_existing}")
                print(f"balance_snapshot_writes={balance_writes}")
                print(f"order_snapshot_writes={order_writes}")
            else:
                print("[DRY_RUN] --write-db not set; no DB writes performed")
            print("broker_private_calls=2")
            print("broker_writes=0")
            print("order_submission=0")
            print("executor=none")

        return 0

    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
