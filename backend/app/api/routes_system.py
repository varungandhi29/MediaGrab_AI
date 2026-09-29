import os
import time
from fastapi import APIRouter
from ..config import settings
from ..models.schemas import LinkPreCheckRequest, LinkReportRequest, RatingFeedbackRequest
from ..services.link_checker import check_link_instant, SUPPORTED_PLATFORMS
from ..services.feedback_manager import feedback_manager
from ..resilience.synthetic_playback_monitor import synthetic_playback_monitor

router = APIRouter(prefix="/api", tags=["system"])
START_TIME = time.time()


import shutil

@router.get("/health")
async def health_check():
    ffmpeg_ok = bool(
        (settings.FFMPEG_LOCATION and os.path.exists(settings.FFMPEG_LOCATION))
        or shutil.which("ffmpeg")
        or shutil.which(settings.FFMPEG_LOCATION or "")
    )
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "ffmpeg_available": ffmpeg_ok,
        "storage_ready": settings.STORAGE_DIR.exists(),
        "uptime_seconds": int(time.time() - START_TIME),
    }


@router.get("/stats")
async def system_stats():
    """
    Anonymous, aggregate-only analytics (strictly zero PII).
    """
    try:
        active_files = len(list(settings.STORAGE_DIR.glob("*.*")))
    except Exception:
        active_files = 0

    return {
        "supported_platforms": "YouTube, Vimeo, X, Reddit, SoundCloud, Twitch, Direct Links",
        "ssrf_protection_active": True,
        "sliding_window_rate_limits": {
            "metadata_limit": f"{settings.METADATA_RATE_LIMIT_REQUESTS} / {settings.METADATA_RATE_LIMIT_WINDOW_SECONDS}s",
            "download_limit": f"{settings.DOWNLOAD_RATE_LIMIT_REQUESTS} / {settings.DOWNLOAD_RATE_LIMIT_WINDOW_SECONDS}s",
            "max_concurrent": settings.MAX_CONCURRENT_DOWNLOADS_PER_IP,
        },
        "temporary_files_stored": active_files,
        "file_ttl_minutes": settings.FILE_TTL_SECONDS // 60,
    }


@router.post("/check-link")
async def check_link(payload: LinkPreCheckRequest):
    """
    Fast pre-check (< 50ms) to provide instant feedback as soon as a link is pasted.
    """
    return check_link_instant(payload.url)


@router.post("/feedback/report")
async def submit_link_report(payload: LinkReportRequest):
    """
    1-click anonymous link failure report.
    """
    return await feedback_manager.save_report(
        domain=payload.domain,
        error_class=payload.error_class,
        job_id=payload.job_id,
        tier_results=payload.tier_results,
        comment=payload.comment,
    )


@router.post("/feedback/rating")
async def submit_rating(payload: RatingFeedbackRequest):
    """
    Anonymous thumbs up/down user feedback after playback or download.
    """
    return await feedback_manager.save_rating(
        domain=payload.domain,
        rating=payload.rating,
        job_id=payload.job_id,
        action=payload.action,
    )


@router.get("/system/status-banner")
async def get_status_banner():
    """
    Provides real-time system status banner driven by synthetic checks and UX health metrics.
    """
    failing_sites = []
    # Check synthetic playback monitor
    synth_res = synthetic_playback_monitor.last_result
    if synth_res and synth_res.get("overall_status") == "FAIL":
        for target in synth_res.get("targets", []):
            if target.get("status") == "FAIL":
                failing_sites.append(target.get("target", "Streaming Core"))

    # Check rolling alerts
    ux_metrics = await feedback_manager.get_ux_metrics()
    for alert in ux_metrics.get("alerts", []):
        d = alert.get("domain", "")
        if d and d not in failing_sites:
            failing_sites.append(d)

    if failing_sites:
        return {
            "status": "degraded",
            "message": f"Some sites are currently experiencing issues: {', '.join(failing_sites)}",
            "failing_sites": failing_sites,
            "last_checked": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        }

    return {
        "status": "healthy",
        "message": "All systems normal",
        "failing_sites": [],
        "last_checked": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
    }


@router.get("/system/ux-metrics")
async def get_ux_metrics():
    """
    Dashboard metrics: success rate per domain, top failing domains, top error classes,
    average time to ready, thumbs up/down ratio, and weekly summary of top unsupported domains.
    """
    return await feedback_manager.get_ux_metrics()


@router.get("/system/supported-sites")
async def get_supported_sites():
    """
    Returns the verified supported sites list, disclaimer, and last updated date.
    """
    return {
        "verified_sites": [
            {"name": "YouTube", "domain": "youtube.com", "badge": "4K/HD Video & Audio", "type": "Video & Audio (up to 4K)"},
            {"name": "Vimeo", "domain": "vimeo.com", "badge": "High Bitrate 1080p", "type": "High Bitrate HD/4K"},
            {"name": "Direct file links (.mp4, .webm, .m3u8)", "domain": ".mp4, .webm, .m3u8", "badge": "Lossless Native", "type": "Direct Video & Audio Streams"},
        ],
        "disclaimer": "File-sharing pages, private videos, DRM-protected and login-only content are not supported.",
        "last_updated": "September 2026",
    }
