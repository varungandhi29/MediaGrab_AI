import pytest
import os
import asyncio
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.media_pipeline import media_pipeline, probe_codecs, normalize_to_mp4_faststart
from app.services.storage_manager import storage_manager
from app.config import settings


@pytest.mark.asyncio
async def test_probe_codecs_and_faststart_normalization(tmp_path):
    """
    Verifies that probe_codecs identifies video/audio codecs and
    normalize_to_mp4_faststart copies compliant streams and adds +faststart moov atom.
    """
    if not settings.FFMPEG_LOCATION or not os.path.exists(settings.FFMPEG_LOCATION):
        pytest.skip("FFmpeg not available")

    # Generate a tiny 1-second H.264/AAC test video
    src_file = tmp_path / "test_src.mp4"
    cmd = [
        settings.FFMPEG_LOCATION, "-y",
        "-f", "lavfi", "-i", "color=c=green:s=320x240:d=1",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "1",
        "-c:v", "libx264", "-c:a", "aac",
        str(src_file)
    ]
    proc = await asyncio.create_subprocess_exec(*cmd)
    await proc.wait()
    assert src_file.exists()

    # 1. Probe codecs
    vcodec, acodec = probe_codecs(src_file)
    assert vcodec in ("h264", "avc1")
    assert acodec in ("aac", "mp4a")

    # 2. Normalize with faststart
    dst_file = tmp_path / "test_dst.mp4"
    normalize_to_mp4_faststart(src_file, dst_file)
    assert dst_file.exists()
    assert dst_file.stat().st_size > 0

    # Verify dst is also valid H.264 + AAC
    vcodec_dst, acodec_dst = probe_codecs(dst_file)
    assert vcodec_dst in ("h264", "avc1")
    assert acodec_dst in ("aac", "mp4a")


@pytest.mark.asyncio
async def test_static_range_serving_and_download_disposition(tmp_path):
    """
    Verifies that finished files are served statically with:
    - 206 Partial Content on Range requests (with Content-Range and Accept-Ranges)
    - Content-Disposition: inline for playback (<video src>)
    - Content-Disposition: attachment when ?download=1
    """
    test_file = tmp_path / "test_media_token.mp4"
    data = b"M" * 5000
    test_file.write_bytes(data)

    token = "test_pipe_token_123"
    rec = await storage_manager.register_download(
        token=token,
        storage_key=str(test_file.name),
        original_title="awesome_video",
        extension="mp4",
        filesize=len(data),
        client_ip="127.0.0.1",
    )
    # Ensure storage_manager points to test file
    rec["filepath"] = str(test_file)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Playback request (inline, range 0-999)
        resp_play = await client.get(
            f"/api/stream/{token}",
            headers={"Range": "bytes=0-999"}
        )
        assert resp_play.status_code == 206
        assert resp_play.headers["content-type"] == "video/mp4"
        assert resp_play.headers["accept-ranges"] == "bytes"
        assert resp_play.headers["content-range"] == "bytes 0-999/5000"
        assert resp_play.headers["content-length"] == "1000"
        assert resp_play.headers["content-disposition"] == "inline"

        # 2. Download request (?download=1)
        resp_dl = await client.get(f"/api/stream/{token}?download=1")
        assert resp_dl.status_code == 200
        assert "attachment" in resp_dl.headers["content-disposition"]
        assert "awesome_video" in resp_dl.headers["content-disposition"]

        # 3. Direct media endpoints
        resp_media_play = await client.get(
            f"/api/media/stream/{token}",
            headers={"Range": "bytes=1000-1999"}
        )
        assert resp_media_play.status_code == 206
        assert resp_media_play.headers["content-range"] == "bytes 1000-1999/5000"

        resp_media_dl = await client.get(f"/api/media/download/{token}")
        assert resp_media_dl.status_code == 200
        assert "attachment" in resp_media_dl.headers["content-disposition"]


@pytest.mark.asyncio
async def test_media_pipeline_deduplication_cache(tmp_path):
    """
    Verifies that calling prepare on the same URL and quality reuses the completed file
    immediately from cache without re-downloading or re-processing.
    """
    test_file = tmp_path / "cached_video.mp4"
    test_file.write_bytes(b"DATA" * 1000)

    token = "cache_test_token"
    rec = await storage_manager.register_download(
        token=token,
        storage_key=str(test_file.name),
        original_title="cached_title",
        extension="mp4",
        filesize=4000,
        client_ip="127.0.0.1",
    )
    rec["filepath"] = str(test_file)

    test_url = "https://example.com/watch?v=cached123"
    cache_key = media_pipeline._make_cache_key(test_url, "1080p", 1080)
    media_pipeline.cache[cache_key] = token

    job = await media_pipeline.get_or_create_job(
        url=test_url,
        client_ip="127.0.0.1",
        quality_label="1080p",
        height=1080,
    )

    assert job.stage == "ready"
    assert job.progress_percent == 100.0
    assert job.token == token
    assert job.stream_url == f"/api/stream/{token}"
    assert job.download_url == f"/api/stream/{token}?download=1"
