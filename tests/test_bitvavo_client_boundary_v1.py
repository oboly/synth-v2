from __future__ import annotations

from typing import Any

import pytest

from src.execution.bitvavo_client import (
    BROKER_PRIVATE_READ_PERMISSION_ENV,
    BROKER_PRIVATE_READ_PERMISSION_GRANTED_VALUE,
    BROKER_WRITE_PERMISSION_ENV,
    BROKER_WRITE_PERMISSION_GRANTED_VALUE,
    BitvavoClient,
    BitvavoOrderRequest,
)


class _Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


def test_private_read_client_requires_explicit_credentials() -> None:
    with pytest.raises(ValueError) as exc:
        BitvavoClient.for_private_read(api_key="", api_secret="secret")

    assert "BITVAVO_PRIVATE_READ_EXPLICIT_CREDENTIALS_REQUIRED" in str(exc.value)
    assert "secret" not in str(exc.value)


def test_public_client_cannot_call_private_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        BROKER_PRIVATE_READ_PERMISSION_ENV,
        BROKER_PRIVATE_READ_PERMISSION_GRANTED_VALUE,
    )
    client = BitvavoClient.for_public()

    with pytest.raises(RuntimeError) as exc:
        client.get_balance()

    assert "private endpoint blocked fail-closed" in str(exc.value)


def test_default_client_is_public_and_ignores_global_bitvavo_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BITVAVO_API_KEY", "global-key")
    monkeypatch.setenv("BITVAVO_API_SECRET", "global-secret")

    client = BitvavoClient()

    assert client.auth_context == "public"
    assert client.api_key == ""
    assert client.api_secret == ""


def test_private_read_client_uses_explicit_key_not_global_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_headers: list[dict[str, str]] = []
    monkeypatch.setenv("BITVAVO_API_KEY", "global-key")
    monkeypatch.setenv("BITVAVO_API_SECRET", "global-secret")
    monkeypatch.setenv(
        BROKER_PRIVATE_READ_PERMISSION_ENV,
        BROKER_PRIVATE_READ_PERMISSION_GRANTED_VALUE,
    )

    def _fake_get(_url: str, **kwargs: Any) -> _Response:
        captured_headers.append(dict(kwargs.get("headers") or {}))
        return _Response([])

    monkeypatch.setattr("requests.get", _fake_get)

    client = BitvavoClient.for_private_read(
        api_key="account-key",
        api_secret="account-secret",
    )
    assert client.get_balance() == []

    assert captured_headers
    assert captured_headers[0]["Bitvavo-Access-Key"] == "account-key"
    assert captured_headers[0]["Bitvavo-Access-Key"] != "global-key"


def test_private_read_client_cannot_write_even_when_global_write_permission_is_granted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BROKER_WRITE_PERMISSION_ENV, BROKER_WRITE_PERMISSION_GRANTED_VALUE)
    monkeypatch.setattr(
        "requests.post",
        lambda *_args, **_kwargs: pytest.fail("private-read client attempted broker write"),
    )
    client = BitvavoClient.for_private_read(
        api_key="account-key",
        api_secret="account-secret",
    )

    with pytest.raises(PermissionError) as exc:
        client.place_order(
            BitvavoOrderRequest(
                market="BTC-EUR",
                side="buy",
                order_type="limit",
                amount="0.001",
                price="1",
            )
        )

    assert "auth_context='private_read' cannot write" in str(exc.value)
    assert "account-key" not in str(exc.value)
    assert "account-secret" not in str(exc.value)


def test_no_secret_appears_in_private_client_errors() -> None:
    with pytest.raises(ValueError) as exc:
        BitvavoClient(api_key="only-key")

    assert "only-key" not in str(exc.value)
    assert "BITVAVO_EXPLICIT_CREDENTIAL_PAIR_REQUIRED" in str(exc.value)
