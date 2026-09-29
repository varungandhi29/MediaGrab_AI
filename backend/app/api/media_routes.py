"""
media_routes.py  --  drop-in FastAPI routes for MediaGrab AI

Two DIFFERENT URLs for the SAME finished file:

  GET /api/media/{job_id}/play      -> Content-Disposition: inline      (browser plays it)
  GET /api/media/{job_id}/download  -> Content-Disposition: attachment  (browser saves it)

Both support HTTP Range (206 Partial Content), so seeking works.

HOW TO HOOK IT UP (only one function to edit):
  Edit get_job_file() below so it returns the Path of the finished,
  normalized MP4 for that job_id (the file your pipeline produced after
  the ffmpeg faststart step). Return None if the job isn't ready.

Then in your main app:
  from app.api.media_routes import router as media_router
  app.include_router(media_router)
"""

import mimetypes
import re
from pathlib import Path
from typing import Iterator, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

router = APIRouter()

CHUNK_SIZE = 1024 * 512  # 512 KB


# --------------------------------------------------------------------------
# EDIT THIS ONE FUNCTION
# --------------------------------------------------------------------------
def get_job_file(job_id: str) -> Optional[Path]:
    """
    Return the Path of the finished video file for this job, or None.
    """
    from app.services.downloader import download_manager
    from app.services.media_pipeline import media_pipeline
    import logging
    _log = logging.getLogger("mediagrab.media_routes")
    job = download_manager.jobs.get(job_id)
    if not job:
        job = media_pipeline.jobs.get(job_id)

    if job:
        status = getattr(job, "status", None)
        stage = getattr(job, "stage", None)
        if status in ("ready", "completed") or stage in ("ready", "completed"):
            if getattr(job, "output_path", None):
                p = Path(job.output_path)
                if p.is_file():
                    return p
            if getattr(job, "download_token", None):
                from app.services.storage_manager import storage_manager
                record = storage_manager.downloads_meta.get(job.download_token)
                if record and "filepath" in record:
                    p = Path(record["filepath"])
                    if p.is_file():
                        return p
            if getattr(job, "token", None):
                from app.config import settings
                p = settings.STORAGE_DIR / f"{job.token}.mp4"
                if p.is_file():
                    return p

    from app.config import settings
    direct_p = settings.STORAGE_DIR / f"{job_id}.mp4"
    if direct_p.is_file():
        return direct_p
    return None


def get_download_name(job_id: str, path: Path) -> str:
    """Filename shown in the browser's Save dialog. Edit if you store titles."""
    from app.services.downloader import download_manager
    job = download_manager.jobs.get(job_id)
    if job and getattr(job, "filename", None):
        return job.filename
    return path.name


# --------------------------------------------------------------------------
# Range handling
# --------------------------------------------------------------------------
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def parse_range(header: str, size: int) -> Optional[Tuple[int, int]]:
    """
    Parse a single 'bytes=start-end' header.
    Returns (start, end) inclusive, or None if the header is invalid/unsatisfiable.
    """
    m = _RANGE_RE.match(header.strip())
    if not m:
        return None
    start_s, end_s = m.groups()
    if start_s == "" and end_s == "":
        return None
    if start_s == "":  # suffix range: last N bytes
        length = int(end_s)
        if length == 0:
            return None
        start = max(size - length, 0)
        end = size - 1
    else:
        start = int(start_s)
        end = int(end_s) if end_s != "" else size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        return None
    return start, end


def iter_file(path: Path, start: int, end: int) -> Iterator[bytes]:
    remaining = end - start + 1
    with open(path, "rb") as f:
        f.seek(start)
        while remaining > 0:
            chunk = f.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def content_type_for(path: Path) -> str:
    if path.suffix.lower() == ".mp4":
        return "video/mp4"
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def build_response(request: Request, path: Path, disposition: str, filename: str) -> Response:
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found or expired")

    size = path.stat().st_size
    ctype = content_type_for(path)

    # RFC 5987 filename so non-ASCII titles don't break the header
    safe_ascii = re.sub(r'[^A-Za-z0-9._-]+', "_", filename) or "video.mp4"
    cd = f"{disposition}; filename=\"{safe_ascii}\"; filename*=UTF-8''{quote(filename)}"

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": cd,
        "Cache-Control": "private, max-age=0, must-revalidate",
        "X-Content-Type-Options": "nosniff",
    }

    range_header = request.headers.get("range")

    # No Range header -> full file
    if not range_header:
        headers["Content-Length"] = str(size)
        if request.method == "HEAD":
            return Response(status_code=200, headers={**headers, "Content-Type": ctype})
        return StreamingResponse(
            iter_file(path, 0, size - 1),
            status_code=200,
            media_type=ctype,
            headers=headers,
        )

    # Range header -> partial content
    rng = parse_range(range_header, size)
    if rng is None:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"},
        )

    start, end = rng
    length = end - start + 1
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(length)

    if request.method == "HEAD":
        return Response(status_code=206, headers={**headers, "Content-Type": ctype})

    return StreamingResponse(
        iter_file(path, start, end),
        status_code=206,
        media_type=ctype,
        headers=headers,
    )


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@router.api_route("/api/media/{job_id}/play", methods=["GET", "HEAD"])
async def play(job_id: str, request: Request):
    """INLINE: the browser plays this in a <video> tag. It must never force a download."""
    path = get_job_file(job_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Video not ready")
    return build_response(request, path, "inline", get_download_name(job_id, path))


@router.api_route("/api/media/{job_id}/download", methods=["GET", "HEAD"])
async def download(job_id: str, request: Request):
    """ATTACHMENT: the browser saves this file."""
    path = get_job_file(job_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Video not ready")
    return build_response(request, path, "attachment", get_download_name(job_id, path))
