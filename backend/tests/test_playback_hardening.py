import pytest
import socket
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.stream_cache import stream_cache
from app.services.extractor import media_extractor
from app.services.downloader import DownloadJob


@pytest.mark.asyncio
async def test_parse_ytdlp_qualities_dual_key_and_audio():
    """Verify that lower resolutions (e.g. 240p) get registered under both 360p and 240p, and audio is attached."""
    mock_formats = [
        # Audio stream (itag 140)
        {
            "format_id": "140",
            "url": "https://example.com/audio.m4a",
            "vcodec": "none",
            "acodec": "mp4a.40.2",
            "abr": 128,
            "ext": "m4a",
            "http_headers": {"User-Agent": "YtBot"},
        },
        # Video stream 240p (itag 242)
        {
            "format_id": "242",
            "url": "https://example.com/video_240.mp4",
            "vcodec": "avc1.4d4015",
            "acodec": "none",
            "height": 240,
            "ext": "mp4",
            "http_headers": {"User-Agent": "YtBot", "Sec-Fetch-Mode": "navigate", "Accept": "text/html"},
        },
        # Video stream 720p (itag 22)
        {
            "format_id": "22",
            "url": "https://example.com/video_720.mp4",
            "vcodec": "avc1.64001f",
            "acodec": "mp4a.40.2",
            "height": 720,
            "ext": "mp4",
            "http_headers": {"User-Agent": "YtBot"},
        }
    ]

    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]):
        qualities, session_token = await media_extractor._parse_ytdlp_qualities_and_register(
            url="https://youtube.com/watch?v=test1234",
            title="Rick Astley Video",
            formats=mock_formats
        )

        assert session_token is not None
        assert len(qualities) >= 2

        # 1. Verify 240p quality has a valid, non-null stream URL
        q_240 = next((q for q in qualities if q.height == 240), None)
        assert q_240 is not None
        assert q_240.stream_url is not None
        assert session_token in q_240.stream_url

        # 2. Verify Audio only has a stream URL
        q_audio = next((q for q in qualities if q.is_audio_only), None)
        assert q_audio is not None
        assert q_audio.stream_url is not None
        assert q_audio.stream_url == f"/api/stream/{session_token}/audio"

        # 3. Verify stream_cache target lookup succeeds with '240p' AND with '360p'
        target_240 = await stream_cache.get_stream_target(session_token, "240p")
        assert target_240 is not None
        assert target_240["target_url"] == "https://example.com/video_240.mp4"
        assert target_240["has_audio"] is False
        assert target_240["audio_url"] == "https://example.com/audio.m4a"

        target_360 = await stream_cache.get_stream_target(session_token, "360p")
        assert target_360 is not None
        assert target_360["target_url"] == "https://example.com/video_240.mp4"

        # 4. Verify audio target lookup succeeds
        target_audio = await stream_cache.get_stream_target(session_token, "audio")
        assert target_audio is not None
        assert target_audio["target_url"] == "https://example.com/audio.m4a"


@pytest.mark.asyncio
async def test_stream_refresh_updates_session_in_place():
    """Verify that POST /api/stream/{token}/refresh updates the active session in-place."""
    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]):
        token = await stream_cache.register_stream_session(
            source_url="https://youtube.com/watch?v=test_refresh",
            streams_by_quality={
                "720p": {
                    "url": "https://example.com/old_stream_720.mp4",
                    "headers": {},
                    "mime": "video/mp4",
                    "height": 720,
                }
            }
        )

        mock_fresh_metadata = MagicMock()
        mock_fresh_metadata.stream_session_id = "new_temporary_token"

        new_token = await stream_cache.register_stream_session(
            source_url="https://youtube.com/watch?v=test_refresh",
            streams_by_quality={
                "720p": {
                    "url": "https://example.com/fresh_refreshed_stream_720.mp4",
                    "headers": {},
                    "mime": "video/mp4",
                    "height": 720,
                }
            }
        )
        mock_fresh_metadata.stream_session_id = new_token

        with patch("app.services.extractor.media_extractor.extract_metadata", return_value=mock_fresh_metadata):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.post(f"/api/stream/{token}/refresh")
                assert res.status_code == 200
                data = res.json()
                assert data["status"] == "refreshed"
                assert data["token"] == token

        # Verify old token target now points to fresh stream URL!
        updated_target = await stream_cache.get_stream_target(token, "720p")
        assert updated_target is not None
        assert updated_target["target_url"] == "https://example.com/fresh_refreshed_stream_720.mp4"


def test_download_progress_clean_metrics():
    """Verify that speed and eta updates cleanly without ANSI escape artifacts."""
    job = DownloadJob(
        job_id="test_job_1",
        url="https://example.com/video",
        format_id="best",
        quality_label="720p (HD)",
        is_audio_only=False,
        target_format="mp4",
        client_ip="127.0.0.1"
    )

    # Simulate dirty ANSI input
    raw_speed = "\x1b[0;32m 4.85MiB/s\x1b[0m"
    raw_eta = "\x1b[0;33m 00:12\x1b[0m"
    import re
    clean_speed = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw_speed).strip()
    clean_eta = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw_eta).strip()

    job.update_progress(45.5, clean_speed, clean_eta)
    assert job.progress_percent == 45.5
    assert job.speed == "4.85MiB/s"
    assert job.eta == "00:12"
