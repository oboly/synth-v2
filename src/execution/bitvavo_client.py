from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env", override=True)

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


class BitvavoClient:
    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        rest_url: str | None = None,
        timeout_seconds: int = 15,
    ) -> None:
        self.api_key = api_key or os.getenv("BITVAVO_API_KEY", "")
        self.api_secret = api_secret or os.getenv("BITVAVO_API_SECRET", "")
        self.rest_url = rest_url or BITVAVO_REST_URL
        self.timeout_seconds = timeout_seconds

    def _has_auth(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _require_private_read_permission(self, action: str) -> None:
        permission_value = os.getenv(BROKER_PRIVATE_READ_PERMISSION_ENV, "")
        if permission_value != BROKER_PRIVATE_READ_PERMISSION_GRANTED_VALUE:
            raise PermissionError(
                "Bitvavo private read blocked fail-closed. "
                f"action={action} env={BROKER_PRIVATE_READ_PERMISSION_ENV} "
                "is not explicitly granted."
            )

    def _require_private_write_permission(self, action: str) -> None:
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
            /{market}/order

        Therefore the signed path must become:
            /v2/balance
            /v2/{market}/order
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

        path = f"/{order.market}/order"
        url = f"{self.rest_url}{path}"

        payload: dict[str, Any] = {
            "market": order.market,
            "side": order.side,
            "orderType": order.order_type,
            "amount": order.amount,
        }

        if order.price is not None:
            payload["price"] = order.price

        if order.order_type.lower() == "limit":
            payload["postOnly"] = order.post_only
            payload["timeInForce"] = order.time_in_force

        body = json.dumps(payload, separators=(",", ":"))
        headers = self._headers("POST", path, body)

        response = requests.post(
            url,
            headers=headers,
            data=body,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def get_order(self, market: str, order_id: str) -> dict[str, Any]:
        self._require_private_read_permission("get_order")

        path = f"/{market}/order"
        url = f"{self.rest_url}{path}"

        params = {"orderId": order_id}
        query_string = urlencode(params)
        signed_path = f"{path}?{query_string}"
        headers = self._headers("GET", signed_path, "")

        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

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
                f"status_code={response.status_code} response_text={response.text}"
            ) from exc
        return response.json()
