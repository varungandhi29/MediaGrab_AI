import asyncio
from pathlib import Path

from app.config import settings
from app.services.media_validator import validate_download, MediaValidationError
from app.services.media_normalizer import normalize_to_mp4, NormalizeError
from app.resilience.media_errors import classify_error, user_message

STORAGE_DIR = settings.STORAGE_DIR


async def finalize_download(
    job,
    downloaded_path: Path,
    *,
    content_type=None,       # response Content-Type of the download, if you have it
    status_code=None,        # HTTP status of the download, if you have it
    expected_length=None,    # Content-Length, if the server sent one
    tiers_found_media=None,  # pass False when every extraction tier found no media
):
    job_id = getattr(job, "id", None) or getattr(job, "job_id", "unknown_job")
    out_path = Path(STORAGE_DIR) / f"{job_id}.mp4"
    try:
        await asyncio.to_thread(validate_download, downloaded_path, content_type, status_code, expected_length)
        await asyncio.to_thread(normalize_to_mp4, downloaded_path, out_path)
        job.output_path = str(out_path)
        job.status = "ready"
        if hasattr(job, "progress_percent"):
            job.progress_percent = 100.0
        if hasattr(job, "speed"):
            job.speed = "Ready"
        if hasattr(job, "event_notify"):
            job.event_notify.set()
    except MediaValidationError as e:
        cls = classify_error(f"{e.code}: {e.detail}", tiers_found_media=tiers_found_media)
        mark_failed(job, cls, e.detail)
    except NormalizeError as e:
        cls = classify_error(e.stderr_tail, tiers_found_media=tiers_found_media)
        mark_failed(job, cls, e.stderr_tail)
    finally:
        downloaded_path.unlink(missing_ok=True)       # always delete the temp download


def mark_failed(job, cls, debug_text):
    job.status = "failed"
    job.error_class = cls.value if hasattr(cls, "value") else str(cls)
    job.user_message = user_message(cls)
    job.error_message = user_message(cls)
    job.debug = "\n".join((debug_text or "").splitlines()[-30:])   # last 30 lines only
    if hasattr(job, "event_notify"):
        job.event_notify.set()


async def run_with_one_retry(job, attempt_fn):
    """attempt_fn(job) downloads + finalizes, and leaves job.status as 'ready' or 'failed'."""
    for attempt in (1, 2):
        job.status = "downloading"
        await attempt_fn(job)
        if job.status == "ready":
            return
        if job.error_class != "DOWNLOAD_INCOMPLETE" or attempt == 2:
            return
        await asyncio.sleep(2)
