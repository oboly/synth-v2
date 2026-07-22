from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from src.account_provisioning.contracts_v1 import (
    CredentialStatus,
    CredentialValidationState,
    StoredAccountCredential,
)

CREDENTIAL_KIND_API_KEY_SECRET = "API_KEY_SECRET"
DEFINITIVE_PRIVATE_READ_VALIDATION_ERROR_CODES = frozenset(
    {
        "INVALID_CREDENTIALS",
        "INVALID_CREDENTIALS_OR_READ_PERMISSION",
        "TRADE_PERMISSION_REQUIRED",
    }
)
_REVALIDATION_PERSISTENCE_STATES = frozenset(
    {
        CredentialValidationState.VALID_PRIVATE_READ.value,
        CredentialValidationState.INVALID_CREDENTIALS.value,
    }
)


class CredentialValidationUpdateError(RuntimeError):
    """Fail-closed exact-row validation update error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _utc_text(value: datetime) -> str:
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def _validated_ts_text(validation_state: str, now_utc: datetime) -> str | None:
    if validation_state in {"VALID_READ_ONLY", "VALID_PRIVATE_READ"}:
        return _utc_text(now_utc)
    return None


def _parse_opt_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value)).replace(tzinfo=UTC)


def _validation_update_values(
    *,
    validation_state: str,
    validated_ts_utc: datetime | None,
    safe_error_code: str | None,
) -> tuple[str, str | None, str | None]:
    if validation_state not in _REVALIDATION_PERSISTENCE_STATES:
        raise CredentialValidationUpdateError("UNSUPPORTED_VALIDATION_STATE")
    if validation_state == CredentialValidationState.VALID_PRIVATE_READ.value:
        if validated_ts_utc is None or safe_error_code is not None:
            raise CredentialValidationUpdateError("INVALID_SUCCESS_VALIDATION_UPDATE")
        return validation_state, _utc_text(validated_ts_utc), None
    if (
        validated_ts_utc is not None
        or safe_error_code not in DEFINITIVE_PRIVATE_READ_VALIDATION_ERROR_CODES
    ):
        raise CredentialValidationUpdateError("INVALID_FAILURE_VALIDATION_UPDATE")
    return validation_state, None, safe_error_code


def _row_to_stored(row: Any) -> StoredAccountCredential:
    return StoredAccountCredential(
        trading_account_credential_id=int(row["trading_account_credential_id"]),
        trading_account_id=int(row["trading_account_id"]),
        venue=str(row["venue"]),
        credential_kind=str(row["credential_kind"]),
        encrypted_envelope=str(row["encrypted_envelope"]),
        encryption_algorithm=str(row["encryption_algorithm"]),
        key_version=str(row["key_version"]),
        credential_fingerprint=str(row["credential_fingerprint"]),
        credential_status=CredentialStatus(row["credential_status"]),
        validation_state=CredentialValidationState(row["validation_state"]),
        created_ts_utc=_parse_opt_datetime(row["created_ts_utc"]),  # type: ignore[arg-type]
        validated_ts_utc=_parse_opt_datetime(row["validated_ts_utc"]),
        rotated_ts_utc=_parse_opt_datetime(row["rotated_ts_utc"]),
        revoked_ts_utc=_parse_opt_datetime(row["revoked_ts_utc"]),
    )


class CredentialRepository:
    """
    MariaDB credential repository.

    Takes a caller-owned connection. Does not commit or rollback.
    The provisioning service is responsible for transaction boundaries.

    Safety:
      broker_private_calls=0
      broker_writes=0
      order_submission=0
      executor=none
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def insert_active_credential(
        self,
        *,
        trading_account_id: int,
        venue: str,
        credential_kind: str,
        encrypted_envelope: str,
        encryption_algorithm: str,
        key_version: str,
        credential_fingerprint: str,
        now_utc: datetime,
        validation_state: str = "UNVALIDATED",
    ) -> int:
        """
        Insert an ACTIVE credential row.

        Raises ValueError(DUPLICATE_ACTIVE_CREDENTIAL) if an ACTIVE credential
        already exists for this trading_account_id + venue.
        Does not commit.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt"
                " FROM trading_account_credential"
                " WHERE trading_account_id = %s AND venue = %s AND credential_status = 'ACTIVE'",
                (trading_account_id, venue),
            )
            row = cur.fetchone()
        count = int(row["cnt"] if isinstance(row, dict) else row[0])
        if count > 0:
            raise ValueError("DUPLICATE_ACTIVE_CREDENTIAL")

        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO trading_account_credential (
                    trading_account_id, venue, credential_kind,
                    encrypted_envelope, encryption_algorithm, key_version,
                    credential_fingerprint, credential_status, validation_state,
                    created_ts_utc, validated_ts_utc
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'ACTIVE', %s, %s, %s)
                """,
                (
                    trading_account_id,
                    venue,
                    credential_kind,
                    encrypted_envelope,
                    encryption_algorithm,
                    key_version,
                    credential_fingerprint,
                    validation_state,
                    _utc_text(now_utc),
                    _validated_ts_text(validation_state, now_utc),
                ),
            )
            return int(cur.lastrowid)

    def load_active_encrypted_credential(
        self,
        *,
        trading_account_id: int,
        venue: str,
    ) -> StoredAccountCredential | None:
        """
        Load the single ACTIVE credential for this trading_account_id + venue.

        Returns None if no active credential exists.
        Raises RuntimeError if multiple active credentials exist (data integrity violation).
        Never returns plaintext credentials.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    trading_account_credential_id,
                    trading_account_id,
                    venue,
                    credential_kind,
                    encrypted_envelope,
                    encryption_algorithm,
                    key_version,
                    credential_fingerprint,
                    credential_status,
                    validation_state,
                    created_ts_utc,
                    validated_ts_utc,
                    rotated_ts_utc,
                    revoked_ts_utc
                FROM trading_account_credential
                WHERE trading_account_id = %s
                  AND venue = %s
                  AND credential_status = 'ACTIVE'
                ORDER BY trading_account_credential_id
                LIMIT 2
                """,
                (trading_account_id, venue),
            )
            rows = cur.fetchall()

        if not rows:
            return None
        if len(rows) > 1:
            raise RuntimeError(
                f"MULTIPLE_ACTIVE_CREDENTIALS: trading_account_id={trading_account_id} venue={venue!r}"
            )
        return _row_to_stored(rows[0])

    def update_existing_active_credential_validation(
        self,
        *,
        trading_account_credential_id: int,
        trading_account_id: int,
        venue: str,
        validation_state: str,
        validated_ts_utc: datetime | None,
        safe_error_code: str | None,
    ) -> int:
        """Update one exact ACTIVE credential row without committing.

        The caller owns commit/rollback. A missing or non-exact match raises so
        the transaction-owning service can roll back instead of widening the
        predicate or inferring a different credential.
        """
        state, validated_text, error_code = _validation_update_values(
            validation_state=validation_state,
            validated_ts_utc=validated_ts_utc,
            safe_error_code=safe_error_code,
        )
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE trading_account_credential
                SET validation_state = %s,
                    validated_ts_utc = %s,
                    last_validation_error_code = %s
                WHERE trading_account_credential_id = %s
                  AND trading_account_id = %s
                  AND venue = %s
                  AND credential_status = 'ACTIVE'
                """,
                (
                    state,
                    validated_text,
                    error_code,
                    trading_account_credential_id,
                    trading_account_id,
                    venue,
                ),
            )
            affected = int(cur.rowcount)
        if affected != 1:
            raise CredentialValidationUpdateError(
                "EXACT_ACTIVE_CREDENTIAL_UPDATE_REQUIRED"
            )
        return affected

    def mark_revoked(
        self,
        *,
        trading_account_credential_id: int,
        now_utc: datetime,
    ) -> None:
        """Mark a credential REVOKED. Does not commit."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE trading_account_credential
                SET credential_status = 'REVOKED',
                    revoked_ts_utc = %s
                WHERE trading_account_credential_id = %s
                """,
                (_utc_text(now_utc), trading_account_credential_id),
            )

    def mark_rotated(
        self,
        *,
        trading_account_credential_id: int,
        now_utc: datetime,
    ) -> None:
        """Mark a credential ROTATED. Does not commit."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE trading_account_credential
                SET credential_status = 'ROTATED',
                    rotated_ts_utc = %s
                WHERE trading_account_credential_id = %s
                """,
                (_utc_text(now_utc), trading_account_credential_id),
            )

    def find_by_fingerprint(
        self,
        *,
        credential_fingerprint: str,
        venue: str,
    ) -> StoredAccountCredential | None:
        """
        Return the most recent credential row matching this fingerprint + venue.

        Returns None if not found. Does not restrict by status — allows
        detection of revoked/rotated duplicates.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    trading_account_credential_id,
                    trading_account_id,
                    venue,
                    credential_kind,
                    encrypted_envelope,
                    encryption_algorithm,
                    key_version,
                    credential_fingerprint,
                    credential_status,
                    validation_state,
                    created_ts_utc,
                    validated_ts_utc,
                    rotated_ts_utc,
                    revoked_ts_utc
                FROM trading_account_credential
                WHERE credential_fingerprint = %s
                  AND venue = %s
                ORDER BY trading_account_credential_id DESC
                LIMIT 1
                """,
                (credential_fingerprint, venue),
            )
            row = cur.fetchone()
        return None if row is None else _row_to_stored(row)


# ---------------------------------------------------------------------------
# SQLite implementation for tests
# ---------------------------------------------------------------------------

class SqliteCredentialRepository:
    """
    SQLite-backed credential repository for use in tests.

    Mirrors CredentialRepository interface but uses sqlite3 connection
    with ? placeholders. Does not commit — callers own transactions.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS trading_account_credential (
        trading_account_credential_id INTEGER PRIMARY KEY AUTOINCREMENT,
        trading_account_id INTEGER NOT NULL,
        venue TEXT NOT NULL,
        credential_kind TEXT NOT NULL,
        encrypted_envelope TEXT NOT NULL,
        encryption_algorithm TEXT NOT NULL,
        key_version TEXT NOT NULL,
        credential_fingerprint TEXT NOT NULL,
        credential_status TEXT NOT NULL DEFAULT 'ACTIVE',
        validation_state TEXT NOT NULL DEFAULT 'UNVALIDATED',
        created_ts_utc TEXT NOT NULL,
        validated_ts_utc TEXT NULL,
        rotated_ts_utc TEXT NULL,
        revoked_ts_utc TEXT NULL,
        credential_source TEXT NOT NULL DEFAULT 'db_encrypted',
        permission_scope TEXT NOT NULL DEFAULT 'READ_ONLY_PRIVATE',
        allowed_private_read INTEGER NOT NULL DEFAULT 1,
        allowed_order_write INTEGER NOT NULL DEFAULT 0,
        allowed_withdrawal INTEGER NOT NULL DEFAULT 0,
        last_validation_error_code TEXT NULL,
        CHECK (credential_status IN ('ACTIVE', 'REVOKED', 'ROTATED', 'INVALID')),
        CHECK (validation_state IN ('UNVALIDATED', 'VALID_READ_ONLY', 'VALID_PRIVATE_READ', 'INVALID_CREDENTIALS'))
    );
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    def create_schema(self) -> None:
        self._conn.executescript(self._SCHEMA)

    def _fetchall(self, sql: str, params: tuple) -> list[sqlite3.Row]:
        cur = self._conn.execute(sql.replace("%s", "?"), params)
        return cur.fetchall()

    def _fetchone(self, sql: str, params: tuple) -> sqlite3.Row | None:
        cur = self._conn.execute(sql.replace("%s", "?"), params)
        return cur.fetchone()

    def _execute(self, sql: str, params: tuple) -> int:
        cur = self._conn.execute(sql.replace("%s", "?"), params)
        return cur.lastrowid or 0

    def insert_active_credential(
        self,
        *,
        trading_account_id: int,
        venue: str,
        credential_kind: str,
        encrypted_envelope: str,
        encryption_algorithm: str,
        key_version: str,
        credential_fingerprint: str,
        now_utc: datetime,
        validation_state: str = "UNVALIDATED",
    ) -> int:
        row = self._fetchone(
            "SELECT COUNT(*) AS cnt FROM trading_account_credential"
            " WHERE trading_account_id = %s AND venue = %s AND credential_status = 'ACTIVE'",
            (trading_account_id, venue),
        )
        if row is not None and int(row["cnt"]) > 0:
            raise ValueError("DUPLICATE_ACTIVE_CREDENTIAL")

        return self._execute(
            """
            INSERT INTO trading_account_credential (
                trading_account_id, venue, credential_kind,
                encrypted_envelope, encryption_algorithm, key_version,
                credential_fingerprint, credential_status, validation_state,
                created_ts_utc, validated_ts_utc
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'ACTIVE', %s, %s, %s)
            """,
            (
                trading_account_id,
                venue,
                credential_kind,
                encrypted_envelope,
                encryption_algorithm,
                key_version,
                credential_fingerprint,
                validation_state,
                _utc_text(now_utc),
                _validated_ts_text(validation_state, now_utc),
            ),
        )

    def load_active_encrypted_credential(
        self,
        *,
        trading_account_id: int,
        venue: str,
    ) -> StoredAccountCredential | None:
        rows = self._fetchall(
            """
            SELECT
                trading_account_credential_id,
                trading_account_id,
                venue,
                credential_kind,
                encrypted_envelope,
                encryption_algorithm,
                key_version,
                credential_fingerprint,
                credential_status,
                validation_state,
                created_ts_utc,
                validated_ts_utc,
                rotated_ts_utc,
                revoked_ts_utc
            FROM trading_account_credential
            WHERE trading_account_id = %s
              AND venue = %s
              AND credential_status = 'ACTIVE'
            ORDER BY trading_account_credential_id
            LIMIT 2
            """,
            (trading_account_id, venue),
        )
        if not rows:
            return None
        if len(rows) > 1:
            raise RuntimeError(
                f"MULTIPLE_ACTIVE_CREDENTIALS: trading_account_id={trading_account_id} venue={venue!r}"
            )
        return _row_to_stored(rows[0])

    def update_existing_active_credential_validation(
        self,
        *,
        trading_account_credential_id: int,
        trading_account_id: int,
        venue: str,
        validation_state: str,
        validated_ts_utc: datetime | None,
        safe_error_code: str | None,
    ) -> int:
        """SQLite equivalent of the caller-owned exact ACTIVE-row update."""
        state, validated_text, error_code = _validation_update_values(
            validation_state=validation_state,
            validated_ts_utc=validated_ts_utc,
            safe_error_code=safe_error_code,
        )
        cur = self._conn.execute(
            """
            UPDATE trading_account_credential
            SET validation_state = %s,
                validated_ts_utc = %s,
                last_validation_error_code = %s
            WHERE trading_account_credential_id = %s
              AND trading_account_id = %s
              AND venue = %s
              AND credential_status = 'ACTIVE'
            """.replace("%s", "?"),
            (
                state,
                validated_text,
                error_code,
                trading_account_credential_id,
                trading_account_id,
                venue,
            ),
        )
        affected = int(cur.rowcount)
        if affected != 1:
            raise CredentialValidationUpdateError(
                "EXACT_ACTIVE_CREDENTIAL_UPDATE_REQUIRED"
            )
        return affected

    def mark_revoked(
        self,
        *,
        trading_account_credential_id: int,
        now_utc: datetime,
    ) -> None:
        self._execute(
            """
            UPDATE trading_account_credential
            SET credential_status = 'REVOKED',
                revoked_ts_utc = %s
            WHERE trading_account_credential_id = %s
            """,
            (_utc_text(now_utc), trading_account_credential_id),
        )

    def mark_rotated(
        self,
        *,
        trading_account_credential_id: int,
        now_utc: datetime,
    ) -> None:
        self._execute(
            """
            UPDATE trading_account_credential
            SET credential_status = 'ROTATED',
                rotated_ts_utc = %s
            WHERE trading_account_credential_id = %s
            """,
            (_utc_text(now_utc), trading_account_credential_id),
        )

    def find_by_fingerprint(
        self,
        *,
        credential_fingerprint: str,
        venue: str,
    ) -> StoredAccountCredential | None:
        row = self._fetchone(
            """
            SELECT
                trading_account_credential_id,
                trading_account_id,
                venue,
                credential_kind,
                encrypted_envelope,
                encryption_algorithm,
                key_version,
                credential_fingerprint,
                credential_status,
                validation_state,
                created_ts_utc,
                validated_ts_utc,
                rotated_ts_utc,
                revoked_ts_utc
            FROM trading_account_credential
            WHERE credential_fingerprint = %s
              AND venue = %s
            ORDER BY trading_account_credential_id DESC
            LIMIT 1
            """,
            (credential_fingerprint, venue),
        )
        return None if row is None else _row_to_stored(row)
