import os
import sys
import re
import time
import uuid
import asyncio
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

from ..config import settings
from ..security.sanitizer import (
    generate_storage_key,
    sanitize_download_filename,
    sanitize_error_message,
    sanitize_for_logging,
)
from ..security.sandbox import build_sandboxed_ytdlp_args, get_sandboxed_environment
from ..security.ssrf_validator import validate_url_ssrf, safe_http_request
from ..security.rate_limiter import concurrent_jobs_tracker
from .storage_manager import storage_manager

logger = logging.getLogger("mediagrab.pipeline")

# Progress regex patterns for yt-dlp output
PROGRESS_PIPE_REGEX = re.compile(r'\[PROGRESS\]\|([^|]+)\|([^|]+)\|([^|]+)')
GENERIC_PROGRESS_REGEX = re.compile(r'\[download\]\s+([0-9\.]+)%\s+of\s+~?([0-9\.]+\w+)\s+at\s+([0-9\.]+\w+/s)\s+ETA\s+([0-9:]+)')


def probe_codecs(file_path: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    Probes video and audio codecs of a media file using FFmpeg.
    Returns (vcodec, acodec), e.g. ('h264', 'aac') or ('vp9', 'opus').
    """
    if not settings.FFMPEG_LOCATION or not os.path.exists(settings.FFMPEG_LOCATION):
        return None, None

    cmd = [settings.FFMPEG_LOCATION, "-i", str(file_path)]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=10)
    except Exception as e:
        logger.warning(f"Failed to probe codecs for {file_path}: {e}")
        return None, None

    vcodec = None
    acodec = None
    for line in res.stderr.splitlines():
        line_clean = line.strip()
        if "Stream #" in line_clean:
            if "Video:" in line_clean and not vcodec:
                part = line_clean.split("Video:", 1)[1].strip()
                vcodec = part.split()[0].rstrip(",").lower()
            elif "Audio:" in line_clean and not acodec:
                part = line_clean.split("Audio:", 1)[1].strip()
                acodec = part.split()[0].rstrip(",").lower()

    return vcodec, acodec


def normalize_to_mp4_faststart(src_path: Path, dst_path: Path) -> Path:
    """
    Normalizes any media file into H.264 + AAC in an MP4 container with -movflags +faststart.
    If the source already uses H.264 and AAC, streams are copied (-c copy) with zero re-encoding
    to save CPU and finish in milliseconds.
    """
    vcodec, acodec = probe_codecs(src_path)
    logger.info(f"Normalizing {src_path.name} -> {dst_path.name} (detected vcodec={vcodec}, acodec={acodec})")

    is_h264 = vcodec in ("h264", "avc1")
    is_aac = acodec in ("aac", "mp4a") or acodec is None

    cmd = [settings.FFMPEG_LOCATION, "-y", "-i", str(src_path)]

    if is_h264 and is_aac:
        # Stream copy: ultra fast and zero CPU re-encoding
        logger.info(f"File {src_path.name} is already H.264/AAC. Using stream copy.")
        cmd.extend(["-c", "copy"])
    else:
        # Re-encode non-compliant streams
        logger.info(f"Re-encoding {src_path.name} to H.264/AAC (vcodec={vcodec}, acodec={acodec}).")
        if not is_h264:
            cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p"])
        else:
            cmd.extend(["-c:v", "copy"])

        if not is_aac:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])

    cmd.extend(["-movflags", "+faststart", str(dst_path)])

    res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=300)
    if res.returncode != 0:
        err_snippet = res.stderr[-500:] if res.stderr else "Unknown FFmpeg error"
        raise RuntimeError(f"FFmpeg faststart normalization failed: {err_snippet}")

    if not dst_path.exists() or dst_path.stat().st_size == 0:
        raise RuntimeError("Normalized output file was empty or missing.")

    return dst_path


class MediaPrepareJob:
    """
    Represents the unified preparation job for a media file (for both playback & download).
    Tracks stages: resolving -> downloading -> preparing -> ready (or failed).
    """
    def __init__(
        self,
        job_id: str,
        url: str,
        client_ip: str,
        quality_label: str = "Best",
        format_id: Optional[str] = None,
        height: Optional[int] = None,
        is_audio_only: bool = False,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ):
        self.job_id = job_id
        self.id = job_id
        self.url = url
        self.client_ip = client_ip
        self.quality_label = quality_label
        self.format_id = format_id
        self.height = height
        self.is_audio_only = is_audio_only
        self.start_time = start_time
        self.end_time = end_time

        # Stages: resolving, downloading, preparing, ready, failed
        self.stage = "resolving"
        self.progress_percent = 0.0
        self.speed = "0 KB/s"
        self.eta = "--:--"
        self.error_message: Optional[str] = None
        self.output_path: Optional[str] = None
        self.error_class: Optional[str] = None
        self.user_message: Optional[str] = None
        self.debug: Optional[str] = None

        self.token: Optional[str] = None
        self.stream_url: Optional[str] = None
        self.download_url: Optional[str] = None
        self.filename: Optional[str] = None
        self.filesize: Optional[int] = None
        self.duration_seconds: Optional[float] = None
        self.title: Optional[str] = None

        self.created_at = time.time()
        self.event_notify = asyncio.Event()
        self.process = None
        self.is_cancelled = False

    def update_stage(self, stage: str, percent: float = 0.0, speed: str = "0 KB/s", eta: str = "--:--"):
        self.stage = stage
        self.progress_percent = round(percent, 1)
        self.speed = speed.strip() if speed else self.speed
        self.eta = eta.strip() if eta else self.eta
        self.event_notify.set()
        self.event_notify.clear()

    def update_progress(self, percent: float, speed: str, eta: str):
        self.progress_percent = round(percent, 1)
        self.speed = speed.strip() if speed else self.speed
        self.eta = eta.strip() if eta else self.eta
        self.event_notify.set()
        self.event_notify.clear()

    def set_ready(
        self,
        token: str,
        filename: str,
        filesize: int,
        stream_url: str,
        download_url: str,
        title: Optional[str] = None,
        duration_seconds: Optional[float] = None,
    ):
        self.stage = "ready"
        self.status = "ready"
        self.progress_percent = 100.0
        self.speed = "Complete"
        self.eta = "00:00"
        self.token = token
        self.filename = filename
        self.filesize = filesize
        self.stream_url = stream_url
        self.download_url = download_url
        self.title = title or self.title
        self.duration_seconds = duration_seconds
        self.event_notify.set()

    def set_failed(self, error: str, cls=None, debug: Optional[str] = None):
        from ..resilience.media_errors import classify_error, user_message
        self.stage = "failed"
        classified_cls = cls or classify_error(error)
        self.error_class = classified_cls.value if hasattr(classified_cls, "value") else str(classified_cls)
        msg = user_message(classified_cls)
        self.user_message = msg
        self.error_message = msg
        self.debug = "\n".join((debug or error or "").splitlines()[-30:])
        self.event_notify.set()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "id": self.job_id,
            "stage": self.stage,
            "status": self.stage,
            "progress_percent": self.progress_percent,
            "speed": self.speed,
            "eta": self.eta,
            "error_message": self.error_message,
            "token": self.token,
            "stream_url": self.stream_url,
            "download_url": self.download_url,
            "filename": self.filename,
            "filesize": self.filesize,
            "title": self.title,
            "quality_label": self.quality_label,
            "duration_seconds": self.duration_seconds,
            "output_path": self.output_path,
            "error_class": self.error_class,
            "user_message": self.user_message,
            "debug": self.debug,
        }


class MediaPipelineManager:
    """
    Single unified pipeline for MediaGrab AI playback and download.
    1. Resolve & check cache
    2. Download to server with yt-dlp (merging separate video+audio streams with ffmpeg)
    3. Normalize to H.264 + AAC in MP4 with -movflags +faststart
    4. Store under random UUID with TTL auto-delete
    5. Serve finished static file with HTTP 206 Range support
    6. Play (<video src>) and Download (?download=1) from one file
    """
    def __init__(self):
        self.jobs: Dict[str, MediaPrepareJob] = {}
        self.cache: Dict[str, str] = {}  # cache_key -> token
        self._lock = asyncio.Lock()

    def _make_cache_key(self, url: str, quality_label: str, height: Optional[int]) -> str:
        h_str = str(height) if height else quality_label.lower()
        return f"{url.strip()}::{h_str}"

    async def get_or_create_job(
        self,
        url: str,
        client_ip: str,
        quality_label: str = "Best",
        format_id: Optional[str] = None,
        height: Optional[int] = None,
        is_audio_only: bool = False,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> MediaPrepareJob:
        cache_key = self._make_cache_key(url, quality_label, height)

        # Check existing active or completed job for this key
        async with self._lock:
            # Check if we already have a cached completed token
            cached_token = self.cache.get(cache_key)
            if cached_token:
                rec = await storage_manager.get_download(cached_token)
                if rec and Path(rec["filepath"]).exists():
                    # Create instantly completed job
                    instant_job = MediaPrepareJob(
                        job_id=uuid.uuid4().hex,
                        url=url,
                        client_ip=client_ip,
                        quality_label=quality_label,
                        format_id=format_id,
                        height=height,
                        is_audio_only=is_audio_only,
                    )
                    instant_job.set_ready(
                        token=cached_token,
                        filename=rec["filename"],
                        filesize=rec["filesize"],
                        stream_url=f"/api/stream/{cached_token}",
                        download_url=f"/api/stream/{cached_token}?download=1",
                    )
                    self.jobs[instant_job.job_id] = instant_job
                    return instant_job

            # Otherwise create a new background job
            job_id = uuid.uuid4().hex
            job = MediaPrepareJob(
                job_id=job_id,
                url=url,
                client_ip=client_ip,
                quality_label=quality_label,
                format_id=format_id,
                height=height,
                is_audio_only=is_audio_only,
                start_time=start_time,
                end_time=end_time,
            )
            self.jobs[job_id] = job

        # Spawn pipeline worker
        asyncio.create_task(self._execute_pipeline(job, cache_key))
        return job

    async def get_job(self, job_id: str) -> Optional[MediaPrepareJob]:
        async with self._lock:
            return self.jobs.get(job_id)

    async def cancel_job(self, job_id: str) -> bool:
        async with self._lock:
            job = self.jobs.get(job_id)
            if not job or job.stage in ("ready", "failed"):
                return False
            job.is_cancelled = True
            job.set_failed("Preparation cancelled by user.")
            if job.process and job.process.returncode is None:
                try:
                    job.process.kill()
                except Exception:
                    pass
            return True

    async def _execute_pipeline(self, job: MediaPrepareJob, cache_key: str):
        # Concurrency limit per IP
        acquired = await concurrent_jobs_tracker.acquire(job.client_ip)
        if not acquired:
            job.set_failed("Concurrent preparation limit reached. Please wait for previous job to finish.")
            return

        try:
            # Stage 1: Resolving & SSRF Verification
            job.update_stage("resolving", percent=5.0, speed="Verifying...", eta="--:--")
            is_valid, clean_url, ssrf_err = validate_url_ssrf(job.url)
            if not is_valid:
                job.set_failed(f"Security validation blocked: {ssrf_err}")
                return

            # Check if direct media file or yt-dlp source
            if job.format_id and job.format_id.startswith("direct"):
                await self._process_direct_stream(job, clean_url, cache_key)
            else:
                await self._process_ytdlp_stream(job, clean_url, cache_key)

        except Exception as e:
            logger.exception(f"Pipeline failed for job {job.job_id}: {e}")
            job.set_failed(f"Processing failed: {sanitize_error_message(e)}")
        finally:
            await concurrent_jobs_tracker.release(job.client_ip)

    async def _process_ytdlp_stream(self, job: MediaPrepareJob, url: str, cache_key: str):
        """
        Downloads target format with yt-dlp, merges audio and video streams with FFmpeg,
        then normalizes to H.264 + AAC with -movflags +faststart.
        """
        # Stage 2: Downloading
        job.update_stage("downloading", percent=10.0, speed="Connecting to source...", eta="--:--")

        raw_base = f"raw_{uuid.uuid4().hex}"
        raw_template = str(settings.STORAGE_DIR / f"{raw_base}.%(ext)s")

        target_height = None
        if job.height and isinstance(job.height, int) and job.height > 0:
            target_height = job.height
        elif job.format_id and job.format_id.endswith("p") and job.format_id[:-1].isdigit():
            target_height = int(job.format_id[:-1])
        elif job.quality_label and "p" in job.quality_label:
            m_h = re.search(r'(\d+)p', job.quality_label)
            if m_h:
                target_height = int(m_h.group(1))

        # Build format selector to merge video + audio with strict original language preference
        audio_spec = (
            "bestaudio[language_preference>=0][acodec^=mp4a]/"
            "bestaudio[language_preference>=0]/"
            "bestaudio[acodec^=mp4a]/"
            "bestaudio/best"
        )

        if job.is_audio_only:
            format_selector = audio_spec
            extra_args = [
                "-x",
                "--audio-format", "m4a",
            ]
        elif target_height:
            # Request genuine target resolution (e.g. 1080p, 720p, 480p, 2160p) with preference for H.264/AAC for instant stream-copy
            format_selector = (
                f"bestvideo[height<={target_height}][vcodec^=avc1]+{audio_spec}/"
                f"bestvideo[height<={target_height}]+{audio_spec}/"
                f"best[height<={target_height}]/best"
            )
            extra_args = [
                "--merge-output-format", "mp4"
            ]
        elif job.format_id and job.format_id not in ("best", "auto") and job.format_id.isdigit():
            # Specific numeric format ID selected, merge with original audio
            format_selector = f"{job.format_id}+{audio_spec}"
            extra_args = [
                "--merge-output-format", "mp4"
            ]
        else:
            format_selector = (
                f"bestvideo[height<=1080][vcodec^=avc1]+{audio_spec}/"
                f"bestvideo[height<=1080]+{audio_spec}/"
                "best[height<=1080]/best"
            )
            extra_args = [
                "--merge-output-format", "mp4"
            ]

        # Trimming support
        if job.start_time or job.end_time:
            st = job.start_time.strip() if job.start_time else "0"
            et = job.end_time.strip() if job.end_time else "inf"
            extra_args.extend([
                "--download-sections", f"*{st}-{et}",
                "--force-keyframes-at-cuts"
            ])

        cmd_args = build_sandboxed_ytdlp_args(
            target_url=url,
            output_template=raw_template,
            format_selector=format_selector,
            is_metadata_only=False,
            extra_safe_args=extra_args,
        )

        clean_env = get_sandboxed_environment()
        proc = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(settings.STORAGE_DIR),
            env=clean_env,
        )
        job.process = proc

        async def read_stdout():
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()

                # Parse custom pipe delimited progress: download:[PROGRESS]|pct|speed|eta
                if "[PROGRESS]|" in line:
                    parts = line.strip().split("|")
                    if len(parts) >= 4:
                        clean_parts = [re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', p).strip() for p in parts]
                        pct_raw = clean_parts[1].replace("%", "").strip()
                        speed_raw = clean_parts[2].strip()
                        eta_raw = clean_parts[3].strip()
                        try:
                            pct = float(pct_raw)
                        except ValueError:
                            pct = job.progress_percent
                        clean_speed = speed_raw if speed_raw and speed_raw.lower() not in ("unknown", "na", "none", "") else job.speed
                        clean_eta = eta_raw if eta_raw and eta_raw.lower() not in ("unknown", "na", "none", "") else job.eta
                        job.update_progress(min(95.0, pct), clean_speed, clean_eta)
                        continue

                # Fallback to generic progress regex
                clean_generic = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line)
                m = GENERIC_PROGRESS_REGEX.search(clean_generic)
                if m:
                    pct = float(m.group(1))
                    speed = m.group(3).strip()
                    eta = m.group(4).strip()
                    job.update_progress(min(95.0, pct), speed, eta)
                    continue

                if "[Merger]" in line or "ffmpeg" in line.lower() or "postprocessing" in line.lower():
                    job.update_stage("preparing", percent=96.0, speed="Merging audio+video streams...", eta="--:--")

        stdout_task = asyncio.create_task(read_stdout())

        try:
            _, stderr_bytes = await asyncio.wait_for(
                asyncio.gather(proc.wait(), proc.stderr.read()),
                timeout=settings.DOWNLOAD_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            try:
                proc.terminate()
                await asyncio.sleep(0.5)
                proc.kill()
            except Exception:
                pass
            job.set_failed("Download timed out after exceeding allocation.")
            return
        finally:
            if not stdout_task.done():
                stdout_task.cancel()

        if proc.returncode != 0:
            stderr_str = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
            job.set_failed(f"Stream download failed: {stderr_str[:300]}")
            return

        # Locate downloaded raw file
        matching = list(settings.STORAGE_DIR.glob(f"{raw_base}.*"))
        if not matching:
            job.set_failed("Downloaded media file could not be located on server.")
            return

        raw_file = matching[0]

        # Stage 3: Validate and Normalize to H.264 + AAC in MP4 with faststart
        job.update_stage("preparing", percent=97.0, speed="Normalizing H.264/AAC with faststart...", eta="--:--")

        token = uuid.uuid4().hex
        final_filename = f"{token}.mp4"
        final_path = settings.STORAGE_DIR / final_filename

        from .media_validator import validate_download, MediaValidationError
        from .media_normalizer import normalize_to_mp4, NormalizeError
        from ..resilience.media_errors import classify_error

        try:
            await asyncio.to_thread(validate_download, raw_file)
            await asyncio.to_thread(normalize_to_mp4, raw_file, final_path)
        except MediaValidationError as e:
            cls = classify_error(f"{e.code}: {e.detail}", tiers_found_media=True)
            job.set_failed(f"{e.code}: {e.detail}", cls=cls, debug=e.detail)
            return
        except NormalizeError as e:
            cls = classify_error(e.stderr_tail, tiers_found_media=True)
            job.set_failed(e.stderr_tail, cls=cls, debug=e.stderr_tail)
            return
        except Exception as e:
            cls = classify_error(str(e), tiers_found_media=True)
            job.set_failed(str(e), cls=cls, debug=str(e))
            return
        finally:
            raw_file.unlink(missing_ok=True)

        job.output_path = str(final_path)

        # Stage 4: Ready
        filesize = final_path.stat().st_size
        safe_title = sanitize_download_filename(f"mediagrab_{job.quality_label}", "mp4")

        rec = await storage_manager.register_download(
            token=token,
            storage_key=final_filename,
            original_title=safe_title,
            extension="mp4",
            filesize=filesize,
            client_ip=job.client_ip,
        )

        stream_url = f"/api/media/{job.job_id}/play"
        download_url = f"/api/media/{job.job_id}/download"

        async with self._lock:
            self.cache[cache_key] = token

        job.set_ready(
            token=token,
            filename=rec["filename"],
            filesize=filesize,
            stream_url=stream_url,
            download_url=download_url,
        )
        logger.info(f"Pipeline completed successfully: job {job.job_id} -> {final_filename} ({filesize} bytes)")

    async def _process_direct_stream(self, job: MediaPrepareJob, url: str, cache_key: str):
        """
        Handles direct media URLs (e.g. mp4, webm direct links).
        Streams chunk-by-chunk to raw file, then normalizes with faststart.
        """
        from .downloader import download_direct
        from .job_finalize import run_with_one_retry
        from ..security.ssrf_validator import create_safe_client
        from .media_validator import validate_download, MediaValidationError
        from .media_normalizer import normalize_to_mp4, NormalizeError
        from ..resilience.media_errors import classify_error, ErrorClass

        headers = {"User-Agent": "MediaGrabAI-Bot/1.0"}

        is_hls = (job.format_id == "direct_hls") or ("m3u8" in url.lower())

        async def attempt_fn(j):
            token = uuid.uuid4().hex
            final_filename = f"{token}.mp4"
            final_path = settings.STORAGE_DIR / final_filename

            if is_hls:
                j.update_stage("downloading", percent=30.0, speed="Downloading HLS stream via FFmpeg...", eta="--:--")

                if j.height:
                    cmd = [
                        settings.FFMPEG_LOCATION, "-y",
                        "-headers", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36\r\n",
                        "-i", url,
                        "-vf", f"scale=-2:min(ih\\,{j.height})",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                        "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart",
                        str(final_path)
                    ]
                else:
                    cmd = [
                        settings.FFMPEG_LOCATION, "-y",
                        "-headers", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36\r\n",
                        "-i", url,
                        "-c", "copy",
                        "-movflags", "+faststart",
                        str(final_path)
                    ]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(settings.STORAGE_DIR),
                )
                j.process = proc
                _, stderr_bytes = await asyncio.wait_for(
                    asyncio.gather(proc.wait(), proc.stderr.read()),
                    timeout=settings.DOWNLOAD_TIMEOUT_SECONDS,
                )
                if proc.returncode != 0 or not final_path.exists() or final_path.stat().st_size == 0:
                    # Retry with transcode fallback
                    cmd_reencode = [
                        settings.FFMPEG_LOCATION, "-y",
                        "-headers", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36\r\n",
                        "-i", url,
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                        "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart",
                        str(final_path)
                    ]
                    proc2 = await asyncio.create_subprocess_exec(
                        *cmd_reencode,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(settings.STORAGE_DIR),
                    )
                    j.process = proc2
                    _, stderr2 = await asyncio.wait_for(
                        asyncio.gather(proc2.wait(), proc2.stderr.read()),
                        timeout=settings.DOWNLOAD_TIMEOUT_SECONDS,
                    )
                    if proc2.returncode != 0 or not final_path.exists() or final_path.stat().st_size == 0:
                        err_str = stderr2.decode("utf-8", errors="replace") if stderr2 else "HLS download failed"
                        j.set_failed(f"HLS download failed: {err_str[:200]}")
                        return
            else:
                j.update_stage("downloading", percent=5.0, speed="Connecting to direct stream...", eta="--:--")
                raw_token = f"raw_{uuid.uuid4().hex}.tmp"
                raw_path = settings.STORAGE_DIR / raw_token

                async with create_safe_client(url) as client:
                    meta = await download_direct(client, url, raw_path, headers)
                    if not meta["complete"]:
                        raw_path.unlink(missing_ok=True)
                        j.set_failed("Download incomplete", cls=ErrorClass.DOWNLOAD_INCOMPLETE, debug=meta["debug"])
                        return

                    # Normalize to H.264 + AAC + faststart
                    j.update_stage("preparing", percent=97.0, speed="Normalizing H.264/AAC with faststart...", eta="--:--")

                    try:
                        # Do NOT pass expected_length here: transfer_complete already checked it
                        await asyncio.to_thread(
                            validate_download,
                            raw_path,
                            content_type=meta["content_type"],
                            status_code=meta["status_code"],
                        )
                        await asyncio.to_thread(normalize_to_mp4, raw_path, final_path, target_height=j.height)
                    except MediaValidationError as e:
                        cls = classify_error(f"{e.code}: {e.detail}", tiers_found_media=True)
                        j.set_failed(f"{e.code}: {e.detail}", cls=cls, debug=e.detail)
                        return
                    except NormalizeError as e:
                        cls = classify_error(e.stderr_tail, tiers_found_media=True)
                        j.set_failed(e.stderr_tail, cls=cls, debug=e.stderr_tail)
                        return
                    except Exception as e:
                        cls = classify_error(str(e), tiers_found_media=True)
                        j.set_failed(str(e), cls=cls, debug=str(e))
                        return
                    finally:
                        raw_path.unlink(missing_ok=True)

            j.output_path = str(final_path)
            filesize = final_path.stat().st_size
            safe_title = sanitize_download_filename(f"mediagrab_direct", "mp4")

            rec = await storage_manager.register_download(
                token=token,
                storage_key=final_filename,
                original_title=safe_title,
                extension="mp4",
                filesize=filesize,
                client_ip=j.client_ip,
            )

            stream_url = f"/api/media/{j.job_id}/play"
            download_url = f"/api/media/{j.job_id}/download"

            async with self._lock:
                self.cache[cache_key] = token

            j.set_ready(
                token=token,
                filename=rec["filename"],
                filesize=filesize,
                stream_url=stream_url,
                download_url=download_url,
            )

        await run_with_one_retry(job, attempt_fn)


media_pipeline = MediaPipelineManager()
