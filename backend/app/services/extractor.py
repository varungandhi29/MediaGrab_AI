import json
import re
import urllib.parse
import asyncio
from typing import Dict, Any, List, Optional, Tuple, Callable
from bs4 import BeautifulSoup

from ..config import settings
from ..models.schemas import MediaMetadataResponse, MediaQualityOption
from ..security.ssrf_validator import validate_url_ssrf, safe_http_request, SSRFValidationError
from ..security.sandbox import build_sandboxed_ytdlp_args, run_sandboxed_subprocess
from ..security.sanitizer import sanitize_for_logging, sanitize_error_message
from .headless_browser import headless_browser


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
        Executes sequential fast-fail extraction bounded by a 30s hard timeout.
        """
        try:
            return await asyncio.wait_for(
                self._extract_metadata_sequential(url, status_callback),
                timeout=float(settings.TOTAL_EXTRACTION_TIMEOUT_SECONDS)
            )
        except asyncio.TimeoutError:
            raise TimeoutError("Extraction exceeded maximum duration allocation (30s). The source platform may be unresponsive.")

    async def _extract_metadata_sequential(
        self,
        url: str,
        status_callback: Optional[Callable[[int, str, str], Any]] = None
    ) -> MediaMetadataResponse:
        # Step 0: SSRF validation before touching network
        is_valid, clean_url, error_msg = validate_url_ssrf(url)
        if not is_valid:
            raise SSRFValidationError(error_msg or "URL failed SSRF validation.")

        # ==========================================
        # TIER 1: yt-dlp Extraction (8s limit)
        # ==========================================
        if status_callback:
            await status_callback(1, "ytdlp", "Trying standard extraction (yt-dlp)...")
        try:
            tier1_res = await self._try_ytdlp_extraction(clean_url)
            if tier1_res:
                return tier1_res
        except SSRFValidationError:
            raise
        except ValueError:
            # Re-raise explicit platform errors (private video, geo-blocked)
            raise
        except Exception:
            pass

        # ==========================================
        # TIER 2: Direct Media Link Inspection (5s limit)
        # ==========================================
        if status_callback:
            await status_callback(2, "direct", "Checking direct media headers...")
        try:
            tier2_res = await self._try_direct_media_link(clean_url)
            if tier2_res:
                return tier2_res
        except SSRFValidationError:
            raise
        except Exception:
            pass

        # ==========================================
        # TIER 3: Lightweight Embedded Video Scraper (5s limit)
        # ==========================================
        if status_callback:
            await status_callback(3, "static_scrape", "Scanning page HTML for embedded media...")
        try:
            tier3_res = await self._try_embedded_html_scrape(clean_url)
            if tier3_res:
                return tier3_res
        except SSRFValidationError:
            raise
        except Exception:
            pass

        # ==========================================
        # TIER 4: Headless Browser Fallback (15s limit)
        # ==========================================
        if status_callback:
            await status_callback(4, "headless_browser", "Launching headless browser render (Playwright)...")
        try:
            tier4_res = await self._try_headless_browser_fallback(clean_url)
            if tier4_res:
                return tier4_res
        except SSRFValidationError:
            raise
        except Exception:
            pass

        # Specific user-requested error message when all 4 tiers fail
        raise ValueError(
            "This site uses protections we can't bypass (dynamic tokens, anti-bot measures, or requires login) — try downloading the file directly from the source page instead"
        )

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

            # Check if any candidate can be inspected via direct link inspector
            for cand_url in candidate_urls:
                direct_meta = await self._try_direct_media_link(cand_url)
                if direct_meta:
                    direct_meta.title = page_title
                    direct_meta.thumbnail = page_thumb or direct_meta.thumbnail
                    direct_meta.platform = "Headless Browser Render (Dynamic JS)"
                    direct_meta.source_type = "headless_browser"
                    direct_meta.extraction_tier = 4
                    return direct_meta

            # Direct fallback stream
            first_cand = candidate_urls[0]
            parsed_cand = urllib.parse.urlparse(first_cand)
            ext = "mp4"
            if ".m3u8" in first_cand.lower():
                ext = "m3u8"
            elif ".webm" in first_cand.lower():
                ext = "webm"
            elif ".mp3" in first_cand.lower():
                ext = "mp3"

            return MediaMetadataResponse(
                url=first_cand,
                platform="Headless Browser Render (Dynamic JS)",
                title=page_title,
                thumbnail=page_thumb,
                duration_seconds=None,
                duration_formatted=None,
                uploader=parsed_cand.netloc,
                description="Extracted via Tier 4 headless browser network sniffing.",
                available_qualities=[
                    MediaQualityOption(
                        quality_label="Native Stream (Dynamic Render)",
                        format_id="direct",
                        ext=ext,
                        filesize_approx=None,
                        filesize_display=None,
                        resolution="Native",
                        is_audio_only=(ext == "mp3"),
                    ),
                    MediaQualityOption(
                        quality_label="Audio only (MP3)",
                        format_id="direct_audio",
                        ext="mp3",
                        filesize_approx=None,
                        filesize_display=None,
                        resolution="Audio",
                        is_audio_only=True,
                    )
                ],
                source_type="headless_browser",
                extraction_tier=4,
            )
        except Exception:
            return None

    async def _try_ytdlp_extraction(self, url: str) -> Optional[MediaMetadataResponse]:
        """Runs yt-dlp in a sandboxed subprocess with 8-second fast-fail timeout."""
        cmd_args = build_sandboxed_ytdlp_args(
            target_url=url,
            is_metadata_only=True
        )

        try:
            retcode, stdout, stderr = await run_sandboxed_subprocess(
                cmd_args,
                timeout_seconds=settings.TIER1_YTDLP_TIMEOUT_SECONDS
            )
        except TimeoutError:
            # Fast fail to Tier 2 on timeout
            return None

        if retcode != 0 or not stdout.strip():
            lower_err = stderr.lower()
            if "private video" in lower_err:
                raise ValueError("This video is private or requires authentication.")
            if "geo-restricted" in lower_err or "not available in your country" in lower_err:
                raise ValueError("This media is geo-blocked by the source platform.")
            # Fast bail on unsupported URL or errors
            return None

        try:
            info = json.loads(stdout.strip())
        except json.JSONDecodeError:
            return None

        # Parse extracted info
        title = info.get("title") or "Untitled Media"
        thumbnail = info.get("thumbnail")
        duration = info.get("duration")
        uploader = info.get("uploader") or info.get("channel") or info.get("creator")
        description = (info.get("description") or "")[:250]
        platform = determine_platform_name(url, info.get("extractor_key") or info.get("extractor"))

        # Build genuine available qualities
        formats = info.get("formats", [])
        qualities = self._parse_ytdlp_qualities(formats)

        return MediaMetadataResponse(
            url=url,
            platform=platform,
            title=title,
            thumbnail=thumbnail,
            duration_seconds=float(duration) if duration else None,
            duration_formatted=format_duration(duration),
            uploader=uploader,
            description=description,
            available_qualities=qualities,
            source_type="ytdlp",
            extraction_tier=1,
        )

    def _parse_ytdlp_qualities(self, formats: List[Dict[str, Any]]) -> List[MediaQualityOption]:
        """
        Parses actual video and audio formats. Only includes qualities that
        genuinely exist in the source stream. Never fabricates unavailable resolutions.
        Standard targets: 2160p (4K), 1440p (2K), 1080p, 720p, 480p, 360p.
        Plus 'Audio only (MP3)'.
        """
        existing_heights = set()
        height_to_format_info = {}

        has_audio = False
        has_video = False

        for f in formats:
            vcodec = f.get("vcodec")
            acodec = f.get("acodec")
            height = f.get("height")
            filesize = f.get("filesize") or f.get("filesize_approx")

            if acodec and acodec != "none":
                has_audio = True

            ext = (f.get("ext") or "").lower()
            if ext in ("mp4", "webm", "mov", "mkv", "flv"):
                has_video = True

            if vcodec and vcodec != "none" and height and height > 0:
                has_video = True
                existing_heights.add(height)
                # Keep the format with known filesize if possible
                if height not in height_to_format_info or (filesize and not height_to_format_info[height].get("filesize")):
                    height_to_format_info[height] = f

        qualities: List[MediaQualityOption] = []

        # Target tiers to evaluate
        standard_tiers = [
            (2160, "2160p (4K)"),
            (1440, "1440p (2K)"),
            (1080, "1080p (Full HD)"),
            (720, "720p (HD)"),
            (480, "480p (SD)"),
            (360, "360p"),
        ]

        if has_video:
            for max_h, label in standard_tiers:
                matching_heights = [h for h in existing_heights if (h <= max_h and (max_h == 360 or h > (max_h * 0.7)))]
                if matching_heights:
                    best_match = max(matching_heights)
                    f_info = height_to_format_info.get(best_match, {})
                    approx_size = f_info.get("filesize") or f_info.get("filesize_approx")

                    fmt_selector = f"bestvideo[height<={max_h}]+bestaudio/best[height<={max_h}]/best"
                    qualities.append(MediaQualityOption(
                        quality_label=label,
                        format_id=fmt_selector,
                        ext="mp4",
                        filesize_approx=approx_size,
                        filesize_display=format_bytes(approx_size),
                        resolution=f"{best_match}p",
                        is_audio_only=False,
                        vcodec=f_info.get("vcodec"),
                        acodec=f_info.get("acodec"),
                    ))
                    for h in matching_heights:
                        existing_heights.discard(h)

            # If no standard height tier matched but video format exists
            if not qualities:
                max_h_label = f"{max(existing_heights)}p" if existing_heights else "Native Video Quality"
                qualities.append(MediaQualityOption(
                    quality_label=max_h_label,
                    format_id="best",
                    ext="mp4",
                    filesize_approx=None,
                    filesize_display=None,
                    resolution=max_h_label,
                    is_audio_only=False,
                ))

        # Always offer "Audio only (MP3)" if audio stream is available
        if has_audio or not has_video:
            qualities.append(MediaQualityOption(
                quality_label="Audio only (MP3)",
                format_id="bestaudio/best",
                ext="mp3",
                filesize_approx=None,
                filesize_display=None,
                resolution="Audio",
                is_audio_only=True,
            ))

        return qualities

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
        if not is_audio:
            qualities.append(MediaQualityOption(
                quality_label="Native Direct Stream",
                format_id="direct",
                ext=matched_ext,
                filesize_approx=filesize,
                filesize_display=format_bytes(filesize),
                resolution="Native",
                is_audio_only=False,
            ))
            qualities.append(MediaQualityOption(
                quality_label="Audio only (MP3)",
                format_id="direct_audio",
                ext="mp3",
                filesize_approx=None,
                filesize_display=None,
                resolution="Audio",
                is_audio_only=True,
            ))
        else:
            qualities.append(MediaQualityOption(
                quality_label=f"Audio ({matched_ext.upper()})",
                format_id="direct_audio",
                ext=matched_ext,
                filesize_approx=filesize,
                filesize_display=format_bytes(filesize),
                resolution="Audio",
                is_audio_only=True,
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
                direct_meta.platform = "Embedded HTML5 Video"
                direct_meta.source_type = "scraped"
                direct_meta.extraction_tier = 3
                return direct_meta

        return None


media_extractor = MediaExtractionService()
