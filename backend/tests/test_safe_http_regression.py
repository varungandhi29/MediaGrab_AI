import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.security.ssrf_validator import safe_http_request


@pytest.mark.asyncio
async def test_safe_http_request_as_async_context_manager_real_link():
    """
    Regression test for:
    "'coroutine' object does not support the asynchronous context manager protocol (missed __aexit__ method)"
    Verifies that safe_http_request works with `async with` on a real link and streams chunks.
    """
    real_url = "https://httpbin.org/robots.txt"

    async with safe_http_request("GET", real_url) as resp:
        assert resp.status_code == 200
        chunks = []
        async for chunk in resp.aiter_bytes(chunk_size=128):
            chunks.append(chunk)

        body = b"".join(chunks)
        assert len(body) > 0
        assert b"Disallow" in body or b"User-agent" in body


@pytest.mark.asyncio
async def test_safe_http_request_as_awaitable_real_link():
    """
    Verifies backwards compatibility: safe_http_request can also be directly awaited.
    """
    real_url = "https://httpbin.org/robots.txt"

    resp = await safe_http_request("GET", real_url)
    assert resp.status_code == 200
    assert len(resp.text) > 0
    assert "Disallow" in resp.text or "User-agent" in resp.text


@pytest.mark.asyncio
async def test_thumbnail_proxy_real_link_end_to_end():
    """
    End-to-end test for /api/stream/thumbnail using a real link.
    Executes the exact failing code path in routes_stream.py (line 218).
    """
    transport = ASGITransport(app=app)
    real_thumb_url = "https://httpbin.org/image/jpeg"

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(f"/api/stream/thumbnail?u={real_thumb_url}")
        assert resp.status_code == 200
        assert "image" in resp.headers.get("content-type", "")
        assert len(resp.content) > 100


@pytest.mark.asyncio
async def test_subtitle_proxy_real_link_end_to_end():
    """
    End-to-end test for /api/stream/subtitle using a real link.
    Executes the exact failing code path in routes_stream.py (line 233).
    """
    transport = ASGITransport(app=app)
    real_sub_url = "https://httpbin.org/robots.txt"

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(f"/api/stream/subtitle?u={real_sub_url}")
        assert resp.status_code == 200
        assert len(resp.content) > 0
