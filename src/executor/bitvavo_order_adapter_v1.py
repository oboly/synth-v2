"""
bitvavo_order_adapter_v1 -- the side-neutral LIVE broker boundary shared by
algorithmic SELL (#392) and algorithmic BUY (#399) (Issue #206).

Layer: executor. This module is the *only* place in the shared algorithmic
submission lane that ever imports/uses decrypted credential material or
calls src.execution.bitvavo_client.BitvavoClient's private-write endpoints.
It implements
src.executor.execution_submission_orchestrator_v1.OrderPlacementAdapter so
the orchestrator runs the identical sequential/crash-safe code path against
this adapter as it does against the non-live stub
(src.executor.stub_order_adapter_v1) in tests/paper acceptance.

Issue #206 P0-A: this is the ONLY place Bitvavo's order-status vocabulary
(new/partiallyFilled/filled/canceled*/expired/rejected) may appear. Every
raw status this adapter receives -- from a create-order response AND from
a get-order reconciliation lookup -- is classified through
src.executor.broker_ack_classification_v1.resolve_canonical_state before
being handed to the orchestrator; a status that fails to classify
(missing, empty, or unrecognized) raises SubmissionUncertainError rather
than being silently treated as active. In particular
``canceledPostOnly`` (an immediate post-only self-cross cancellation) is
classified CANCELED, never ACTIVE -- this is the exact defect this module
closes relative to the pre-#206 manual-lane adapter (see
broker_ack_classification_v1's docstring), which persisted every
non-exception create-order response as SUBMITTED regardless of its status.

Credential path (Issue #206 contract, re-verified fresh at call time -- not
merely trusted from handoff intake, in case a binding was revoked in the
interim). Credential resolution is reused directly from
src.executor.manual_execution_credential_scope_v1 -- that module has no
manual-workflow coupling at all (it resolves purely on account/venue/
executor identity), so it is SHARED_GENERIC as-is:

    executor_credential_binding (trading_account_id, venue,
        executor_identity, runtime_owner) -> exactly one ACTIVE
        TRADE_EXECUTION trading_account_credential with
        allowed_order_write=1, allowed_withdrawal=0
    -> encrypted envelope decrypt (src.account_provisioning.credential_crypto_v1)
    -> BitvavoClient.for_private_write(...)

No fallback credential, no cross-account reuse, no secret material ever
logged or included in an exception/repr.

Exception translation:

    - network-level ambiguity (timeout, connection drop, or any other
      exception where the broker's true receipt of the request is unknown)
      -> SubmissionUncertainError;
    - a definitive HTTP 4xx broker response with no order object at all
      (order was not created) -> BrokerOrderRejectedError;
    - a definitive HTTP 5xx broker response is treated as ambiguous
      (the broker may have processed the order before failing downstream)
      -> SubmissionUncertainError, never BrokerOrderRejectedError;
    - a successful HTTP response whose order object has a status this
      module cannot classify -> SubmissionUncertainError, never a
      silently-accepted OrderAck;
    - a confirmed-absent Get Order response (404)
      -> find_order_by_client_order_id returns None.

broker_private_calls=1 when actually invoked (this is the live lane)
broker_writes=1 when place_order is actually invoked
order_submission=1 when place_order is actually invoked
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Mapping

import requests

from src.account_provisioning.account_credential_loader_v1 import load_account_credential_by_id
from src.execution.bitvavo_client import (
    BitvavoClient,
    BitvavoOrderNotFoundError,
    BitvavoOrderRequest,
    BitvavoOrderRequestError,
)
from src.executor.broker_ack_classification_v1 import (
    ACK_STATE_ACTIVE,
    ACK_STATE_AMBIGUOUS,
    ACK_STATE_CANCELED,
    ACK_STATE_EXPIRED,
    ACK_STATE_FILLED,
    ACK_STATE_PARTIALLY_FILLED,
    ACK_STATE_REJECTED,
    resolve_canonical_state,
)
from src.executor.manual_execution_credential_scope_v1 import (
    CredentialScopeDeniedError,
    ExecutorCredentialScopeRepository,
)
from src.executor.execution_submission_orchestrator_v1 import (
    BrokerOrderRejectedError,
    OrderAck,
    SubmissionUncertainError,
)


# The ONLY place Bitvavo's order-status vocabulary may appear (P0-A).
# Values are Bitvavo's public v2 order `status` field. Anything not in this
# map classifies to AMBIGUOUS (resolve_canonical_state fails closed) and is
# escalated to SubmissionUncertainError below -- never guessed as active.
BITVAVO_STATUS_MAP: Final[Mapping[str, str]] = {
    "new": ACK_STATE_ACTIVE,
    "partiallyFilled": ACK_STATE_PARTIALLY_FILLED,
    "filled": ACK_STATE_FILLED,
    "canceled": ACK_STATE_CANCELED,
    "canceledAuction": ACK_STATE_CANCELED,
    "canceledSelfTradePrevention": ACK_STATE_CANCELED,
    "canceledIOC": ACK_STATE_CANCELED,
    "canceledFOK": ACK_STATE_CANCELED,
    "canceledMarketProtection": ACK_STATE_CANCELED,
    # Immediate post-only self-cross cancellation -- must classify CANCELED,
    # never ACTIVE. This is the exact scenario Issue #206 P0-A names.
    "canceledPostOnly": ACK_STATE_CANCELED,
    "expired": ACK_STATE_EXPIRED,
    "rejected": ACK_STATE_REJECTED,
}


class LiveCredentialResolutionDeniedError(PermissionError):
    """Fail-closed: the live credential chain could not be resolved for the
    exact (trading_account_id, venue, executor_identity, runtime_owner)
    tuple requested."""


def build_live_bitvavo_client(
    *,
    conn: Any,
    trading_account_id: int,
    venue: str,
    executor_identity: str,
    runtime_owner: str,
    master_key_bytes: bytes,
    cred_repo_factory: Any,
    credential_scope_repository: ExecutorCredentialScopeRepository | None = None,
) -> BitvavoClient:
    """Chain #206 credential binding -> canonical decrypt path ->
    BitvavoClient. Fails closed on any missing/ambiguous/revoked/scope-
    mismatched binding; never falls back to a different credential."""
    scope_repo = credential_scope_repository or ExecutorCredentialScopeRepository()
    try:
        binding = scope_repo.resolve(
            trading_account_id=trading_account_id,
            venue=venue,
            executor_identity=executor_identity,
            runtime_owner=runtime_owner,
        )
    except CredentialScopeDeniedError as exc:
        raise LiveCredentialResolutionDeniedError(str(exc)) from exc

    if (
        binding.trading_account_id != trading_account_id
        or binding.venue != venue
        or binding.executor_identity != executor_identity
        or binding.runtime_owner != runtime_owner
    ):
        raise LiveCredentialResolutionDeniedError(
            "LIVE_CREDENTIAL_BINDING_IDENTITY_MISMATCH"
        )

    credential = load_account_credential_by_id(
        conn,
        trading_account_credential_id=binding.trading_account_credential_id,
        trading_account_id=trading_account_id,
        venue=venue,
        master_key_bytes=master_key_bytes,
        cred_repo_factory=cred_repo_factory,
    )
    return BitvavoClient.for_private_write(
        api_key=credential.api_key,
        api_secret=credential.api_secret,
    )


def _classify_order_request_error(exc: BitvavoOrderRequestError) -> Exception:
    if 400 <= exc.status_code < 500:
        return BrokerOrderRejectedError(
            safe_error_code=f"BROKER_REJECTED_HTTP_{exc.status_code}",
        )
    # 5xx (or any other non-4xx status): the broker may have processed the
    # order before failing downstream. Never a definitive rejection.
    return SubmissionUncertainError(
        f"BROKER_RESPONSE_AMBIGUOUS_HTTP_{exc.status_code}"
    )


def _classify_response_status(raw_status: str | None) -> str:
    """P0-A: classify a raw Bitvavo status string. Raises
    SubmissionUncertainError (never returns AMBIGUOUS) so callers can treat
    every OrderAck.ack_state as one of the seven non-ambiguous canonical
    states."""
    canonical = resolve_canonical_state(raw_status=raw_status, venue_status_map=BITVAVO_STATUS_MAP)
    if canonical == ACK_STATE_AMBIGUOUS:
        raise SubmissionUncertainError(
            f"BROKER_STATUS_UNCLASSIFIED: {raw_status!r}"
        )
    return canonical


@dataclass
class LiveBitvavoOrderAdapter:
    """Implements OrderPlacementAdapter against one already-authorized
    BitvavoClient. Construct exactly one instance per submission run via
    build_live_bitvavo_client(); never share/cache across accounts. Side
    (BUY/SELL) is passed straight through to the client -- this adapter
    never branches on it."""

    client: BitvavoClient

    def place_order(
        self,
        *,
        market: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        client_order_id: str,
        operator_id: int,
    ) -> OrderAck:
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
            response = self.client.place_order(request)
        except BitvavoOrderRequestError as exc:
            raise _classify_order_request_error(exc) from exc
        except requests.exceptions.RequestException as exc:
            raise SubmissionUncertainError(
                f"BROKER_REQUEST_EXCEPTION: {type(exc).__name__}"
            ) from exc

        broker_order_id = response.get("orderId")
        if not broker_order_id:
            raise SubmissionUncertainError(
                "BROKER_RESPONSE_MISSING_ORDER_ID"
            )
        raw_status = response.get("status")
        ack_state = _classify_response_status(raw_status)
        return OrderAck(
            broker_order_id=str(broker_order_id),
            broker_status=str(raw_status),
            ack_state=ack_state,
        )

    def find_order_by_client_order_id(
        self, *, market: str, client_order_id: str
    ) -> OrderAck | None:
        try:
            response = self.client.get_order_by_client_order_id(market, client_order_id)
        except BitvavoOrderNotFoundError:
            return None
        except requests.exceptions.RequestException as exc:
            raise SubmissionUncertainError(
                f"BROKER_RECONCILE_REQUEST_EXCEPTION: {type(exc).__name__}"
            ) from exc

        broker_order_id = response.get("orderId")
        if not broker_order_id:
            raise SubmissionUncertainError(
                "BROKER_RECONCILE_RESPONSE_MISSING_ORDER_ID"
            )
        raw_status = response.get("status")
        ack_state = _classify_response_status(raw_status)
        return OrderAck(
            broker_order_id=str(broker_order_id),
            broker_status=str(raw_status),
            ack_state=ack_state,
        )
