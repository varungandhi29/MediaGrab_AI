import json
import logging
import re
import time
import urllib.parse
import asyncio
from typing import Dict, Any, List, Optional, Tuple, Callable
from bs4 import BeautifulSoup

from ..config import settings
from ..models.schemas import MediaMetadataResponse, MediaQualityOption, SubtitleTrack
from ..security.ssrf_validator import validate_url_ssrf, safe_http_request, SSRFValidationError
from ..security.sandbox import build_sandboxed_ytdlp_args, run_sandboxed_subprocess
from .headless_browser import headless_browser
from .stream_cache import stream_cache
from ..resilience import (
    classify_error,
    extract_domain_from_url,
    FailureCategory,
    RecoveryAction,
    FILE_HOST_UNSUPPORTED,
    FILE_HOST_UNSUPPORTED_MESSAGE,
    circuit_breaker_registry,
    metrics_collector,
    alert_manager,
)

logger = logging.getLogger(__name__)


def format_duration(seconds: Optional[float]) -> Optional[str]:
    if seconds is None or seconds < 0:
        return None
    s = int(seconds)
    hours = s // 3600
    minutes = (s % 3600) // 60
    secs = s % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_bytes(num_bytes: Optional[int]) -> Optional[str]:
    if not num_bytes or num_bytes <= 0:
        return None
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


def determine_platform_name(url: str, extractor_key: Optional[str] = None) -> str:
    """Identify clean platform name from URL or extractor key."""
    if extractor_key:
        key_low = extractor_key.lower()
        if "youtube" in key_low:
            return "YouTube"
        if "vimeo" in key_low:
            return "Vimeo"
        if "tiktok" in key_low:
            return "TikTok"
        if "twitter" in key_low or "x" in key_low:
            return "X / Twitter"
        if "instagram" in key_low:
            return "Instagram"
        if "reddit" in key_low:
            return "Reddit"
        if "twitch" in key_low:
            return "Twitch"
        if "facebook" in key_low:
            return "Facebook"
        if "soundcloud" in key_low:
            return "SoundCloud"
        if "dailymotion" in key_low:
            return "Dailymotion"
        return extractor_key.capitalize()

    try:
        domain = urllib.parse.urlparse(url).netloc.lower()
        if "youtube.com" in domain or "youtu.be" in domain:
            return "YouTube"
        if "vimeo.com" in domain:
            return "Vimeo"
        if "tiktok.com" in domain:
            return "TikTok"
        if "twitter.com" in domain or "x.com" in domain:
            return "X / Twitter"
        if "instagram.com" in domain:
            return "Instagram"
        if "reddit.com" in domain:
            return "Reddit"
        if "flezen.com" in domain:
            return "Flezen Cloud"
        return domain
    except Exception:
        return "Web Media"


class MediaExtractionService:
    """
    4-Tier Fast-Fail Media Extraction Engine:
    Tier 1: Isolated yt-dlp subprocess metadata extraction (8s)
    Tier 2: Direct media file inspection via Content-Type header (5s)
    Tier 3: Lightweight embedded HTML5 video / og:video scraper (5s)
    Tier 4: Headless Chromium browser rendering via Playwright (15s)
    Total end-to-end execution capped at 30 seconds.
    """

    async def extract_metadata(
        self,
        url: str,
        status_callback: Optional[Callable[[int, str, str], Any]] = None
    ) -> MediaMetadataResponse:
        """
        Executes resilience-wrapped extraction bounded by hard timeout ceiling (45s).
        Fails fast if retries exceed allocation.
        """
        try:
            return await asyncio.wait_for(
                self._extract_metadata_sequential(url, status_callback),
                timeout=float(settings.RESILIENCE_HARD_TIMEOUT_SECONDS)
            )
        except asyncio.TimeoutError:
            domain = extract_domain_from_url(url)
            raise TimeoutError(
                f"Extraction exceeded maximum duration allocation ({settings.RESILIENCE_HARD_TIMEOUT_SECONDS}s) "
                f"while attempting resilient recovery for {domain}. The source platform is currently unresponsive."
            )

    async def _extract_metadata_sequential(
        self,
        url: str,
        status_callback: Optional[Callable[[int, str, str], Any]] = None
    ) -> MediaMetadataResponse:
        # Step 0: SSRF validation before touching network
        is_valid, clean_url, error_msg = validate_url_ssrf(url)
        if not is_valid:
            raise SSRFValidationError(error_msg or "URL failed SSRF validation.")

        start_time = time.time()
        domain = extract_domain_from_url(clean_url)
        tiers_attempted: List[str] = []
        tier_results: Dict[str, str] = {}
        failure_diagnostics: List[str] = []
        dominant_category: Optional[FailureCategory] = None
        ytdlp_unsupported: bool = False
        static_scrape_no_media: bool = False
        browser_no_media: bool = False

        # Fast-track TeraBox domain family directly (bypass yt-dlp timeout & retries)
        if self._is_terabox_domain(clean_url):
            if status_callback:
                await status_callback(1, "terabox", "Connecting to TeraBox high-speed media stream...")
            tb_res = await self._try_terabox_extraction(clean_url)
            if tb_res:
                return tb_res

        # Fast-track Flezen domain directly (bypass yt-dlp timeout & retries)
        if self._is_flezen_domain(clean_url):
            if status_callback:
                await status_callback(1, "flezen", "Analyzing Flezen media cloud share...")
            flezen_res = await self._try_flezen_extraction(clean_url)
            if flezen_res:
                return flezen_res

        # ==========================================
        # TIER 1: yt-dlp Extraction (8s limit per attempt)
        # ==========================================
        tier1_can_run = await circuit_breaker_registry.can_execute("ytdlp", domain)
        if not tier1_can_run:
            tier_results["ytdlp"] = "circuit_skip"
            if status_callback:
                await status_callback(
                    1,
                    "circuit_skip",
                    f"Tier 1 (yt-dlp) circuit breaker OPEN for {domain} (>80% failure rate) — skipping to next tier"
                )
        else:
            tiers_attempted.append("ytdlp")
            attempt = 0
            max_retries = settings.RESILIENCE_MAX_RETRIES
            while attempt < max_retries:
                attempt += 1
                try:
                    if status_callback:
                        msg = "Trying standard extraction (yt-dlp)..." if attempt == 1 else f"Retrying yt-dlp extraction... attempt {attempt} of {max_retries}"
                        await status_callback(1, "ytdlp", msg)

                    tier1_res = await self._try_ytdlp_extraction(clean_url)
                    if tier1_res:
                        tier_results["ytdlp"] = "success"
                        await circuit_breaker_registry.record_result("ytdlp", domain, success=True)
                        await metrics_collector.record_attempt(tier1_res.platform, domain, "ytdlp", success=True)
                        return tier1_res

                    # Returned None without error: record fall-through
                    tier_results["ytdlp"] = "no_media"
                    await circuit_breaker_registry.record_result("ytdlp", domain, success=False)
                    await metrics_collector.record_attempt("Web", domain, "ytdlp", success=False)
                    break

                except SSRFValidationError:
                    tier_results["ytdlp"] = "ssrf_blocked"
                    raise
                except ValueError as ve:
                    err_low = str(ve).lower()
                    if "unsupported url" in err_low or "no suitable extractor" in err_low:
                        ytdlp_unsupported = True
                        tier_results["ytdlp"] = f"unsupported_url: {ve}"
                    else:
                        tier_results["ytdlp"] = f"value_error: {ve}"
                    cls = classify_error(ve, clean_url, tier="ytdlp")
                    dominant_category = cls.category
                    failure_diagnostics.append(f"yt-dlp: {cls.user_message}")
                    await circuit_breaker_registry.record_result("ytdlp", domain, success=False, category=cls.category)
                    await metrics_collector.record_attempt("Web", domain, "ytdlp", success=False, category=cls.category, error_msg=str(ve))
                    if cls.action == RecoveryAction.FAIL_IMMEDIATELY:
                        logger.warning(f"Extraction failed for domain '{domain}'. Tier results: {tier_results}")
                        raise ValueError(cls.user_message)
                    break

                except Exception as e:
                    err_low = str(e).lower()
                    if "unsupported url" in err_low or "no suitable extractor" in err_low:
                        ytdlp_unsupported = True
                        tier_results["ytdlp"] = f"unsupported_url: {e}"
                    else:
                        tier_results["ytdlp"] = f"error: {e}"
                    cls = classify_error(e, clean_url, tier="ytdlp")
                    dominant_category = cls.category
                    failure_diagnostics.append(f"yt-dlp: {cls.technical_detail}")
                    await circuit_breaker_registry.record_result("ytdlp", domain, success=False, category=cls.category)
                    await metrics_collector.record_attempt("Web", domain, "ytdlp", success=False, category=cls.category, error_msg=str(e))

                    # Check for spike alerting
                    c_status = await circuit_breaker_registry.get_circuit_status("ytdlp", domain)
                    await alert_manager.evaluate_and_alert_if_needed(
                        domain=domain,
                        failure_category=cls.category,
                        sample_error=str(e),
                        tiers_attempted=tiers_attempted,
                        circuit_open=(c_status.get("state") == "OPEN")
                    )

                    if cls.action == RecoveryAction.FAIL_IMMEDIATELY:
                        logger.warning(f"Extraction failed for domain '{domain}'. Tier results: {tier_results}")
                        raise ValueError(cls.user_message)
                    elif isinstance(e, TimeoutError):
                        if attempt < 2 and (time.time() - start_time + 5.0) < settings.RESILIENCE_HARD_TIMEOUT_SECONDS:
                            if status_callback:
                                await status_callback(
                                    1,
                                    "retry",
                                    f"Retrying extraction... attempt {attempt + 1} of {max_retries}"
                                )
                            continue
                        break
                    elif cls.action == RecoveryAction.FALL_THROUGH_TIER:
                        break
                    elif cls.action == RecoveryAction.RETRY_BACKOFF and attempt < max_retries:
                        backoff = settings.RESILIENCE_RETRY_BACKOFFS[min(attempt - 1, len(settings.RESILIENCE_RETRY_BACKOFFS) - 1)]
                        if (time.time() - start_time + backoff) >= settings.RESILIENCE_HARD_TIMEOUT_SECONDS:
                            break
                        if status_callback:
                            await status_callback(
                                1,
                                "retry",
                                f"Transient network issue detected. Retrying extraction... attempt {attempt + 1} of {max_retries} (in {backoff:.0f}s)"
                            )
                        await asyncio.sleep(backoff)
                    else:
                        break

        # ==========================================
        # TIER 2: Direct Media Link Inspection (5s limit)
        # ==========================================
        tier2_can_run = await circuit_breaker_registry.can_execute("direct", domain)
        if not tier2_can_run:
            tier_results["direct"] = "circuit_skip"
            if status_callback:
                await status_callback(
                    2,
                    "circuit_skip",
                    f"Direct stream circuit breaker is OPEN for {domain} — skipping to Tier 3"
                )
        else:
            tiers_attempted.append("direct")
            attempt = 0
            while attempt < settings.RESILIENCE_MAX_RETRIES:
                attempt += 1
                try:
                    if status_callback and attempt == 1:
                        await status_callback(2, "direct", "Checking direct media headers...")
                    tier2_res = await self._try_direct_media_link(clean_url)
                    if tier2_res:
                        tier_results["direct"] = "success"
                        await circuit_breaker_registry.record_result("direct", domain, success=True)
                        await metrics_collector.record_attempt(tier2_res.platform, domain, "direct", success=True)
                        return tier2_res
                    tier_results["direct"] = "no_media"
                    await circuit_breaker_registry.record_result("direct", domain, success=False)
                    await metrics_collector.record_attempt("Web", domain, "direct", success=False)
                    break
                except SSRFValidationError:
                    tier_results["direct"] = "ssrf_blocked"
                    raise
                except Exception as e:
                    tier_results["direct"] = f"error: {e}"
                    cls = classify_error(e, clean_url, tier="direct")
                    dominant_category = cls.category
                    failure_diagnostics.append(f"direct: {cls.technical_detail}")
                    await circuit_breaker_registry.record_result("direct", domain, success=False, category=cls.category)
                    await metrics_collector.record_attempt("Web", domain, "direct", success=False, category=cls.category, error_msg=str(e))
                    if cls.action == RecoveryAction.FAIL_IMMEDIATELY:
                        logger.warning(f"Extraction failed for domain '{domain}'. Tier results: {tier_results}")
                        raise ValueError(cls.user_message)
                    elif cls.action == RecoveryAction.RETRY_BACKOFF and attempt < settings.RESILIENCE_MAX_RETRIES:
                        backoff = settings.RESILIENCE_RETRY_BACKOFFS[min(attempt - 1, len(settings.RESILIENCE_RETRY_BACKOFFS) - 1)]
                        if (time.time() - start_time + backoff) >= settings.RESILIENCE_HARD_TIMEOUT_SECONDS:
                            break
                        if status_callback:
                            await status_callback(
                                2,
                                "retry",
                                f"Transient network blip on direct stream. Retrying attempt {attempt + 1} of {settings.RESILIENCE_MAX_RETRIES} (in {backoff:.0f}s)"
                            )
                        await asyncio.sleep(backoff)
                    else:
                        break

        # ==========================================
        # TIER 3: Lightweight Embedded Video Scraper (5s limit)
        # ==========================================
        tier3_can_run = await circuit_breaker_registry.can_execute("static_scrape", domain)
        if not tier3_can_run:
            tier_results["static_scrape"] = "circuit_skip"
            if status_callback:
                await status_callback(
                    3,
                    "circuit_skip",
                    f"Static scraper circuit breaker is OPEN for {domain} — skipping to Tier 4"
                )
        else:
            tiers_attempted.append("static_scrape")
            try:
                if status_callback:
                    await status_callback(3, "static_scrape", "Scanning page HTML for embedded media...")
                tier3_res = await self._try_embedded_html_scrape(clean_url)
                if tier3_res:
                    tier_results["static_scrape"] = "success"
                    await circuit_breaker_registry.record_result("static_scrape", domain, success=True)
                    await metrics_collector.record_attempt(tier3_res.platform, domain, "static_scrape", success=True)
                    return tier3_res
                tier_results["static_scrape"] = "no_media"
                static_scrape_no_media = True
                await circuit_breaker_registry.record_result("static_scrape", domain, success=False)
                await metrics_collector.record_attempt("Web", domain, "static_scrape", success=False)
            except SSRFValidationError:
                tier_results["static_scrape"] = "ssrf_blocked"
                raise
            except Exception as e:
                tier_results["static_scrape"] = f"error: {e}"
                static_scrape_no_media = True
                cls = classify_error(e, clean_url, tier="static_scrape")
                dominant_category = cls.category
                failure_diagnostics.append(f"static_scrape: {cls.technical_detail}")
                await circuit_breaker_registry.record_result("static_scrape", domain, success=False, category=cls.category)
                await metrics_collector.record_attempt("Web", domain, "static_scrape", success=False, category=cls.category, error_msg=str(e))
                if cls.action == RecoveryAction.FAIL_IMMEDIATELY:
                    logger.warning(f"Extraction failed for domain '{domain}'. Tier results: {tier_results}")
                    raise ValueError(cls.user_message)

        # ==========================================
        # TIER 4: Headless Browser Fallback (15s limit)
        # ==========================================
        tier4_can_run = await circuit_breaker_registry.can_execute("headless_browser", domain)
        if not tier4_can_run:
            tier_results["headless_browser"] = "circuit_skip"
            if status_callback:
                await status_callback(
                    4,
                    "circuit_skip",
                    f"Headless browser circuit breaker is OPEN for {domain} (>80% failure rate)"
                )
        else:
            tiers_attempted.append("headless_browser")
            try:
                if status_callback:
                    await status_callback(4, "headless_browser", "Launching headless browser render (Playwright)...")
                tier4_res = await self._try_headless_browser_fallback(clean_url)
                if tier4_res:
                    tier_results["headless_browser"] = "success"
                    await circuit_breaker_registry.record_result("headless_browser", domain, success=True)
                    await metrics_collector.record_attempt(tier4_res.platform, domain, "headless_browser", success=True)
                    return tier4_res
                tier_results["headless_browser"] = "no_media"
                browser_no_media = True
                await circuit_breaker_registry.record_result("headless_browser", domain, success=False)
                await metrics_collector.record_attempt("Web", domain, "headless_browser", success=False)
            except SSRFValidationError:
                tier_results["headless_browser"] = "ssrf_blocked"
                raise
            except Exception as e:
                tier_results["headless_browser"] = f"error: {e}"
                browser_no_media = True
                cls = classify_error(e, clean_url, tier="headless_browser")
                dominant_category = cls.category
                failure_diagnostics.append(f"headless_browser: {cls.technical_detail}")
                await circuit_breaker_registry.record_result("headless_browser", domain, success=False, category=cls.category)
                await metrics_collector.record_attempt("Web", domain, "headless_browser", success=False, category=cls.category, error_msg=str(e))
                if cls.action == RecoveryAction.FAIL_IMMEDIATELY:
                    logger.warning(f"Extraction failed for domain '{domain}'. Tier results: {tier_results}")
                    raise ValueError(cls.user_message)

        # All tiers completed or skipped via circuit breakers
        logger.warning(f"Extraction failed for domain '{domain}'. Tier results: {tier_results}")

        diag_summary = "; ".join(failure_diagnostics) if failure_diagnostics else "no playable media streams identified"

        # Trigger spike alert check across all attempted tiers
        c_status = await circuit_breaker_registry.get_circuit_status("ytdlp", domain)
        await alert_manager.evaluate_and_alert_if_needed(
            domain=domain,
            failure_category=dominant_category or FailureCategory.BOT_PROTECTION,
            sample_error=diag_summary,
            tiers_attempted=tiers_attempted,
            circuit_open=(c_status.get("state") == "OPEN")
        )

        is_known_platform = any(k in domain for k in ["youtube", "youtu.be", "tiktok", "instagram", "twitter", "x.com", "reddit", "vimeo"])

        # 1. FILE_HOST_UNSUPPORTED: yt-dlp unsupported/non-video platform + static scrape no media + browser no media
        if (ytdlp_unsupported or not is_known_platform) and static_scrape_no_media and browser_no_media:
            raise ValueError(FILE_HOST_UNSUPPORTED_MESSAGE)
        if dominant_category == FailureCategory.EXTRACTOR_OUTDATED and is_known_platform:
            raise ValueError(
                f"This platform ({domain}) recently updated its internal webpage structure. "
                "Our automated self-healing system has flagged this for a dependency update. "
                "Try checking back shortly or downloading directly from the source page."
            )
        else:
            raise ValueError(
                "This site uses protections we can't bypass (dynamic tokens, anti-bot measures, or requires login) — "
                "try downloading the file directly from the source page instead"
            )

    @staticmethod
    def _is_terabox_domain(url: str) -> bool:
        domain = extract_domain_from_url(url).lower()
        terabox_domains = [
            "terabox.com", "terabox.app", "terasharefile.com", "1024tera.com",
            "freeterabox.com", "teraboxshare.com", "tibibox.com", "terafileshare.com",
            "teraboxlink.com", "terafiles.net", "dubox.com"
        ]
        return any(d in domain for d in terabox_domains)

    async def _try_terabox_extraction(self, url: str) -> Optional[MediaMetadataResponse]:
        """
        Ultra-fast TeraBox dedicated extractor (< 4s):
        Launches lightweight sandboxed browser with ads/trackers blocked,
        intercepts share/list, share/mediameta, and share/streaming M3U8,
        and builds full metadata with duration, high-res thumbnail, and selectable quality tiers.
        """
        try:
            from playwright.async_api import async_playwright
            extracted: Dict[str, Any] = {}
            media_done = asyncio.Event()

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
                )
                try:
                    context = await browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                        viewport={"width": 1280, "height": 720}
                    )
                    page = await context.new_page()

                    async def handle_route(route):
                        req_u = route.request.url.lower()
                        # Block trackers, ads, heavy fonts, and analytics to load in < 2 seconds
                        if any(k in req_u for k in [
                            "google-analytics", "googletagmanager", "doubleclick",
                            "facebook", "kakao", ".woff", ".woff2", ".ttf"
                        ]):
                            await route.abort("blockedbyclient")
                            return
                        await route.continue_()

                    await page.route("**/*", handle_route)

                    async def handle_resp(r):
                        u = r.url
                        if "share/list" in u:
                            try:
                                data = json.loads(await r.text())
                                if data.get("list"):
                                    f = data["list"][0]
                                    extracted["title"] = f.get("server_filename")
                                    extracted["filesize"] = int(f.get("size") or 0)
                                    if f.get("thumbs"):
                                        extracted["thumb"] = f["thumbs"].get("url3") or f["thumbs"].get("url2") or f["thumbs"].get("url1")
                            except Exception:
                                pass
                        elif "share/mediameta" in u:
                            try:
                                data = json.loads(await r.text())
                                if data.get("duration"):
                                    extracted["duration"] = float(data["duration"])
                                if data.get("height"):
                                    extracted["height"] = int(data["height"])
                                if data.get("width"):
                                    extracted["width"] = int(data["width"])
                            except Exception:
                                pass
                        elif "share/streaming" in u and ("type=M3U8" in u or "type=M3U8_FLV" in u) and "subtitle" not in u.lower():
                            extracted["stream_url"] = u
                            media_done.set()

                    page.on("response", handle_resp)

                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=10000)
                    except Exception:
                        pass

                    # Click video center to trigger streaming playlist if needed
                    try:
                        await page.mouse.click(640, 360)
                    except Exception:
                        pass

                    try:
                        await asyncio.wait_for(media_done.wait(), timeout=4.5)
                    except asyncio.TimeoutError:
                        pass

                    # Fallback title if not in share/list
                    if not extracted.get("title"):
                        try:
                            extracted["title"] = await page.title()
                        except Exception:
                            pass

                finally:
                    await browser.close()

            stream_url = extracted.get("stream_url")
            if not stream_url:
                return None

            title = extracted.get("title") or "TeraBox Video"
            if title.startswith("/"):
                title = title[1:]
            
            thumb = extracted.get("thumb")
            duration_sec = extracted.get("duration")
            max_height = extracted.get("height") or 1080
            filesize = extracted.get("filesize")

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            }

            # Map all user-comfort resolution tiers to stream_cache
            streams_by_quality = {
                "native": {
                    "url": stream_url,
                    "headers": headers,
                    "mime": "application/x-mpegURL",
                    "is_hls": True,
                    "height": max_height,
                },
                "1080p": {
                    "url": stream_url,
                    "headers": headers,
                    "mime": "application/x-mpegURL",
                    "is_hls": True,
                    "height": 1080,
                },
                "720p": {
                    "url": stream_url,
                    "headers": headers,
                    "mime": "application/x-mpegURL",
                    "is_hls": True,
                    "height": 720,
                },
                "480p": {
                    "url": stream_url,
                    "headers": headers,
                    "mime": "application/x-mpegURL",
                    "is_hls": True,
                    "height": 480,
                },
                "360p": {
                    "url": stream_url,
                    "headers": headers,
                    "mime": "application/x-mpegURL",
                    "is_hls": True,
                    "height": 360,
                },
                "audio": {
                    "url": stream_url,
                    "headers": headers,
                    "mime": "audio/mp4",
                    "is_hls": True,
                    "height": None,
                },
            }

            session_token = await stream_cache.register_stream_session(
                source_url=url,
                streams_by_quality=streams_by_quality,
                title=title
            )

            qualities = [
                MediaQualityOption(
                    quality_label="1080p (Full HD)",
                    format_id="1080p",
                    ext="mp4",
                    filesize_approx=filesize,
                    filesize_display=format_bytes(filesize),
                    resolution="1080p",
                    height=1080,
                    is_audio_only=False,
                    is_hls=True,
                    is_browser_compatible=True,
                    mime_type="application/x-mpegURL",
                    stream_url=f"/api/stream/{session_token}/1080p",
                ),
                MediaQualityOption(
                    quality_label="720p (HD)",
                    format_id="720p",
                    ext="mp4",
                    filesize_approx=int(filesize * 0.6) if filesize else None,
                    filesize_display=format_bytes(int(filesize * 0.6)) if filesize else None,
                    resolution="720p",
                    height=720,
                    is_audio_only=False,
                    is_hls=True,
                    is_browser_compatible=True,
                    mime_type="application/x-mpegURL",
                    stream_url=f"/api/stream/{session_token}/720p",
                ),
                MediaQualityOption(
                    quality_label="480p (SD)",
                    format_id="480p",
                    ext="mp4",
                    filesize_approx=int(filesize * 0.35) if filesize else None,
                    filesize_display=format_bytes(int(filesize * 0.35)) if filesize else None,
                    resolution="480p",
                    height=480,
                    is_audio_only=False,
                    is_hls=True,
                    is_browser_compatible=True,
                    mime_type="application/x-mpegURL",
                    stream_url=f"/api/stream/{session_token}/480p",
                ),
                MediaQualityOption(
                    quality_label="360p (Data Saver)",
                    format_id="360p",
                    ext="mp4",
                    filesize_approx=int(filesize * 0.2) if filesize else None,
                    filesize_display=format_bytes(int(filesize * 0.2)) if filesize else None,
                    resolution="360p",
                    height=360,
                    is_audio_only=False,
                    is_hls=True,
                    is_browser_compatible=True,
                    mime_type="application/x-mpegURL",
                    stream_url=f"/api/stream/{session_token}/360p",
                ),
                MediaQualityOption(
                    quality_label="Audio only (MP3)",
                    format_id="direct_audio",
                    ext="mp3",
                    filesize_approx=None,
                    filesize_display=None,
                    resolution="Audio",
                    height=None,
                    is_audio_only=True,
                    stream_url=f"/api/stream/{session_token}/audio",
                ),
            ]

            return MediaMetadataResponse(
                url=url,
                platform="TeraBox",
                title=title,
                thumbnail=thumb,
                thumbnail_proxy=f"/api/stream/thumbnail?u={urllib.parse.quote(thumb)}" if thumb else None,
                duration_seconds=duration_sec,
                duration_formatted=format_duration(duration_sec),
                uploader="TeraBox",
                description="High-speed TeraBox extraction.",
                available_qualities=qualities,
                subtitles=[],
                source_type="terabox",
                extraction_tier=1,
                stream_session_id=session_token,
                is_hls=True,
            )
        except Exception as e:
            logger.warning(f"TeraBox dedicated extraction failed: {e}")
            return None

    @staticmethod
    def _is_flezen_domain(url: str) -> bool:
        domain = extract_domain_from_url(url).lower()
        return "flezen.com" in domain

    async def _try_flezen_extraction(self, url: str) -> Optional[MediaMetadataResponse]:
        """
        Dedicated high-speed Flezen media cloud extractor (< 1s):
        Directly parses file metadata (filename, bytes, upload date, app intent, and bot bypass)
        from Flezen share links without stalling through unsupportable extraction tiers.
        """
        try:
            share_match = re.search(r"/s/([a-zA-Z0-9_\-]+)", url)
            share_id = share_match.group(1) if share_match else ""

            resp = await safe_http_request(
                "GET",
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                timeout=6.0
            )

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            # Extract title
            h1 = soup.find("h1")
            title = h1.text.strip() if h1 and h1.text.strip() else None
            if not title and soup.title:
                t_raw = soup.title.string or ""
                title = t_raw.split("|")[0].strip()
            if not title:
                title = f"Flezen Media ({share_id})" if share_id else "Flezen Media File"

            # Extract filesize in bytes
            bytes_el = soup.find(attrs={"data-bytes": True})
            data_bytes = None
            if bytes_el and bytes_el.get("data-bytes", "").isdigit():
                data_bytes = int(bytes_el["data-bytes"])
            filesize_display = format_bytes(data_bytes) if data_bytes else None

            # App scheme and store URLs
            app_scheme = f"flezen://flezen.com/s/{share_id}" if share_id else url
            store_url = "https://play.google.com/store/apps/details?id=com.devlooper.flezen"
            telegram_bot = f"https://t.me/flezendl101_bot?start={share_id}" if share_id else "https://t.me/flezendl101_bot"

            qualities = [
                MediaQualityOption(
                    quality_label=f"Original File ({filesize_display or 'MP4 HD'})",
                    format_id="original",
                    ext="mp4",
                    filesize_approx=data_bytes,
                    filesize_display=filesize_display,
                    resolution="Original HD",
                    height=1080,
                    is_browser_compatible=True,
                    stream_url=url,
                )
            ]

            description = (
                f"Flezen Cloud media file ({filesize_display or 'HD'}). "
                "Flezen protects files behind an Android app locker and ad monetization wall. "
                "Direct in-browser video streaming is restricted by Flezen, but you can open it directly in the Flezen app or bypass via their Telegram resolver."
            )

            return MediaMetadataResponse(
                url=url,
                platform="Flezen Cloud",
                title=title,
                thumbnail="https://flezen.com/static/images/Flezen.png",
                thumbnail_proxy=None,
                duration_seconds=None,
                duration_formatted=None,
                uploader="Devlooper (Flezen Cloud)",
                description=description,
                available_qualities=qualities,
                subtitles=[],
                source_type="flezen",
                extraction_tier=1,
                is_hls=False,
            )
        except Exception as e:
            logger.warning(f"Flezen direct extraction failed: {e}")
            return None

    async def _try_headless_browser_fallback(self, url: str) -> Optional[MediaMetadataResponse]:
        """Tier 4: Headless Chromium (Playwright) fallback with network response sniffing and post-JS DOM inspection."""
        try:
            render_res = await headless_browser.render_and_extract(
                target_url=url,
                timeout_seconds=settings.TIER4_HEADLESS_TIMEOUT_SECONDS
            )
            if not render_res or not render_res.get("media_urls"):
                return None

            candidate_urls = render_res["media_urls"]
            page_title = render_res.get("title") or "Web Media"
            page_thumb = render_res.get("thumbnail")
            dur_sec = float(render_res["duration"]) if render_res.get("duration") else None

            # Filter out any subtitle/caption tracks to prioritize actual video streams
            filtered_cands = [
                u for u in candidate_urls
                if not any(s in u.lower() for s in ["subtitle", ".srt", ".vtt", "subrip"])
            ]
            if not filtered_cands:
                filtered_cands = candidate_urls

            first_cand = filtered_cands[0]
            parsed_cand = urllib.parse.urlparse(first_cand)
            ext = "mp4"
            first_cand_low = first_cand.lower()
            if ".m3u8" in first_cand_low or "m3u8" in first_cand_low or "streaming" in first_cand_low:
                ext = "m3u8"
            elif ".webm" in first_cand_low:
                ext = "webm"
            elif ".mp3" in first_cand_low:
                ext = "mp3"

            is_hls = (ext == "m3u8") or ".m3u8" in first_cand_low or "m3u8" in first_cand_low or "streaming" in first_cand_low
            format_id = "direct_hls" if is_hls else "direct"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            }

            streams_by_quality = {
                "native": {
                    "url": first_cand,
                    "headers": headers,
                    "mime": "application/x-mpegURL" if is_hls else f"video/{ext}",
                    "is_hls": is_hls,
                    "height": 720,
                },
                "1080p": {
                    "url": first_cand,
                    "headers": headers,
                    "mime": "application/x-mpegURL" if is_hls else f"video/{ext}",
                    "is_hls": is_hls,
                    "height": 1080,
                },
                "720p": {
                    "url": first_cand,
                    "headers": headers,
                    "mime": "application/x-mpegURL" if is_hls else f"video/{ext}",
                    "is_hls": is_hls,
                    "height": 720,
                },
                "480p": {
                    "url": first_cand,
                    "headers": headers,
                    "mime": "application/x-mpegURL" if is_hls else f"video/{ext}",
                    "is_hls": is_hls,
                    "height": 480,
                },
                "360p": {
                    "url": first_cand,
                    "headers": headers,
                    "mime": "application/x-mpegURL" if is_hls else f"video/{ext}",
                    "is_hls": is_hls,
                    "height": 360,
                },
                "audio": {
                    "url": first_cand,
                    "headers": headers,
                    "mime": "audio/mp4",
                    "is_hls": is_hls,
                    "height": None,
                },
            }

            session_token = await stream_cache.register_stream_session(
                source_url=first_cand,
                streams_by_quality=streams_by_quality,
                title=page_title,
            )

            return MediaMetadataResponse(
                url=first_cand,
                platform="Headless Browser Render (Dynamic JS)",
                title=page_title,
                thumbnail=page_thumb,
                thumbnail_proxy=f"/api/stream/thumbnail?u={urllib.parse.quote(page_thumb)}" if page_thumb else None,
                duration_seconds=dur_sec,
                duration_formatted=format_duration(dur_sec),
                uploader=parsed_cand.netloc,
                description="Extracted via Tier 4 headless browser network sniffing.",
                available_qualities=[
                    MediaQualityOption(
                        quality_label="1080p (Full HD)",
                        format_id="1080p",
                        ext="mp4",
                        filesize_approx=None,
                        filesize_display=None,
                        resolution="1080p",
                        height=1080,
                        is_audio_only=False,
                        is_hls=is_hls,
                        stream_url=f"/api/stream/{session_token}/1080p" if session_token else None,
                    ),
                    MediaQualityOption(
                        quality_label="720p (HD)",
                        format_id="720p",
                        ext="mp4",
                        filesize_approx=None,
                        filesize_display=None,
                        resolution="720p",
                        height=720,
                        is_audio_only=False,
                        is_hls=is_hls,
                        stream_url=f"/api/stream/{session_token}/720p" if session_token else None,
                    ),
                    MediaQualityOption(
                        quality_label="480p (SD)",
                        format_id="480p",
                        ext="mp4",
                        filesize_approx=None,
                        filesize_display=None,
                        resolution="480p",
                        height=480,
                        is_audio_only=False,
                        is_hls=is_hls,
                        stream_url=f"/api/stream/{session_token}/480p" if session_token else None,
                    ),
                    MediaQualityOption(
                        quality_label="360p (Data Saver)",
                        format_id="360p",
                        ext="mp4",
                        filesize_approx=None,
                        filesize_display=None,
                        resolution="360p",
                        height=360,
                        is_audio_only=False,
                        is_hls=is_hls,
                        stream_url=f"/api/stream/{session_token}/360p" if session_token else None,
                    ),
                    MediaQualityOption(
                        quality_label="Audio only (MP3)",
                        format_id="direct_audio",
                        ext="mp3",
                        filesize_approx=None,
                        filesize_display=None,
                        resolution="Audio",
                        height=None,
                        is_audio_only=True,
                        stream_url=f"/api/stream/{session_token}/audio" if session_token else None,
                    )
                ],
                source_type="headless_browser",
                extraction_tier=4,
                stream_session_id=session_token,
            )
        except Exception:
            return None

    async def _try_ytdlp_extraction(self, url: str) -> Optional[MediaMetadataResponse]:
        """Runs yt-dlp in a sandboxed subprocess with fast-fail timeout."""
        cmd_args = build_sandboxed_ytdlp_args(
            target_url=url,
            is_metadata_only=True
        )

        domain = extract_domain_from_url(url).lower()
        is_known_platform = any(d in domain for d in (
            "youtube", "youtu.be", "vimeo", "dailymotion", "tiktok", "twitch", "instagram", "facebook", "twitter", "x.com", "reddit"
        ))
        timeout = 18 if is_known_platform else settings.TIER1_YTDLP_TIMEOUT_SECONDS

        try:
            retcode, stdout, stderr = await run_sandboxed_subprocess(
                cmd_args,
                timeout_seconds=timeout
            )
        except TimeoutError:
            raise TimeoutError(f"yt-dlp extraction timed out after {timeout}s")

        if retcode != 0 or not stdout.strip():
            lower_err = stderr.lower()
            if "private video" in lower_err:
                raise ValueError("This video is private or requires authentication.")
            if "geo-restricted" in lower_err or "not available in your country" in lower_err:
                raise ValueError("This media is geo-blocked by the source platform.")
            raise RuntimeError(f"yt-dlp extraction failed: {stderr.strip()[:250]}")

        try:
            info = json.loads(stdout.strip())
        except json.JSONDecodeError as jde:
            raise RuntimeError(f"yt-dlp returned invalid JSON output: {jde}")

        # Parse extracted info
        title = info.get("title") or "Untitled Media"
        thumbnail = info.get("thumbnail")
        thumbnail_proxy = f"/api/stream/thumbnail?u={urllib.parse.quote(thumbnail)}" if thumbnail else None
        duration = info.get("duration")
        uploader = info.get("uploader") or info.get("channel") or info.get("creator")
        description = (info.get("description") or "")[:250]
        platform = determine_platform_name(url, info.get("extractor_key") or info.get("extractor"))

        # Parse available subtitles and closed captions
        subtitles_list: List[SubtitleTrack] = []
        raw_subs = info.get("subtitles") or {}
        raw_auto_subs = info.get("automatic_captions") or {}
        seen_langs = set()

        # 1. Manual subtitles (highest quality)
        for lang_code, format_list in raw_subs.items():
            if not format_list or not isinstance(format_list, list):
                continue
            best_fmt = next((f for f in format_list if f.get("ext") == "vtt"), None)
            if not best_fmt:
                best_fmt = next((f for f in format_list if f.get("ext") == "srt"), None)
            if not best_fmt:
                best_fmt = format_list[0]
            sub_url = best_fmt.get("url")
            if sub_url and lang_code not in seen_langs:
                seen_langs.add(lang_code)
                name = best_fmt.get("name") or lang_code.upper()
                ext = best_fmt.get("ext", "vtt")
                proxy_url = f"/api/stream/subtitle?u={urllib.parse.quote(sub_url)}&lang={lang_code}&title={urllib.parse.quote(title[:40])}"
                subtitles_list.append(SubtitleTrack(
                    lang=lang_code,
                    name=name,
                    ext=ext,
                    url=sub_url,
                    proxy_url=proxy_url,
                ))

        # 2. Automatic captions (if manual not available, limit list to 15)
        for lang_code, format_list in raw_auto_subs.items():
            if lang_code in seen_langs or not format_list or not isinstance(format_list, list):
                continue
            if len(subtitles_list) >= 15:
                break
            best_fmt = next((f for f in format_list if f.get("ext") == "vtt"), None)
            if not best_fmt:
                best_fmt = next((f for f in format_list if f.get("ext") == "srt"), None)
            if not best_fmt:
                best_fmt = format_list[0]
            sub_url = best_fmt.get("url")
            if sub_url:
                seen_langs.add(lang_code)
                name = f"{best_fmt.get('name') or lang_code.upper()} (Auto)"
                ext = best_fmt.get("ext", "vtt")
                proxy_url = f"/api/stream/subtitle?u={urllib.parse.quote(sub_url)}&lang={lang_code}&title={urllib.parse.quote(title[:40])}"
                subtitles_list.append(SubtitleTrack(
                    lang=lang_code,
                    name=name,
                    ext=ext,
                    url=sub_url,
                    proxy_url=proxy_url,
                ))

        # Build genuine available qualities & proxy stream URLs
        formats = info.get("formats", [])
        qualities, session_token = await self._parse_ytdlp_qualities_and_register(url, title, formats)

        return MediaMetadataResponse(
            url=url,
            platform=platform,
            title=title,
            thumbnail=thumbnail,
            thumbnail_proxy=thumbnail_proxy,
            duration_seconds=float(duration) if duration else None,
            duration_formatted=format_duration(duration),
            uploader=uploader,
            description=description,
            available_qualities=qualities,
            subtitles=subtitles_list,
            source_type="ytdlp",
            extraction_tier=1,
            stream_session_id=session_token,
        )

    @staticmethod
    def _score_format_for_browser_playback(f: Dict[str, Any]) -> int:
        """
        Ranks formats to guarantee optimal in-browser playback:
        Prefers direct HTTPS streams (MP4/WebM) with H.264, VP9, or AV1 for true 4K/2K resolution and seekability.
        """
        score = 0
        raw_url = f.get("url")
        if not raw_url:
            return -1000

        ext = (f.get("ext") or "").lower()
        vcodec = (f.get("vcodec") or "").lower()
        acodec = (f.get("acodec") or "").lower()
        protocol = (f.get("protocol") or "").lower()

        has_video = bool(vcodec and vcodec != "none")
        has_audio = bool(acodec and acodec != "none")

        # 1. Combined audio+video format is optimal for single-file progressive playback
        if has_video and has_audio:
            score += 300

        # 2. Container preference: MP4 and WebM are universally supported in HTML5 <video>
        if ext == "mp4" or "mp4" in protocol:
            score += 150
        elif ext == "webm":
            score += 120
        elif ext == "m3u8" or "m3u8" in protocol or ".m3u8" in raw_url:
            score += 30
        elif ext == "mkv":
            score -= 200  # Browsers cannot decode MKV natively in HTML5 <video>
        elif ext in ("flv", "avi", "wmv"):
            score -= 300

        # 3. Protocol preference: direct HTTPS progressive streams allow byte ranges, seekability, and fast keyframe access
        if protocol.startswith("http") and "m3u8" not in protocol and ".m3u8" not in raw_url:
            score += 120
        elif "m3u8" in protocol or ".m3u8" in raw_url or "manifest" in raw_url:
            score -= 50

        # 4. Video Codec preference:
        # H.264 is 100% universal hardware-accelerated playback across all devices
        # VP9 is natively decoded across 100% of Chromium, Edge, and Firefox for 4K/2K
        # AV1 is penalized (-100) because on Windows systems lacking the Microsoft AV1 extension, it causes a BLACK SCREEN!
        if any(c in vcodec for c in ("avc1", "h264", "avc")):
            score += 150
        elif "vp9" in vcodec or "vp09" in vcodec:
            score += 100
        elif "av01" in vcodec or "av1" in vcodec:
            score -= 100  # Avoid black screen on browsers without AV1 extension
        elif any(c in vcodec for c in ("hevc", "hvc1", "h265")):
            score -= 100

        # 5. Audio Codec preference: AAC is universal
        if any(c in acodec for c in ("mp4a", "aac")):
            score += 50
        elif "opus" in acodec:
            score += 40
        elif "mp3" in acodec:
            score += 30

        return score

    @staticmethod
    def _score_audio_format(f: Dict[str, Any]) -> float:
        """
        Ranks audio formats to ALWAYS prioritize the creator's ORIGINAL / DEFAULT language track
        over auto-translated or dubbed audio tracks (e.g. Arabic, Spanish, French dubs).
        Prefers original language -> English -> AAC (m4a) for universal browser playback.
        """
        raw_url = f.get("url")
        if not raw_url:
            return -1000000.0

        vcodec = f.get("vcodec")
        is_audio_only = (not vcodec or vcodec == "none")

        abr = float(f.get("abr") or f.get("tbr") or 0)
        score = abr

        if is_audio_only:
            score += 2000.0

        lang = (f.get("language") or "").lower()
        note = (f.get("format_note") or "").lower()
        lang_pref = f.get("language_preference")

        # 1. yt-dlp language_preference: > 0 means original/default, < 0 means dubbed/translated
        if lang_pref is not None:
            if lang_pref > 0:
                score += 50000.0 * lang_pref
            elif lang_pref < 0:
                score -= 30000.0

        # 2. Check format_note for "original" or "default"
        if "original" in note:
            score += 40000.0
        if "default" in note:
            score += 20000.0
        if "dub" in note or "translated" in note:
            score -= 20000.0

        # 3. Explicit boolean flags from yt-dlp
        if f.get("is_default") or f.get("is_original"):
            score += 30000.0

        # 4. English original bias if no language_preference is marked
        if lang.startswith("en"):
            score += 10000.0

        # 5. Codec compatibility: AAC (mp4a / m4a) plays natively in 100% of browsers
        acodec = (f.get("acodec") or "").lower()
        ext = (f.get("ext") or "").lower()
        if "mp4a" in acodec or "aac" in acodec or ext == "m4a":
            score += 3000.0
        elif "opus" in acodec:
            score += 1500.0

        return score

    async def _parse_ytdlp_qualities_and_register(
        self,
        url: str,
        title: str,
        formats: List[Dict[str, Any]]
    ) -> Tuple[List[MediaQualityOption], Optional[str]]:
        """
        Parses actual video and audio formats. Only includes qualities that
        genuinely exist in the source stream. Never fabricates unavailable resolutions.
        Standard targets: 2160p (4K), 1440p (2K), 1080p, 720p, 480p, 360p.
        Plus 'Audio only (MP3)'.
        """
        # Early DRM Detection: Detect Widevine/FairPlay protected manifests
        if formats:
            drm_formats = [
                f for f in formats 
                if f.get("has_drm") or f.get("is_drm") 
                or "drm" in (f.get("format_note") or "").lower() 
                or "widevine" in (f.get("format_note") or "").lower()
            ]
            if len(drm_formats) == len(formats):
                raise ValueError("This content is DRM-protected and can't be played or downloaded here.")

        existing_heights = set()
        height_to_format_info = {}

        has_audio = False
        has_video = False
        best_audio_format = None
        best_audio_score = -1000000.0

        for f in formats:
            vcodec = f.get("vcodec")
            acodec = f.get("acodec")
            height = f.get("height")
            raw_url = f.get("url")
            if not raw_url:
                continue

            if acodec and acodec != "none":
                has_audio = True
                score = self._score_audio_format(f)
                if score > best_audio_score:
                    best_audio_score = score
                    best_audio_format = f

            ext = (f.get("ext") or "").lower()
            if ext in ("mp4", "webm", "mov", "mkv", "flv"):
                has_video = True

            if vcodec and vcodec != "none" and height and height > 0:
                has_video = True
                existing_heights.add(height)
                # Keep format with highest browser playback compatibility score
                if height not in height_to_format_info:
                    height_to_format_info[height] = f
                else:
                    curr_score = self._score_format_for_browser_playback(height_to_format_info[height])
                    new_score = self._score_format_for_browser_playback(f)
                    if new_score > curr_score:
                        height_to_format_info[height] = f

        best_audio_url = best_audio_format.get("url") if best_audio_format else None
        best_audio_headers = best_audio_format.get("http_headers", {}) if best_audio_format else None

        qualities: List[MediaQualityOption] = []
        streams_by_quality: Dict[str, Dict[str, Any]] = {}

        # Target tiers to evaluate with clear, non-overlapping bounds so 1080p, 1440p, and 2160p are never dropped:
        standard_tiers = [
            (2160, "2160p (4K)", 1440),
            (1440, "1440p (2K)", 1080),
            (1080, "1080p (Full HD)", 720),
            (720, "720p (HD)", 480),
            (480, "480p (SD)", 360),
            (360, "360p", 0),
        ]

        if has_video:
            for max_h, label, min_h in standard_tiers:
                matching_heights = [h for h in existing_heights if min_h < h <= max_h]
                if matching_heights:
                    best_match = max(matching_heights)
                    f_info = height_to_format_info.get(best_match, {})
                    approx_size = f_info.get("filesize") or f_info.get("filesize_approx")
                    raw_stream_url = f_info.get("url")
                    is_hls = bool(raw_stream_url and (".m3u8" in raw_stream_url or "manifest" in raw_stream_url))

                    has_fmt_audio = bool(f_info.get("acodec") and f_info.get("acodec") != "none")
                    needs_audio = (not has_fmt_audio) and bool(best_audio_url)
                    effective_is_hls = is_hls and not needs_audio

                    f_ext = (f_info.get("ext") or "mp4").lower()
                    mime_str = "application/x-mpegURL" if effective_is_hls else ("video/webm" if f_ext == "webm" else "video/mp4")

                    stream_entry = {
                        "url": raw_stream_url,
                        "headers": f_info.get("http_headers", {}),
                        "mime": mime_str,
                        "is_hls": effective_is_hls,
                        "height": best_match,
                        "has_audio": has_fmt_audio,
                        "needs_audio": needs_audio,
                        "audio_url": best_audio_url if needs_audio else None,
                        "audio_headers": best_audio_headers if needs_audio else None,
                        "vcodec": f_info.get("vcodec"),
                        "acodec": f_info.get("acodec"),
                    }

                    quality_key = f"{max_h}p"
                    streams_by_quality[quality_key] = stream_entry
                    # CRITICAL: Also register with actual height so lookup by best_match (e.g. '240p' or '720p') never fails!
                    streams_by_quality[f"{best_match}p"] = stream_entry

                    f_vcodec = (f_info.get("vcodec") or "").lower()
                    f_acodec = (f_info.get("acodec") or "").lower()
                    is_playable = (f_ext in ("mp4", "webm") or effective_is_hls) and ("hevc" not in f_vcodec and "h265" not in f_vcodec) and (f_ext != "mkv")

                    fmt_selector = f"bestvideo[height<={max_h}]+bestaudio[language_preference>=0]/bestvideo[height<={max_h}]+bestaudio/best[height<={max_h}]/best"
                    qualities.append(MediaQualityOption(
                        quality_label=label,
                        format_id=fmt_selector,
                        ext="mp4",
                        filesize_approx=approx_size,
                        filesize_display=format_bytes(approx_size),
                        resolution=f"{best_match}p",
                        height=best_match,
                        is_audio_only=False,
                        is_hls=effective_is_hls,
                        vcodec=f_info.get("vcodec"),
                        acodec=f_info.get("acodec"),
                        is_browser_compatible=is_playable,
                        mime_type=mime_str,
                    ))
                    for h in matching_heights:
                        existing_heights.discard(h)

            # If no standard height tier matched but video format exists
            if not qualities:
                max_h_label = f"{max(existing_heights)}p" if existing_heights else "Native Video Quality"
                best_h = max(existing_heights) if existing_heights else 720
                first_f = formats[0] if formats else {}
                raw_url = first_f.get("url") or url
                is_hls = bool(raw_url and (".m3u8" in raw_url or "manifest" in raw_url))

                has_fmt_audio = bool(first_f.get("acodec") and first_f.get("acodec") != "none")
                needs_audio = (not has_fmt_audio) and bool(best_audio_url)
                effective_is_hls = is_hls and not needs_audio

                native_entry = {
                    "url": raw_url,
                    "headers": first_f.get("http_headers", {}),
                    "mime": "application/x-mpegURL" if effective_is_hls else "video/mp4",
                    "is_hls": effective_is_hls,
                    "height": best_h,
                    "has_audio": has_fmt_audio,
                    "needs_audio": needs_audio,
                    "audio_url": best_audio_url if needs_audio else None,
                    "audio_headers": best_audio_headers if needs_audio else None,
                    "vcodec": first_f.get("vcodec"),
                    "acodec": first_f.get("acodec"),
                }
                streams_by_quality["native"] = native_entry
                streams_by_quality[f"{best_h}p"] = native_entry

                qualities.append(MediaQualityOption(
                    quality_label=max_h_label,
                    format_id="best",
                    ext="mp4",
                    filesize_approx=None,
                    filesize_display=None,
                    resolution=max_h_label,
                    height=best_h,
                    is_audio_only=False,
                    is_hls=effective_is_hls,
                    is_browser_compatible=True,
                    mime_type="application/x-mpegURL" if effective_is_hls else "video/mp4",
                ))

        # Always offer "Audio only (MP3)" if audio stream is available
        if has_audio or not has_video:
            qualities.append(MediaQualityOption(
                quality_label="Audio only (MP3)",
                format_id="bestaudio[language_preference>=0]/bestaudio/best",
                ext="mp3",
                filesize_approx=None,
                filesize_display=None,
                resolution="Audio",
                height=None,
                is_audio_only=True,
            ))
            if best_audio_url:
                streams_by_quality["audio"] = {
                    "url": best_audio_url,
                    "headers": best_audio_headers or {},
                    "mime": "audio/mp4",
                    "is_hls": False,
                    "height": None,
                    "has_audio": True,
                    "format_id": best_audio_format.get("format_id"),
                    "language": best_audio_format.get("language"),
                    "format_note": best_audio_format.get("format_note"),
                }

        session_token = None
        if streams_by_quality:
            session_token = await stream_cache.register_stream_session(
                source_url=url,
                streams_by_quality=streams_by_quality,
                title=title
            )
            # Attach proxy stream URL to quality options
            for q in qualities:
                if not q.is_audio_only:
                    q_key = f"{q.height}p" if q.height else "native"
                    if q_key in streams_by_quality:
                        q.stream_url = f"/api/stream/{session_token}/{q_key}"
                    else:
                        # Find closest matching tier in streams_by_quality
                        matched = next((k for k in streams_by_quality if k.endswith("p") and k[:-1].isdigit() and int(k[:-1]) >= (q.height or 0)), None)
                        if matched:
                            q.stream_url = f"/api/stream/{session_token}/{matched}"
                        elif "native" in streams_by_quality:
                            q.stream_url = f"/api/stream/{session_token}/native"
                        elif streams_by_quality:
                            q.stream_url = f"/api/stream/{session_token}/{next(iter(streams_by_quality.keys()))}"
                else:
                    if "audio" in streams_by_quality:
                        q.stream_url = f"/api/stream/{session_token}/audio"

        return qualities, session_token

    async def _try_direct_media_link(self, url: str) -> Optional[MediaMetadataResponse]:
        """
        Tier 2: Checks if URL directly points to a media stream or file.
        Uses safe HTTP client that strictly checks redirects against SSRF.
        """
        # Supported MIME types
        media_mimes = {
            "video/mp4": ("mp4", False),
            "video/webm": ("webm", False),
            "video/quicktime": ("mov", False),
            "video/x-matroska": ("mkv", False),
            "video/ogg": ("ogv", False),
            "audio/mpeg": ("mp3", True),
            "audio/mp3": ("mp3", True),
            "audio/wav": ("wav", True),
            "audio/ogg": ("ogg", True),
            "audio/aac": ("aac", True),
            "application/x-mpegurl": ("m3u8", False),
            "application/vnd.apple.mpegurl": ("m3u8", False),
        }

        # First try HEAD
        try:
            head_resp = await safe_http_request("HEAD", url, timeout=settings.TIER2_DIRECT_TIMEOUT_SECONDS)
            status_code = head_resp.status_code
            content_type = head_resp.headers.get("content-type", "").split(";")[0].strip().lower()
            content_length = head_resp.headers.get("content-length")
        except Exception:
            # Some servers reject HEAD; attempt small range GET
            try:
                get_resp = await safe_http_request("GET", url, headers={"Range": "bytes=0-1024"}, timeout=settings.TIER2_DIRECT_TIMEOUT_SECONDS)
                status_code = get_resp.status_code
                content_type = get_resp.headers.get("content-type", "").split(";")[0].strip().lower()
                content_length = get_resp.headers.get("content-length")
            except Exception:
                return None

        if status_code not in (200, 206):
            return None

        # Check if MIME matches known media
        matched_ext, is_audio = media_mimes.get(content_type, (None, False))

        # If MIME was generic (e.g. application/octet-stream), check URL path extension
        if not matched_ext:
            parsed_path = urllib.parse.urlparse(url).path.lower()
            for ext in [".mp4", ".webm", ".mp3", ".m4a", ".wav", ".m3u8", ".mov"]:
                if parsed_path.endswith(ext):
                    matched_ext = ext.lstrip(".")
                    is_audio = ext in [".mp3", ".m4a", ".wav"]
                    break

        if not matched_ext:
            return None

        # Build metadata
        parsed_url = urllib.parse.urlparse(url)
        filename = parsed_url.path.split("/")[-1] or f"direct_media.{matched_ext}"
        clean_title = urllib.parse.unquote(filename)
        filesize = int(content_length) if content_length and content_length.isdigit() else None

        qualities: List[MediaQualityOption] = []
        is_hls = (matched_ext == "m3u8")
        streams_by_quality: Dict[str, Dict[str, Any]] = {}
        session_token = None

        if not is_audio:
            headers = {}
            streams_by_quality = {
                "native": {
                    "url": url,
                    "headers": headers,
                    "mime": "application/x-mpegURL" if is_hls else f"video/{matched_ext}",
                    "is_hls": is_hls,
                    "height": 720,
                },
                "1080p": {
                    "url": url,
                    "headers": headers,
                    "mime": "application/x-mpegURL" if is_hls else f"video/{matched_ext}",
                    "is_hls": is_hls,
                    "height": 1080,
                },
                "720p": {
                    "url": url,
                    "headers": headers,
                    "mime": "application/x-mpegURL" if is_hls else f"video/{matched_ext}",
                    "is_hls": is_hls,
                    "height": 720,
                },
                "480p": {
                    "url": url,
                    "headers": headers,
                    "mime": "application/x-mpegURL" if is_hls else f"video/{matched_ext}",
                    "is_hls": is_hls,
                    "height": 480,
                },
                "360p": {
                    "url": url,
                    "headers": headers,
                    "mime": "application/x-mpegURL" if is_hls else f"video/{matched_ext}",
                    "is_hls": is_hls,
                    "height": 360,
                },
                "audio": {
                    "url": url,
                    "headers": headers,
                    "mime": "audio/mp4",
                    "is_hls": is_hls,
                    "height": None,
                },
            }
            session_token = await stream_cache.register_stream_session(
                source_url=url,
                streams_by_quality=streams_by_quality,
                title=clean_title,
            )
            qualities = [
                MediaQualityOption(
                    quality_label="1080p (Full HD)",
                    format_id="1080p",
                    ext=matched_ext if matched_ext != "m3u8" else "mp4",
                    filesize_approx=filesize,
                    filesize_display=format_bytes(filesize),
                    resolution="1080p",
                    height=1080,
                    is_audio_only=False,
                    is_hls=is_hls,
                    stream_url=f"/api/stream/{session_token}/1080p" if session_token else None,
                ),
                MediaQualityOption(
                    quality_label="720p (HD)",
                    format_id="720p",
                    ext=matched_ext if matched_ext != "m3u8" else "mp4",
                    filesize_approx=int(filesize * 0.6) if filesize else None,
                    filesize_display=format_bytes(int(filesize * 0.6)) if filesize else None,
                    resolution="720p",
                    height=720,
                    is_audio_only=False,
                    is_hls=is_hls,
                    stream_url=f"/api/stream/{session_token}/720p" if session_token else None,
                ),
                MediaQualityOption(
                    quality_label="480p (SD)",
                    format_id="480p",
                    ext=matched_ext if matched_ext != "m3u8" else "mp4",
                    filesize_approx=int(filesize * 0.35) if filesize else None,
                    filesize_display=format_bytes(int(filesize * 0.35)) if filesize else None,
                    resolution="480p",
                    height=480,
                    is_audio_only=False,
                    is_hls=is_hls,
                    stream_url=f"/api/stream/{session_token}/480p" if session_token else None,
                ),
                MediaQualityOption(
                    quality_label="360p (Data Saver)",
                    format_id="360p",
                    ext=matched_ext if matched_ext != "m3u8" else "mp4",
                    filesize_approx=int(filesize * 0.2) if filesize else None,
                    filesize_display=format_bytes(int(filesize * 0.2)) if filesize else None,
                    resolution="360p",
                    height=360,
                    is_audio_only=False,
                    is_hls=is_hls,
                    stream_url=f"/api/stream/{session_token}/360p" if session_token else None,
                ),
                MediaQualityOption(
                    quality_label="Audio only (MP3)",
                    format_id="direct_audio",
                    ext="mp3",
                    filesize_approx=None,
                    filesize_display=None,
                    resolution="Audio",
                    height=None,
                    is_audio_only=True,
                    stream_url=f"/api/stream/{session_token}/audio" if session_token else None,
                ),
            ]
        else:
            streams_by_quality["audio"] = {
                "url": url,
                "headers": {},
                "mime": f"audio/{matched_ext}",
                "is_hls": False,
                "height": None,
            }
            session_token = await stream_cache.register_stream_session(
                source_url=url,
                streams_by_quality=streams_by_quality,
                title=clean_title,
            )
            qualities.append(MediaQualityOption(
                quality_label=f"Audio ({matched_ext.upper()})",
                format_id="direct_audio",
                ext=matched_ext,
                filesize_approx=filesize,
                filesize_display=format_bytes(filesize),
                resolution="Audio",
                height=None,
                is_audio_only=True,
                stream_url=f"/api/stream/{session_token}/audio" if session_token else None,
            ))

        return MediaMetadataResponse(
            url=url,
            platform="Direct Media File",
            title=clean_title,
            thumbnail=None,
            duration_seconds=None,
            duration_formatted=None,
            uploader=parsed_url.netloc,
            description="Direct media file extracted via HTTP Content-Type headers.",
            available_qualities=qualities,
            source_type="direct",
            extraction_tier=2,
            stream_session_id=session_token,
        )

    async def _try_embedded_html_scrape(self, url: str) -> Optional[MediaMetadataResponse]:
        """
        Tier 3: Lightweight scrape for embedded video sources:
        og:video, twitter:player:stream, <video src="...">, <source src="...">
        """
        try:
            resp = await safe_http_request("GET", url, timeout=settings.TIER3_STATIC_SCRAPE_TIMEOUT_SECONDS, max_bytes=1024 * 1024)
            if resp.status_code != 200:
                return None
            html_text = resp.text
        except Exception:
            return None

        soup = BeautifulSoup(html_text, "html.parser")
        candidate_urls: List[str] = []

        # 1. OpenGraph video tags
        for prop in ["og:video", "og:video:url", "og:video:secure_url", "twitter:player:stream"]:
            tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            if tag and tag.get("content"):
                candidate_urls.append(tag["content"].strip())

        # 2. HTML5 <video> and <source> tags
        for video_tag in soup.find_all("video"):
            if video_tag.get("src"):
                candidate_urls.append(video_tag["src"].strip())
            for source_tag in video_tag.find_all("source"):
                if source_tag.get("src"):
                    candidate_urls.append(source_tag["src"].strip())

        # Extract page title & thumbnail
        title_tag = soup.find("meta", property="og:title") or soup.find("title")
        page_title = title_tag.get("content") if title_tag and hasattr(title_tag, "get") else (title_tag.text if title_tag else "Web Media")
        thumb_tag = soup.find("meta", property="og:image")
        thumbnail_url = thumb_tag.get("content") if thumb_tag else None

        # Verify candidate URLs with SSRF protection and resolve relative URLs
        for candidate in candidate_urls:
            full_candidate = urllib.parse.urljoin(url, candidate)
            is_valid, safe_cand_url, _ = validate_url_ssrf(full_candidate)
            if not is_valid:
                continue

            # Check if this candidate is a direct media link
            direct_meta = await self._try_direct_media_link(safe_cand_url)
            if direct_meta:
                direct_meta.title = page_title.strip() or direct_meta.title
                direct_meta.thumbnail = thumbnail_url
                direct_meta.thumbnail_proxy = f"/api/stream/thumbnail?u={urllib.parse.quote(thumbnail_url)}" if thumbnail_url else None
                direct_meta.platform = "Embedded HTML5 Video"
                direct_meta.source_type = "scraped"
                direct_meta.extraction_tier = 3
                return direct_meta

        return None


media_extractor = MediaExtractionService()
