import os
import time
from fastapi import APIRouter
from ..config import settings

router = APIRouter(prefix="/api", tags=["system"])
START_TIME = time.time()


@router.get("/health")
async def health_check():
    ffmpeg_ok = bool(settings.FFMPEG_LOCATION and os.path.exists(settings.FFMPEG_LOCATION))
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
        "supported_platforms": "1800+",
        "ssrf_protection_active": True,
        "sliding_window_rate_limits": {
            "metadata_limit": f"{settings.METADATA_RATE_LIMIT_REQUESTS} / {settings.METADATA_RATE_LIMIT_WINDOW_SECONDS}s",
            "download_limit": f"{settings.DOWNLOAD_RATE_LIMIT_REQUESTS} / {settings.DOWNLOAD_RATE_LIMIT_WINDOW_SECONDS}s",
            "max_concurrent": settings.MAX_CONCURRENT_DOWNLOADS_PER_IP,
        },
        "temporary_files_stored": active_files,
        "file_ttl_minutes": settings.FILE_TTL_SECONDS // 60,
    }
