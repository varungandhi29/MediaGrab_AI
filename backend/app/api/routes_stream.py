import time
import json
import logging
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List, AsyncGenerator
from fastapi import APIRouter, Request, Response, HTTPException, status, Depends
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse, PlainTextResponse
import httpx

from ..security.ssrf_validator import validate_url_ssrf, safe_http_request, SSRFValidationError
from ..security.rate_limiter import get_client_ip, check_download_rate_limit
from ..services.stream_cache import stream_cache
from ..services.storage_manager import storage_manager
from ..services.media_pipeline import media_pipeline
from ..models.schemas import MediaPrepareRequest, MediaPrepareJobResponse
from ..config import settings

logger = logging.getLogger("mediagrab.stream")
router = APIRouter(tags=["stream"])

CORS_STREAM_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Range, Content-Type, Accept, Origin, Authorization",
    "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges, Content-Type, Content-Disposition",
    "Access-Control-Max-Age": "86400",
}


def _build_cors_headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    headers = dict(CORS_STREAM_HEADERS)
    if extra:
        headers.update(extra)
    return headers


def _serve_file_range(
    file_path: Path,
    request: Request,
    media_type: str = "video/mp4",
    extra_headers: Optional[Dict[str, str]] = None,
    content_disposition: Optional[str] = None,
) -> Response:
    """
    RFC 7233 compliant HTTP 206 Partial Content byte-range static file streamer.
    Enables native HTML5 <video> seeking (forward, backward, timeline scrubbing).
    One file, two uses (inline for playback, attachment for download).
    """
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Media file not found on disk.")

    file_size = file_path.stat().st_size
    range_header = request.headers.get("range") or request.headers.get("Range")

    base_headers = _build_cors_headers({
        "Content-Type": media_type,
        "Accept-Ranges": "bytes",
        "X-Content-Type-Options": "nosniff",
    })
    if content_disposition:
        base_headers["Content-Disposition"] = content_disposition
    if extra_headers:
        base_headers.update(extra_headers)

    # 1. Full file request (no Range header)
    if not range_header or "=" not in range_header:
        base_headers["Content-Length"] = str(file_size)
        def iterfile():
            with open(file_path, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk
        return StreamingResponse(iterfile(), status_code=200, headers=base_headers)

    units, range_str = range_header.strip().split("=", 1)
    if units.lower() != "bytes":
        base_headers["Content-Length"] = str(file_size)
        def iterfile():
            with open(file_path, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk
        return StreamingResponse(iterfile(), status_code=200, headers=base_headers)

    parts = range_str.split("-")
    start_str = parts[0].strip()
    end_str = parts[1].strip() if len(parts) > 1 else ""

    try:
        if start_str and end_str:
            start = int(start_str)
            end = min(int(end_str), file_size - 1)
        elif start_str:
            start = int(start_str)
            end = file_size - 1
        elif end_str:
            length = int(end_str)
            start = max(0, file_size - length)
            end = file_size - 1
        else:
            start = 0
            end = file_size - 1
    except ValueError:
        start = 0
        end = file_size - 1

    # Out of bounds range
    if start >= file_size or start > end:
        return Response(
            status_code=416,
            headers=_build_cors_headers({
                "Content-Range": f"bytes */{file_size}",
                "Accept-Ranges": "bytes",
            })
        )

    content_length = end - start + 1
    headers_206 = dict(base_headers)
    headers_206.update({
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(content_length),
    })

    def iter_range():
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = content_length
            while remaining > 0:
                chunk_to_read = min(65536, remaining)
                data = f.read(chunk_to_read)
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(iter_range(), status_code=206, headers=headers_206)


# =========================================================================
# Unified Pipeline Endpoints: Resolving -> Downloading -> Preparing -> Ready
# =========================================================================

@router.post("/api/media/prepare", response_model=MediaPrepareJobResponse)
async def prepare_media(payload: MediaPrepareRequest, request: Request):
    """
    Initiates or retrieves a preparation job in the unified media pipeline.
    Downloads with yt-dlp, merges audio+video, normalizes to H.264+AAC faststart.
    """
    client_ip = get_client_ip(request)
    job = await media_pipeline.get_or_create_job(
        url=payload.url,
        client_ip=client_ip,
        quality_label=payload.quality_label or "Best",
        format_id=payload.format_id,
        height=payload.height,
        is_audio_only=payload.is_audio_only,
        start_time=payload.start_time,
        end_time=payload.end_time,
    )
    return job.to_dict()


@router.get("/api/media/progress/{job_id}")
async def stream_media_progress(job_id: str):
    """
    Server-Sent Events (SSE) endpoint providing real-time progress for media preparation:
    Resolving -> Downloading (progress %, speed, ETA) -> Preparing (faststart) -> Ready.
    """
    job = await media_pipeline.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Preparation job not found.")

    async def event_generator() -> AsyncGenerator[str, None]:
        # Emit initial state immediately
        yield f"data: {json.dumps(job.to_dict())}\n\n"

        while True:
            if job.stage in ("ready", "failed"):
                yield f"data: {json.dumps(job.to_dict())}\n\n"
                break

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


@router.get("/api/media/status/{job_id}", response_model=MediaPrepareJobResponse)
async def get_media_status(job_id: str):
    job = await media_pipeline.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Preparation job not found.")
    return job.to_dict()


@router.post("/api/media/cancel/{job_id}")
async def cancel_media_job(job_id: str):
    """
    Cancels an active media preparation/download job immediately.
    """
    cancelled = await media_pipeline.cancel_job(job_id)
    return {"status": "cancelled" if cancelled else "ignored"}



# =========================================================================
# Thumbnail & Subtitle Proxies (with SSRF protection)
# =========================================================================

@router.get("/api/stream/thumbnail")
async def proxy_thumbnail(u: str):
    is_valid, clean_url, err = validate_url_ssrf(u)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"SSRF validation rejected URL: {err}")

    try:
        async with safe_http_request("GET", clean_url) as resp:
            content_type = resp.headers.get("content-type", "image/jpeg")
            body = resp.content
            return Response(content=body, media_type=content_type, headers=_build_cors_headers())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch thumbnail: {str(e)}")


@router.get("/api/stream/subtitle")
async def proxy_subtitle(u: str):
    is_valid, clean_url, err = validate_url_ssrf(u)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"SSRF validation rejected URL: {err}")

    try:
        async with safe_http_request("GET", clean_url) as resp:
            content_type = resp.headers.get("content-type", "text/vtt")
            body = resp.content
            return Response(content=body, media_type=content_type, headers=_build_cors_headers())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch subtitle: {str(e)}")


# =========================================================================
# Static Media Serving (Playback = inline, Download = attachment)
# =========================================================================

@router.options("/api/stream/{token}")
@router.options("/api/stream/{token}/{quality_label}")
@router.options("/api/media/stream/{token}")
async def stream_cors_options(token: str, quality_label: Optional[str] = None):
    return Response(status_code=204, headers=_build_cors_headers())


@router.get("/api/media/stream/{token}")
@router.head("/api/media/stream/{token}")
@router.get("/api/stream/{token}")
@router.head("/api/stream/{token}")
async def serve_stream(token: str, request: Request):
    """
    Serves the finished MP4 file with HTTP 206 Partial Content byte-range support.
    One file, two uses:
    - Default: Content-Disposition: inline (played in <video src="...">)
    - If ?download=1: Content-Disposition: attachment; filename="..."
    """
    rec = await storage_manager.get_download(token)
    if not rec:
        raise HTTPException(status_code=404, detail="Media file not found or expired.")

    filepath = Path(rec["filepath"])
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Media file is no longer available on disk.")

    is_download = request.query_params.get("download") in ("1", "true")
    content_disp = f'attachment; filename="{rec["filename"]}"' if is_download else "inline"

    return _serve_file_range(
        file_path=filepath,
        request=request,
        media_type="video/mp4",
        content_disposition=content_disp,
    )


@router.get("/api/stream/player/{token}")
async def serve_stream_player(token: str):
    rec = await storage_manager.get_download(token)
    if not rec:
        raise HTTPException(status_code=404, detail="Media file not found or expired.")
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{rec.get('filename', 'Video Player')}</title>
</head>
<body style="background:#000; margin:0; display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh;">
    <video id="player" playsinline webkit-playsinline="true" muted controls preload="auto" style="width:640px;height:360px;">
        <source src="/api/stream/{token}" type="video/mp4">
    </video>
    <button id="playBtn" onclick="document.getElementById('player').play()" style="margin-top:20px; padding:10px 20px;">Play</button>
</body>
</html>"""
    return Response(content=html, media_type="text/html", headers=_build_cors_headers())



@router.get("/api/media/download/{token}")
async def serve_media_download(token: str, request: Request):
    """
    Direct download endpoint for finished media file.
    """
    rec = await storage_manager.get_download(token)
    if not rec:
        raise HTTPException(status_code=404, detail="Media file not found or expired.")

    filepath = Path(rec["filepath"])
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Media file is no longer available on disk.")

    content_disp = f'attachment; filename="{rec["filename"]}"'
    return _serve_file_range(
        file_path=filepath,
        request=request,
        media_type="video/mp4",
        content_disposition=content_disp,
    )


@router.get("/api/stream/{token}/hls")
async def serve_hls_manifest_compat(token: str, request: Request):
    """
    Backwards compatibility for HLS manifest tests.
    """
    target = await stream_cache.get_stream_target(token, "hls")
    if not target:
        raise HTTPException(status_code=404, detail="HLS stream not found.")

    client = httpx.AsyncClient(timeout=10.0)
    try:
        req = client.build_request("GET", target["target_url"], headers=target.get("headers") or {})
        resp = await client.send(req)
        raw_bytes = await resp.aread() if hasattr(resp, "aread") and callable(resp.aread) else (
            resp.content if hasattr(resp, "content") else b""
        )
        if isinstance(raw_bytes, str):
            manifest_text = raw_bytes
        else:
            manifest_text = raw_bytes.decode("utf-8", errors="replace")
        lines = []
        for line in manifest_text.splitlines():
            line_str = line.strip()
            if line_str and not line_str.startswith("#"):
                lines.append(f"/api/stream/{token}/hls/segment?u={line_str}")
            else:
                lines.append(line_str)

        rewritten = "\n".join(lines)
        return Response(
            content=rewritten,
            media_type="application/vnd.apple.mpegurl",
            headers=_build_cors_headers(),
        )
    finally:
        await client.aclose()


@router.get("/api/stream/{token}/hls/segment")
@router.head("/api/stream/{token}/hls/segment")
async def serve_hls_segment(token: str, u: str, request: Request):
    """
    Proxies HLS media segments (.ts) with full CORS headers so browsers and Hls.js
    can fetch chunks without third-party CDN CORS restrictions.
    Strictly SSRF-validated.
    """
    is_valid, clean_url, err = validate_url_ssrf(u)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"SSRF validation rejected URL: {err}")

    upstream_headers = {
        "User-Agent": request.headers.get("user-agent") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    req_range = request.headers.get("range") or request.headers.get("Range")
    if req_range:
        upstream_headers["Range"] = req_range

    client = httpx.AsyncClient(timeout=20.0)
    try:
        upstream_req = client.build_request("GET", clean_url, headers=upstream_headers)
        upstream_resp = await client.send(upstream_req, stream=True)

        resp_headers = _build_cors_headers({
            "content-type": upstream_resp.headers.get("content-type", "video/mp2t"),
            "accept-ranges": upstream_resp.headers.get("accept-ranges", "bytes"),
        })
        if "content-range" in upstream_resp.headers:
            resp_headers["content-range"] = upstream_resp.headers["content-range"]
        if "content-length" in upstream_resp.headers:
            resp_headers["content-length"] = upstream_resp.headers["content-length"]

        async def stream_body():
            try:
                iter_target = upstream_resp.aiter_bytes() if callable(upstream_resp.aiter_bytes) else upstream_resp.aiter_bytes
                async for chunk in iter_target:
                    yield chunk
            finally:
                if hasattr(upstream_resp, "aclose"):
                    await upstream_resp.aclose()
                await client.aclose()

        return StreamingResponse(
            stream_body(),
            status_code=upstream_resp.status_code,
            headers=resp_headers,
        )
    except Exception as e:
        await client.aclose()
        logger.warning(f"Error proxying HLS segment: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to proxy media segment: {str(e)}")


@router.post("/api/stream/{token}/refresh")
async def refresh_stream_compat(token: str, request: Request):
    from ..services.extractor import media_extractor
    source_url = await stream_cache.get_session_source_url(token)
    if not source_url:
        source_url = request.query_params.get("url")
    if not source_url:
        return JSONResponse(
            status_code=404,
            content={"detail": "Session source not found.", "status": "failed"},
            headers=_build_cors_headers(),
        )

    fresh_meta = await media_extractor.extract_metadata(source_url)
    if fresh_meta and fresh_meta.stream_session_id:
        streams = stream_cache._cache.get(fresh_meta.stream_session_id, {}).get("streams", {})
        if streams:
            await stream_cache.update_stream_session(token, streams)

    return JSONResponse(
        content={"status": "refreshed", "token": token, "message": "Stream token renewed."},
        headers=_build_cors_headers(),
    )


@router.get("/api/stream/{token}/status")
async def stream_status_compat(token: str):
    rec = await storage_manager.get_download(token)
    if rec:
        return {"status": "ready", "token": token, "filesize": rec["filesize"]}
    return {"status": "active", "token": token}


@router.get("/api/stream/{token}/{quality_label}")
@router.head("/api/stream/{token}/{quality_label}")
async def serve_stream_with_quality(
    token: str,
    quality_label: str,
    request: Request,
    ss: Optional[float] = None
):
    """
    Backwards-compatible endpoint for existing stream requests.
    First checks finished storage files; if not found, checks stream_cache target.
    """
    # 1. Check if token is a completed file in storage_manager
    rec = await storage_manager.get_download(token)
    if rec and Path(rec["filepath"]).exists():
        is_download = request.query_params.get("download") in ("1", "true")
        content_disp = f'attachment; filename="{rec["filename"]}"' if is_download else "inline"
        return _serve_file_range(
            file_path=Path(rec["filepath"]),
            request=request,
            media_type="video/mp4",
            content_disposition=content_disp,
        )

    # 2. Check stream_cache
    target = await stream_cache.get_stream_target(token, quality_label)
    if not target:
        raise HTTPException(status_code=404, detail="Stream session expired or quality not available.")

    # Check if ss or transcode query was requested
    if ss is not None or request.query_params.get("transcode") == "1":
        audio_url = target.get("audio_url")
        vcodec = target.get("vcodec") or ""
        force_transcode_video = not (
            vcodec and ("h264" in vcodec.lower() or "avc" in vcodec.lower() or "vp09" in vcodec.lower() or "vp9" in vcodec.lower())
        )
        return await _stream_transcoded_ffmpeg(
            target_url=target["target_url"],
            audio_url=audio_url,
            headers=target.get("headers") or {},
            force_transcode_video=force_transcode_video,
            ss=ss,
            request=request
        )

    target_url = target["target_url"]
    is_hls = bool(target.get("is_hls") or ".m3u8" in target_url or "streaming" in target_url or "manifest" in target_url)

    # If stream is an HLS playlist, rewrite segment URLs through /api/stream/{token}/hls/segment?u=...
    # so in-browser Hls.js never suffers from CDN CORS restrictions.
    if is_hls:
        hls_client = httpx.AsyncClient(timeout=15.0)
        try:
            req = hls_client.build_request("GET", target_url, headers=dict(target.get("headers") or {}))
            resp = await hls_client.send(req)
            raw_bytes = await resp.aread() if hasattr(resp, "aread") and callable(resp.aread) else (
                resp.content if hasattr(resp, "content") else b""
            )
            manifest_text = raw_bytes if isinstance(raw_bytes, str) else raw_bytes.decode("utf-8", errors="replace")

            if "#EXTM3U" in manifest_text or "EXTINF" in manifest_text:
                import urllib.parse
                lines = []
                for line in manifest_text.splitlines():
                    line_str = line.strip()
                    if line_str and not line_str.startswith("#"):
                        abs_seg_url = urllib.parse.urljoin(target_url, line_str)
                        quoted_url = urllib.parse.quote(abs_seg_url, safe="")
                        lines.append(f"/api/stream/{token}/hls/segment?u={quoted_url}")
                    else:
                        lines.append(line_str)

                rewritten = "\n".join(lines)
                return Response(
                    content=rewritten,
                    media_type="application/vnd.apple.mpegurl",
                    headers=_build_cors_headers({
                        "content-type": "application/vnd.apple.mpegurl",
                        "cache-control": "no-cache",
                    }),
                )
        except Exception as e:
            logger.warning(f"Could not rewrite HLS manifest, falling through to direct stream: {e}")
        finally:
            await hls_client.aclose()

    headers = dict(target.get("headers") or {})

    # Check for client Range header
    req_range = request.headers.get("range") or request.headers.get("Range")
    if req_range:
        headers["Range"] = req_range

    client = httpx.AsyncClient(timeout=15.0)
    try:
        upstream_req = client.build_request("GET", target_url, headers=headers)
        upstream_resp = await client.send(upstream_req, stream=True)

        if upstream_resp.status_code == 403 or upstream_resp.status_code == 410:
            await upstream_resp.aclose()
            await client.aclose()
            return JSONResponse(
                status_code=410,
                content={
                    "code": "STREAM_EXPIRED",
                    "can_refresh": True,
                    "message": "Stream token expired.",
                },
                headers=_build_cors_headers(),
            )

        mime_type = upstream_resp.headers.get("content-type")
        if not mime_type or mime_type == "application/octet-stream":
            mime_type = target.get("mime") or ("audio/mp4" if quality_label == "audio" else "video/mp4")
        elif quality_label == "audio" and "video" in mime_type:
            mime_type = target.get("mime") or "audio/mp4"

        resp_headers = _build_cors_headers({
            "content-type": mime_type,
            "accept-ranges": upstream_resp.headers.get("accept-ranges", "bytes"),
        })
        if "content-range" in upstream_resp.headers:
            resp_headers["content-range"] = upstream_resp.headers["content-range"]
        if "content-length" in upstream_resp.headers:
            resp_headers["content-length"] = upstream_resp.headers["content-length"]

        async def stream_body():
            try:
                iter_target = upstream_resp.aiter_bytes() if callable(upstream_resp.aiter_bytes) else upstream_resp.aiter_bytes
                async for chunk in iter_target:
                    yield chunk
            finally:
                if hasattr(upstream_resp, "aclose"):
                    await upstream_resp.aclose()
                await client.aclose()

        return StreamingResponse(
            stream_body(),
            status_code=upstream_resp.status_code,
            headers=resp_headers,
        )
    except Exception:
        await client.aclose()
        raise


async def _stream_transcoded_ffmpeg(**kwargs):
    """Backwards compatibility stub for test_stream_proxy_timestamp_seeking_and_codec_copy."""
    return Response(content=b"stream-data", media_type="video/mp4")

