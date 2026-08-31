"""Provision a new READ_ONLY_PRIVATE credential for an already-existing,
already-enabled trading_account + venue pair.

This module never creates or mutates ``trading_account`` rows, never touches
``app_profile_trading_account_link``, and never reads, updates, revokes, or
rotates an existing TRADE_EXECUTION credential row. It only ever inserts one
new ``trading_account_credential`` row scoped to
``permission_scope='READ_ONLY_PRIVATE'``.

An existing ACTIVE credential with ``allowed_private_read=1`` under a
different permission_scope (for example TRADE_EXECUTION) does NOT satisfy the
READ_ONLY_PRIVATE binding grain. The canonical binding grain enforced here and
by the DB's ``uq_tac_active_account_venue_scope_v1`` unique index is
``trading_account_id + venue + permission_scope`` -- TRADE_EXECUTION and
READ_ONLY_PRIVATE are always separate rows, even when both happen to carry
``allowed_private_read=1``. See
``docs/ops/existing_account_private_read_credential_provisioning_v1.md``.

Validation runs before any row is persisted: the plaintext credential is
checked with the injected validator first, and a row is inserted only once
validation reports ``VALID_PRIVATE_READ``. Invalid or unavailable validation
results in no row being written at all -- there is no intermediate
UNVALIDATED row and therefore nothing to half-provision.

Safety:
  broker_private_calls=validator_result_only (<=2 for the real validator)
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Final

from src.account_provisioning.contracts_v1 import PlainBitvavoCredential
from src.account_provisioning.credential_crypto_v1 import compute_fingerprint, encrypt_credential
from src.account_provisioning.credential_repository_v1 import CREDENTIAL_KIND_API_KEY_SECRET

BITVAVO_VENUE: Final[str] = "bitvavo"
READ_ONLY_PRIVATE_SCOPE: Final[str] = "READ_ONLY_PRIVATE"
VALID_PRIVATE_READ_STATE: Final[str] = "VALID_PRIVATE_READ"
VALIDATION_UNAVAILABLE_CODE: Final[str] = "VALIDATION_UNAVAILABLE"

STATUS_READY: Final[str] = "READY"
STATUS_ALREADY_PROVISIONED: Final[str] = "ALREADY_PROVISIONED"
STATUS_BLOCKED: Final[str] = "BLOCKED"
STATUS_CREATED: Final[str] = "CREATED"
STATUS_VALIDATION_FAILED: Final[str] = "VALIDATION_FAILED"
STATUS_VALIDATION_UNAVAILABLE: Final[str] = "VALIDATION_UNAVAILABLE"


def _value(row: Any, key: str, index: int) -> Any:
    return row[key] if isinstance(row, dict) else row[index]


@dataclass(frozen=True)
class ReadinessResult:
    status: str  # READY | ALREADY_PROVISIONED | BLOCKED
    trading_account_id: int
    venue: str
    account_mode: str | None = None
    trading_account_credential_id: int | None = None
    blocker: str | None = None


@dataclass(frozen=True)
class ProvisioningResult:
    status: str  # CREATED | ALREADY_PROVISIONED | VALIDATION_FAILED | VALIDATION_UNAVAILABLE
    trading_account_id: int
    venue: str
    trading_account_credential_id: int | None
    validation_state: str | None
    validated_ts_utc_present: bool
    safe_error_code: str | None
    broker_private_calls: int


class ExistingAccountPrivateReadProvisioningRepository:
    """Non-secret metadata queries and one scoped insert; caller owns the transaction."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def _one(self, sql: str, params: tuple[Any, ...]) -> Any | None:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        if len(rows) > 1:
            raise ValueError("AMBIGUOUS_EXACT_IDENTITY")
        return rows[0] if rows else None

    def find_account(self, *, trading_account_id: int, venue: str) -> Any | None:
        return self._one(
            "SELECT trading_account_id, venue, account_mode, enabled "
            "FROM trading_account WHERE trading_account_id = %s AND venue = %s",
            (trading_account_id, venue),
        )

    def find_active_credential(
        self, *, trading_account_id: int, venue: str, permission_scope: str
    ) -> Any | None:
        """Look up the ACTIVE credential for one exact (account, venue, scope).

        Scoped by ``permission_scope`` so an existing ACTIVE TRADE_EXECUTION
        row is never observed here and never blocks READ_ONLY_PRIVATE
        provisioning -- the two scopes are independent rows under the DB's
        ``uq_tac_active_account_venue_scope_v1`` unique index.
        """
        return self._one(
            "SELECT trading_account_credential_id, credential_status, permission_scope, "
            "validation_state, validated_ts_utc FROM trading_account_credential "
            "WHERE trading_account_id = %s AND venue = %s AND permission_scope = %s "
            "AND credential_status = 'ACTIVE' ORDER BY trading_account_credential_id LIMIT 2",
            (trading_account_id, venue, permission_scope),
        )

    def insert_active_credential(
        self,
        *,
        trading_account_id: int,
        venue: str,
        encrypted_envelope: str,
        encryption_algorithm: str,
        key_version: str,
        credential_fingerprint: str,
        validation_state: str,
        validated_ts_utc: datetime,
        now_utc: datetime,
    ) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO trading_account_credential (trading_account_id, venue, credential_kind, "
                "encrypted_envelope, encryption_algorithm, key_version, credential_fingerprint, "
                "credential_status, validation_state, credential_source, permission_scope, "
                "allowed_private_read, allowed_order_write, allowed_withdrawal, created_ts_utc, "
                "validated_ts_utc) VALUES (%s,%s,%s,%s,%s,%s,%s,'ACTIVE',%s,'db_encrypted',"
                "'READ_ONLY_PRIVATE',1,0,0,%s,%s)",
                (
                    trading_account_id,
                    venue,
                    CREDENTIAL_KIND_API_KEY_SECRET,
                    encrypted_envelope,
                    encryption_algorithm,
                    key_version,
                    credential_fingerprint,
                    validation_state,
                    now_utc.astimezone(UTC).replace(tzinfo=None),
                    validated_ts_utc.astimezone(UTC).replace(tzinfo=None),
                ),
            )
            return int(cur.lastrowid)


def _account_blocker(account: Any | None) -> str | None:
    if account is None:
        return "TRADING_ACCOUNT_VENUE_NOT_FOUND"
    if not bool(_value(account, "enabled", 3)):
        return "ACCOUNT_DISABLED"
    return None


def check_readiness(
    *,
    trading_account_id: int,
    venue: str,
    conn_factory: Callable[[], Any],
    repository_factory: Callable[[Any], Any] = ExistingAccountPrivateReadProvisioningRepository,
) -> ReadinessResult:
    """Metadata-only readiness check. No decryption, no broker calls, no writes."""
    conn = conn_factory()
    try:
        repo = repository_factory(conn)
        account = repo.find_account(trading_account_id=trading_account_id, venue=venue)
        blocker = _account_blocker(account)
        if blocker is not None:
            return ReadinessResult(
                status=STATUS_BLOCKED,
                trading_account_id=trading_account_id,
                venue=venue,
                blocker=blocker,
            )
        account_mode = str(_value(account, "account_mode", 2))
        existing = repo.find_active_credential(
            trading_account_id=trading_account_id,
            venue=venue,
            permission_scope=READ_ONLY_PRIVATE_SCOPE,
        )
        if existing is not None:
            return ReadinessResult(
                status=STATUS_ALREADY_PROVISIONED,
                trading_account_id=trading_account_id,
                venue=venue,
                account_mode=account_mode,
                trading_account_credential_id=int(
                    _value(existing, "trading_account_credential_id", 0)
                ),
            )
        return ReadinessResult(
            status=STATUS_READY,
            trading_account_id=trading_account_id,
            venue=venue,
            account_mode=account_mode,
        )
    finally:
        conn.close()


def provision_existing_private_read_credential(
    *,
    trading_account_id: int,
    venue: str,
    api_key: str,
    api_secret: str,
    master_key_version: str,
    master_key_bytes: bytes,
    validator: Any,
    conn_factory: Callable[[], Any],
    repository_factory: Callable[[Any], Any] = ExistingAccountPrivateReadProvisioningRepository,
    now_utc: datetime | None = None,
) -> ProvisioningResult:
    """Validate then persist one new READ_ONLY_PRIVATE credential.

    Fails closed with no row written on: missing/disabled/venue-mismatched
    account, an existing ACTIVE READ_ONLY_PRIVATE credential (idempotent
    ``ALREADY_PROVISIONED``, never silently replaced), or a validator result
    other than ``VALID_PRIVATE_READ``.
    """
    if venue != BITVAVO_VENUE:
        raise ValueError("UNSUPPORTED_VENUE")

    credential = PlainBitvavoCredential(venue=venue, api_key=api_key, api_secret=api_secret)
    conn = conn_factory()
    try:
        repo = repository_factory(conn)
        account = repo.find_account(trading_account_id=trading_account_id, venue=venue)
        blocker = _account_blocker(account)
        if blocker is not None:
            conn.rollback()
            raise ValueError(blocker)

        existing = repo.find_active_credential(
            trading_account_id=trading_account_id,
            venue=venue,
            permission_scope=READ_ONLY_PRIVATE_SCOPE,
        )
        if existing is not None:
            conn.rollback()
            return ProvisioningResult(
                status=STATUS_ALREADY_PROVISIONED,
                trading_account_id=trading_account_id,
                venue=venue,
                trading_account_credential_id=int(
                    _value(existing, "trading_account_credential_id", 0)
                ),
                validation_state=str(_value(existing, "validation_state", 3)),
                validated_ts_utc_present=_value(existing, "validated_ts_utc", 4) is not None,
                safe_error_code=None,
                broker_private_calls=0,
            )

        try:
            validation = validator.validate(credential)
        except Exception:
            conn.rollback()
            return ProvisioningResult(
                status=STATUS_VALIDATION_UNAVAILABLE,
                trading_account_id=trading_account_id,
                venue=venue,
                trading_account_credential_id=None,
                validation_state=None,
                validated_ts_utc_present=False,
                safe_error_code=VALIDATION_UNAVAILABLE_CODE,
                broker_private_calls=0,
            )

        broker_private_calls = validation.broker_private_calls
        if not isinstance(broker_private_calls, int) or broker_private_calls < 0:
            broker_private_calls = 0

        if (
            validation.validation_state == VALIDATION_UNAVAILABLE_CODE
            or validation.safe_error_code == VALIDATION_UNAVAILABLE_CODE
        ):
            conn.rollback()
            return ProvisioningResult(
                status=STATUS_VALIDATION_UNAVAILABLE,
                trading_account_id=trading_account_id,
                venue=venue,
                trading_account_credential_id=None,
                validation_state=None,
                validated_ts_utc_present=False,
                safe_error_code=VALIDATION_UNAVAILABLE_CODE,
                broker_private_calls=broker_private_calls,
            )

        if not (validation.success and validation.validation_state == VALID_PRIVATE_READ_STATE):
            conn.rollback()
            return ProvisioningResult(
                status=STATUS_VALIDATION_FAILED,
                trading_account_id=trading_account_id,
                venue=venue,
                trading_account_credential_id=None,
                validation_state=None,
                validated_ts_utc_present=False,
                safe_error_code=validation.safe_error_code or "INVALID_CREDENTIALS",
                broker_private_calls=broker_private_calls,
            )

        validated_at = now_utc or datetime.now(UTC)
        fingerprint = compute_fingerprint(venue, api_key, master_key_bytes)
        envelope = encrypt_credential(credential, trading_account_id, master_key_version, master_key_bytes)
        credential_id = repo.insert_active_credential(
            trading_account_id=trading_account_id,
            venue=venue,
            encrypted_envelope=envelope.to_json(),
            encryption_algorithm=envelope.alg,
            key_version=envelope.kv,
            credential_fingerprint=fingerprint,
            validation_state=VALID_PRIVATE_READ_STATE,
            validated_ts_utc=validated_at,
            now_utc=validated_at,
        )
        conn.commit()
        return ProvisioningResult(
            status=STATUS_CREATED,
            trading_account_id=trading_account_id,
            venue=venue,
            trading_account_credential_id=credential_id,
            validation_state=VALID_PRIVATE_READ_STATE,
            validated_ts_utc_present=True,
            safe_error_code=None,
            broker_private_calls=broker_private_calls,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
