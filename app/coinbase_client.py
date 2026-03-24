from __future__ import annotations

import base64
import json
import time
import uuid

import httpx
import jwt


class CoinbaseClient:
    """
    Coinbase Advanced Trade REST client.

    Auth method:
    - Build JWT signed by user's EC private key (PEM).
    - Send `Authorization: Bearer <jwt>`.
    """

    def __init__(self, api_base_url: str, api_key_name: str, private_key_pem: str, timeout_seconds: float = 10.0):
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key_name = api_key_name
        self.private_key_pem = private_key_pem
        self.timeout_seconds = timeout_seconds

    def _build_jwt(self, method: str, path: str) -> str:
        now = int(time.time())
        uri = f"{method.upper()} api.coinbase.com{path}"
        payload = {
            "sub": self.api_key_name,
            "iss": "coinbase-cloud",
            "nbf": now,
            "exp": now + 120,
            "uri": uri,
        }
        headers = {
            "kid": self.api_key_name,
            "nonce": base64.urlsafe_b64encode(uuid.uuid4().bytes).decode("utf-8").rstrip("="),
        }
        token = jwt.encode(payload=payload, key=self.private_key_pem, algorithm="ES256", headers=headers)
        if isinstance(token, bytes):
            return token.decode("utf-8")
        return token

    async def create_market_order(
        self,
        product_id: str,
        side: str,
        quote_size: float,
        client_order_id: str,
    ) -> dict:
        path = "/api/v3/brokerage/orders"
        if not self.api_key_name or not self.private_key_pem:
            return {
                "success": False,
                "order_id": None,
                "status": "error",
                "reason": "coinbase credentials are not configured",
                "raw": {},
            }

        payload = {
            "client_order_id": client_order_id,
            "product_id": product_id,
            "side": side.upper(),
            "order_configuration": {
                "market_market_ioc": {
                    "quote_size": f"{quote_size:.2f}",
                }
            },
        }
        token = self._build_jwt("POST", path)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(base_url=self.api_base_url, timeout=self.timeout_seconds) as client:
            response = await client.post(path, headers=headers, content=json.dumps(payload))
        try:
            data = response.json()
        except json.JSONDecodeError:
            data = {"raw_text": response.text}
        success = bool(data.get("success")) and response.status_code < 300
        order_id = data.get("success_response", {}).get("order_id")
        reason = None if success else data.get("error_response", {}).get("message", f"HTTP {response.status_code}")
        return {
            "success": success,
            "order_id": order_id,
            "status": "submitted" if success else "error",
            "reason": reason,
            "raw": data,
        }
