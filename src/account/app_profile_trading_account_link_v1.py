from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable


LINK_STATUS_ACTIVE = "ACTIVE"
LINK_STATUS_REVOKED = "REVOKED"
ACCOUNT_CONNECTION_NONE = "NO_EXCHANGE_ACCOUNT_CONNECTED"
ACCOUNT_CONNECTION_READ_ONLY = "READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_text(value: datetime) -> str:
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


class AppProfileTradingAccountLinkRepository:
    """
    Account layer: explicit app_profile → trading_account linkage.

    No credentials are stored or read here.
    No broker calls. No order placement.
    """

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def _with_conn(self, fn: Callable[[Any, Any], Any]) -> Any:
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                result = fn(conn, cur)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def resolve_primary_link_by_profile_code(
        self, *, profile_code: str, venue: str
    ) -> dict[str, Any] | None:
        """
        Return the single primary active link row for profile+venue, or None if unlinked.
        Raises RuntimeError on ambiguous result (multiple primary active links).
        Never infers account from profile name.
        """
        def _run(_conn: Any, cur: Any) -> dict[str, Any] | None:
            cur.execute(
                """
                SELECT
                    aptl.link_id,
                    aptl.app_profile_id,
                    aptl.trading_account_id,
                    aptl.link_status,
                    aptl.is_primary,
                    aptl.created_ts_utc,
                    ta.account_code,
                    ta.venue,
                    ap.profile_code,
                    ap.display_timezone
                FROM app_profile_trading_account_link aptl
                JOIN app_profile ap
                  ON ap.app_profile_id = aptl.app_profile_id
                JOIN trading_account ta
                  ON ta.trading_account_id = aptl.trading_account_id
                WHERE ap.profile_code = %s
                  AND ta.venue = %s
                  AND aptl.link_status = %s
                  AND aptl.is_primary = 1
                ORDER BY aptl.link_id
                LIMIT 2
                """,
                (profile_code, venue, LINK_STATUS_ACTIVE),
            )
            rows = cur.fetchall()
            if not rows:
                return None
            if len(rows) > 1:
                raise RuntimeError(
                    f"AMBIGUOUS_PRIMARY_LINK: profile_code={profile_code!r} venue={venue!r} "
                    f"has multiple primary active links"
                )
            return dict(rows[0])
        return self._with_conn(_run)

    def upsert_link(
        self,
        *,
        profile_code: str,
        venue: str,
        account_code: str,
        set_primary: bool,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Create or update link between app_profile and trading_account. Idempotent.
        Fails explicitly on missing profile, missing account, or ambiguous account.
        Never infers account from profile name.
        No broker calls. No credential reads. DB link write only.
        """
        now = now_utc or _utc_now()
        now_text = _utc_text(now)

        def _run(_conn: Any, cur: Any) -> dict[str, Any]:
            cur.execute(
                "SELECT app_profile_id, profile_code FROM app_profile WHERE profile_code = %s",
                (profile_code,),
            )
            profile_row = cur.fetchone()
            if not profile_row:
                raise RuntimeError(f"PROFILE_NOT_FOUND: profile_code={profile_code!r}")
            app_profile_id = int(profile_row["app_profile_id"])

            cur.execute(
                """
                SELECT trading_account_id, account_code, venue
                FROM trading_account
                WHERE account_code = %s AND venue = %s
                ORDER BY trading_account_id
                LIMIT 2
                """,
                (account_code, venue),
            )
            ta_rows = cur.fetchall()
            if not ta_rows:
                raise RuntimeError(
                    f"TRADING_ACCOUNT_NOT_FOUND: account_code={account_code!r} venue={venue!r}"
                )
            if len(ta_rows) > 1:
                raise RuntimeError(
                    f"TRADING_ACCOUNT_AMBIGUOUS: account_code={account_code!r} venue={venue!r} "
                    f"matches {len(ta_rows)} rows"
                )
            trading_account_id = int(ta_rows[0]["trading_account_id"])

            cur.execute(
                """
                INSERT INTO app_profile_trading_account_link
                    (app_profile_id, trading_account_id, link_status, is_primary,
                     created_ts_utc, updated_ts_utc)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    link_status    = VALUES(link_status),
                    is_primary     = VALUES(is_primary),
                    updated_ts_utc = VALUES(updated_ts_utc)
                """,
                (
                    app_profile_id,
                    trading_account_id,
                    LINK_STATUS_ACTIVE,
                    1 if set_primary else 0,
                    now_text,
                    now_text,
                ),
            )
            cur.execute(
                """
                SELECT link_id FROM app_profile_trading_account_link
                WHERE app_profile_id = %s AND trading_account_id = %s
                """,
                (app_profile_id, trading_account_id),
            )
            link_row = cur.fetchone()
            return {
                "profile_code": profile_code,
                "app_profile_id": app_profile_id,
                "trading_account_id": trading_account_id,
                "account_code": account_code,
                "venue": venue,
                "is_primary": set_primary,
                "link_status": LINK_STATUS_ACTIVE,
                "link_id": int(link_row["link_id"]),
                "updated_ts_utc": now_text,
            }
        return self._with_conn(_run)
