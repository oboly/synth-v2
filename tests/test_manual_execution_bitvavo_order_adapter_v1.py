"""Tests for src/executor/manual_execution_bitvavo_order_adapter_v1.py
(Issue #369) — the live broker boundary's credential chain and exception
translation."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
import requests

from src.execution.bitvavo_client import (
    BROKER_WRITE_PERMISSION_ENV,
    BROKER_WRITE_PERMISSION_GRANTED_VALUE,
    BitvavoClient,
)
from src.executor.manual_execution_bitvavo_order_adapter_v1 import (
    LiveBitvavoOrderAdapter,
    LiveCredentialResolutionDeniedError,
    build_live_bitvavo_client,
)
from src.executor.manual_execution_credential_scope_v1 import (
    CredentialScopeBinding,
    CredentialScopeDeniedError,
)
from src.executor.manual_execution_submission_orchestrator_v1 import (
    BrokerOrderRejectedError,
    SubmissionUncertainError,
)


TRADING_ACCOUNT_ID = 1
VENUE = "bitvavo"
EXECUTOR_IDENTITY = "executor-manual-sell-v1"
RUNTIME_OWNER = "devlap"


class _StubCredentialScopeRepository:
    def __init__(self, binding: CredentialScopeBinding | None = None, *, deny: bool = False) -> None:
        self.binding = binding or CredentialScopeBinding(
            executor_credential_binding_id=1, trading_account_credential_id=1,
            trading_account_id=TRADING_ACCOUNT_ID, venue=VENUE, permission_scope="TRADE_EXECUTION",
            executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER,
            credential_status="ACTIVE", credential_source="db_encrypted",
            allowed_order_write=True, allowed_withdrawal=False,
        )
        self.deny = deny

    def resolve(self, *, trading_account_id, venue, executor_identity, runtime_owner):
        if self.deny:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_NOT_BOUND: denied by stub")
        return self.binding


class TestCredentialChain:
    def test_denied_binding_translates_to_live_denied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(LiveCredentialResolutionDeniedError):
            build_live_bitvavo_client(
                conn=object(),
                trading_account_id=TRADING_ACCOUNT_ID,
                venue=VENUE,
                executor_identity=EXECUTOR_IDENTITY,
                runtime_owner=RUNTIME_OWNER,
                master_key_bytes=b"0" * 32,
                cred_repo_factory=lambda conn: None,
                credential_scope_repository=_StubCredentialScopeRepository(deny=True),
            )

    def test_binding_identity_mismatch_denied_even_if_resolved(self) -> None:
        mismatched_binding = CredentialScopeBinding(
            executor_credential_binding_id=1, trading_account_credential_id=1,
            trading_account_id=999, venue=VENUE, permission_scope="TRADE_EXECUTION",
            executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER,
            credential_status="ACTIVE", credential_source="db_encrypted",
            allowed_order_write=True, allowed_withdrawal=False,
        )
        with pytest.raises(LiveCredentialResolutionDeniedError, match="IDENTITY_MISMATCH"):
            build_live_bitvavo_client(
                conn=object(),
                trading_account_id=TRADING_ACCOUNT_ID,
                venue=VENUE,
                executor_identity=EXECUTOR_IDENTITY,
                runtime_owner=RUNTIME_OWNER,
                master_key_bytes=b"0" * 32,
                cred_repo_factory=lambda conn: None,
                credential_scope_repository=_StubCredentialScopeRepository(mismatched_binding),
            )

    def test_valid_binding_chains_to_decrypted_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.account_provisioning.contracts_v1 import PlainBitvavoCredential

        monkeypatch.setattr(
            "src.executor.manual_execution_bitvavo_order_adapter_v1.load_account_credential",
            lambda conn, **kwargs: PlainBitvavoCredential(venue=VENUE, api_key="k", api_secret="s"),
        )

        client = build_live_bitvavo_client(
            conn=object(),
            trading_account_id=TRADING_ACCOUNT_ID,
            venue=VENUE,
            executor_identity=EXECUTOR_IDENTITY,
            runtime_owner=RUNTIME_OWNER,
            master_key_bytes=b"0" * 32,
            cred_repo_factory=lambda conn: None,
            credential_scope_repository=_StubCredentialScopeRepository(),
        )
        assert isinstance(client, BitvavoClient)
        assert client.api_key == "k"
        assert client.auth_context == "private_write"


class _Response:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self) -> Any:
        return self._payload


def _adapter(monkeypatch: pytest.MonkeyPatch) -> LiveBitvavoOrderAdapter:
    monkeypatch.setenv(BROKER_WRITE_PERMISSION_ENV, BROKER_WRITE_PERMISSION_GRANTED_VALUE)
    client = BitvavoClient.for_private_write(api_key="k", api_secret="s")
    return LiveBitvavoOrderAdapter(client=client)


class TestPlaceOrderExceptionTranslation:
    def test_success_returns_order_ack(self, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = _adapter(monkeypatch)
        monkeypatch.setattr(
            "requests.post", lambda *_a, **_k: _Response({"orderId": "o-1", "status": "open"})
        )
        ack = adapter.place_order(
            market="BTC-EUR", side="SELL", price=Decimal("1"), quantity=Decimal("1"),
            client_order_id="cid-1", operator_id=1,
        )
        assert ack.broker_order_id == "o-1"
        assert ack.broker_status == "open"

    def test_http_4xx_translates_to_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = _adapter(monkeypatch)
        monkeypatch.setattr("requests.post", lambda *_a, **_k: _Response({}, status_code=400))
        with pytest.raises(BrokerOrderRejectedError) as exc:
            adapter.place_order(
                market="BTC-EUR", side="SELL", price=Decimal("1"), quantity=Decimal("1"),
                client_order_id="cid-1", operator_id=1,
            )
        assert exc.value.safe_error_code == "BROKER_REJECTED_HTTP_400"

    def test_http_5xx_is_ambiguous_not_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = _adapter(monkeypatch)
        monkeypatch.setattr("requests.post", lambda *_a, **_k: _Response({}, status_code=503))
        with pytest.raises(SubmissionUncertainError):
            adapter.place_order(
                market="BTC-EUR", side="SELL", price=Decimal("1"), quantity=Decimal("1"),
                client_order_id="cid-1", operator_id=1,
            )

    def test_network_timeout_is_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = _adapter(monkeypatch)

        def _raise(*_a: Any, **_k: Any) -> Any:
            raise requests.exceptions.Timeout("timed out")

        monkeypatch.setattr("requests.post", _raise)
        with pytest.raises(SubmissionUncertainError):
            adapter.place_order(
                market="BTC-EUR", side="SELL", price=Decimal("1"), quantity=Decimal("1"),
                client_order_id="cid-1", operator_id=1,
            )


class TestFindOrderByClientOrderId:
    def test_confirmed_order_returns_ack(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "SYNTH_BROKER_PRIVATE_READ_PERMISSION", "I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA"
        )
        client = BitvavoClient.for_private_read(api_key="k", api_secret="s")
        adapter = LiveBitvavoOrderAdapter(client=client)
        monkeypatch.setattr(
            "requests.get", lambda *_a, **_k: _Response({"orderId": "o-1", "status": "open"})
        )
        ack = adapter.find_order_by_client_order_id(market="BTC-EUR", client_order_id="cid-1")
        assert ack.broker_order_id == "o-1"

    def test_confirmed_absent_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "SYNTH_BROKER_PRIVATE_READ_PERMISSION", "I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA"
        )
        client = BitvavoClient.for_private_read(api_key="k", api_secret="s")
        adapter = LiveBitvavoOrderAdapter(client=client)
        monkeypatch.setattr("requests.get", lambda *_a, **_k: _Response({}, status_code=404))
        assert adapter.find_order_by_client_order_id(market="BTC-EUR", client_order_id="cid-1") is None

    def test_network_timeout_is_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "SYNTH_BROKER_PRIVATE_READ_PERMISSION", "I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA"
        )
        client = BitvavoClient.for_private_read(api_key="k", api_secret="s")
        adapter = LiveBitvavoOrderAdapter(client=client)

        def _raise(*_a: Any, **_k: Any) -> Any:
            raise requests.exceptions.ConnectionError("reset")

        monkeypatch.setattr("requests.get", _raise)
        with pytest.raises(SubmissionUncertainError):
            adapter.find_order_by_client_order_id(market="BTC-EUR", client_order_id="cid-1")
