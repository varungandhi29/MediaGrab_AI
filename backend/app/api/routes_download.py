import os
import json
import asyncio
from pathlib import Path
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse, FileResponse
from ..models.schemas import DownloadRequest, DownloadJobResponse
from ..security.rate_limiter import check_download_rate_limit, get_client_ip
from ..security.sanitizer import sanitize_for_logging
from ..services.downloader import download_manager
from ..services.storage_manager import storage_manager

router = APIRouter(prefix="/api/download", tags=["download"])


@router.post(
    "",
    response_model=DownloadJobResponse,
    dependencies=[Depends(check_download_rate_limit)],
    summary="Initiate a background media download"
)
async def start_download(payload: DownloadRequest, request: Request):
    client_ip = get_client_ip(request)
    job = await download_manager.create_job(
        url=payload.url,
        client_ip=client_ip,
        quality_label=payload.quality_label,
        format_id=payload.format_id,
        is_audio_only=payload.is_audio_only,
        target_format=payload.target_format,
        start_time=payload.start_time,
        end_time=payload.end_time,
    )
    return job.to_dict()


@router.get("/status/{job_id}", response_model=DownloadJobResponse)
async def get_download_status(job_id: str):
    job = await download_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job.to_dict()


@router.get("/progress/{job_id}")
async def stream_download_progress(job_id: str):
    """
    Server-Sent Events (SSE) endpoint providing live progress updates.
    """
    job = await download_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    async def event_generator() -> AsyncGenerator[str, None]:
        # Send initial state immediately
        yield f"data: {json.dumps(job.to_dict())}\n\n"

        while True:
            if job.status in ("completed", "failed"):
                yield f"data: {json.dumps(job.to_dict())}\n\n"
                break

            # Wait for update event or periodic heartbeat
            try:
                await asyncio.wait_for(job.event_notify.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

            yield f"data: {json.dumps(job.to_dict())}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/file/{token}")
async def serve_downloaded_file(token: str):
    """
    Secure file streaming endpoint. Streams large files in chunks without memory buffering.
    Applies strict Content-Disposition and sandboxed filename.
    """
    record = await storage_manager.get_download(token)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download token is invalid or has expired."
        )

    filepath = Path(record["filepath"])
    if not filepath.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media file is no longer available on disk."
        )

    # Determine MIME type
    ext = record.get("extension", "mp4").lower()
    content_types = {
        "mp4": "video/mp4",
        "webm": "video/webm",
        "mov": "video/quicktime",
        "mkv": "video/x-matroska",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
        "m4a": "audio/mp4",
    }
    media_type = content_types.get(ext, "application/octet-stream")
    safe_filename = record.get("filename", f"mediagrab_download.{ext}")

    def iterfile():
        # Stream 128KB chunks rather than loading entire file into RAM
        with open(filepath, mode="rb") as file_like:
            while chunk := file_like.read(131072):
                yield chunk

    headers = {
        "Content-Disposition": f'attachment; filename="{safe_filename}"',
        "Content-Length": str(record["filesize"]),
        "X-Content-Type-Options": "nosniff",
    }

    return StreamingResponse(
        iterfile(),
        media_type=media_type,
        headers=headers,
    )
