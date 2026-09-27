import asyncio
import re
import urllib.parse
from typing import Optional, List, Dict, Any
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Route, Request as PlaywrightRequest, Response as PlaywrightResponse

from ..config import settings
from ..models.schemas import MediaMetadataResponse, MediaQualityOption
from ..security.ssrf_validator import validate_url_ssrf, safe_http_request
from ..security.sanitizer import sanitize_for_logging

# Media extensions and patterns
MEDIA_EXT_PATTERN = re.compile(r'\.(mp4|m3u8|webm|mp3|m4a|mov|ogg)(?:\?.*)?$', re.IGNORECASE)


class HeadlessBrowserService:
    """
    Tier 4 Extraction Engine:
    Uses headless Chromium (Playwright) to render dynamic JS applications,
    intercepts network requests for media stream signatures, and inspects
    post-JS DOM nodes with strict SSRF request blocking and resource isolation.
    """

    async def render_and_extract(
        self,
        target_url: str,
        timeout_seconds: int = 15,
    ) -> Optional[Dict[str, Any]]:
        """
        Executes headless browser extraction with:
        1. Strict per-request SSRF interception on ALL browser-initiated network routes.
        2. Network response inspection for video/* MIME and media file signatures (.mp4, .m3u8, .webm).
        3. Post-JS DOM extraction for <video>, <source>, and og:video meta tags.
        4. Fresh ephemeral browser context with zero persistence.
        """
        # Step 0: Ensure target URL passes SSRF validation
        is_valid, safe_url, err = validate_url_ssrf(target_url)
        if not is_valid:
            return None

        discovered_media_urls: List[str] = []
        page_title: str = "Web Media"
        page_thumbnail: Optional[str] = None

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ]
                )

                try:
                    # Ephemeral context with zero persistent state
                    context = await browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                        viewport={"width": 1280, "height": 720},
                        ignore_https_errors=False,
                    )

                    page = await context.new_page()

                    # ROUTE INTERCEPTION: Enforce strict SSRF protection inside the browser!
                    # Any subresource request resolving to private/loopback/cloud metadata is instantly aborted.
                    async def handle_route(route: Route):
                        req = route.request
                        req_url = req.url
                        try:
                            # Verify every subresource URL against SSRF policy
                            sub_valid, _, _ = validate_url_ssrf(req_url)
                            if not sub_valid:
                                await route.abort("blockedbyclient")
                                return
                            await route.continue_()
                        except Exception:
                            await route.abort("blockedbyclient")

                    await page.route("**/*", handle_route)

                    # NETWORK RESPONSE INTERCEPTION: Sniff media streaming responses
                    async def handle_response(response: PlaywrightResponse):
                        resp_url = response.url
                        headers = response.headers
                        content_type = headers.get("content-type", "").lower()

                        # Check if response is a media stream (.mp4, .m3u8, .webm) or video MIME
                        is_media_signature = bool(MEDIA_EXT_PATTERN.search(resp_url))
                        is_media_mime = any(
                            content_type.startswith(prefix)
                            for prefix in ["video/", "audio/", "application/x-mpegurl", "application/vnd.apple.mpegurl"]
                        )

                        if is_media_signature or is_media_mime:
                            # Re-verify candidate URL before storing
                            valid_cand, clean_cand, _ = validate_url_ssrf(resp_url)
                            if valid_cand and clean_cand not in discovered_media_urls:
                                discovered_media_urls.append(clean_cand)

                    page.on("response", handle_response)

                    # Navigate with strict timeout
                    nav_timeout_ms = min(timeout_seconds * 1000, 15000)
                    try:
                        await page.goto(safe_url, timeout=nav_timeout_ms, wait_until="domcontentloaded")
                    except Exception:
                        # Page load may have partially completed; proceed to check what was captured
                        pass

                    # Wait for network idle up to max 10s to let JS-driven content load
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass

                    # Small grace period for dynamic player initialization
                    await asyncio.sleep(1.0)

                    # Inspect rendered post-JS DOM
                    try:
                        page_title = await page.title() or "Web Media"
                    except Exception:
                        pass

                    # Check for video elements in rendered DOM
                    try:
                        dom_video_sources = await page.evaluate("""
                            () => {
                                const urls = [];
                                document.querySelectorAll('video').forEach(v => {
                                    if (v.src) urls.push(v.src);
                                    if (v.currentSrc) urls.push(v.currentSrc);
                                });
                                document.querySelectorAll('video source').forEach(s => {
                                    if (s.src) urls.push(s.src);
                                });
                                const og = document.querySelector('meta[property="og:video"], meta[property="og:video:url"], meta[name="twitter:player:stream"]');
                                if (og && og.content) urls.push(og.content);
                                const ogThumb = document.querySelector('meta[property="og:image"]');
                                const thumb = ogThumb ? ogThumb.content : null;
                                return { urls, thumb };
                            }
                        """)

                        if dom_video_sources:
                            for raw_src in dom_video_sources.get("urls", []):
                                if raw_src:
                                    full_src = urllib.parse.urljoin(safe_url, raw_src)
                                    val, clean_val, _ = validate_url_ssrf(full_src)
                                    if val and clean_val not in discovered_media_urls:
                                        discovered_media_urls.append(clean_val)

                            page_thumbnail = dom_video_sources.get("thumb")
                    except Exception:
                        pass

                finally:
                    await browser.close()

        except Exception as e:
            # Playwright or Chromium runtime issue, log sanitized
            return None

        if not discovered_media_urls:
            return None

        # Return discovered media candidate info
        return {
            "media_urls": discovered_media_urls,
            "title": page_title.strip() or "Rendered Web Media",
            "thumbnail": page_thumbnail,
        }


headless_browser = HeadlessBrowserService()
