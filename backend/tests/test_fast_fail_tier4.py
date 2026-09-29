import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.extractor import media_extractor
from app.config import settings


@pytest.mark.asyncio
async def test_fast_fail_all_tiers_specific_error():
    """
    Verifies that when tiers 1-4 cannot find media on a generic page without media,
    it fast-fails and returns the exact specific error message requested by user.
    """
    # Use a real public page with no media: e.g. example.com
    test_url = "https://example.com"

    with pytest.raises(ValueError) as excinfo:
        await media_extractor.extract_metadata(test_url)

    err_msg = str(excinfo.value)
    expected_substring = "This looks like a file-sharing page, not a video platform. It can't be played or downloaded here. Open the page and use its own download button, or paste a direct video link (.mp4 / .m3u8) or a supported site link."
    assert expected_substring in err_msg, f"Expected specific error message, got: {err_msg}"


@pytest.mark.asyncio
async def test_metadata_sse_streaming_stages():
    """
    Verifies that /api/metadata/stream sends real-time SSE stage events.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Request stream on a valid test link
        resp = await client.get("/api/metadata/stream?url=https://www.w3schools.com/html/mov_bbb.mp4")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        # Check content includes stage progression
        text = resp.text
        assert "data:" in text
        assert "stage" in text or "result" in text


@pytest.mark.asyncio
async def test_tier_timeout_configurations():
    """
    Verifies that per-tier fast-fail timeouts are correctly calibrated.
    """
    assert settings.TIER1_YTDLP_TIMEOUT_SECONDS == 8
    assert settings.TIER2_DIRECT_TIMEOUT_SECONDS == 5
    assert settings.TIER3_STATIC_SCRAPE_TIMEOUT_SECONDS == 5
    assert settings.TIER4_HEADLESS_TIMEOUT_SECONDS == 15
    assert settings.TOTAL_EXTRACTION_TIMEOUT_SECONDS == 30
