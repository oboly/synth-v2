"""
linked_account_resolver_v1 — Resolve profile_code + venue to a linked trading account.

Returns a LinkedAccountIdentity containing the canonical trading_account_id and
account_code for a given profile_code. The result is used to scope all subsequent
credential lookups, snapshot writes, and dashboard renders.

Fails closed on every ambiguous or invalid state:
  NO_PROFILE_FOUND          — profile_code not in app_profile
  NO_ACTIVE_PRIMARY_LINK    — no ACTIVE/is_primary=1 link for the profile
  AMBIGUOUS_PRIMARY_LINK    — more than one ACTIVE primary link (data invariant violation)
  ACCOUNT_VENUE_MISMATCH    — linked account is for a different venue
  ACCOUNT_DISABLED          — trading_account.enabled = 0
  LIVE_TRADING_ENABLED      — live_trading_enabled != 0 (wallet refresh refused)

No fallback to inferred account names such as bitvavo_<profile>_read.
No global env credential fallback.

Safety:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  executor=none
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LinkedAccountIdentity:
    profile_code: str
    trading_account_id: int
    account_code: str
    venue: str


def _query_one(conn: Any, sql: str, params: tuple) -> Any:
    """SELECT one row on either a MariaDB or SQLite connection."""
    normalized = sql.replace("%s", "?")
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    except (AttributeError, TypeError):
        return conn.execute(normalized, params).fetchone()


def _query_all(conn: Any, sql: str, params: tuple) -> list:
    """SELECT all rows on either a MariaDB or SQLite connection."""
    normalized = sql.replace("%s", "?")
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())
    except (AttributeError, TypeError):
        return list(conn.execute(normalized, params).fetchall())


def _row_get(row: Any, key: str, fallback_index: int) -> Any:
    """Dict-style or index-style row access — handles both MariaDB dicts and SQLite Rows."""
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return row[fallback_index]


def resolve_primary_linked_account(
    conn: Any,
    *,
    profile_code: str,
    venue: str,
) -> LinkedAccountIdentity:
    """
    Resolve profile_code + venue → LinkedAccountIdentity.

    All failure modes raise ValueError with a machine-readable diagnostic code
    as the leading token so callers can distinguish them. No credentials are
    loaded here — this is DB metadata only.
    """
    profile_row = _query_one(
        conn,
        "SELECT app_profile_id FROM app_profile WHERE profile_code = %s",
        (profile_code,),
    )
    if not profile_row:
        raise ValueError(f"NO_PROFILE_FOUND: profile_code={profile_code!r}")

    app_profile_id = int(_row_get(profile_row, "app_profile_id", 0))

    links = _query_all(
        conn,
        """
        SELECT trading_account_id
        FROM app_profile_trading_account_link
        WHERE app_profile_id = %s
          AND link_status = 'ACTIVE'
          AND is_primary = 1
        """,
        (app_profile_id,),
    )
    if not links:
        raise ValueError(
            f"NO_ACTIVE_PRIMARY_LINK: profile_code={profile_code!r}"
        )
    if len(links) > 1:
        raise ValueError(
            f"AMBIGUOUS_PRIMARY_LINK: profile_code={profile_code!r} count={len(links)}"
        )

    trading_account_id = int(_row_get(links[0], "trading_account_id", 0))

    ta_row = _query_one(
        conn,
        """
        SELECT account_code, venue, enabled, live_trading_enabled
        FROM trading_account
        WHERE trading_account_id = %s
        """,
        (trading_account_id,),
    )
    if not ta_row:
        raise ValueError(
            f"TRADING_ACCOUNT_NOT_FOUND: trading_account_id={trading_account_id}"
        )

    account_code = str(_row_get(ta_row, "account_code", 0))
    ta_venue = str(_row_get(ta_row, "venue", 1))
    enabled = int(_row_get(ta_row, "enabled", 2))
    live = int(_row_get(ta_row, "live_trading_enabled", 3))

    if ta_venue != venue:
        raise ValueError(
            f"ACCOUNT_VENUE_MISMATCH: profile={profile_code!r} "
            f"expected_venue={venue!r} actual_venue={ta_venue!r}"
        )
    if not enabled:
        raise ValueError(
            f"ACCOUNT_DISABLED: account_code={account_code!r}"
        )
    if live != 0:
        raise ValueError(
            f"LIVE_TRADING_ENABLED: account_code={account_code!r} "
            f"live_trading_enabled={live}"
        )

    return LinkedAccountIdentity(
        profile_code=profile_code,
        trading_account_id=trading_account_id,
        account_code=account_code,
        venue=venue,
    )
