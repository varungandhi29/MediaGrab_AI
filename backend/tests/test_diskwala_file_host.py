import logging
import pytest
from unittest.mock import AsyncMock, patch

from app.services.extractor import media_extractor
from app.models.schemas import MediaMetadataResponse, MediaQualityOption
from app.resilience.error_classifier import (
    FailureCategory,
    classify_error,
    get_ux_error_details,
    FILE_HOST_UNSUPPORTED,
    FILE_HOST_UNSUPPORTED_MESSAGE,
)


@pytest.mark.asyncio
async def test_diskwala_file_host_unsupported(caplog):
    """
    Asserts requirement 1, 2, 4, 6:
    When yt-dlp reports Unsupported URL AND static-scrape and browser tiers
    find no media source, extractor raises FILE_HOST_UNSUPPORTED with the exact message,
    and logs the domain and result of each tier.
    Zero real network calls are made: all tier results are mocked.
    """
    diskwala_url = "https://diskwala.com/view/sample123"

    with patch("app.services.extractor.validate_url_ssrf", return_value=(True, diskwala_url, None)), \
         patch.object(
             media_extractor,
             "_try_ytdlp_extraction",
             new=AsyncMock(side_effect=RuntimeError(f"yt-dlp extraction failed: ERROR: Unsupported URL: {diskwala_url}"))
         ), \
         patch.object(media_extractor, "_try_direct_media_link", new=AsyncMock(return_value=None)), \
         patch.object(media_extractor, "_try_embedded_html_scrape", new=AsyncMock(return_value=None)), \
         patch.object(media_extractor, "_try_headless_browser_fallback", new=AsyncMock(return_value=None)):

        with caplog.at_level(logging.WARNING):
            with pytest.raises(ValueError) as exc_info:
                await media_extractor.extract_metadata(diskwala_url)

        err_msg = str(exc_info.value)
        # 1. Exact message assertion
        expected_msg = (
            "This looks like a file-sharing page, not a video platform. It can't be played or downloaded here. "
            "Open the page and use its own download button, or paste a direct video link (.mp4 / .m3u8) or a supported site link."
        )
        assert err_msg == expected_msg
        assert err_msg == FILE_HOST_UNSUPPORTED_MESSAGE

        # 2. FailureCategory assertion
        classification = classify_error(exc_info.value, diskwala_url)
        assert classification.category == FailureCategory.FILE_HOST_UNSUPPORTED
        assert classification.category == FILE_HOST_UNSUPPORTED

        # 3. UX error details assertion
        ux_details = get_ux_error_details(err_msg, diskwala_url)
        assert ux_details["error_class"] == "FILE_HOST_UNSUPPORTED"
        assert ux_details["what_happened"] == expected_msg

        # 4. Tier results logging assertion
        log_text = caplog.text
        assert "Extraction failed for domain 'diskwala.com'. Tier results:" in log_text
        assert "unsupported_url" in log_text
        assert "no_media" in log_text


@pytest.mark.asyncio
async def test_ytdlp_unsupported_but_scrape_finds_media():
    """
    If yt-dlp reports Unsupported URL, but static scrape (Tier 3) finds an embedded video tag,
    it succeeds and does NOT raise FILE_HOST_UNSUPPORTED.
    """
    url = "https://some-video-host.com/watch/123"
    fake_meta = MediaMetadataResponse(
        url=url,
        platform="Embedded HTML5 Video",
        title="Sample Video",
        thumbnail=None,
        thumbnail_proxy=None,
        duration_seconds=120.0,
        duration_formatted="2:00",
        uploader="some-video-host.com",
        description="Extracted via scrape",
        available_qualities=[
            MediaQualityOption(
                quality_label="Native Direct Stream",
                format_id="direct",
                ext="mp4",
                filesize_approx=1000,
                filesize_display="1.0 KB",
                resolution="Native",
                height=720,
                is_audio_only=False,
                is_hls=False,
                stream_url="https://some-video-host.com/stream.mp4"
            )
        ],
        source_type="scraped",
        extraction_tier=3
    )

    with patch("app.services.extractor.validate_url_ssrf", return_value=(True, url, None)), \
         patch.object(
             media_extractor,
             "_try_ytdlp_extraction",
             new=AsyncMock(side_effect=RuntimeError(f"yt-dlp extraction failed: ERROR: Unsupported URL: {url}"))
         ), \
         patch.object(media_extractor, "_try_direct_media_link", new=AsyncMock(return_value=None)), \
         patch.object(media_extractor, "_try_embedded_html_scrape", new=AsyncMock(return_value=fake_meta)), \
         patch.object(media_extractor, "_try_headless_browser_fallback", new=AsyncMock(return_value=None)):

        result = await media_extractor.extract_metadata(url)
        assert result.title == "Sample Video"
        assert result.extraction_tier == 3


@pytest.mark.asyncio
async def test_safe_http_request_max_bytes_exceeded_raises_error():
    """
    Asserts requirement: safe_http_request enforces max_bytes on the awaited path
    and raises ValueError if the response body is larger than max_bytes.
    """
    from app.security.ssrf_validator import safe_http_request
    import httpx

    fake_resp = httpx.Response(
        status_code=200,
        content=b"A" * 500,
        headers={"content-length": "500", "content-type": "text/plain"},
        request=httpx.Request("GET", "https://example.com/test"),
    )

    with patch("app.security.ssrf_validator.validate_url_ssrf", return_value=(True, "https://example.com/test", None)), \
         patch("httpx.AsyncClient.request", new=AsyncMock(return_value=fake_resp)):

        # Should raise ValueError because 500 > max_bytes=100
        with pytest.raises(ValueError) as exc_info:
            await safe_http_request("GET", "https://example.com/test", max_bytes=100)

        assert "Response body exceeded maximum allowed size" in str(exc_info.value)


@pytest.mark.asyncio
async def test_pinned_network_backend_uses_pinned_ip():
    """
    Asserts requirement: safe_http_request pins the validated IP for the actual
    connection so DNS rebinding cannot bypass the SSRF check.
    """
    from app.security.ssrf_validator import PinnedNetworkBackend
    from unittest.mock import MagicMock

    ip_map = {"example.com": "93.184.216.34"}
    backend = PinnedNetworkBackend(ip_map)

    mock_stream = AsyncMock()
    mock_base = MagicMock()
    mock_base.connect_tcp = AsyncMock(return_value=mock_stream)
    backend._backend = mock_base

    await backend.connect_tcp(
        host="example.com",
        port=443,
        timeout=5.0
    )

    # Verify that connect_tcp connected to the PINNED IP 93.184.216.34 instead of the hostname
    mock_base.connect_tcp.assert_awaited_once()
    called_args, called_kwargs = mock_base.connect_tcp.call_args
    assert called_kwargs.get("host") == "93.184.216.34"
    assert called_kwargs.get("port") == 443

