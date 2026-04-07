from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import requests


BITVAVO_REST_URL = os.getenv("BITVAVO_REST_URL", "https://api.bitvavo.com/v2")


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

    def _sign(self, timestamp_ms: str, method: str, path: str, body: str) -> str:
        message = f"{timestamp_ms}{method}{path}{body}"
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

    def place_order(self, order: BitvavoOrderRequest) -> dict[str, Any]:
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
        path = f"/{market}/order"
        url = f"{self.rest_url}{path}"

        params = {"orderId": order_id}
        query = f"?orderId={order_id}"
        headers = self._headers("GET", f"{path}{query}", "")

        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def cancel_order(self, market: str, order_id: str) -> dict[str, Any]:
        path = f"/{market}/order"
        url = f"{self.rest_url}{path}"

        body = json.dumps({"orderId": order_id}, separators=(",", ":"))
        headers = self._headers("DELETE", path, body)

        response = requests.delete(
            url,
            headers=headers,
            data=body,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
