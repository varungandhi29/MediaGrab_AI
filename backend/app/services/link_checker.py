import re
import urllib.parse
from typing import Dict, Any, List, Optional
from ..security.ssrf_validator import validate_url_ssrf
from ..models.schemas import LinkPreCheckResponse

FILE_SHARING_DOMAINS = {
    "drive.google.com": "Google Drive",
    "docs.google.com": "Google Drive",
    "dropbox.com": "Dropbox",
    "mega.nz": "Mega",
    "mega.io": "Mega",
    "mediafire.com": "MediaFire",
    "wetransfer.com": "WeTransfer",
    "rapidgator.net": "Rapidgator",
    "1fichier.com": "1fichier",
    "sendspace.com": "Sendspace",
    "uptobox.com": "Uptobox",
    "turbobit.net": "Turbobit",
    "zippyshare.com": "Zippyshare",
    "box.com": "Box",
    "onedrive.live.com": "OneDrive",
    "1drv.ms": "OneDrive",
    "icloud.com": "iCloud",
    "anonfiles.com": "AnonFiles",
    "filefactory.com": "FileFactory",
    "depositfiles.com": "DepositFiles",
    "uploading.com": "Uploading",
    "4shared.com": "4shared",
    "nitroflare.com": "Nitroflare",
    "katfile.com": "Katfile",
    "k2s.cc": "Keep2Share",
    "bayfiles.com": "BayFiles",
    "openload.co": "Openload",
}

DRM_LOGIN_DOMAINS = {
    "netflix.com": "Netflix",
    "spotify.com": "Spotify",
    "disneyplus.com": "Disney+",
    "hulu.com": "Hulu",
    "max.com": "Max (HBO)",
    "hbomax.com": "HBO Max",
    "primevideo.com": "Amazon Prime Video",
    "peacocktv.com": "Peacock",
    "paramountplus.com": "Paramount+",
    "apple.com": "Apple TV+",
    "crunchyroll.com": "Crunchyroll",
}

SUPPORTED_PLATFORMS = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "vimeo.com": "Vimeo",
    "twitter.com": "X / Twitter",
    "x.com": "X / Twitter",
    "reddit.com": "Reddit",
    "soundcloud.com": "SoundCloud",
    "twitch.tv": "Twitch",
    "dailymotion.com": "Dailymotion",
    "bilibili.com": "Bilibili",
    "tiktok.com": "TikTok",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "threads.net": "Threads",
    "tumblr.com": "Tumblr",
    "vk.com": "VK",
    "pinterest.com": "Pinterest",
    "bandcamp.com": "Bandcamp",
    "terabox.com": "TeraBox",
    "terabox.app": "TeraBox",
    "terasharefile.com": "TeraBox",
    "1024tera.com": "TeraBox",
    "freeterabox.com": "TeraBox",
    "teraboxshare.com": "TeraBox",
    "tibibox.com": "TeraBox",
    "terafileshare.com": "TeraBox",
    "teraboxlink.com": "TeraBox",
    "terafiles.net": "TeraBox",
    "dubox.com": "TeraBox",
}

DIRECT_EXTENSIONS = (
    ".mp4", ".webm", ".m3u8", ".mov", ".mkv", ".avi", ".flv",
    ".mp3", ".wav", ".m4a", ".aac", ".ogg"
)


def check_link_instant(url: str) -> LinkPreCheckResponse:
    """
    Performs instant (< 50ms) classification of user submitted links before any extraction starts.
    Categorizes into:
    1. Supported site
    2. Direct video file
    3. Probably unsupported (file-sharing page)
    4. Not a valid link
    """
    cleaned_url = (url or "").strip()
    if not cleaned_url:
        return LinkPreCheckResponse(
            url=cleaned_url,
            domain="",
            status="invalid",
            label="Not a valid link",
            platform_name="Invalid",
            can_extract=False,
            explanation="Please paste a valid video URL.",
            alternatives=["Paste a link from YouTube, Vimeo, X, Reddit, or a direct .mp4 link."],
            error_class="invalid",
        )

    # Basic scheme validation
    try:
        parsed = urllib.parse.urlparse(cleaned_url)
    except Exception:
        return LinkPreCheckResponse(
            url=cleaned_url,
            domain="",
            status="invalid",
            label="Not a valid link",
            platform_name="Invalid",
            can_extract=False,
            explanation="The provided text could not be parsed as a URL.",
            alternatives=["Ensure the link starts with http:// or https://."],
            error_class="invalid",
        )

    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return LinkPreCheckResponse(
            url=cleaned_url,
            domain="",
            status="invalid",
            label="Not a valid link",
            platform_name="Invalid",
            can_extract=False,
            explanation="URL must begin with http:// or https:// and include a valid domain name.",
            alternatives=["Check for typos or copy the full link from your browser address bar."],
            error_class="invalid",
        )

    # SSRF safety validation
    is_valid_ssrf, _, ssrf_err = validate_url_ssrf(cleaned_url)
    if not is_valid_ssrf:
        return LinkPreCheckResponse(
            url=cleaned_url,
            domain=parsed.netloc,
            status="invalid",
            label="Not a valid link",
            platform_name="Restricted Network",
            can_extract=False,
            explanation=f"Security check rejected this address: {ssrf_err or 'Private or internal network not allowed.'}",
            alternatives=["Provide a public internet URL."],
            error_class="invalid",
        )

    domain = parsed.netloc.lower().split(":")[0]
    # Strip leading www.
    clean_domain = domain[4:] if domain.startswith("www.") else domain
    path = parsed.path.lower()

    # 1. File-sharing / cloud storage check (check first so dropbox.com/s/.../video.mp4 is caught)
    for fs_domain, fs_name in FILE_SHARING_DOMAINS.items():
        if clean_domain == fs_domain or clean_domain.endswith("." + fs_domain):
            return LinkPreCheckResponse(
                url=cleaned_url,
                domain=domain,
                status="unsupported_file_sharing",
                label="Probably unsupported (file-sharing page)",
                platform_name=fs_name,
                can_extract=False,
                explanation=f"{fs_name} is a file-sharing/cloud storage service, not a streaming video host.",
                alternatives=[
                    f"Download the file directly from {fs_name}'s own download button.",
                    "If sharing a video, obtain a direct public link ending in .mp4 or .webm.",
                    "Use supported streaming platforms like YouTube, Vimeo, or Reddit.",
                ],
                error_class="file_sharing",
            )

    # 2. DRM / Login-walled streaming check
    for drm_domain, drm_name in DRM_LOGIN_DOMAINS.items():
        if clean_domain == drm_domain or clean_domain.endswith("." + drm_domain):
            return LinkPreCheckResponse(
                url=cleaned_url,
                domain=domain,
                status="unsupported_drm",
                label="Probably unsupported (DRM-protected)",
                platform_name=drm_name,
                can_extract=False,
                explanation=f"{drm_name} content is protected by Digital Rights Management (DRM) encryption and subscriber authentication.",
                alternatives=[
                    f"Watch this content directly on {drm_name} inside their official app or website.",
                    "MediaGrab AI does not support or bypass DRM-protected streaming services.",
                    "Try public videos on YouTube, Vimeo, or Reddit instead.",
                ],
                error_class="drm",
            )

    # 3. Direct media file check
    if any(path.endswith(ext) for ext in DIRECT_EXTENSIONS):
        return LinkPreCheckResponse(
            url=cleaned_url,
            domain=domain,
            status="direct_media",
            label="Direct video file",
            platform_name="Direct Video Link",
            can_extract=True,
            explanation="Direct media stream detected. Ready for immediate playback and download.",
            alternatives=[],
            error_class=None,
        )

    # 4. Known supported platform check
    for supp_domain, supp_name in SUPPORTED_PLATFORMS.items():
        if clean_domain == supp_domain or clean_domain.endswith("." + supp_domain):
            return LinkPreCheckResponse(
                url=cleaned_url,
                domain=domain,
                status="supported_site",
                label="Supported site",
                platform_name=supp_name,
                can_extract=True,
                explanation=f"Verified {supp_name} video link. Audio and video extraction fully supported.",
                alternatives=[],
                error_class=None,
            )

    # 5. Generic public web page check
    return LinkPreCheckResponse(
        url=cleaned_url,
        domain=domain,
        status="supported_site",
        label="Supported site",
        platform_name=clean_domain or "Web Source",
        can_extract=True,
        explanation="Public web link detected. MediaGrab AI will inspect the page for streamable media.",
        alternatives=[],
        error_class=None,
    )
