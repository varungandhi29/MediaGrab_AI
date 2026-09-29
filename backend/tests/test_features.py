import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.schemas import MediaMetadataResponse, DownloadRequest, SubtitleTrack
from app.services.extractor import media_extractor


@pytest.mark.asyncio
async def test_thumbnail_proxy_blocks_ssrf():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Loopback IP
        resp = await client.get("/api/stream/thumbnail?u=http://127.0.0.1:8080/secret.jpg")
        assert resp.status_code == 400
        assert "SSRF" in resp.text or "rejected" in resp.text

        # AWS metadata endpoint
        resp_aws = await client.get("/api/stream/thumbnail?u=http://169.254.169.254/latest/meta-data/thumb.png")
        assert resp_aws.status_code == 400


@pytest.mark.asyncio
async def test_subtitle_proxy_blocks_ssrf():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/stream/subtitle?u=http://10.0.0.1/subtitles.vtt")
        assert resp.status_code == 400
        assert "SSRF" in resp.text or "rejected" in resp.text


@pytest.mark.asyncio
async def test_download_schema_supports_clip_trimming():
    payload = {
        "url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
        "quality_label": "1080p",
        "format_id": "bestvideo+bestaudio/best",
        "is_audio_only": False,
        "target_format": "mp4",
        "start_time": "00:00:15",
        "end_time": "00:01:30"
    }
    req = DownloadRequest(**payload)
    assert req.start_time == "00:00:15"
    assert req.end_time == "00:01:30"


@pytest.mark.asyncio
async def test_subtitle_track_model():
    track = SubtitleTrack(
        lang="en",
        name="English (CC)",
        ext="vtt",
        url="https://example.com/subs.vtt",
        proxy_url="/api/stream/subtitle?u=https%3A%2F%2Fexample.com%2Fsubs.vtt&lang=en"
    )
    assert track.lang == "en"
    assert track.name == "English (CC)"
    assert track.proxy_url.startswith("/api/stream/subtitle")
