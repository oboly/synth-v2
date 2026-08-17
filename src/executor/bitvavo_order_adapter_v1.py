"""Bitvavo venue boundary for the shared BUY/SELL executor path.

This module grants no permission. Every private operation verifies the exact
persisted LIVE handoff, credential metadata, and current operational gate
before loading secret material or constructing a private client.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Protocol

import requests

from src.account_provisioning.account_credential_loader_v1 import load_account_credential_by_id
from src.execution.bitvavo_client import (
    BitvavoClient,
    BitvavoOrderNotFoundError,
    BitvavoOrderRequest,
    BitvavoOrderRequestError,
)
from src.executor.broker_ack_classification_v1 import BrokerAckStateV1, OrderAckV1
from src.executor.execution_credential_scope_v1 import (
    BINDING_STATUS_ACTIVE,
    CREDENTIAL_STATUS_ACTIVE,
    TRADE_EXECUTION_SCOPE,
    CredentialScopeBinding,
    CredentialScopeDeniedError,
    ExecutorCredentialScopeRepository,
)
from src.executor.execution_handoff_v1 import (
    ExecutionHandoffRepositoryV1,
    ExecutionHandoffV1,
)
from src.executor.execution_kill_switch_v1 import ExecutionKillSwitchRepositoryV1
from src.executor.execution_live_authority_v1 import (
    ExecutionLiveAuthorityDeniedError,
    ExecutionLiveAuthorityRepositoryV1,
    require_execution_live_authority_v1,
)


_BITVAVO_STATUS_MAP = {
    "new": BrokerAckStateV1.ACTIVE,
    "awaitingTrigger": BrokerAckStateV1.ACTIVE,
    "partiallyFilled": BrokerAckStateV1.PARTIALLY_FILLED,
    "filled": BrokerAckStateV1.FILLED,
    "canceled": BrokerAckStateV1.CANCELED,
    "expired": BrokerAckStateV1.EXPIRED,
}


class BitvavoAdapterUnavailableError(PermissionError):
    """The dormant adapter lacks an exact, currently valid binding."""


class BitvavoSubmissionUncertainError(RuntimeError):
    """The venue outcome cannot be authoritatively determined."""


class _BitvavoClientProtocol(Protocol):
    def place_order(self, order: BitvavoOrderRequest) -> dict[str, Any]: ...
    def get_order_by_client_order_id(self, market: str, client_order_id: str) -> dict[str, Any]: ...


def classify_bitvavo_order_response(response: object) -> OrderAckV1:
    """Translate only the current documented Bitvavo status vocabulary."""
    if not isinstance(response, dict):
        return OrderAckV1(None, BrokerAckStateV1.AMBIGUOUS)
    raw_status = response.get("status")
    status = raw_status if isinstance(raw_status, str) else None
    state = _BITVAVO_STATUS_MAP.get(status, BrokerAckStateV1.AMBIGUOUS)
    raw_order_id = response.get("orderId")
    broker_order_id = raw_order_id if isinstance(raw_order_id, str) else None
    if broker_order_id is not None and not broker_order_id.strip():
        broker_order_id = None
    reason_value = response.get("restatementReason")
    reason = (
        reason_value
        if isinstance(reason_value, str)
        and reason_value
        and len(reason_value) <= 128
        and reason_value.isprintable()
        else None
    )
    if state is not BrokerAckStateV1.AMBIGUOUS and broker_order_id is None:
        state = BrokerAckStateV1.AMBIGUOUS
    return OrderAckV1(
        broker_order_id=broker_order_id,
        state=state,
        broker_raw_status=status,
        restatement_reason=reason,
    )


def _classify_exact_order_response(
    response: object,
    *,
    market: str,
    client_order_id: str,
    side: str | None = None,
) -> OrderAckV1:
    ack = classify_bitvavo_order_response(response)
    if not isinstance(response, dict):
        return ack
    if (
        response.get("market") != market
        or response.get("clientOrderId") != client_order_id
        or (side is not None and response.get("side") != side.lower())
    ):
        return OrderAckV1(None, BrokerAckStateV1.AMBIGUOUS)
    return ack


def _assert_exact_binding(binding: CredentialScopeBinding, handoff: ExecutionHandoffV1) -> None:
    if (
        binding.executor_credential_binding_id != handoff.executor_credential_binding_id
        or binding.trading_account_id != handoff.trading_account_id
        or binding.venue != handoff.venue
        or binding.executor_identity != handoff.executor_identity
        or binding.runtime_owner != handoff.runtime_owner
        or binding.permission_scope != TRADE_EXECUTION_SCOPE
        or binding.credential_status != CREDENTIAL_STATUS_ACTIVE
        or binding.binding_status != BINDING_STATUS_ACTIVE
        or not binding.allowed_order_write
        or binding.allowed_withdrawal
    ):
        raise BitvavoAdapterUnavailableError("BITVAVO_CREDENTIAL_BINDING_MISMATCH")


def _assert_dormant_live_handoff(handoff: ExecutionHandoffV1) -> None:
    if handoff.handoff_id is None:
        raise BitvavoAdapterUnavailableError("BITVAVO_HANDOFF_NOT_PERSISTED")
    if handoff.executor_mode != "LIVE":
        raise BitvavoAdapterUnavailableError("BITVAVO_ADAPTER_REQUIRES_LIVE_HANDOFF")
    if handoff.venue != "bitvavo":
        raise BitvavoAdapterUnavailableError("BITVAVO_ADAPTER_VENUE_MISMATCH")


_HANDOFF_IDENTITY_FIELDS = (
    "handoff_id",
    "plan_source",
    "plan_reference_id",
    "plan_content_hash",
    "trading_account_id",
    "venue",
    "market",
    "side",
    "executor_mode",
    "executor_identity",
    "runtime_owner",
    "executor_credential_binding_id",
)


def _assert_canonical_persisted_handoff(
    handoff: ExecutionHandoffV1,
    repository: ExecutionHandoffRepositoryV1,
) -> None:
    _assert_dormant_live_handoff(handoff)
    if handoff.handoff_id is None:  # guarded above; explicit for optimized Python
        raise BitvavoAdapterUnavailableError("BITVAVO_HANDOFF_NOT_PERSISTED")
    try:
        persisted = repository.find(handoff.handoff_id)
    except Exception:
        raise BitvavoAdapterUnavailableError(
            "BITVAVO_PERSISTED_HANDOFF_VERIFICATION_FAILED"
        ) from None
    if persisted is None:
        raise BitvavoAdapterUnavailableError("BITVAVO_PERSISTED_HANDOFF_NOT_FOUND")
    if not isinstance(persisted, ExecutionHandoffV1):
        raise BitvavoAdapterUnavailableError(
            "BITVAVO_PERSISTED_HANDOFF_IDENTITY_MISMATCH"
        )
    if any(
        getattr(persisted, field_name) != getattr(handoff, field_name)
        for field_name in _HANDOFF_IDENTITY_FIELDS
    ):
        raise BitvavoAdapterUnavailableError(
            "BITVAVO_PERSISTED_HANDOFF_IDENTITY_MISMATCH"
        )


@dataclass(repr=False)
class BitvavoOrderAdapterV1:
    """Shared side-neutral adapter; each operation re-resolves credentials."""

    handoff: ExecutionHandoffV1
    conn: Any = field(repr=False)
    master_key_bytes: bytes = field(repr=False)
    cred_repo_factory: Any = field(repr=False)
    credential_scope_repository: ExecutorCredentialScopeRepository = field(repr=False)
    handoff_repository: ExecutionHandoffRepositoryV1 = field(repr=False)
    live_authority_repository: ExecutionLiveAuthorityRepositoryV1 = field(repr=False)
    kill_switch_repository: ExecutionKillSwitchRepositoryV1 = field(repr=False)
    credential_loader: Callable[..., Any] = field(default=load_account_credential_by_id, repr=False)
    client_factory: Callable[..., _BitvavoClientProtocol] = field(default=BitvavoClient.for_private_write, repr=False)

    def _fresh_client(self) -> _BitvavoClientProtocol:
        _assert_canonical_persisted_handoff(self.handoff, self.handoff_repository)
        try:
            binding = self.credential_scope_repository.resolve(
                trading_account_id=self.handoff.trading_account_id,
                venue=self.handoff.venue,
                executor_identity=self.handoff.executor_identity,
                runtime_owner=self.handoff.runtime_owner,
            )
        except CredentialScopeDeniedError as exc:
            raise BitvavoAdapterUnavailableError(
                "BITVAVO_CREDENTIAL_SCOPE_DENIED"
            ) from None
        _assert_exact_binding(binding, self.handoff)
        try:
            require_execution_live_authority_v1(
                trading_account_id=self.handoff.trading_account_id,
                venue=self.handoff.venue,
                side=self.handoff.side,
                market=self.handoff.market,
                executor_identity=self.handoff.executor_identity,
                runtime_owner=self.handoff.runtime_owner,
                authority_repository=self.live_authority_repository,
                kill_switch_repository=self.kill_switch_repository,
            )
        except ExecutionLiveAuthorityDeniedError:
            raise BitvavoAdapterUnavailableError(
                "BITVAVO_EXECUTION_LIVE_AUTHORITY_DENIED"
            ) from None
        credential = self.credential_loader(
            self.conn,
            trading_account_credential_id=binding.trading_account_credential_id,
            trading_account_id=self.handoff.trading_account_id,
            venue=self.handoff.venue,
            master_key_bytes=self.master_key_bytes,
            cred_repo_factory=self.cred_repo_factory,
        )
        return self.client_factory(
            api_key=credential.api_key,
            api_secret=credential.api_secret,
        )

    def place_order(
        self,
        *,
        market: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        client_order_id: str,
        operator_id: int,
    ) -> OrderAckV1:
        if market != self.handoff.market or side != self.handoff.side:
            raise BitvavoAdapterUnavailableError(
                "BITVAVO_ORDER_HANDOFF_IDENTITY_MISMATCH"
            )
        client = self._fresh_client()
        request = BitvavoOrderRequest(
            market=market,
            side=side.lower(),
            order_type="limit",
            amount=str(quantity),
            price=str(price),
            post_only=True,
            time_in_force="GTC",
            operator_id=operator_id,
            client_order_id=client_order_id,
        )
        try:
            response = client.place_order(request)
        except BitvavoOrderRequestError as exc:
            if 400 <= exc.status_code < 500:
                return OrderAckV1(
                    broker_order_id=None,
                    state=BrokerAckStateV1.REJECTED,
                    broker_raw_status=f"HTTP_{exc.status_code}",
                )
            raise BitvavoSubmissionUncertainError(
                f"BITVAVO_CREATE_AMBIGUOUS_HTTP_{exc.status_code}"
            ) from None
        except requests.exceptions.RequestException as exc:
            raise BitvavoSubmissionUncertainError(
                f"BITVAVO_CREATE_TRANSPORT_{type(exc).__name__}"
            ) from None
        except Exception as exc:
            raise BitvavoSubmissionUncertainError(
                f"BITVAVO_CREATE_AMBIGUOUS_{type(exc).__name__}"
            ) from None
        return _classify_exact_order_response(
            response,
            market=market,
            client_order_id=client_order_id,
            side=side,
        )

    def find_order_by_client_order_id(
        self, *, market: str, client_order_id: str
    ) -> OrderAckV1 | None:
        if market != self.handoff.market:
            raise BitvavoAdapterUnavailableError(
                "BITVAVO_LOOKUP_HANDOFF_IDENTITY_MISMATCH"
            )
        client = self._fresh_client()
        try:
            response = client.get_order_by_client_order_id(market, client_order_id)
        except BitvavoOrderNotFoundError:
            return None
        except Exception as exc:
            raise BitvavoSubmissionUncertainError(
                f"BITVAVO_LOOKUP_AMBIGUOUS_{type(exc).__name__}"
            ) from None
        return _classify_exact_order_response(
            response,
            market=market,
            client_order_id=client_order_id,
            side=self.handoff.side,
        )


def build_bitvavo_order_adapter_v1(
    *,
    handoff: ExecutionHandoffV1,
    conn: Any,
    master_key_bytes: bytes,
    cred_repo_factory: Any,
    credential_scope_repository: ExecutorCredentialScopeRepository | None = None,
    handoff_repository: ExecutionHandoffRepositoryV1 | None = None,
    live_authority_repository: ExecutionLiveAuthorityRepositoryV1 | None = None,
    kill_switch_repository: ExecutionKillSwitchRepositoryV1 | None = None,
    credential_loader: Callable[..., Any] = load_account_credential_by_id,
    client_factory: Callable[..., _BitvavoClientProtocol] = BitvavoClient.for_private_write,
) -> BitvavoOrderAdapterV1:
    """Build the boundary without granting or activating LIVE mode."""
    _assert_dormant_live_handoff(handoff)
    canonical_handoff_repository = handoff_repository or ExecutionHandoffRepositoryV1(
        cursor_factory=lambda **_kwargs: conn.cursor()
    )
    _assert_canonical_persisted_handoff(handoff, canonical_handoff_repository)
    return BitvavoOrderAdapterV1(
        handoff=handoff,
        conn=conn,
        master_key_bytes=master_key_bytes,
        cred_repo_factory=cred_repo_factory,
        credential_scope_repository=(
            credential_scope_repository or ExecutorCredentialScopeRepository()
        ),
        handoff_repository=canonical_handoff_repository,
        live_authority_repository=(
            live_authority_repository or ExecutionLiveAuthorityRepositoryV1()
        ),
        kill_switch_repository=(
            kill_switch_repository or ExecutionKillSwitchRepositoryV1()
        ),
        credential_loader=credential_loader,
        client_factory=client_factory,
    )
