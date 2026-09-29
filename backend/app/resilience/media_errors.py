"""
media_errors.py -- turn raw yt-dlp / ffmpeg / validator output into a specific
error class and a friendly message with a next step.
Replaces the single "protections we can't bypass" message.
"""
import re
from enum import Enum
from typing import Optional


class ErrorClass(str, Enum):
    UNSUPPORTED_URL = "UNSUPPORTED_URL"
    FILE_HOST_UNSUPPORTED = "FILE_HOST_UNSUPPORTED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    BOT_CHECK = "BOT_CHECK"
    GEO_BLOCKED = "GEO_BLOCKED"
    PRIVATE_OR_DELETED = "PRIVATE_OR_DELETED"
    DRM = "DRM"
    OUTDATED_EXTRACTOR = "OUTDATED_EXTRACTOR"
    FFMPEG_MISSING = "FFMPEG_MISSING"
    INVALID_MEDIA = "INVALID_MEDIA"
    DOWNLOAD_INCOMPLETE = "DOWNLOAD_INCOMPLETE"
    TIMEOUT = "TIMEOUT"
    SSRF_BLOCKED = "SSRF_BLOCKED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


MESSAGES = {
    ErrorClass.UNSUPPORTED_URL: "This site isn't supported. Try a link from a supported site, or a direct video file link (.mp4 / .m3u8).",
    ErrorClass.FILE_HOST_UNSUPPORTED: "This looks like a file-sharing page, not a video platform. It can't be played or downloaded here. Open the page and use its own download button, or paste a direct video link (.mp4 / .m3u8) or a supported site link.",
    ErrorClass.LOGIN_REQUIRED: "This video needs a sign-in, so it can't be played or downloaded here. Try a public link instead.",
    ErrorClass.BOT_CHECK: "The site is blocking automated access right now. Try again later, or use the site's own download option.",
    ErrorClass.GEO_BLOCKED: "This video isn't available in the region our server is in. Try the platform's own app or download option.",
    ErrorClass.PRIVATE_OR_DELETED: "This video is private, deleted or unavailable. Check that the link works in your browser.",
    ErrorClass.DRM: "This content is DRM-protected and can't be played or downloaded here.",
    ErrorClass.OUTDATED_EXTRACTOR: "We couldn't read this site right now. Our extractor may need an update. Try again later.",
    ErrorClass.FFMPEG_MISSING: "The server is missing a required tool (ffmpeg). The site owner has been notified.",
    ErrorClass.INVALID_MEDIA: "The link didn't return a real video file. Try another link.",
    ErrorClass.DOWNLOAD_INCOMPLETE: "The download was cut off before it finished. Please retry.",
    ErrorClass.TIMEOUT: "This took too long and was stopped. Try again, or try a shorter video.",
    ErrorClass.SSRF_BLOCKED: "This address can't be used.",
    ErrorClass.INTERNAL_ERROR: "Something went wrong on our side. Retry, or copy the debug info and report it.",
}

# (compiled pattern, class). First match wins, so order matters.
_PATTERNS = [
    (r"unsupported url", ErrorClass.UNSUPPORTED_URL),
    (r"\bdrm\b|widevine|fairplay|playready|sample-aes", ErrorClass.DRM),
    (r"not available in your country|geo.?restrict|geo.?block|blocked it in your country|not made this video available in your country", ErrorClass.GEO_BLOCKED),
    (r"sign in to confirm|not a bot|http error (403|429)|too many requests|captcha", ErrorClass.BOT_CHECK),
    (r"private video|login required|sign in|members-only|age.?restricted|requires? (a )?login", ErrorClass.LOGIN_REQUIRED),
    (r"video unavailable|has been removed|does not exist|deleted|http error 404|http error 410", ErrorClass.PRIVATE_OR_DELETED),
    (r"nsig|requested format is not available|unable to extract|javascript runtime|player response", ErrorClass.OUTDATED_EXTRACTOR),
    (r"ffmpeg.*not found|ffprobe.*(missing|not installed)|ffmpeg is not installed|ffprobe_missing", ErrorClass.FFMPEG_MISSING),
    (r"download_incomplete|too_small", ErrorClass.DOWNLOAD_INCOMPLETE),
    (r"invalid_media|invalid data found|moov atom not found|no audio or video streams", ErrorClass.INVALID_MEDIA),
    (r"timed out|timeout", ErrorClass.TIMEOUT),
    (r"ssrf|private or internal", ErrorClass.SSRF_BLOCKED),
]
_COMPILED = [(re.compile(p, re.I), c) for p, c in _PATTERNS]


def classify_error(text: str, *, tiers_found_media: Optional[bool] = None) -> ErrorClass:
    """
    text: raw stderr / exception text.
    tiers_found_media: pass False when yt-dlp, the static scrape AND the browser tier all
    found no media. An unsupported URL or invalid file then means a file-hosting page.
    """
    text = text or ""
    cls = next((c for rx, c in _COMPILED if rx.search(text)), ErrorClass.INTERNAL_ERROR)
    if cls in (ErrorClass.UNSUPPORTED_URL, ErrorClass.INVALID_MEDIA) and tiers_found_media is False:
        return ErrorClass.FILE_HOST_UNSUPPORTED
    return cls


def user_message(cls: ErrorClass) -> str:
    return MESSAGES[cls]
