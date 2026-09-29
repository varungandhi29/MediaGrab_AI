import pytest
import socket
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.stream_cache import stream_cache
from app.security.ssrf_validator import SSRFValidationError


@pytest.mark.asyncio
async def test_stream_cache_registration_and_lookup():
    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]):
        token = await stream_cache.register_stream_session(
            source_url="https://example.com/watch?v=123",
            streams_by_quality={
                "1080p": {
                    "url": "https://example.com/video_1080.mp4",
                    "headers": {"User-Agent": "TestPlayer"},
                    "mime": "video/mp4",
                    "is_hls": False,
                    "height": 1080,
                },
                "720p": {
                    "url": "https://example.com/video_720.mp4",
                    "headers": {},
                    "mime": "video/mp4",
                    "is_hls": False,
                    "height": 720,
                }
            },
            title="Test Stream"
        )
        assert token is not None
        assert len(token) > 10

        # Retrieve 1080p
        target_1080 = await stream_cache.get_stream_target(token, "1080p")
        assert target_1080 is not None
        assert target_1080["target_url"] == "https://example.com/video_1080.mp4"
        assert target_1080["mime"] == "video/mp4"

        # Retrieve fallback when unknown quality requested
        target_fallback = await stream_cache.get_stream_target(token, "unknown_4k")
        assert target_fallback is not None

        # Retrieve with non-existent token
        target_none = await stream_cache.get_stream_target("invalid_token_xyz", "1080p")
        assert target_none is None


@pytest.mark.asyncio
async def test_stream_cache_ssrf_rejection():
    # Attempting to register an internal SSRF target
    token = await stream_cache.register_stream_session(
        source_url="https://example.com",
        streams_by_quality={
            "native": {
                "url": "http://169.254.169.254/latest/meta-data/",
                "headers": {},
                "mime": "video/mp4",
                "is_hls": False,
                "height": 720,
            }
        }
    )

    # Retrieval should raise SSRFValidationError
    with pytest.raises(SSRFValidationError):
        await stream_cache.get_stream_target(token, "native")


@pytest.mark.asyncio
async def test_proxy_media_stream_range_206():
    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]):
        token = await stream_cache.register_stream_session(
            source_url="https://example.com/video",
            streams_by_quality={
                "720p": {
                    "url": "https://example.com/media/sample_720.mp4",
                    "headers": {},
                    "mime": "video/mp4",
                    "is_hls": False,
                    "height": 720,
                }
            }
        )

    # Mock response object for upstream httpx
    mock_resp = MagicMock()
    mock_resp.status_code = 206
    mock_resp.is_redirect = False
    mock_resp.headers = {
        "content-type": "video/mp4",
        "content-range": "bytes 0-499/1000",
        "content-length": "500",
        "accept-ranges": "bytes",
    }

    async def gen_chunks(chunk_size=65536):
        yield b"x" * 500

    mock_resp.aiter_bytes = gen_chunks
    mock_resp.aclose = AsyncMock()

    mock_client_instance = MagicMock()
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=None)
    mock_client_instance.build_request = MagicMock()
    mock_client_instance.send = AsyncMock(return_value=mock_resp)
    mock_client_instance.aclose = AsyncMock()

    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]):
        with patch("app.api.routes_stream.httpx.AsyncClient", return_value=mock_client_instance):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                resp = await client.get(
                    f"/api/stream/{token}/720p",
                    headers={"Range": "bytes=0-499"}
                )
                assert resp.status_code == 206
                assert resp.headers["content-type"] == "video/mp4"
                assert resp.headers["accept-ranges"] == "bytes"
                assert resp.headers.get("content-range") == "bytes 0-499/1000"
                assert resp.content == b"x" * 500

                # Request with invalid token
                resp_404 = await client.get("/api/stream/nonexistent_token/720p")
                assert resp_404.status_code == 404


@pytest.mark.asyncio
async def test_stream_cors_options_preflight():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.options("/api/stream/some_token/720p")
        assert resp.status_code == 204
        assert resp.headers["access-control-allow-origin"] == "*"
        assert "GET" in resp.headers["access-control-allow-methods"]
        assert "HEAD" in resp.headers["access-control-allow-methods"]
        assert "Range" in resp.headers["access-control-allow-headers"]
        assert "Content-Range" in resp.headers["access-control-expose-headers"]


@pytest.mark.asyncio
async def test_stream_expired_detection():
    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]):
        token = await stream_cache.register_stream_session(
            source_url="https://example.com/expired-video",
            streams_by_quality={
                "1080p": {
                    "url": "https://example.com/signed_expired_token.mp4",
                    "headers": {},
                    "mime": "video/mp4",
                    "is_hls": False,
                    "height": 1080,
                }
            }
        )

    # Upstream returns 403 Forbidden because CDN token expired
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.is_redirect = False
    mock_resp.headers = {"content-type": "text/html"}
    mock_resp.aclose = AsyncMock()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.build_request = MagicMock()
    mock_client.send = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]):
        with patch("app.api.routes_stream.httpx.AsyncClient", return_value=mock_client):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                resp = await client.get(f"/api/stream/{token}/1080p")
                assert resp.status_code == 410
                data = resp.json()
                assert data["code"] == "STREAM_EXPIRED"
                assert data["can_refresh"] is True


@pytest.mark.asyncio
async def test_hls_manifest_rewriting():
    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]):
        token = await stream_cache.register_stream_session(
            source_url="https://example.com/playlist",
            streams_by_quality={
                "hls": {
                    "url": "https://example.com/media/master.m3u8",
                    "headers": {},
                    "mime": "application/x-mpegURL",
                    "is_hls": True,
                    "height": 720,
                }
            }
        )

    raw_manifest = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXT-X-TARGETDURATION:10\n"
        "#EXTINF:10.0,\n"
        "segment_0.ts\n"
        "#EXTINF:10.0,\n"
        "https://cdn.example.com/segment_1.ts\n"
        "#EXT-X-ENDLIST\n"
    ).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_redirect = False
    mock_resp.headers = {"content-type": "application/vnd.apple.mpegurl"}
    mock_resp.aread = AsyncMock(return_value=raw_manifest)
    mock_resp.aclose = AsyncMock()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.build_request = MagicMock()
    mock_client.send = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]):
        with patch("app.api.routes_stream.httpx.AsyncClient", return_value=mock_client):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                resp = await client.get(f"/api/stream/{token}/hls")
                assert resp.status_code == 200
                manifest_text = resp.text
                assert f"/api/stream/{token}/hls/segment?u=" in manifest_text
                assert "segment_0.ts" in manifest_text
                assert resp.headers["access-control-allow-origin"] == "*"


@pytest.mark.asyncio
async def test_serve_file_range_partial_content(tmp_path):
    from app.api.routes_stream import _serve_file_range
    from starlette.requests import Request

    test_file = tmp_path / "test_media.mp4"
    data = b"0123456789" * 100  # 1000 bytes
    test_file.write_bytes(data)

    # 1. Full file request (no Range) -> 200 OK
    scope_full = {"type": "http", "method": "GET", "headers": []}
    req_full = Request(scope_full)
    resp_full = _serve_file_range(test_file, req_full)
    assert resp_full.status_code == 200
    assert resp_full.headers["Content-Length"] == "1000"
    assert resp_full.headers["Accept-Ranges"] == "bytes"

    # 2. Byte Range request Range: bytes=100-199 -> 206 Partial Content
    scope_range = {
        "type": "http",
        "method": "GET",
        "headers": [(b"range", b"bytes=100-199")],
    }
    req_range = Request(scope_range)
    resp_range = _serve_file_range(test_file, req_range)
    assert resp_range.status_code == 206
    assert resp_range.headers["Content-Range"] == "bytes 100-199/1000"
    assert resp_range.headers["Content-Length"] == "100"

    # 3. Open-ended Range: bytes=900- -> 206 Partial Content (last 100 bytes)
    scope_open = {
        "type": "http",
        "method": "GET",
        "headers": [(b"range", b"bytes=900-")],
    }
    req_open = Request(scope_open)
    resp_open = _serve_file_range(test_file, req_open)
    assert resp_open.status_code == 206
    assert resp_open.headers["Content-Range"] == "bytes 900-999/1000"
    assert resp_open.headers["Content-Length"] == "100"

    # 4. Out of bounds Range: bytes=2000- -> 416 Range Not Satisfiable
    scope_invalid = {
        "type": "http",
        "method": "GET",
        "headers": [(b"range", b"bytes=2000-")],
    }
    req_invalid = Request(scope_invalid)
    resp_invalid = _serve_file_range(test_file, req_invalid)
    assert resp_invalid.status_code == 416
    assert resp_invalid.headers["Content-Range"] == "bytes */1000"


@pytest.mark.asyncio
async def test_stream_proxy_timestamp_seeking_and_codec_copy():
    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]):
        token = await stream_cache.register_stream_session(
            source_url="https://example.com/test-4k",
            streams_by_quality={
                "2160p": {
                    "url": "https://example.com/video_4k.mp4",
                    "headers": {},
                    "mime": "video/mp4",
                    "is_hls": False,
                    "height": 2160,
                    "vcodec": "vp09.00.51.08",
                    "acodec": "none",
                    "has_audio": False,
                    "audio_url": "https://example.com/audio.m4a",
                }
            }
        )

    # Mock _stream_transcoded_ffmpeg to verify parameters passed
    with patch("app.api.routes_stream._stream_transcoded_ffmpeg", new_callable=AsyncMock) as mock_ffmpeg:
        from fastapi.responses import Response
        mock_ffmpeg.return_value = Response(content=b"stream-data", media_type="video/mp4")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get(f"/api/stream/{token}/2160p?ss=35.5")
            assert resp.status_code == 200
            mock_ffmpeg.assert_called_once()
            call_kwargs = mock_ffmpeg.call_args.kwargs
            # VP9 stream should NOT force video re-encoding (preserves pristine 4K quality with copy)
            assert call_kwargs["force_transcode_video"] is False
            # ss timestamp should be accurately passed
            assert call_kwargs["ss"] == 35.5
            assert call_kwargs["audio_url"] == "https://example.com/audio.m4a"


