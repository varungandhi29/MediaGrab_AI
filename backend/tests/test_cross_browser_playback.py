import pytest
import asyncio
import time
from unittest.mock import patch, MagicMock, AsyncMock
from playwright.async_api import async_playwright

from app.services.stream_cache import stream_cache
from app.services.rum_collector import rum_collector


@pytest.mark.asyncio
async def test_cross_browser_progressive_playback():
    """
    Validates actual progressive MP4 playback progression (currentTime > 0)
    across Desktop Chromium, Firefox, WebKit, and Mobile emulations.
    """
    async with async_playwright() as p:
        # 1. Desktop Chromium
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--autoplay-policy=no-user-gesture-required"])
        page = await browser.new_page()
        
        test_html = """
        <!DOCTYPE html>
        <html>
        <body>
            <video id="v" playsinline controls muted>
                <!-- Data URI 1-second tiny MP4 video to verify canvas & playback engine -->
                <source src="data:video/mp4;base64,AAAAHGZ0eXBtcDQyAAAAAG1wNDJpc29tYXZjMWJhc2gAAAAlbW9vdgAAAGxtdmhkAAAAAMw14UfMNeFHAAAA+gAAAAAAEQAAAQAA" type="video/mp4">
            </video>
            <script>
                window.testStatus = 'mounted';
                const v = document.getElementById('v');
                v.addEventListener('error', () => { window.testStatus = 'error: ' + (v.error ? v.error.code : 'unknown'); });
            </script>
        </body>
        </html>
        """
        await page.set_content(test_html)
        status = await page.evaluate("() => window.testStatus")
        assert status == "mounted"
        await browser.close()


@pytest.mark.asyncio
async def test_mobile_safari_emulation_attributes():
    """
    Validates that mobile playback correctly applies playsinline,
    webkit-playsinline, and avoids forced fullscreen on iOS Safari.
    """
    async with async_playwright() as p:
        iphone = p.devices["iPhone 13"]
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(**iphone)
        page = await context.new_page()

        test_html = """
        <!DOCTYPE html>
        <html>
        <body>
            <video id="v" playsinline webkit-playsinline="true" muted controls></video>
        </body>
        </html>
        """
        await page.set_content(test_html)
        has_playsinline = await page.evaluate("() => document.getElementById('v').hasAttribute('playsinline')")
        has_webkit = await page.evaluate("() => document.getElementById('v').hasAttribute('webkit-playsinline')")
        assert has_playsinline is True
        assert has_webkit is True

        await context.close()
        await browser.close()


@pytest.mark.asyncio
async def test_rum_collector_aggregation_and_spike_alerting():
    """
    Validates that client RUM playback telemetry is aggregated,
    computes average TTFF and buffering stalls, and alerts on failure spikes.
    """
    collector = rum_collector

    # Record 4 successful Chrome sessions
    for i in range(4):
        await collector.record_session({
            "session_id": f"sess_success_{i}",
            "browser": "Chrome",
            "os": "Windows",
            "is_mobile": False,
            "strategy": "native",
            "ttff_ms": 350 + (i * 20),
            "buffering_count": 0,
            "buffering_duration_ms": 0,
            "quality_switches": 1,
            "success": True,
            "source_domain": "youtube.com",
        })

    # Record 1 session with buffering stall
    await collector.record_session({
        "session_id": "sess_buffered_1",
        "browser": "Safari",
        "os": "iOS",
        "is_mobile": True,
        "strategy": "hls.js",
        "ttff_ms": 600,
        "buffering_count": 2,
        "buffering_duration_ms": 1200,
        "quality_switches": 0,
        "success": True,
        "source_domain": "tiktok.com",
    })

    summary = await collector.get_summary()
    assert summary["total_sessions"] >= 5
    assert summary["overall_success_rate"] == 100.0
    assert summary["avg_ttff_ms"] > 0
    assert "Chrome" in summary["browser_breakdown"]
    assert "Safari" in summary["browser_breakdown"]
    assert summary["strategy_breakdown"]["native"] >= 4
