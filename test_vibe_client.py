import httpx
import pytest

from clarity.core.vibe_client import VibeTradingClient


@pytest.mark.asyncio
async def test_vibe_http_boundary():
    def handler(request: httpx.Request):
        payloads = {
            "/health": {"status": "healthy", "service": "Vibe-Trading API"},
            "/api": {"version": "0.1.14"},
            "/sessions": {"session_id": "s1", "title": "Clarity"},
            "/sessions/s1/messages": [] if request.method == "GET" else {"status": "started"},
        }
        return httpx.Response(200, json=payloads[request.url.path])

    client = VibeTradingClient("http://vibe.test", httpx.MockTransport(handler))
    assert (await client.status())["version"] == "0.1.14"
    assert (await client.create_session("Clarity"))["session_id"] == "s1"
    assert (await client.send_message("s1", "研究 NVDA"))["status"] == "started"
    assert await client.messages("s1") == []
