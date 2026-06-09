"""
account_snapshot_service_v1 — First-time account snapshot after provisioning.

Fetches balance using account-scoped credentials (never global env),
writes balance rows to the snapshot table, and returns a SnapshotResult.

Read-only credential policy: calls get_balance() only.
Open-order details require Trade permission and are unavailable under the initial
read-only credential. order_row_count is always 0 after first snapshot.

Called post-commit by the connect_bitvavo runner after successful provisioning.
Must not be called in the provisioning transaction.

Safety:
  broker_private_calls=1 (read-only: get_balance only)
  broker_writes=0
  order_submission=0
  executor=none
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

_SOURCE_NAME = "account_provisioning_first_snapshot_v1"


@dataclass(frozen=True)
class SnapshotResult:
    ok: bool
    error_code: str | None = None
    balance_row_count: int = 0
    order_row_count: int = 0


def _utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _execute(conn: Any, sql: str, params: tuple) -> Any:
    """Execute SQL on either a MariaDB connection (cursor) or SQLite connection (direct)."""
    normalized = sql.replace("%s", "?")
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur
    except (AttributeError, TypeError):
        return conn.execute(normalized, params)


def _insert_balance_rows(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    raw_balances: list[dict],
    snapshot_ts_utc: datetime,
) -> int:
    sql = (
        "INSERT INTO trading_account_balance_snapshot ("
        "snapshot_ts_utc, trading_account_id, venue, currency_code, "
        "available_amount, reserved_amount, total_amount, source_name, raw_json"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    count = 0
    for raw in raw_balances:
        available = _decimal(raw.get("available"))
        reserved = _decimal(raw.get("inOrder") if raw.get("inOrder") is not None else raw.get("reserved"))
        total = available + reserved
        currency = str(raw.get("symbol") or raw.get("currency") or "")
        if not currency:
            continue
        _execute(
            conn,
            sql,
            (
                snapshot_ts_utc.strftime("%Y-%m-%d %H:%M:%S"),
                trading_account_id,
                venue,
                currency,
                str(available),
                str(reserved),
                str(total),
                _SOURCE_NAME,
                json.dumps(raw),
            ),
        )
        count += 1
    return count


def _insert_order_rows(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    raw_orders: list[dict],
    snapshot_ts_utc: datetime,
) -> int:
    sql = (
        "INSERT INTO broker_order_snapshot ("
        "snapshot_ts_utc, trading_account_id, execution_intent_id, venue, symbol, "
        "broker_order_id, client_order_id, side, order_type, "
        "limit_price_eur, quantity_base, filled_quantity_base, "
        "remaining_quantity_base, broker_status, raw_json"
        ") VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    count = 0
    for raw in raw_orders:
        _execute(
            conn,
            sql,
            (
                snapshot_ts_utc.strftime("%Y-%m-%d %H:%M:%S"),
                trading_account_id,
                venue,
                str(raw.get("market") or ""),
                str(raw.get("orderId") or ""),
                raw.get("clientOrderId"),
                str(raw.get("side") or ""),
                str(raw.get("orderType") or ""),
                raw.get("price"),
                str(_decimal(raw.get("amount"))),
                str(_decimal(raw.get("filledAmount"))),
                str(_decimal(raw.get("amountRemaining"))),
                str(raw.get("status") or ""),
                json.dumps(raw),
            ),
        )
        count += 1
    return count


def take_first_snapshot(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    bitvavo_client: Any,
    now_utc: datetime | None = None,
) -> SnapshotResult:
    """
    Fetch balance for the account and write to trading_account_balance_snapshot.

    Open-order details are not fetched — the initial read-only credential does not
    have Trade permission. order_row_count is always 0.

    bitvavo_client must be created with explicit api_key + api_secret from the
    account's decrypted credential — never from global env vars.

    conn is a committed/writable connection (outside the provisioning transaction).
    Commits the snapshot writes.

    broker_private_calls=1 (get_balance only — no writes, no orders placed).
    """
    snapshot_ts_utc = (now_utc or _utc_naive()).replace(tzinfo=None)

    try:
        raw_balances = bitvavo_client.get_balance()
    except Exception:
        return SnapshotResult(ok=False, error_code="BALANCE_FETCH_FAILED")

    try:
        balance_count = _insert_balance_rows(
            conn,
            trading_account_id=trading_account_id,
            venue=venue,
            raw_balances=raw_balances,
            snapshot_ts_utc=snapshot_ts_utc,
        )
        try:
            conn.commit()
        except (AttributeError, TypeError):
            pass
        return SnapshotResult(ok=True, balance_row_count=balance_count, order_row_count=0)
    except Exception:
        try:
            conn.rollback()
        except (AttributeError, TypeError):
            pass
        return SnapshotResult(ok=False, error_code="SNAPSHOT_WRITE_FAILED")
