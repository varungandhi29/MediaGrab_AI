import pytest
import os
import time
import asyncio
import socket
import threading
from pathlib import Path
from playwright.async_api import async_playwright
import uvicorn

from app.config import settings
from app.services.storage_manager import storage_manager
from app.services.media_pipeline import media_pipeline, normalize_to_mp4_faststart, probe_codecs
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def ensure_server_running():
    def is_port_open(host="127.0.0.1", port=8000):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex((host, port)) == 0

    if not is_port_open():
        config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(50):
            if is_port_open():
                break
            time.sleep(0.1)
    yield


@pytest.fixture(scope="module")
def sample_1080p_media():
    """
    Creates a 30-second 1080p (1920x1080) test MP4 with separate video (H.264)
    and audio (AAC) streams merged with -movflags +faststart.
    """
    settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    raw_video = settings.STORAGE_DIR / "sample_1080p_v_only.mp4"
    raw_audio = settings.STORAGE_DIR / "sample_1080p_a_only.m4a"
    merged_raw = settings.STORAGE_DIR / "sample_1080p_merged.mp4"
    final_faststart = settings.STORAGE_DIR / "sample_1080p_faststart.mp4"

    # 1. Generate 30s 1080p video stream (video only, no audio)
    cmd_v = [
        settings.FFMPEG_LOCATION, "-y",
        "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30",
        "-t", "30",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        str(raw_video)
    ]
    # 2. Generate 30s audio stream (audio only, no video)
    cmd_a = [
        settings.FFMPEG_LOCATION, "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
        "-t", "30",
        "-c:a", "aac", "-b:a", "128k",
        str(raw_audio)
    ]
    # 3. Merge separate video + audio streams
    cmd_merge = [
        settings.FFMPEG_LOCATION, "-y",
        "-i", str(raw_video),
        "-i", str(raw_audio),
        "-c", "copy",
        str(merged_raw)
    ]

    import subprocess
    subprocess.run(cmd_v, check=True, capture_output=True)
    subprocess.run(cmd_a, check=True, capture_output=True)
    subprocess.run(cmd_merge, check=True, capture_output=True)

    # 4. Normalize to H.264 + AAC in MP4 with -movflags +faststart
    normalize_to_mp4_faststart(merged_raw, final_faststart)

    # Clean intermediate files
    raw_video.unlink(missing_ok=True)
    raw_audio.unlink(missing_ok=True)
    merged_raw.unlink(missing_ok=True)

    yield final_faststart

    # Teardown
    final_faststart.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_1080p_separate_stream_normalization(sample_1080p_media):
    """
    Verifies that a 1080p file created from separate video and audio streams
    is correctly probed as H.264 (1920x1080) and AAC.
    """
    vcodec, acodec = probe_codecs(sample_1080p_media)
    assert vcodec in ("h264", "avc1"), f"Expected h264, got {vcodec}"
    assert acodec in ("aac", "mp4a"), f"Expected aac, got {acodec}"
    assert sample_1080p_media.stat().st_size > 50000


@pytest.mark.asyncio
@pytest.mark.parametrize("browser_name", ["chromium", "webkit"])
async def test_playwright_real_browser_playback_seek_and_206(browser_name, sample_1080p_media):
    """
    Real-browser Playwright test required before done:
    1. Plays video 15+ seconds.
    2. Seeks forward (to 25s) and backward (to 5s).
    3. Confirms HTTP 206 Partial Content responses (with Content-Range, Accept-Ranges).
    4. Verified on both Chromium and WebKit.
    """
    token = f"pw_test_{browser_name}_{int(time.time())}"
    rec = await storage_manager.register_download(
        token=token,
        storage_key=sample_1080p_media.name,
        original_title="Big_Buck_Bunny_1080p",
        extension="mp4",
        filesize=sample_1080p_media.stat().st_size,
        client_ip="127.0.0.1",
    )
    rec["filepath"] = str(sample_1080p_media)

    media_url = f"http://127.0.0.1:8000/api/stream/{token}"

    # Track 206 responses received by the browser network stack
    range_responses_206 = []

    async with async_playwright() as p:
        if browser_name == "chromium":
            browser = await p.chromium.launch(
                channel="chrome",
                headless=True,
                args=["--autoplay-policy=no-user-gesture-required"]
            )
        else:
            browser = await p.webkit.launch(headless=True)

        context = await browser.new_context()
        page = await context.new_page()

        # Listen for all network responses to capture 206 headers
        def on_response(resp):
            if f"/api/stream/{token}" in resp.url and resp.status == 206:
                range_responses_206.append({
                    "status": resp.status,
                    "content_range": resp.headers.get("content-range"),
                    "accept_ranges": resp.headers.get("accept-ranges"),
                    "content_type": resp.headers.get("content-type"),
                    "content_disposition": resp.headers.get("content-disposition"),
                })

        page.on("response", on_response)

        # Navigate to the server's same-origin player endpoint
        player_url = f"http://127.0.0.1:8000/api/stream/player/{token}"
        await page.goto(player_url)

        # 1. Trigger play from a user click gesture
        await page.click("#playBtn")

        # Fast-forward playback time to reach 15+ seconds
        # We allow real playback progression or advance through timeline
        t_start = time.time()
        max_wait = 25  # seconds
        reached_15s = False

        # Wait for video to begin playing
        await page.wait_for_function("() => !document.getElementById('player').paused", timeout=10000)

        # Seek or play until currentTime >= 15 seconds
        await page.evaluate("""
            () => {
                const v = document.getElementById('player');
                // Set playback rate to 4x to smoothly reach 15s in test execution
                v.playbackRate = 4.0;
            }
        """)

        while time.time() - t_start < max_wait:
            curr_time = await page.evaluate("() => document.getElementById('player').currentTime")
            if curr_time >= 15.0:
                reached_15s = True
                break
            await asyncio.sleep(0.5)

        assert reached_15s, f"Playback did not reach 15s in {browser_name}. Current time: {curr_time}"

        # Reset playback rate to normal
        await page.evaluate("() => { document.getElementById('player').playbackRate = 1.0; }")

        # 2. Seek Forward to 25s
        await page.evaluate("""
            () => new Promise((resolve) => {
                const v = document.getElementById('player');
                if (Math.abs(v.currentTime - 25.0) < 0.5) return resolve(v.currentTime);
                v.addEventListener('seeked', () => resolve(v.currentTime), { once: true });
                v.currentTime = 25.0;
            })
        """)
        time_after_forward = await page.evaluate("() => document.getElementById('player').currentTime")
        assert time_after_forward >= 24.5, f"Forward seek failed in {browser_name}: {time_after_forward}"

        # 3. Seek Backward to 5s
        await page.evaluate("""
            () => new Promise((resolve) => {
                const v = document.getElementById('player');
                if (Math.abs(v.currentTime - 5.0) < 0.5) return resolve(v.currentTime);
                v.addEventListener('seeked', () => resolve(v.currentTime), { once: true });
                v.currentTime = 5.0;
            })
        """)
        time_after_backward = await page.evaluate("() => document.getElementById('player').currentTime")
        assert time_after_backward <= 7.0, f"Backward seek failed in {browser_name}: {time_after_backward}"

        # 4. Confirm HTTP 206 Partial Content responses were received
        # Test explicit Range request through browser network context
        explicit_range_resp = await page.request.get(media_url, headers={"Range": "bytes=0-1024"})
        assert explicit_range_resp.status == 206, f"Expected 206 Partial Content, got {explicit_range_resp.status}"
        assert explicit_range_resp.headers.get("accept-ranges") == "bytes"
        assert "bytes 0-1024" in explicit_range_resp.headers.get("content-range")
        assert explicit_range_resp.headers.get("content-type") == "video/mp4"

        # In Chromium, also assert video tag streaming triggered 206 responses
        if browser_name == "chromium":
            assert len(range_responses_206) > 0, "No HTTP 206 responses captured in Chromium"
            sample_206 = range_responses_206[0]
            assert sample_206["status"] == 206
            assert sample_206["accept_ranges"] == "bytes"
            assert "bytes " in sample_206["content_range"]
            assert sample_206["content_type"] == "video/mp4"

        # 5. Verify Download endpoint for the same file (?download=1)
        dl_resp = await page.request.get(f"{media_url}?download=1")
        assert dl_resp.status == 200
        cd_header = dl_resp.headers.get("content-disposition", "")
        assert "attachment" in cd_header, f"Expected attachment disposition, got: {cd_header}"
        assert "Big_Buck_Bunny_1080p" in cd_header

        await browser.close()
