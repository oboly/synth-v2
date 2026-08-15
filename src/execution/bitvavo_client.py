from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse
from urllib.parse import urlencode

import requests


BITVAVO_REST_URL = (
    os.getenv("BITVAVO_REST_URL")
    or os.getenv("BITVAVO_BASE_URL")
    or "https://api.bitvavo.com/v2"
)

# Broker private read calls are fail-closed by default.
# Required exact value:
#   SYNTH_BROKER_PRIVATE_READ_PERMISSION=I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA
BROKER_PRIVATE_READ_PERMISSION_ENV = "SYNTH_BROKER_PRIVATE_READ_PERMISSION"
BROKER_PRIVATE_READ_PERMISSION_GRANTED_VALUE = "I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA"

# Broker write calls are fail-closed by default.
# Required exact value:
#   SYNTH_BROKER_WRITE_PERMISSION=I_UNDERSTAND_THIS_PLACES_REAL_ORDERS
BROKER_WRITE_PERMISSION_ENV = "SYNTH_BROKER_WRITE_PERMISSION"
BROKER_WRITE_PERMISSION_GRANTED_VALUE = "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS"


@dataclass(slots=True)
class BitvavoOrderRequest:
    market: str
    side: str
    order_type: str
    amount: str
    price: str | None = None
    post_only: bool = True
    time_in_force: str = "GTC"
    operator_id: int | None = None
    client_order_id: str | None = None


class BitvavoOrderRequestError(RuntimeError):
    """Bitvavo returned a definitive HTTP error response (a real response
    was received; the request was not lost in flight). Carries the
    normalized status_code so callers can distinguish a definitive
    rejection from network-level ambiguity without parsing message text.
    Never includes credential material."""

    def __init__(self, *, action: str, status_code: int, response_text: str = "") -> None:
        self.action = action
        self.status_code = status_code
        # response_text is deliberately discarded: raw broker bodies are not
        # safe exception or persistence evidence.
        super().__init__(f"Bitvavo {action} failed. status_code={status_code}")


class BitvavoOrderNotFoundError(LookupError):
    """The broker definitively confirmed no such order exists (e.g. HTTP
    404). Distinct from network-level ambiguity, where the exception
    propagates unchanged instead of being translated to this type."""


class BitvavoClient:
    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        rest_url: str | None = None,
        timeout_seconds: int = 15,
        auth_context: str = "public",
    ) -> None:
        if bool(api_key) != bool(api_secret):
            raise ValueError("BITVAVO_EXPLICIT_CREDENTIAL_PAIR_REQUIRED")
        self.api_key = api_key or ""
        self.api_secret = api_secret or ""
        self.rest_url = rest_url or BITVAVO_REST_URL
        self.timeout_seconds = timeout_seconds
        self.auth_context = auth_context

    @classmethod
    def for_public(
        cls,
        *,
        rest_url: str | None = None,
        timeout_seconds: int = 15,
    ) -> "BitvavoClient":
        return cls(
            rest_url=rest_url,
            timeout_seconds=timeout_seconds,
            auth_context="public",
        )

    @classmethod
    def for_private_read(
        cls,
        *,
        api_key: str,
        api_secret: str,
        rest_url: str | None = None,
        timeout_seconds: int = 15,
    ) -> "BitvavoClient":
        if not (api_key or "").strip() or not (api_secret or "").strip():
            raise ValueError("BITVAVO_PRIVATE_READ_EXPLICIT_CREDENTIALS_REQUIRED")
        return cls(
            api_key=api_key,
            api_secret=api_secret,
            rest_url=rest_url,
            timeout_seconds=timeout_seconds,
            auth_context="private_read",
        )

    @classmethod
    def for_private_write(
        cls,
        *,
        api_key: str,
        api_secret: str,
        rest_url: str | None = None,
        timeout_seconds: int = 15,
    ) -> "BitvavoClient":
        if not (api_key or "").strip() or not (api_secret or "").strip():
            raise ValueError("BITVAVO_PRIVATE_WRITE_EXPLICIT_CREDENTIALS_REQUIRED")
        return cls(
            api_key=api_key,
            api_secret=api_secret,
            rest_url=rest_url,
            timeout_seconds=timeout_seconds,
            auth_context="private_write",
        )

    def _has_auth(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _require_private_auth(self, action: str) -> None:
        if not self._has_auth():
            raise RuntimeError(
                "Bitvavo private endpoint blocked fail-closed. "
                f"action={action} auth_context={self.auth_context!r} "
                "requires explicit private credentials."
            )

    def _require_private_read_permission(self, action: str) -> None:
        self._require_private_auth(action)
        permission_value = os.getenv(BROKER_PRIVATE_READ_PERMISSION_ENV, "")
        if permission_value != BROKER_PRIVATE_READ_PERMISSION_GRANTED_VALUE:
            raise PermissionError(
                "Bitvavo private read blocked fail-closed. "
                f"action={action} env={BROKER_PRIVATE_READ_PERMISSION_ENV} "
                "is not explicitly granted."
            )

    def _require_private_write_permission(self, action: str) -> None:
        self._require_private_auth(action)
        if self.auth_context == "private_read":
            raise PermissionError(
                "Bitvavo broker write blocked fail-closed. "
                f"action={action} auth_context='private_read' cannot write."
            )
        permission_value = os.getenv(BROKER_WRITE_PERMISSION_ENV, "")
        if permission_value != BROKER_WRITE_PERMISSION_GRANTED_VALUE:
            raise PermissionError(
                "Bitvavo broker write blocked fail-closed. "
                f"action={action} env={BROKER_WRITE_PERMISSION_ENV} "
                "is not explicitly granted."
            )

    def _signed_path(self, path: str) -> str:
        """
        Bitvavo signs the API path including the REST version prefix.

        Runtime URLs use rest_url such as:
            https://api.bitvavo.com/v2

        Endpoint paths inside this client use:
            /balance
            /order

        Therefore the signed path must become:
            /v2/balance
            /v2/order
        """
        rest_path = urlparse(self.rest_url).path.rstrip("/")

        if not path.startswith("/"):
            path = f"/{path}"

        if rest_path and not path.startswith(f"{rest_path}/") and path != rest_path:
            return f"{rest_path}{path}"

        return path

    def _sign(self, timestamp_ms: str, method: str, path: str, body: str) -> str:
        signed_path = self._signed_path(path)
        message = f"{timestamp_ms}{method}{signed_path}{body}"
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    def _headers(self, method: str, path: str, body: str) -> dict[str, str]:
        if not self._has_auth():
            raise RuntimeError("Bitvavo API credentials are not configured.")

        timestamp_ms = str(int(time.time() * 1000))
        signature = self._sign(timestamp_ms, method, path, body)

        return {
            "Bitvavo-Access-Key": self.api_key,
            "Bitvavo-Access-Signature": signature,
            "Bitvavo-Access-Timestamp": timestamp_ms,
            "Bitvavo-Access-Window": "10000",
            "Content-Type": "application/json",
        }

    def get_ticker_price(self, market: str) -> Decimal:
        url = f"{self.rest_url}/ticker/price"
        response = requests.get(
            url,
            params={"market": market},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return Decimal(str(data["price"]))

    def get_markets(self) -> list[dict[str, Any]]:
        """Public market metadata: tickSize, quantityDecimals, min/max order
        size, orderTypes, status. No credentials required; no permission gate
        (matches get_ticker_price/get_book, both public)."""
        url = f"{self.rest_url}/markets"
        response = requests.get(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise RuntimeError("Unexpected Bitvavo markets response shape.")
        return data

    def get_book(self, market: str, depth: int = 5) -> dict[str, Any]:
        url = f"{self.rest_url}/{market}/book"
        response = requests.get(
            url,
            params={"depth": depth},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def get_balance(self, symbol: str | None = None) -> list[dict[str, Any]]:
        self._require_private_read_permission("get_balance")

        path = "/balance"
        params: dict[str, str] = {}

        if symbol:
            params["symbol"] = symbol.upper()

        query_string = urlencode(params)
        signed_path = f"{path}?{query_string}" if query_string else path
        url = f"{self.rest_url}{path}"

        headers = self._headers("GET", signed_path, "")

        response = requests.get(
            url,
            headers=headers,
            params=params or None,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()

        data = response.json()
        if not isinstance(data, list):
            raise RuntimeError("Unexpected Bitvavo balance response shape.")

        return data

    def get_open_orders(
        self,
        market: str | None = None,
        base: str | None = None,
    ) -> list[dict[str, Any]]:
        self._require_private_read_permission("get_open_orders")

        path = "/ordersOpen"
        params: dict[str, str] = {}

        if market:
            params["market"] = market

        if base:
            params["base"] = base

        query_string = urlencode(params)
        signed_path = f"{path}?{query_string}" if query_string else path
        url = f"{self.rest_url}{path}"
        headers = self._headers("GET", signed_path, "")

        response = requests.get(
            url,
            headers=headers,
            params=params or None,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()

        data = response.json()
        if not isinstance(data, list):
            raise RuntimeError("Unexpected Bitvavo open orders response shape.")

        return data

    def place_order(self, order: BitvavoOrderRequest) -> dict[str, Any]:
        self._require_private_write_permission("place_order")

        if order.operator_id is None:
            raise ValueError("BitvavoOrderRequest.operator_id is required for place_order")

        path = "/order"
        url = f"{self.rest_url}{path}"

        payload: dict[str, Any] = {
            "market": order.market,
            "side": order.side,
            "orderType": order.order_type,
            "amount": order.amount,
            "operatorId": order.operator_id,
        }

        if order.client_order_id is not None:
            payload["clientOrderId"] = order.client_order_id

        if order.price is not None:
            payload["price"] = order.price

        if order.order_type.lower() == "limit":
            payload["postOnly"] = order.post_only
            payload["timeInForce"] = order.time_in_force

        body = json.dumps(payload, separators=(",", ":"))
        headers = self._headers("POST", path, body)

        # No retry loop here: any network-level exception (timeout,
        # connection drop) propagates to the caller unchanged, since only a
        # caller that knows about crash-safe per-leg reconciliation may
        # resolve the outcome. A caught
        # requests.HTTPError below means a real HTTP response was received,
        # which is a definitive (non-ambiguous) broker outcome.
        response = requests.post(
            url,
            headers=headers,
            data=body,
            timeout=self.timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise BitvavoOrderRequestError(
                action="place_order",
                status_code=response.status_code,
                response_text=response.text,
            ) from exc
        return response.json()

    def get_order(
        self,
        market: str,
        order_id: str | None = None,
        *,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_private_read_permission("get_order")

        if bool(order_id) == bool(client_order_id):
            raise ValueError("get_order requires exactly one of order_id or client_order_id")

        path = "/order"
        url = f"{self.rest_url}{path}"

        params = {"market": market}
        params.update({"orderId": order_id} if order_id else {"clientOrderId": client_order_id})
        query_string = urlencode(params)
        signed_path = f"{path}?{query_string}"
        headers = self._headers("GET", signed_path, "")

        # As in place_order, network-level exceptions propagate unchanged
        # (ambiguous). Only Bitvavo's documented 404/errorCode=240 order-
        # absence response is translated to BitvavoOrderNotFoundError. Other
        # HTTP errors are not confident "does not exist" answers.
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=self.timeout_seconds,
        )
        if response.status_code == 404:
            try:
                error_payload = response.json()
            except (TypeError, ValueError):
                error_payload = None
            if (
                isinstance(error_payload, dict)
                and error_payload.get("errorCode") == 240
            ):
                raise BitvavoOrderNotFoundError("BITVAVO_ORDER_NOT_FOUND")
            raise BitvavoOrderRequestError(
                action="get_order",
                status_code=response.status_code,
            )
        response.raise_for_status()
        return response.json()

    def get_order_by_client_order_id(self, market: str, client_order_id: str) -> dict[str, Any]:
        """Reconciliation-only lookup used by executor orchestrators.
        Raises BitvavoOrderNotFoundError if the broker
        definitively confirms no such order exists; propagates
        network-level exceptions unchanged (ambiguous)."""
        return self.get_order(market, client_order_id=client_order_id)

    def cancel_order(self, market: str, order_id: str) -> dict[str, Any]:
        self._require_private_write_permission("cancel_order")

        path = "/order"
        url = f"{self.rest_url}{path}"
        params = {
            "market": market,
            "orderId": order_id,
            "operatorId": 1,
        }
        query_string = urlencode(params)
        signed_path = f"{path}?{query_string}"
        headers = self._headers("DELETE", signed_path, "")

        response = requests.delete(
            url,
            headers=headers,
            params=params,
            timeout=self.timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                "Bitvavo cancel_order failed. "
                f"status_code={response.status_code}"
            ) from exc
        return response.json()
