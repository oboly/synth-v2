from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
import traceback

import pytest
import requests

from src.execution.bitvavo_client import BitvavoOrderNotFoundError, BitvavoOrderRequestError
from src.executor.bitvavo_order_adapter_v1 import (
    BitvavoAdapterUnavailableError,
    BitvavoOrderAdapterV1,
    BitvavoSubmissionUncertainError,
    build_bitvavo_order_adapter_v1,
    classify_bitvavo_order_response,
)
from src.executor.broker_ack_classification_v1 import BrokerAckStateV1
from src.executor.execution_credential_scope_v1 import CredentialScopeBinding
from src.executor.execution_handoff_v1 import ExecutionHandoffV1


def _handoff(mode: str = "LIVE", side: str = "BUY") -> ExecutionHandoffV1:
    return ExecutionHandoffV1(
        handoff_id=1,
        plan_source="test",
        plan_reference_id="plan-1",
        plan_content_hash="a" * 64,
        trading_account_id=17,
        venue="bitvavo",
        market="BTC-EUR",
        side=side,
        executor_mode=mode,
        executor_identity="shared-executor-v1",
        runtime_owner="devlap",
        executor_credential_binding_id=9,
    )


def _binding(**changes) -> CredentialScopeBinding:
    value = CredentialScopeBinding(
        executor_credential_binding_id=9,
        trading_account_credential_id=22,
        trading_account_id=17,
        venue="bitvavo",
        permission_scope="TRADE_EXECUTION",
        executor_identity="shared-executor-v1",
        runtime_owner="devlap",
        credential_status="ACTIVE",
        credential_source="db_encrypted",
        allowed_order_write=True,
        allowed_withdrawal=False,
        binding_status="ACTIVE",
    )
    return replace(value, **changes)


class _Scope:
    def __init__(self, binding: CredentialScopeBinding) -> None:
        self.binding = binding
        self.calls: list[dict] = []

    def resolve(self, **kwargs):
        self.calls.append(kwargs)
        return self.binding


class _Client:
    def __init__(self, *, create=None, lookup=None) -> None:
        self.create = create
        self.lookup = lookup
        self.requests = []

    def place_order(self, order):
        self.requests.append(order)
        if isinstance(self.create, BaseException):
            raise self.create
        return self.create

    def get_order_by_client_order_id(self, market, client_order_id):
        if isinstance(self.lookup, BaseException):
            raise self.lookup
        return self.lookup


def _order_response(
    status: str,
    *,
    side: str = "buy",
    market: str = "BTC-EUR",
    client_order_id: str = "cid",
) -> dict[str, str]:
    return {
        "orderId": "o-1",
        "status": status,
        "market": market,
        "side": side,
        "clientOrderId": client_order_id,
    }


def _adapter(
    client: _Client,
    binding: CredentialScopeBinding | None = None,
    *,
    side: str = "BUY",
):
    scope = _Scope(binding or _binding())
    adapter = build_bitvavo_order_adapter_v1(
        handoff=_handoff(side=side),
        conn=object(),
        master_key_bytes=b"x" * 32,
        cred_repo_factory=object(),
        credential_scope_repository=scope,
        credential_loader=lambda *_a, **_k: SimpleNamespace(api_key="key", api_secret="secret"),
        client_factory=lambda **_kwargs: client,
    )
    return adapter, scope


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("new", BrokerAckStateV1.ACTIVE),
        ("awaitingTrigger", BrokerAckStateV1.ACTIVE),
        ("partiallyFilled", BrokerAckStateV1.PARTIALLY_FILLED),
        ("filled", BrokerAckStateV1.FILLED),
        ("canceled", BrokerAckStateV1.CANCELED),
        ("expired", BrokerAckStateV1.EXPIRED),
    ],
)
def test_current_bitvavo_status_mapping(raw: str, canonical: BrokerAckStateV1) -> None:
    ack = classify_bitvavo_order_response({"orderId": "o-1", "status": raw})
    assert ack.state is canonical
    assert ack.broker_raw_status == raw


@pytest.mark.parametrize(
    "response",
    [
        {"orderId": "o-1"},
        {"orderId": "o-1", "status": "unknownStatus"},
        {"status": "new"},
        {"orderId": 123, "status": "new"},
        "malformed",
    ],
)
def test_unknown_missing_or_unidentified_status_is_ambiguous(response: object) -> None:
    assert classify_bitvavo_order_response(response).state is BrokerAckStateV1.AMBIGUOUS


def test_restatement_reason_is_bounded_provenance_not_state() -> None:
    ack = classify_bitvavo_order_response(
        {"orderId": "o-1", "status": "canceled", "restatementReason": "cancelPostOnly"}
    )
    assert ack.state is BrokerAckStateV1.CANCELED
    assert ack.restatement_reason == "cancelPostOnly"
    oversized = classify_bitvavo_order_response(
        {"orderId": "o-1", "status": "canceled", "restatementReason": "x" * 129}
    )
    assert oversized.state is BrokerAckStateV1.CANCELED
    assert oversized.restatement_reason is None


@pytest.mark.parametrize(
    "response",
    [
        _order_response("new", market="ETH-EUR"),
        _order_response("new", client_order_id="other"),
        _order_response("new", side="sell"),
        {"orderId": "o-1", "status": "new"},
    ],
)
def test_create_response_identity_mismatch_is_ambiguous(response: object) -> None:
    adapter, _ = _adapter(_Client(create=response))
    ack = adapter.place_order(
        market="BTC-EUR",
        side="BUY",
        price=Decimal("1"),
        quantity=Decimal("1"),
        client_order_id="cid",
        operator_id=1,
    )
    assert ack.state is BrokerAckStateV1.AMBIGUOUS


@pytest.mark.parametrize(
    "response",
    [
        _order_response("new", market="ETH-EUR"),
        _order_response("new", client_order_id="other"),
        {"orderId": "o-1", "status": "new"},
    ],
)
def test_lookup_response_identity_mismatch_is_ambiguous(response: object) -> None:
    adapter, _ = _adapter(_Client(lookup=response))
    ack = adapter.find_order_by_client_order_id(
        market="BTC-EUR", client_order_id="cid"
    )
    assert ack is not None
    assert ack.state is BrokerAckStateV1.AMBIGUOUS


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_buy_and_sell_preserve_exact_order_values(side: str) -> None:
    client = _Client(create=_order_response(
        "new",
        side=side.lower(),
        client_order_id="11111111-1111-5111-8111-111111111111",
    ))
    adapter, scope = _adapter(client, side=side)
    ack = adapter.place_order(
        market="BTC-EUR",
        side=side,
        price=Decimal("123.4500"),
        quantity=Decimal("0.0100"),
        client_order_id="11111111-1111-5111-8111-111111111111",
        operator_id=73,
    )
    request = client.requests[0]
    assert ack.state is BrokerAckStateV1.ACTIVE
    assert (request.market, request.side, request.price, request.amount) == (
        "BTC-EUR", side.lower(), "123.4500", "0.0100"
    )
    assert request.client_order_id == "11111111-1111-5111-8111-111111111111"
    assert request.operator_id == 73
    assert request.post_only is True and request.order_type == "limit"
    assert scope.calls == [{
        "trading_account_id": 17,
        "venue": "bitvavo",
        "executor_identity": "shared-executor-v1",
        "runtime_owner": "devlap",
    }]


@pytest.mark.parametrize(
    ("market", "side"),
    [("ETH-EUR", "BUY"), ("BTC-EUR", "SELL")],
)
def test_adapter_rejects_order_identity_outside_handoff(
    market: str, side: str
) -> None:
    client = _Client(create=_order_response("new"))
    adapter, scope = _adapter(client)
    with pytest.raises(BitvavoAdapterUnavailableError, match="IDENTITY_MISMATCH"):
        adapter.place_order(
            market=market,
            side=side,
            price=Decimal("1"),
            quantity=Decimal("1"),
            client_order_id="cid",
            operator_id=1,
        )
    assert client.requests == []
    assert scope.calls == []


def test_adapter_rejects_lookup_market_outside_handoff() -> None:
    client = _Client(lookup=_order_response("new"))
    adapter, scope = _adapter(client)
    with pytest.raises(BitvavoAdapterUnavailableError, match="IDENTITY_MISMATCH"):
        adapter.find_order_by_client_order_id(
            market="ETH-EUR", client_order_id="cid"
        )
    assert scope.calls == []


def test_create_canceled_is_closed_and_4xx_is_definitive_rejected() -> None:
    canceled, _ = _adapter(_Client(create=_order_response("canceled")))
    assert canceled.place_order(
        market="BTC-EUR", side="BUY", price=Decimal("1"), quantity=Decimal("1"),
        client_order_id="cid", operator_id=1,
    ).state is BrokerAckStateV1.CANCELED

    rejected, _ = _adapter(
        _Client(create=BitvavoOrderRequestError(
            action="place_order", status_code=400, response_text="unsafe raw body"
        )),
        side="SELL",
    )
    ack = rejected.place_order(
        market="BTC-EUR", side="SELL", price=Decimal("1"), quantity=Decimal("1"),
        client_order_id="cid", operator_id=1,
    )
    assert ack.state is BrokerAckStateV1.REJECTED
    assert "unsafe raw body" not in repr(ack)


@pytest.mark.parametrize(
    "error",
    [
        BitvavoOrderRequestError(action="place_order", status_code=503, response_text="raw"),
        requests.exceptions.Timeout("timeout"),
    ],
)
def test_ambiguous_create_errors_are_not_rejected(error: BaseException) -> None:
    adapter, _ = _adapter(_Client(create=error))
    with pytest.raises(BitvavoSubmissionUncertainError):
        adapter.place_order(
            market="BTC-EUR", side="BUY", price=Decimal("1"), quantity=Decimal("1"),
            client_order_id="cid", operator_id=1,
        )


def test_broker_exception_body_is_suppressed_from_traceback() -> None:
    adapter, _ = _adapter(_Client(create=requests.HTTPError("unsafe raw body")))
    with pytest.raises(BitvavoSubmissionUncertainError) as caught:
        adapter.place_order(
            market="BTC-EUR",
            side="BUY",
            price=Decimal("1"),
            quantity=Decimal("1"),
            client_order_id="cid",
            operator_id=1,
        )
    rendered = "".join(traceback.format_exception(caught.value))
    assert "unsafe raw body" not in rendered


def test_lookup_found_absent_and_ambiguous_use_client_order_identity() -> None:
    found, scope = _adapter(_Client(lookup=_order_response("filled")))
    assert found.find_order_by_client_order_id(
        market="BTC-EUR", client_order_id="cid"
    ).state is BrokerAckStateV1.FILLED

    absent, _ = _adapter(_Client(lookup=BitvavoOrderNotFoundError()))
    assert absent.find_order_by_client_order_id(market="BTC-EUR", client_order_id="cid") is None

    ambiguous, _ = _adapter(_Client(lookup=requests.exceptions.ConnectionError("reset")))
    with pytest.raises(BitvavoSubmissionUncertainError):
        ambiguous.find_order_by_client_order_id(market="BTC-EUR", client_order_id="cid")
    assert len(scope.calls) == 1


def test_each_operation_freshly_resolves_the_exact_scope() -> None:
    client = _Client(
        create=_order_response("new"),
        lookup=_order_response("new"),
    )
    adapter, scope = _adapter(client)
    adapter.place_order(
        market="BTC-EUR", side="BUY", price=Decimal("1"), quantity=Decimal("1"),
        client_order_id="cid", operator_id=1,
    )
    adapter.find_order_by_client_order_id(market="BTC-EUR", client_order_id="cid")
    assert len(scope.calls) == 2
    assert scope.calls[0] == scope.calls[1]


@pytest.mark.parametrize(
    "binding",
    [
        _binding(trading_account_id=18),
        _binding(venue="other"),
        _binding(executor_identity="other"),
        _binding(runtime_owner="other"),
        _binding(executor_credential_binding_id=10),
        _binding(permission_scope="READ_ONLY_PRIVATE"),
        _binding(credential_status="REVOKED"),
        _binding(binding_status="REVOKED"),
        _binding(allowed_order_write=False),
        _binding(allowed_withdrawal=True),
    ],
)
def test_nonexact_or_withdrawal_capable_binding_is_denied(binding: CredentialScopeBinding) -> None:
    adapter, _ = _adapter(_Client(create=_order_response("new")), binding)
    with pytest.raises(BitvavoAdapterUnavailableError):
        adapter.place_order(
            market="BTC-EUR", side="BUY", price=Decimal("1"), quantity=Decimal("1"),
            client_order_id="cid", operator_id=1,
        )


def test_builder_does_not_turn_paper_handoff_into_live() -> None:
    with pytest.raises(BitvavoAdapterUnavailableError, match="REQUIRES_LIVE_HANDOFF"):
        build_bitvavo_order_adapter_v1(
            handoff=_handoff("PAPER"), conn=object(), master_key_bytes=b"x" * 32,
            cred_repo_factory=object(), credential_scope_repository=_Scope(_binding()),
        )


def test_direct_adapter_cannot_bypass_live_handoff_requirement() -> None:
    client = _Client(create=_order_response("new"))
    adapter = BitvavoOrderAdapterV1(
        handoff=_handoff("PAPER"),
        conn=object(),
        master_key_bytes=b"x" * 32,
        cred_repo_factory=object(),
        credential_scope_repository=_Scope(_binding()),
        credential_loader=lambda *_a, **_k: SimpleNamespace(
            api_key="key", api_secret="secret"
        ),
        client_factory=lambda **_kwargs: client,
    )
    with pytest.raises(BitvavoAdapterUnavailableError, match="REQUIRES_LIVE_HANDOFF"):
        adapter.place_order(
            market="BTC-EUR",
            side="BUY",
            price=Decimal("1"),
            quantity=Decimal("1"),
            client_order_id="cid",
            operator_id=1,
        )
    assert client.requests == []
