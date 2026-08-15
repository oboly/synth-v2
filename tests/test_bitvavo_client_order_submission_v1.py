from __future__ import annotations

import json
from typing import Any

import pytest
import requests

from src.execution.bitvavo_client import (
    BROKER_WRITE_PERMISSION_ENV,
    BROKER_WRITE_PERMISSION_GRANTED_VALUE,
    BROKER_PRIVATE_READ_PERMISSION_ENV,
    BROKER_PRIVATE_READ_PERMISSION_GRANTED_VALUE,
    BitvavoClient,
    BitvavoOrderNotFoundError,
    BitvavoOrderRequest,
    BitvavoOrderRequestError,
)


class _Response:
    def __init__(self, payload: Any, status_code: int = 200, text: str = "") -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text or json.dumps(payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self) -> Any:
        return self._payload


def _writable_client(monkeypatch: pytest.MonkeyPatch) -> BitvavoClient:
    monkeypatch.setenv(BROKER_WRITE_PERMISSION_ENV, BROKER_WRITE_PERMISSION_GRANTED_VALUE)
    return BitvavoClient.for_private_write(api_key="k", api_secret="s")


def _readable_client(monkeypatch: pytest.MonkeyPatch) -> BitvavoClient:
    monkeypatch.setenv(BROKER_PRIVATE_READ_PERMISSION_ENV, BROKER_PRIVATE_READ_PERMISSION_GRANTED_VALUE)
    return BitvavoClient.for_private_read(api_key="k", api_secret="s")


def test_place_order_requires_operator_id(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _writable_client(monkeypatch)
    with pytest.raises(ValueError, match="operator_id is required"):
        client.place_order(
            BitvavoOrderRequest(market="BTC-EUR", side="sell", order_type="limit", amount="1", price="10")
        )


def test_place_order_sends_operator_id_and_client_order_id(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _writable_client(monkeypatch)
    captured: dict[str, Any] = {}

    def _fake_post(url: str, **kwargs: Any) -> _Response:
        captured["body"] = json.loads(kwargs["data"])
        return _Response({"orderId": "abc-123", "status": "new"})

    monkeypatch.setattr("requests.post", _fake_post)

    result = client.place_order(
        BitvavoOrderRequest(
            market="BTC-EUR",
            side="sell",
            order_type="limit",
            amount="0.5",
            price="50000",
            operator_id=777,
            client_order_id="11111111-1111-5111-8111-111111111111",
        )
    )

    assert result == {"orderId": "abc-123", "status": "new"}
    assert captured["body"]["operatorId"] == 777
    assert captured["body"]["clientOrderId"] == "11111111-1111-5111-8111-111111111111"
    assert captured["body"]["amount"] == "0.5"
    assert captured["body"]["price"] == "50000"


def test_place_order_http_error_raises_structured_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _writable_client(monkeypatch)
    monkeypatch.setattr(
        "requests.post",
        lambda *_a, **_k: _Response({"error": "insufficient balance"}, status_code=400, text="bad"),
    )

    with pytest.raises(BitvavoOrderRequestError) as exc:
        client.place_order(
            BitvavoOrderRequest(
                market="BTC-EUR", side="sell", order_type="limit", amount="1", price="1", operator_id=1
            )
        )
    assert exc.value.status_code == 400


def test_place_order_network_timeout_propagates_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _writable_client(monkeypatch)

    def _raise_timeout(*_a: Any, **_k: Any) -> _Response:
        raise requests.exceptions.Timeout("connect timed out")

    monkeypatch.setattr("requests.post", _raise_timeout)

    with pytest.raises(requests.exceptions.Timeout):
        client.place_order(
            BitvavoOrderRequest(
                market="BTC-EUR", side="sell", order_type="limit", amount="1", price="1", operator_id=1
            )
        )


def test_get_order_by_client_order_id_sends_expected_param(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _readable_client(monkeypatch)
    captured: dict[str, Any] = {}

    def _fake_get(url: str, **kwargs: Any) -> _Response:
        captured["url"] = url
        captured["params"] = kwargs["params"]
        return _Response({"orderId": "abc-123", "status": "open"})

    monkeypatch.setattr("requests.get", _fake_get)

    result = client.get_order_by_client_order_id("BTC-EUR", "cid-1")
    assert result == {"orderId": "abc-123", "status": "open"}
    assert captured["url"] == "https://api.bitvavo.com/v2/order"
    assert captured["params"] == {"market": "BTC-EUR", "clientOrderId": "cid-1"}


def test_get_order_404_raises_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _readable_client(monkeypatch)
    monkeypatch.setattr(
        "requests.get",
        lambda *_a, **_k: _Response({"errorCode": 240}, status_code=404),
    )

    with pytest.raises(BitvavoOrderNotFoundError):
        client.get_order_by_client_order_id("BTC-EUR", "cid-missing")


@pytest.mark.parametrize(
    "payload",
    [{"errorCode": 510, "error": "unsafe raw body"}, {}, "malformed"],
)
def test_get_order_other_404_is_ambiguous_not_absent(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    client = _readable_client(monkeypatch)
    monkeypatch.setattr(
        "requests.get", lambda *_a, **_k: _Response(payload, status_code=404)
    )

    with pytest.raises(BitvavoOrderRequestError) as caught:
        client.get_order_by_client_order_id("BTC-EUR", "cid-1")
    assert caught.value.status_code == 404
    assert "unsafe raw body" not in str(caught.value)


def test_get_order_network_error_propagates_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _readable_client(monkeypatch)

    def _raise_conn_error(*_a: Any, **_k: Any) -> _Response:
        raise requests.exceptions.ConnectionError("reset")

    monkeypatch.setattr("requests.get", _raise_conn_error)

    with pytest.raises(requests.exceptions.ConnectionError):
        client.get_order_by_client_order_id("BTC-EUR", "cid-1")


def test_get_order_requires_exactly_one_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _readable_client(monkeypatch)
    with pytest.raises(ValueError):
        client.get_order("BTC-EUR")
    with pytest.raises(ValueError):
        client.get_order("BTC-EUR", order_id="1", client_order_id="2")
