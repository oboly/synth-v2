"""
manual_execution_request_v1 — canonical immutable manual execution request.

Layer: upstream of decision_gate. Account-aware. This is the single request
parent named as missing in
docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md
finding F12 and docs/todo/manual_execution_ladder_future_readiness_backlog_v1.md
backlog item 7, and confirmed as the root cause of the BLOCK/REJECT
independent review at
docs/reviews/manual_execution_ladder_p0_implementation_review_20260725.md
(finding B1: no request parent; B6: provenance has no request to bind to).

A ManualExecutionRequest records one user's manual execution *intent* only.
It is not an approval and not execution authority — see
src.decision_gate.manual_execution_gate_v1 for the permission decision and
src.manual_execution.manual_execution_service_v1 for the one canonical
orchestration entrypoint that turns a request into a plan preview.

By construction, this dataclass has no field for a free/available base
quantity, an approval or decision state, a tick size, a quantity/amount
step, a minimum quantity/notional, or an executable broker order intent.
There is no keyword a caller can pass to fabricate any of those — they do
not exist on this type. build_manual_execution_request() also rejects any
unexpected keyword argument (Python's own TypeError), so passing one of
those names raises immediately rather than being silently ignored.

Immutability: the request's identity/content fields never change after
construction. Only request_state (and the paired processed_ts_utc/
rejection_* fields) may advance, and only through
advance_manual_execution_request_state() using the fixed transition table
below — mirroring the discipline src.decision_gate.sell_reservation_v1
already uses for reservation_state. A content change must create a new
request (new idempotency_key), never mutate an in-flight one.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Final


MODE_PAPER: Final[str] = "PAPER"
MODE_LIVE: Final[str] = "LIVE"
VALID_MODES: Final[frozenset[str]] = frozenset({MODE_PAPER, MODE_LIVE})

VALID_SIDES: Final[frozenset[str]] = frozenset({"BUY", "SELL"})

SOURCE_OPERATOR_CLI: Final[str] = "OPERATOR_CLI"
SOURCE_COCKPIT_UI: Final[str] = "COCKPIT_UI"
VALID_SOURCES: Final[frozenset[str]] = frozenset({SOURCE_OPERATOR_CLI, SOURCE_COCKPIT_UI})

QUANTITY_POLICY_FULL_AVAILABLE_BASE: Final[str] = "FULL_AVAILABLE_BASE"
QUANTITY_POLICY_FIXED_BASE_QUANTITY: Final[str] = "FIXED_BASE_QUANTITY"
QUANTITY_POLICY_FIXED_QUOTE_NOTIONAL: Final[str] = "FIXED_QUOTE_NOTIONAL"
QUANTITY_POLICY_LADDER_LEVELS: Final[str] = "LADDER_LEVELS"
VALID_QUANTITY_POLICIES: Final[frozenset[str]] = frozenset(
    {
        QUANTITY_POLICY_FULL_AVAILABLE_BASE,
        QUANTITY_POLICY_FIXED_BASE_QUANTITY,
        QUANTITY_POLICY_FIXED_QUOTE_NOTIONAL,
        QUANTITY_POLICY_LADDER_LEVELS,
    }
)

REQUEST_STATE_DRAFT: Final[str] = "DRAFT"
REQUEST_STATE_GATE_BLOCKED: Final[str] = "GATE_BLOCKED"
REQUEST_STATE_PLANNED: Final[str] = "PLANNED"
REQUEST_STATE_PLAN_REJECTED: Final[str] = "PLAN_REJECTED"
REQUEST_STATE_FAILED: Final[str] = "FAILED"

# Single-hop transitions only: this request contract does not yet cover
# submission/reconciliation lifecycle stages (out of scope — see
# docs/reviews/manual_execution_ladder_p0_remediation_implementation_20260726.md).
_ALLOWED_STATE_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    REQUEST_STATE_DRAFT: frozenset(
        {
            REQUEST_STATE_GATE_BLOCKED,
            REQUEST_STATE_PLANNED,
            REQUEST_STATE_PLAN_REJECTED,
            REQUEST_STATE_FAILED,
        }
    ),
}

CURRENT_SCHEMA_VERSION: Final[int] = 1

SCHEMA_VERSION = CURRENT_SCHEMA_VERSION


class ManualExecutionRequestValidationError(ValueError):
    pass


class InvalidManualExecutionRequestTransitionError(ValueError):
    pass


@dataclass(frozen=True)
class ManualExecutionRequest:
    request_id: int | None
    schema_version: int
    idempotency_key: str
    created_ts_utc: datetime
    source: str
    requested_by: str
    mode: str  # PAPER | LIVE

    trading_account_id: int
    account_code: str
    venue: str
    asset_id: int
    base_asset: str
    quote_asset: str

    side: str  # BUY | SELL

    quantity_policy: str
    requested_base_quantity: Decimal | None
    requested_quote_notional: Decimal | None
    ladder_levels: tuple[tuple[Decimal, Decimal], ...]

    provenance_id: int | None

    # Immutable binding to the profile and public map context selected by the
    # operator.  These are intent/provenance, never a permission result.
    operator_request_nonce: str | None
    dedupe_key: str | None
    ladder_profile_id: int | None
    ladder_profile_version: int | None
    anchor_type: str | None
    anchor_price: Decimal | None
    anchor_source: str | None
    source_map_cycle_id: str | None
    source_native_map_id: str | None
    source_map_version: str | None

    request_state: str
    rejection_code: str | None
    rejection_detail: str | None
    processed_ts_utc: datetime | None


def _require_positive_decimal(value: Decimal, field_name: str) -> None:
    if value <= 0:
        raise ManualExecutionRequestValidationError(f"{field_name} must be > 0")


def _validate_quantity_policy_payload(
    *,
    quantity_policy: str,
    requested_base_quantity: Decimal | None,
    requested_quote_notional: Decimal | None,
    ladder_levels: tuple[tuple[Decimal, Decimal], ...],
) -> None:
    if quantity_policy == QUANTITY_POLICY_FULL_AVAILABLE_BASE:
        if requested_base_quantity is not None or requested_quote_notional is not None or ladder_levels:
            raise ManualExecutionRequestValidationError(
                "FULL_AVAILABLE_BASE must not carry a base quantity, quote notional, or ladder levels"
            )
        return

    if quantity_policy == QUANTITY_POLICY_FIXED_BASE_QUANTITY:
        if requested_base_quantity is None:
            raise ManualExecutionRequestValidationError(
                "FIXED_BASE_QUANTITY requires requested_base_quantity"
            )
        _require_positive_decimal(requested_base_quantity, "requested_base_quantity")
        if requested_quote_notional is not None or ladder_levels:
            raise ManualExecutionRequestValidationError(
                "FIXED_BASE_QUANTITY must not also carry a quote notional or ladder levels"
            )
        return

    if quantity_policy == QUANTITY_POLICY_FIXED_QUOTE_NOTIONAL:
        if requested_quote_notional is None:
            raise ManualExecutionRequestValidationError(
                "FIXED_QUOTE_NOTIONAL requires requested_quote_notional"
            )
        _require_positive_decimal(requested_quote_notional, "requested_quote_notional")
        if requested_base_quantity is not None or ladder_levels:
            raise ManualExecutionRequestValidationError(
                "FIXED_QUOTE_NOTIONAL must not also carry a base quantity or ladder levels"
            )
        return

    if quantity_policy == QUANTITY_POLICY_LADDER_LEVELS:
        if not ladder_levels:
            raise ManualExecutionRequestValidationError(
                "LADDER_LEVELS requires at least one (price, fraction) level"
            )
        for price, fraction in ladder_levels:
            _require_positive_decimal(price, "ladder level price")
            _require_positive_decimal(fraction, "ladder level fraction")
        if requested_base_quantity is not None or requested_quote_notional is not None:
            raise ManualExecutionRequestValidationError(
                "LADDER_LEVELS must not also carry a fixed base quantity or quote notional"
            )
        return

    raise ManualExecutionRequestValidationError(f"unknown quantity_policy: {quantity_policy}")


def build_manual_execution_request(
    *,
    idempotency_key: str,
    created_ts_utc: datetime,
    source: str,
    requested_by: str,
    mode: str,
    trading_account_id: int,
    account_code: str,
    venue: str,
    asset_id: int,
    base_asset: str,
    quote_asset: str,
    side: str,
    quantity_policy: str,
    requested_base_quantity: Decimal | None = None,
    requested_quote_notional: Decimal | None = None,
    ladder_levels: tuple[tuple[Decimal, Decimal], ...] = (),
    provenance_id: int | None = None,
    operator_request_nonce: str | None = None,
    ladder_profile_id: int | None = None,
    ladder_profile_version: int | None = None,
    anchor_type: str | None = None,
    anchor_price: Decimal | None = None,
    anchor_source: str | None = None,
    source_map_cycle_id: str | None = None,
    source_native_map_id: str | None = None,
    source_map_version: str | None = None,
) -> ManualExecutionRequest:
    """Construct a validated, not-yet-persisted, DRAFT manual execution request.

    Fails closed on any missing/contradictory field. Only the fields listed
    in this signature are accepted — there is no keyword for free base
    quantity, approval/decision state, tick size, amount step, minimum
    quantity/notional, or a broker order intent, so passing any of those
    names raises TypeError before this function body ever runs.
    """
    if not idempotency_key.strip():
        raise ManualExecutionRequestValidationError("idempotency_key is required")
    if source not in VALID_SOURCES:
        raise ManualExecutionRequestValidationError(f"unknown source: {source}")
    if not requested_by.strip():
        raise ManualExecutionRequestValidationError("requested_by is required")
    if mode not in VALID_MODES:
        raise ManualExecutionRequestValidationError(f"mode must be one of {sorted(VALID_MODES)}")
    if trading_account_id <= 0:
        raise ManualExecutionRequestValidationError("trading_account_id must be > 0")
    if not account_code.strip():
        raise ManualExecutionRequestValidationError("account_code is required")
    if not venue.strip():
        raise ManualExecutionRequestValidationError("venue is required")
    if asset_id <= 0:
        raise ManualExecutionRequestValidationError("asset_id must be > 0")
    if not base_asset.strip():
        raise ManualExecutionRequestValidationError("base_asset is required")
    if not quote_asset.strip():
        raise ManualExecutionRequestValidationError("quote_asset is required")
    if side not in VALID_SIDES:
        raise ManualExecutionRequestValidationError(f"side must be one of {sorted(VALID_SIDES)}")
    if quantity_policy not in VALID_QUANTITY_POLICIES:
        raise ManualExecutionRequestValidationError(f"unknown quantity_policy: {quantity_policy}")

    _validate_quantity_policy_payload(
        quantity_policy=quantity_policy,
        requested_base_quantity=requested_base_quantity,
        requested_quote_notional=requested_quote_notional,
        ladder_levels=ladder_levels,
    )

    binding_values = (
        ladder_profile_id, ladder_profile_version, anchor_type, anchor_price,
        anchor_source, source_map_cycle_id, source_native_map_id, source_map_version,
    )
    if any(value is not None for value in binding_values):
        if not all(value is not None for value in binding_values):
            raise ManualExecutionRequestValidationError(
                "profile/anchor/source-map binding must be complete when supplied"
            )
        if ladder_profile_id <= 0 or ladder_profile_version <= 0:  # type: ignore[operator]
            raise ManualExecutionRequestValidationError("ladder profile identity must be positive")
        _require_positive_decimal(anchor_price, "anchor_price")  # type: ignore[arg-type]
        if not all(str(value).strip() for value in binding_values[2::]):
            raise ManualExecutionRequestValidationError("profile/anchor/source-map binding values are required")
    if operator_request_nonce is not None and not operator_request_nonce.strip():
        raise ManualExecutionRequestValidationError("operator_request_nonce must not be blank")

    canonical_dedupe_key = _derive_dedupe_key(
        idempotency_key=idempotency_key,
        operator_request_nonce=operator_request_nonce,
        trading_account_id=trading_account_id,
        asset_id=asset_id,
        venue=venue,
        base_asset=base_asset,
        quote_asset=quote_asset,
        source=source,
        requested_by=requested_by,
        mode=mode,
        side=side,
        quantity_policy=quantity_policy,
        requested_base_quantity=requested_base_quantity,
        requested_quote_notional=requested_quote_notional,
        ladder_profile_id=ladder_profile_id,
        ladder_profile_version=ladder_profile_version,
        ladder_levels=ladder_levels,
        provenance_id=provenance_id,
        anchor_type=anchor_type,
        anchor_price=anchor_price,
        anchor_source=anchor_source,
        source_map_cycle_id=source_map_cycle_id,
        source_native_map_id=source_native_map_id,
        source_map_version=source_map_version,
    )

    return ManualExecutionRequest(
        request_id=None,
        schema_version=CURRENT_SCHEMA_VERSION,
        idempotency_key=idempotency_key.strip(),
        created_ts_utc=created_ts_utc,
        source=source,
        requested_by=requested_by.strip(),
        mode=mode,
        trading_account_id=trading_account_id,
        account_code=account_code.strip(),
        venue=venue.strip().lower(),
        asset_id=asset_id,
        base_asset=base_asset.strip().upper(),
        quote_asset=quote_asset.strip().upper(),
        side=side,
        quantity_policy=quantity_policy,
        requested_base_quantity=requested_base_quantity,
        requested_quote_notional=requested_quote_notional,
        ladder_levels=tuple(ladder_levels),
        provenance_id=provenance_id,
        operator_request_nonce=(operator_request_nonce.strip() if operator_request_nonce else None),
        dedupe_key=canonical_dedupe_key,
        ladder_profile_id=ladder_profile_id,
        ladder_profile_version=ladder_profile_version,
        anchor_type=(anchor_type.strip() if anchor_type else None),
        anchor_price=anchor_price,
        anchor_source=(anchor_source.strip() if anchor_source else None),
        source_map_cycle_id=(source_map_cycle_id.strip() if source_map_cycle_id else None),
        source_native_map_id=(source_native_map_id.strip() if source_native_map_id else None),
        source_map_version=(source_map_version.strip() if source_map_version else None),
        request_state=REQUEST_STATE_DRAFT,
        rejection_code=None,
        rejection_detail=None,
        processed_ts_utc=None,
    )


def _derive_dedupe_key(
    *,
    idempotency_key: str,
    operator_request_nonce: str | None,
    trading_account_id: int,
    asset_id: int,
    venue: str,
    base_asset: str,
    quote_asset: str,
    source: str,
    requested_by: str,
    mode: str,
    side: str,
    quantity_policy: str,
    requested_base_quantity: Decimal | None,
    requested_quote_notional: Decimal | None,
    ladder_profile_id: int | None,
    ladder_profile_version: int | None,
    ladder_levels: tuple[tuple[Decimal, Decimal], ...],
    provenance_id: int | None,
    anchor_type: str | None,
    anchor_price: Decimal | None,
    anchor_source: str | None,
    source_map_cycle_id: str | None,
    source_native_map_id: str | None,
    source_map_version: str | None,
) -> str:
    """Stable DB-enforced retry identity.

    A caller nonce distinguishes a genuinely new Process action.  The legacy
    idempotency key remains part of the digest for compatible callers that do
    not yet supply a nonce.
    """
    payload = {
        "account": trading_account_id,
        "asset": asset_id,
        "nonce": operator_request_nonce.strip() if operator_request_nonce else None,
        "profile": [ladder_profile_id, ladder_profile_version],
        "provenance": provenance_id,
        "quantity": [str(requested_base_quantity) if requested_base_quantity else None,
                     str(requested_quote_notional) if requested_quote_notional else None,
        ],
        "quantity_policy": quantity_policy,
        "side": side,
        "operator": [source, requested_by.strip()],
        "market": [venue.strip().lower(), base_asset.strip().upper(), quote_asset.strip().upper()],
        "mode": mode,
        "levels": [[str(price), str(fraction)] for price, fraction in ladder_levels],
        "anchor": [anchor_type, str(anchor_price) if anchor_price else None, anchor_source],
        "source_map": [source_map_cycle_id, source_native_map_id, source_map_version],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def advance_manual_execution_request_state(
    request: ManualExecutionRequest,
    *,
    new_state: str,
    processed_ts_utc: datetime,
    rejection_code: str | None = None,
    rejection_detail: str | None = None,
) -> ManualExecutionRequest:
    """The only permitted state-transition path. Content fields are never
    touched; only request_state/processed_ts_utc/rejection_* change."""
    allowed = _ALLOWED_STATE_TRANSITIONS.get(request.request_state, frozenset())
    if new_state not in allowed:
        raise InvalidManualExecutionRequestTransitionError(
            f"request_id={request.request_id} cannot transition "
            f"{request.request_state} -> {new_state}"
        )

    return dataclasses.replace(
        request,
        request_state=new_state,
        processed_ts_utc=processed_ts_utc,
        rejection_code=rejection_code,
        rejection_detail=rejection_detail,
    )


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor

    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    if isinstance(db_obj, tuple):
        return db_obj[1]
    return db_obj


def _ladder_levels_to_json(ladder_levels: tuple[tuple[Decimal, Decimal], ...]) -> str:
    import json

    return json.dumps([[str(price), str(fraction)] for price, fraction in ladder_levels])


def _ladder_levels_from_json(raw: Any) -> tuple[tuple[Decimal, Decimal], ...]:
    import json

    if not raw:
        return ()
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    return tuple((Decimal(str(price)), Decimal(str(fraction))) for price, fraction in parsed)


def _row_to_request(row: Any) -> ManualExecutionRequest:
    return ManualExecutionRequest(
        request_id=int(row["manual_execution_request_id"]),
        schema_version=int(row["schema_version"]),
        idempotency_key=str(row["idempotency_key"]),
        created_ts_utc=row["created_ts_utc"],
        source=str(row["source"]),
        requested_by=str(row["requested_by"]),
        mode=str(row["mode"]),
        trading_account_id=int(row["trading_account_id"]),
        account_code=str(row["account_code"]),
        venue=str(row["venue"]),
        asset_id=int(row["asset_id"]),
        base_asset=str(row["base_asset"]),
        quote_asset=str(row["quote_asset"]),
        side=str(row["side"]),
        quantity_policy=str(row["quantity_policy"]),
        requested_base_quantity=(
            Decimal(str(row["requested_base_quantity"]))
            if row.get("requested_base_quantity") is not None
            else None
        ),
        requested_quote_notional=(
            Decimal(str(row["requested_quote_notional"]))
            if row.get("requested_quote_notional") is not None
            else None
        ),
        ladder_levels=_ladder_levels_from_json(row.get("ladder_levels_json")),
        provenance_id=row.get("provenance_id"),
        operator_request_nonce=row.get("operator_request_nonce"),
        dedupe_key=row.get("dedupe_key"),
        ladder_profile_id=row.get("ladder_profile_id"),
        ladder_profile_version=row.get("ladder_profile_version"),
        anchor_type=row.get("anchor_type"),
        anchor_price=(Decimal(str(row["anchor_price"])) if row.get("anchor_price") is not None else None),
        anchor_source=row.get("anchor_source"),
        source_map_cycle_id=row.get("source_map_cycle_id"),
        source_native_map_id=row.get("source_native_map_id"),
        source_map_version=row.get("source_map_version"),
        request_state=str(row["request_state"]),
        rejection_code=row.get("rejection_code"),
        rejection_detail=row.get("rejection_detail"),
        processed_ts_utc=row.get("processed_ts_utc"),
    )


@dataclass
class ManualExecutionRequestRepository:
    """Persists ManualExecutionRequest rows. Requires the
    manual_execution_request table from
    db/migrations/20260726_manual_execution_request_v1.sql, which is created
    but intentionally not applied by this change — see
    docs/reviews/manual_execution_ladder_p0_remediation_implementation_20260726.md."""

    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False, compare=False)

    def find_by_id(self, request_id: int) -> ManualExecutionRequest | None:
        if request_id <= 0:
            return None
        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "SELECT * FROM manual_execution_request WHERE manual_execution_request_id = %s",
                [request_id],
            )
            row = cursor.fetchone()
            return _row_to_request(row) if row else None

    def create_request_idempotent(self, request: ManualExecutionRequest) -> ManualExecutionRequest:
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                INSERT INTO manual_execution_request (
                    schema_version, idempotency_key, dedupe_key, operator_request_nonce, created_ts_utc, source,
                    requested_by, mode, trading_account_id, account_code, venue,
                    asset_id, base_asset, quote_asset, side, quantity_policy,
                    requested_base_quantity, requested_quote_notional,
                    ladder_levels_json, provenance_id, ladder_profile_id, ladder_profile_version,
                    anchor_type, anchor_price, anchor_source, source_map_cycle_id,
                    source_native_map_id, source_map_version, request_state
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    manual_execution_request_id = LAST_INSERT_ID(manual_execution_request_id)
                """,
                [
                    request.schema_version,
                    request.idempotency_key,
                    request.dedupe_key,
                    request.operator_request_nonce,
                    request.created_ts_utc,
                    request.source,
                    request.requested_by,
                    request.mode,
                    request.trading_account_id,
                    request.account_code,
                    request.venue,
                    request.asset_id,
                    request.base_asset,
                    request.quote_asset,
                    request.side,
                    request.quantity_policy,
                    request.requested_base_quantity,
                    request.requested_quote_notional,
                    _ladder_levels_to_json(request.ladder_levels),
                    request.provenance_id,
                    request.ladder_profile_id,
                    request.ladder_profile_version,
                    request.anchor_type,
                    request.anchor_price,
                    request.anchor_source,
                    request.source_map_cycle_id,
                    request.source_native_map_id,
                    request.source_map_version,
                    request.request_state,
                ],
            )
            # ``LAST_INSERT_ID`` makes both the inserted and duplicate-key
            # paths return the one canonical row identity without an
            # application-level read/insert race.
            request_id = int(cursor.lastrowid)
            cursor.execute(
                "SELECT * FROM manual_execution_request WHERE manual_execution_request_id = %s",
                [request_id],
            )
            row = cursor.fetchone()
            return _row_to_request(row)

    def update_request_state(self, updated_request: ManualExecutionRequest) -> None:
        if updated_request.request_id is None:
            raise ManualExecutionRequestValidationError(
                "update_request_state requires a persisted request_id"
            )

        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                UPDATE manual_execution_request
                SET request_state = %s,
                    processed_ts_utc = %s,
                    rejection_code = %s,
                    rejection_detail = %s
                WHERE manual_execution_request_id = %s
                """,
                [
                    updated_request.request_state,
                    updated_request.processed_ts_utc,
                    updated_request.rejection_code,
                    updated_request.rejection_detail,
                    updated_request.request_id,
                ],
            )
