"""Append-only aligned account-state snapshot run contract.

This module owns only persisted evidence headers.  Private acquisition remains
in ``run_account_wallet_refresh_v1`` and policy/runtime consumers receive no
external-order authority from this contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


ACCOUNT_STATE_SNAPSHOT_RUN_SOURCE = "account_wallet_refresh_v1"
ACCOUNT_OPEN_ORDER_SNAPSHOT_RUN_SOURCE = ACCOUNT_STATE_SNAPSHOT_RUN_SOURCE
COMPLETE_SNAPSHOT_STATE = "COMPLETE"


class AccountStateSnapshotContractError(RuntimeError):
    """Fail-closed aligned-account-state evidence error."""


@dataclass(frozen=True)
class AccountStateSnapshotRunV1:
    account_state_snapshot_run_id: int
    trading_account_id: int
    venue: str
    source_name: str
    snapshot_ts_utc: datetime
    position_source_name: str
    position_snapshot_count: int
    balance_source_name: str
    balance_snapshot_count: int
    account_open_order_snapshot_run_id: int


def _require_nonnegative_count(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AccountStateSnapshotContractError(f"INVALID_{name.upper()}")


def _fetch_one(cur: Any) -> dict[str, Any] | None:
    row = cur.fetchone()
    return None if row is None else dict(row)


def _normalized_venue(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise AccountStateSnapshotContractError("INVALID_VENUE")
    return normalized


def _snapshot_timestamp_key(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.isoformat(sep=" ")
    raw = str(value).strip()
    if not raw:
        raise AccountStateSnapshotContractError("INVALID_SNAPSHOT_TIMESTAMP")
    normalized = raw.replace("T", " ")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise AccountStateSnapshotContractError("INVALID_SNAPSHOT_TIMESTAMP") from exc
    return _snapshot_timestamp_key(parsed)


def _validate_referenced_open_order_header(
    conn: Any,
    *,
    account_open_order_snapshot_run_id: int,
    trading_account_id: int,
    venue: str,
    snapshot_ts_utc: datetime,
    expected_open_order_count: int,
) -> None:
    """Require the referenced COMPLETE open-order evidence to bind exactly."""
    _require_nonnegative_count("open_order_count", expected_open_order_count)
    sql = """
    SELECT
        account_open_order_snapshot_run_id, trading_account_id, venue,
        source_name, snapshot_ts_utc, snapshot_state, open_order_count
    FROM account_open_order_snapshot_run_v1
    WHERE account_open_order_snapshot_run_id = %s
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (account_open_order_snapshot_run_id,))
        row = _fetch_one(cur)
    if row is None:
        raise AccountStateSnapshotContractError("REFERENCED_OPEN_ORDER_HEADER_MISSING")
    if (
        int(row["account_open_order_snapshot_run_id"])
        != account_open_order_snapshot_run_id
        or int(row["trading_account_id"]) != trading_account_id
        or _normalized_venue(row["venue"]) != _normalized_venue(venue)
        or _snapshot_timestamp_key(row["snapshot_ts_utc"])
        != _snapshot_timestamp_key(snapshot_ts_utc)
        or row["snapshot_state"] != COMPLETE_SNAPSHOT_STATE
        or row["source_name"] != ACCOUNT_OPEN_ORDER_SNAPSHOT_RUN_SOURCE
        or int(row["open_order_count"]) != expected_open_order_count
    ):
        raise AccountStateSnapshotContractError("REFERENCED_OPEN_ORDER_HEADER_MISMATCH")


def write_complete_open_order_snapshot_run(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    source_name: str,
    snapshot_ts_utc: datetime,
    open_order_count: int,
) -> int:
    """Append/reuse the authoritative COMPLETE open-order header.

    Call only after exactly ``open_order_count`` normalized order rows have
    been persisted in the caller's current transaction.
    """
    _require_nonnegative_count("open_order_count", open_order_count)
    lookup_sql = """
    SELECT account_open_order_snapshot_run_id, snapshot_state, open_order_count
    FROM account_open_order_snapshot_run_v1
    WHERE trading_account_id = %s
      AND venue = %s
      AND source_name = %s
      AND snapshot_ts_utc = %s
    LIMIT 1
    """
    insert_sql = """
    INSERT INTO account_open_order_snapshot_run_v1 (
        trading_account_id, venue, source_name, snapshot_ts_utc,
        snapshot_state, open_order_count
    ) VALUES (%s, %s, %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        cur.execute(lookup_sql, (trading_account_id, venue, source_name, snapshot_ts_utc))
        existing = _fetch_one(cur)
        if existing is not None:
            if (
                existing["snapshot_state"] != COMPLETE_SNAPSHOT_STATE
                or int(existing["open_order_count"]) != open_order_count
            ):
                raise AccountStateSnapshotContractError(
                    "OPEN_ORDER_COMPLETE_HEADER_CONFLICT"
                )
            return int(existing["account_open_order_snapshot_run_id"])
        cur.execute(
            insert_sql,
            (
                trading_account_id,
                venue,
                source_name,
                snapshot_ts_utc,
                COMPLETE_SNAPSHOT_STATE,
                open_order_count,
            ),
        )
        return int(cur.lastrowid)


def verify_persisted_component_counts(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    snapshot_ts_utc: datetime,
    position_source_name: str,
    expected_position_count: int,
    balance_source_name: str,
    expected_balance_count: int,
    expected_open_order_count: int,
) -> None:
    """Require persisted rows to match the exact COMPLETE bundle counts."""
    _require_nonnegative_count("position_snapshot_count", expected_position_count)
    _require_nonnegative_count("balance_snapshot_count", expected_balance_count)
    _require_nonnegative_count("open_order_count", expected_open_order_count)
    checks = (
        (
            "POSITION_SNAPSHOT_COUNT_MISMATCH",
            """
            SELECT COUNT(*) AS rows_total FROM account_position_snapshot
            WHERE trading_account_id = %s AND venue = %s AND source_name = %s
              AND snapshot_ts_utc = %s
            """,
            (trading_account_id, venue, position_source_name, snapshot_ts_utc),
            expected_position_count,
        ),
        (
            "BALANCE_SNAPSHOT_COUNT_MISMATCH",
            """
            SELECT COUNT(*) AS rows_total FROM trading_account_balance_snapshot
            WHERE trading_account_id = %s AND venue = %s AND source_name = %s
              AND snapshot_ts_utc = %s
            """,
            (trading_account_id, venue, balance_source_name, snapshot_ts_utc),
            expected_balance_count,
        ),
        (
            "OPEN_ORDER_SNAPSHOT_COUNT_MISMATCH",
            """
            SELECT COUNT(*) AS rows_total FROM account_open_order_snapshot
            WHERE trading_account_id = %s AND venue = %s AND snapshot_ts_utc = %s
            """,
            (trading_account_id, venue, snapshot_ts_utc),
            expected_open_order_count,
        ),
    )
    with conn.cursor() as cur:
        for reason, sql, params, expected in checks:
            cur.execute(sql, params)
            row = _fetch_one(cur)
            if row is None or int(row["rows_total"]) != expected:
                raise AccountStateSnapshotContractError(reason)


def write_complete_account_state_snapshot_run(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    source_name: str,
    refresh_started_ts_utc: datetime,
    snapshot_ts_utc: datetime,
    completed_ts_utc: datetime,
    position_source_name: str,
    position_snapshot_count: int,
    balance_source_name: str,
    balance_snapshot_count: int,
    account_open_order_snapshot_run_id: int,
    expected_open_order_count: int,
) -> AccountStateSnapshotRunV1:
    """Append/reuse a COMPLETE aligned evidence bundle in the open transaction."""
    _require_nonnegative_count("position_snapshot_count", position_snapshot_count)
    _require_nonnegative_count("balance_snapshot_count", balance_snapshot_count)
    if account_open_order_snapshot_run_id <= 0:
        raise AccountStateSnapshotContractError("INVALID_OPEN_ORDER_SNAPSHOT_RUN_ID")
    if not position_source_name or not balance_source_name or not source_name:
        raise AccountStateSnapshotContractError("MISSING_COMPONENT_PROVENANCE")
    _validate_referenced_open_order_header(
        conn,
        account_open_order_snapshot_run_id=account_open_order_snapshot_run_id,
        trading_account_id=trading_account_id,
        venue=venue,
        snapshot_ts_utc=snapshot_ts_utc,
        expected_open_order_count=expected_open_order_count,
    )

    lookup_sql = """
    SELECT
        account_state_snapshot_run_id, trading_account_id, venue, source_name,
        snapshot_ts_utc, position_source_name, position_snapshot_count,
        balance_source_name, balance_snapshot_count,
        account_open_order_snapshot_run_id
    FROM account_state_snapshot_run_v1
    WHERE trading_account_id = %s
      AND venue = %s
      AND source_name = %s
      AND snapshot_ts_utc = %s
    LIMIT 1
    """
    insert_sql = """
    INSERT INTO account_state_snapshot_run_v1 (
        trading_account_id, venue, source_name,
        refresh_started_ts_utc, snapshot_ts_utc, completed_ts_utc, run_state,
        position_source_name, position_snapshot_count,
        balance_source_name, balance_snapshot_count,
        account_open_order_snapshot_run_id
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    expected = {
        "trading_account_id": trading_account_id,
        "venue": venue,
        "source_name": source_name,
        "position_source_name": position_source_name,
        "position_snapshot_count": position_snapshot_count,
        "balance_source_name": balance_source_name,
        "balance_snapshot_count": balance_snapshot_count,
        "account_open_order_snapshot_run_id": account_open_order_snapshot_run_id,
    }
    with conn.cursor() as cur:
        cur.execute(lookup_sql, (trading_account_id, venue, source_name, snapshot_ts_utc))
        existing = _fetch_one(cur)
        if existing is not None:
            for name, value in expected.items():
                if existing[name] != value:
                    raise AccountStateSnapshotContractError(
                        "ACCOUNT_STATE_COMPLETE_RUN_CONFLICT"
                    )
            return AccountStateSnapshotRunV1(
                account_state_snapshot_run_id=int(existing["account_state_snapshot_run_id"]),
                trading_account_id=int(existing["trading_account_id"]),
                venue=str(existing["venue"]),
                source_name=str(existing["source_name"]),
                snapshot_ts_utc=existing["snapshot_ts_utc"],
                position_source_name=str(existing["position_source_name"]),
                position_snapshot_count=int(existing["position_snapshot_count"]),
                balance_source_name=str(existing["balance_source_name"]),
                balance_snapshot_count=int(existing["balance_snapshot_count"]),
                account_open_order_snapshot_run_id=int(
                    existing["account_open_order_snapshot_run_id"]
                ),
            )
        cur.execute(
            insert_sql,
            (
                trading_account_id, venue, source_name,
                refresh_started_ts_utc, snapshot_ts_utc, completed_ts_utc,
                COMPLETE_SNAPSHOT_STATE,
                position_source_name, position_snapshot_count,
                balance_source_name, balance_snapshot_count,
                account_open_order_snapshot_run_id,
            ),
        )
        return AccountStateSnapshotRunV1(
            account_state_snapshot_run_id=int(cur.lastrowid),
            trading_account_id=trading_account_id,
            venue=venue,
            source_name=source_name,
            snapshot_ts_utc=snapshot_ts_utc,
            position_source_name=position_source_name,
            position_snapshot_count=position_snapshot_count,
            balance_source_name=balance_source_name,
            balance_snapshot_count=balance_snapshot_count,
            account_open_order_snapshot_run_id=account_open_order_snapshot_run_id,
        )
