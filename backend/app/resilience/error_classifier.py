import re
import urllib.parse
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any


class FailureCategory(str, Enum):
    TRANSIENT = "TRANSIENT"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    EXTRACTOR_OUTDATED = "EXTRACTOR_OUTDATED"
    BOT_PROTECTION = "BOT_PROTECTION"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    FILE_HOST_UNSUPPORTED = "FILE_HOST_UNSUPPORTED"


FILE_HOST_UNSUPPORTED = FailureCategory.FILE_HOST_UNSUPPORTED
FILE_HOST_UNSUPPORTED_MESSAGE = (
    "This looks like a file-sharing page, not a video platform. It can't be played or downloaded here. "
    "Open the page and use its own download button, or paste a direct video link (.mp4 / .m3u8) or a supported site link."
)


class RecoveryAction(str, Enum):
    RETRY_BACKOFF = "RETRY_BACKOFF"
    FAIL_IMMEDIATELY = "FAIL_IMMEDIATELY"
    FALL_THROUGH_TIER = "FALL_THROUGH_TIER"
    QUEUE_WAIT = "QUEUE_WAIT"


@dataclass
class ErrorClassification:
    category: FailureCategory
    action: RecoveryAction
    user_message: str
    technical_detail: str
    can_retry: bool
    needs_dependency_alert: bool
    source_domain: str
    tier: str


# Regex matching patterns for classification
TRANSIENT_PATTERNS = [
    r'timed?\s*out',
    r'connection\s*(reset|refused|closed|aborted)',
    r'network\s*(is\s*)?unreachable',
    r'temporary\s*(failure|glitch|ban|block)',
    r'http\s*(error\s*)?(429|502|503|504)',
    r'too\s*many\s*requests',
    r'rate\s*limit(ed)?',
    r'ssl\s*(handshake|error|eof)',
    r'getaddrinfo\s*failed',
    r'broken\s*pipe',
    r'socket\s*(timeout|error)',
]

SOURCE_UNAVAILABLE_PATTERNS = [
    r'private\s*video',
    r'video\s*(is\s*)?private',
    r'requires?\s*(authentication|login|sign[\s-]in)',
    r'sign\s*in\s*to\s*confirm',
    r'members[\s-]only',
    r'join\s*this\s*channel',
    r'video\s*(is\s*)?unavailable',
    r'this\s*video\s*has\s*been\s*removed',
    r'deleted\s*(video|by\s*the\s*uploader)',
    r'account\s*terminated',
    r'(video|media|page|account|track|file)\s*(is\s*)?not\s*found',
    r'http\s*(error\s*)?404',
    r'geo[\s-]restricted',
    r'not\s*available\s*in\s*your\s*country',
    r'blocked\s*in\s*your\s*(country|region)',
    r'copyright\s*(infringement|claim|owner|takedown)',
    r'dmca',
    r'drm',
    r'widevine',
    r'fairplay',
    r'playready',
    r'encrypted\s*(media|stream|content|video)',
    r'protected\s*by\s*drm',
]

EXTRACTOR_OUTDATED_PATTERNS = [
    r'unable\s*to\s*extract',
    r'regex\s*pattern\s*not\s*found',
    r'signature\s*extraction\s*failed',
    r'player\s*response\s*missing',
    r'throttling\s*parameter\s*decryption\s*failed',
    r'n[\s_-]?sig\s*extraction\s*failed',
    r'extract(or|ion)?\s*error',
    r'jsondecodeerror',
    r'unexpected\s*response\s*format',
    r'unsupported\s*url',
    r'cannot\s*parse\s*(json|xml|html)',
]

BOT_PROTECTION_PATTERNS = [
    r'captcha',
    r'recaptcha',
    r'turnstile',
    r'cloudflare',
    r'ddos[\s-]guard',
    r'perimeterx',
    r'bot\s*(detected|challenge)',
    r'automated\s*(queries|traffic)',
    r'verify\s*(you\s*are\s*a\s*)?human',
    r'just\s*a\s*moment\.\.\.',
    r'http\s*(error\s*)?403',
    r'access\s*denied',
    r'dynamic\s*token',
    r'token\s*(wall|expired|invalid)',
]

RESOURCE_EXHAUSTED_PATTERNS = [
    r'disk\s*(is\s*)?full',
    r'no\s*space\s*left\s*on\s*device',
    r'worker\s*pool\s*saturated',
    r'concurrent\s*download\s*limit',
    r'out\s*of\s*memory',
    r'memoryerror',
]


def extract_domain_from_url(url: str) -> str:
    """Extracts a clean, normalized domain name from a URL."""
    try:
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc or "unknown_domain"
    except Exception:
        return "unknown_domain"


def classify_error(
    error: Exception | str,
    url: str,
    tier: str = "ytdlp",
    stderr: str = "",
    status_code: Optional[int] = None
) -> ErrorClassification:
    """
    Classifies any error occurring within the extraction pipeline.
    Determines category, automated action, user-facing explanation, and telemetry flags.
    """
    domain = extract_domain_from_url(url)
    err_str = str(error)
    combined_err = f"{err_str} {stderr}".lower()

    if status_code:
        combined_err += f" http error {status_code}"

    # 0. Check FILE_HOST_UNSUPPORTED
    if (
        FILE_HOST_UNSUPPORTED_MESSAGE.lower() in combined_err
        or "this looks like a file-sharing page" in combined_err
        or "file_host_unsupported" in combined_err
    ):
        return ErrorClassification(
            category=FailureCategory.FILE_HOST_UNSUPPORTED,
            action=RecoveryAction.FAIL_IMMEDIATELY,
            user_message=FILE_HOST_UNSUPPORTED_MESSAGE,
            technical_detail=f"File-hosting page detected without streamable media: {err_str[:160]}",
            can_retry=False,
            needs_dependency_alert=False,
            source_domain=domain,
            tier=tier,
        )

    # 1. Check RESOURCE_EXHAUSTED first
    for pattern in RESOURCE_EXHAUSTED_PATTERNS:
        if re.search(pattern, combined_err, re.IGNORECASE):
            return ErrorClassification(
                category=FailureCategory.RESOURCE_EXHAUSTED,
                action=RecoveryAction.QUEUE_WAIT,
                user_message="System resources are temporarily busy. Your request has been queued.",
                technical_detail=f"Resource capacity limit reached on tier {tier}: {err_str[:160]}",
                can_retry=True,
                needs_dependency_alert=False,
                source_domain=domain,
                tier=tier,
            )

    # 2. Check EXTRACTOR_OUTDATED (yt-dlp extractor stale or site structure changed)
    # Check if this error came from a tier with known platforms or pattern failures
    is_known_platform = any(k in domain for k in ["youtube", "youtu.be", "tiktok", "instagram", "twitter", "x.com", "reddit", "vimeo"])
    for pattern in EXTRACTOR_OUTDATED_PATTERNS:
        if re.search(pattern, combined_err, re.IGNORECASE) or (is_known_platform and "unsupported" in combined_err):
            return ErrorClassification(
                category=FailureCategory.EXTRACTOR_OUTDATED,
                action=RecoveryAction.FALL_THROUGH_TIER,
                user_message=f"The webpage structure for {domain} has changed, requiring an extractor update.",
                technical_detail=f"Extractor parser mismatch on tier {tier}: {err_str[:160]}",
                can_retry=False,
                needs_dependency_alert=True,
                source_domain=domain,
                tier=tier,
            )

    # 3. Check BOT_PROTECTION (Anti-bot walls, CAPTCHAs, dynamic token walls)
    for pattern in BOT_PROTECTION_PATTERNS:
        if re.search(pattern, combined_err, re.IGNORECASE):
            return ErrorClassification(
                category=FailureCategory.BOT_PROTECTION,
                action=RecoveryAction.FALL_THROUGH_TIER,
                user_message="Anti-bot challenge or dynamic verification detected on source platform.",
                technical_detail=f"Bot protection signature detected on tier {tier}: {err_str[:160]}",
                can_retry=False,
                needs_dependency_alert=False,
                source_domain=domain,
                tier=tier,
            )

    # 4. Check SOURCE_UNAVAILABLE (Definitive platform rejections - Never retry!)
    for pattern in SOURCE_UNAVAILABLE_PATTERNS:
        if re.search(pattern, combined_err, re.IGNORECASE):
            # Produce specific message
            if "drm" in combined_err or "widevine" in combined_err or "fairplay" in combined_err or "playready" in combined_err or "encrypted" in combined_err:
                msg = "This content is DRM-protected and can't be played or downloaded here."
            elif "private" in combined_err or "sign in" in combined_err or "login" in combined_err:
                msg = "This video is private or requires account login on the source platform."
            elif "geo" in combined_err or "country" in combined_err or "region" in combined_err:
                msg = "This video is geo-restricted and unavailable in the server's region."
            elif "copyright" in combined_err or "dmca" in combined_err:
                msg = "This media was removed due to a copyright takedown request."
            else:
                msg = "This video has been deleted or is no longer available on the source platform."

            return ErrorClassification(
                category=FailureCategory.SOURCE_UNAVAILABLE,
                action=RecoveryAction.FAIL_IMMEDIATELY,
                user_message=msg,
                technical_detail=f"Source platform returned definitive rejection: {err_str[:160]}",
                can_retry=False,
                needs_dependency_alert=False,
                source_domain=domain,
                tier=tier,
            )

    # 5. Check TRANSIENT (Network drops, timeouts, 429s, 502/503/504)
    is_timeout = isinstance(error, TimeoutError) or "timeout" in combined_err
    for pattern in TRANSIENT_PATTERNS:
        if re.search(pattern, combined_err, re.IGNORECASE) or is_timeout:
            # If timeout on a domain that is not a primary platform, immediately fall through to subsequent tiers
            # so Playwright / static scraper can resolve it without burning the 45-second deadline.
            action = RecoveryAction.FALL_THROUGH_TIER if (is_timeout and not is_known_platform) else RecoveryAction.RETRY_BACKOFF
            return ErrorClassification(
                category=FailureCategory.TRANSIENT,
                action=action,
                user_message="A temporary network connection issue or rate limit occurred. Retrying automatically..." if action == RecoveryAction.RETRY_BACKOFF else "Standard extractor timed out; switching to fallback extractor.",
                technical_detail=f"Transient failure on tier {tier}: {err_str[:160]}",
                can_retry=(action == RecoveryAction.RETRY_BACKOFF),
                needs_dependency_alert=False,
                source_domain=domain,
                tier=tier,
            )

    # Default fallback: If timeout on Tier 1-4, treat as TRANSIENT
    if is_timeout:
        action = RecoveryAction.FALL_THROUGH_TIER if not is_known_platform else RecoveryAction.RETRY_BACKOFF
        return ErrorClassification(
            category=FailureCategory.TRANSIENT,
            action=action,
            user_message="Request timed out while waiting for source platform response.",
            technical_detail=f"Timeout on tier {tier}: {err_str[:160]}",
            can_retry=(action == RecoveryAction.RETRY_BACKOFF),
            needs_dependency_alert=False,
            source_domain=domain,
            tier=tier,
        )

    # Generic unrecognized error
    return ErrorClassification(
        category=FailureCategory.TRANSIENT,
        action=RecoveryAction.FALL_THROUGH_TIER,
        user_message=f"Extraction encountered an issue on {tier} ({err_str[:100]}). Falling back to next extraction tier.",
        technical_detail=f"Unclassified error on tier {tier}: {err_str[:160]}",
        can_retry=False,
        needs_dependency_alert=False,
        source_domain=domain,
        tier=tier,
    )


def get_ux_error_details(error: Exception | str, url: str = "") -> Dict[str, Any]:
    """
    Returns structured, plain-language error explanations, actionable steps,
    retry recommendations, and sanitized debug info across the 9 UX failure classes.
    """
    import time
    domain = extract_domain_from_url(url)
    err_str = str(error).lower()

    # Security / SSRF check
    if any(k in err_str for k in ("ssrf", "restricted", "private ip", "internal ip", "security")):
        return {
            "error_class": "invalid",
            "plain_title": "Security / Restricted URL",
            "what_happened": "Security check rejected this address: SSRF protection blocked access to an internal or restricted network.",
            "what_to_try": [
                "Provide a public internet URL.",
                "Ensure the address is not on a local or private network."
            ],
            "can_retry": False,
            "debug_info": {"error_class": "invalid", "domain": domain, "timestamp": time.time(), "summary": "SSRF violation blocked"},
        }

    # 0. File Host Unsupported
    if (
        FILE_HOST_UNSUPPORTED_MESSAGE.lower() in err_str
        or "this looks like a file-sharing page" in err_str
        or "file_host_unsupported" in err_str
    ):
        return {
            "error_class": "FILE_HOST_UNSUPPORTED",
            "plain_title": "File-Sharing Page Detected",
            "what_happened": FILE_HOST_UNSUPPORTED_MESSAGE,
            "what_to_try": [
                "Open the page and use its own download button.",
                "Paste a direct video link (.mp4 / .m3u8).",
                "Paste a link from a supported site like YouTube or Vimeo."
            ],
            "can_retry": False,
            "debug_info": {"error_class": "FILE_HOST_UNSUPPORTED", "domain": domain, "timestamp": time.time(), "summary": FILE_HOST_UNSUPPORTED_MESSAGE},
        }

    # 1. File Sharing
    if any(fs in domain for fs in ("drive.google", "dropbox", "mega.nz", "mega.io", "mediafire", "wetransfer", "rapidgator", "1fichier", "box.com", "onedrive")):
        return {
            "error_class": "file_sharing",
            "plain_title": "File-Sharing Page Detected",
            "what_happened": f"{domain} is a cloud storage or file-hosting platform, not a direct streaming host.",
            "what_to_try": [
                f"Download the file directly from {domain}'s own download button.",
                "If sharing a video, obtain a direct public link ending in .mp4 or .webm.",
                "Try videos from supported platforms like YouTube, Vimeo, or Reddit."
            ],
            "can_retry": False,
            "debug_info": {"error_class": "file_sharing", "domain": domain, "timestamp": time.time(), "summary": "File sharing page cannot be extracted as stream"},
        }

    # 2. DRM Protected
    if any(k in err_str for k in ("drm", "widevine", "fairplay", "playready", "encrypted")) or any(d in domain for d in ("netflix", "spotify", "disneyplus", "hulu", "max.com", "hbomax", "primevideo")):
        return {
            "error_class": "drm",
            "plain_title": "DRM-Protected Content",
            "what_happened": "This media is protected by Digital Rights Management (DRM) encryption, which prevents extraction.",
            "what_to_try": [
                "Watch or listen using the provider's official web player or mobile app.",
                "Try public, unprotected content from YouTube, Vimeo, or X."
            ],
            "can_retry": False,
            "debug_info": {"error_class": "drm", "domain": domain, "timestamp": time.time(), "summary": "DRM encryption present"},
        }

    # 3. Private / Login Required
    if any(k in err_str for k in ("private", "sign in", "login", "requires authentication", "members-only", "join this channel")):
        return {
            "error_class": "private_login",
            "plain_title": "Private or Login-Restricted Media",
            "what_happened": "This video requires an account login, membership, or is set to private by the uploader.",
            "what_to_try": [
                "Check if the creator has a publicly accessible link or mirror.",
                "Ensure the link does not require a subscriber or members-only login.",
                "Try a public video link from the same platform."
            ],
            "can_retry": False,
            "debug_info": {"error_class": "private_login", "domain": domain, "timestamp": time.time(), "summary": "Requires login or private credentials"},
        }

    # 4. Geo-Blocked
    if any(k in err_str for k in ("geo", "country", "region", "not available in your")):
        return {
            "error_class": "geo_blocked",
            "plain_title": "Region-Restricted Video",
            "what_happened": "The content owner or platform has blocked this video from being accessed in the server's geographic location.",
            "what_to_try": [
                "Check if an official international or region-free mirror is available.",
                "Try another link or alternate upload of the same content."
            ],
            "can_retry": False,
            "debug_info": {"error_class": "geo_blocked", "domain": domain, "timestamp": time.time(), "summary": "Geographic restriction enforced by source"},
        }

    # 5. Deleted / Removed
    if any(k in err_str for k in ("deleted", "removed", "not found", "404", "takedown", "terminated")):
        return {
            "error_class": "deleted",
            "plain_title": "Video No Longer Available",
            "what_happened": "This media was deleted, removed by the uploader, or taken down by the host platform.",
            "what_to_try": [
                "Verify the link works in your web browser.",
                "Search for an alternate link or newer upload of the video."
            ],
            "can_retry": False,
            "debug_info": {"error_class": "deleted", "domain": domain, "timestamp": time.time(), "summary": "HTTP 404 or video deleted by uploader"},
        }

    # 6. Site Blocking / Bot Protection
    if any(k in err_str for k in ("bot", "captcha", "turnstile", "cloudflare", "403", "forbidden", "rate limit", "429", "too many requests")):
        return {
            "error_class": "site_blocking",
            "plain_title": "Temporary Site Rate Limit",
            "what_happened": f"{domain} is temporarily rate-limiting or blocking automated server connections.",
            "what_to_try": [
                "Wait 1–2 minutes and click Retry.",
                "Try a direct stream link or alternate source.",
                "Download directly from the platform's official site."
            ],
            "can_retry": True,
            "debug_info": {"error_class": "site_blocking", "domain": domain, "timestamp": time.time(), "summary": "Host platform rate limit or challenge"},
        }

    # 7. Timeout
    if any(k in err_str for k in ("timeout", "timed out", "504", "gateway")):
        return {
            "error_class": "timeout",
            "plain_title": "Connection Timed Out",
            "what_happened": f"{domain} took too long to respond to our media extraction request.",
            "what_to_try": [
                "Click Retry to attempt the connection again.",
                "Check if the host platform is experiencing slow loading or downtime.",
                "Try again in a few moments."
            ],
            "can_retry": True,
            "debug_info": {"error_class": "timeout", "domain": domain, "timestamp": time.time(), "summary": "Remote host timed out"},
        }

    # 8. Unsupported Site
    if any(k in err_str for k in ("unsupported url", "no suitable extractor", "unable to extract")):
        return {
            "error_class": "unsupported_site",
            "plain_title": "Site Not Yet Supported",
            "what_happened": f"MediaGrab AI does not currently support automatic video extraction from {domain}.",
            "what_to_try": [
                "Try a direct video file link ending in .mp4, .m3u8, or .webm.",
                "Use supported platforms like YouTube, Vimeo, X, or Reddit.",
                "Click 'Report this link' below to request support for this site!"
            ],
            "can_retry": False,
            "debug_info": {"error_class": "unsupported_site", "domain": domain, "timestamp": time.time(), "summary": "Domain not in supported extractors"},
        }

    # 9. Internal Error
    return {
        "error_class": "internal_error",
        "plain_title": "Processing Error",
        "what_happened": "An unexpected error occurred while analyzing the media stream.",
        "what_to_try": [
            "Click Retry to start a fresh extraction attempt.",
            "Check that the video is playable in your browser.",
            "Click 'Report this link' or copy debug info so our team can resolve it."
        ],
        "can_retry": True,
        "debug_info": {"error_class": "internal_error", "domain": domain, "timestamp": time.time(), "summary": str(error)[:120]},
    }

