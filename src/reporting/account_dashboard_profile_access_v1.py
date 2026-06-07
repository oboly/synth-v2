from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PROFILE_HAS_NO_ACCOUNT_ACCESS = "PROFILE_HAS_NO_ACCOUNT_ACCESS"


@dataclass(frozen=True)
class DashboardProfileAccess:
    account_profile: str
    venue: str
    trading_account_stable_ref: str
    display_timezone: str


def resolve_dashboard_profile_access(*, account_profile: str, venue: str) -> DashboardProfileAccess:
    """
    Resolve profile → trading account from DB-backed explicit linkage.
    Never falls back to profile-name inference.
    Raises RuntimeError (PROFILE_HAS_NO_ACCOUNT_ACCESS) if no active primary link exists.
    """
    return _resolve_from_db(account_profile=account_profile, venue=venue)


def _resolve_from_db(*, account_profile: str, venue: str) -> DashboardProfileAccess:
    from src.common.db import get_connection
    normalized_profile = str(account_profile or "").strip().lower()
    normalized_venue = str(venue or "").strip().lower()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    ap.profile_code,
                    ap.display_timezone,
                    ta.account_code,
                    ta.venue
                FROM app_profile ap
                JOIN app_profile_trading_account_link aptl
                  ON aptl.app_profile_id = ap.app_profile_id
                JOIN trading_account ta
                  ON ta.trading_account_id = aptl.trading_account_id
                WHERE ap.profile_code = %s
                  AND ta.venue = %s
                  AND aptl.link_status = 'ACTIVE'
                  AND aptl.is_primary = 1
                ORDER BY aptl.link_id
                LIMIT 2
                """,
                (normalized_profile, normalized_venue),
            )
            rows: list[Any] = cur.fetchall()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if not rows:
        raise RuntimeError(
            f"{PROFILE_HAS_NO_ACCOUNT_ACCESS}: profile={account_profile!r} venue={venue!r}"
        )
    if len(rows) > 1:
        raise RuntimeError(
            f"AMBIGUOUS_PROFILE_ACCOUNT_LINK: profile={account_profile!r} venue={venue!r} "
            f"matches {len(rows)} active primary links"
        )
    row = rows[0]
    return DashboardProfileAccess(
        account_profile=str(row["profile_code"]),
        venue=str(row["venue"]),
        trading_account_stable_ref=str(row["account_code"]),
        display_timezone=str(row["display_timezone"]),
    )
