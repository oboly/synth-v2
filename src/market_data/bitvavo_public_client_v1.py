from __future__ import annotations

from typing import Any

import requests

from src.execution.bitvavo_client import BITVAVO_REST_URL


class BitvavoPublicMarketDataClient:
    def __init__(self, rest_url: str | None = None, timeout_seconds: int = 15) -> None:
        self.rest_url = rest_url or BITVAVO_REST_URL
        self.timeout_seconds = timeout_seconds

    def get_book(self, market: str, depth: int = 5) -> dict[str, Any]:
        response = requests.get(
            f"{self.rest_url}/{market}/book",
            params={"depth": depth},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
