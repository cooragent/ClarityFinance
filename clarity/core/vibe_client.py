"""Small HTTP boundary for a separately running Vibe-Trading service."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import httpx


class VibeTradingClient:
    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = (base_url or os.getenv("VIBE_TRADING_URL", "http://127.0.0.1:8899")).rstrip("/")
        self.api_key = os.getenv("VIBE_TRADING_API_KEY", "")
        self.transport = transport

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=30,
            transport=self.transport,
        ) as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

    async def status(self) -> dict[str, Any]:
        health = await self._request("GET", "/health")
        try:
            info = await self._request("GET", "/api")
        except httpx.HTTPError:
            info = {}
        return {"connected": True, "url": self.base_url, **health, **info}

    async def create_session(self, title: str) -> dict[str, Any]:
        return await self._request("POST", "/sessions", json={"title": title, "config": {}})

    async def send_message(self, session_id: str, content: str) -> dict[str, Any]:
        return await self._request("POST", f"/sessions/{session_id}/messages", json={"content": content})

    async def messages(self, session_id: str) -> list[dict[str, Any]]:
        return await self._request("GET", f"/sessions/{session_id}/messages")

    async def events(self, session_id: str) -> AsyncIterator[bytes]:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=None,
            transport=self.transport,
        ) as client:
            async with client.stream("GET", f"/sessions/{session_id}/events", params={"replay": "active"}) as response:
                response.raise_for_status()
                async for chunk in response.aiter_raw():
                    yield chunk
