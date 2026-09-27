import os
import sys
import re
import time
import uuid
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
import httpx

from ..config import settings
from ..security.sanitizer import (
    generate_storage_key,
    sanitize_download_filename,
    sanitize_error_message,
    sanitize_for_logging
)
from ..security.sandbox import build_sandboxed_ytdlp_args, get_sandboxed_environment
from ..security.ssrf_validator import validate_url_ssrf, safe_http_request
from ..security.rate_limiter import concurrent_jobs_tracker
from .storage_manager import storage_manager

PROGRESS_REGEX = re.compile(r'download:\[PROGRESS\]:([0-9\.]+)%:([^:]+):([0-9:]+)')
GENERIC_PROGRESS_REGEX = re.compile(r'\[download\]\s+([0-9\.]+)%\s+of\s+~?([0-9\.]+\w+)\s+at\s+([0-9\.]+\w+/s)\s+ETA\s+([0-9:]+)')


class DownloadJob:
    def __init__(self, job_id: str, url: str, client_ip: str, quality_label: str, format_id: str, is_audio_only: bool, target_format: str):
        self.job_id = job_id
        self.url = url
        self.client_ip = client_ip
        self.quality_label = quality_label
        self.format_id = format_id
        self.is_audio_only = is_audio_only
        self.target_format = target_format
        self.status = "pending"  # pending, downloading, converting, completed, failed
        self.progress_percent = 0.0
        self.speed = "0 KB/s"
        self.eta = "--:--"
        self.error_message: Optional[str] = None
        self.download_token: Optional[str] = None
        self.filename: Optional[str] = None
        self.filesize: Optional[int] = None
        self.created_at = time.time()
        self.event_notify = asyncio.Event()

    def update_progress(self, percent: float, speed: str, eta: str, status: Optional[str] = None):
        self.progress_percent = round(percent, 1)
        self.speed = speed.strip() if speed else self.speed
        self.eta = eta.strip() if eta else self.eta
        if status:
            self.status = status
        self.event_notify.set()
        self.event_notify.clear()

    def set_completed(self, token: str, filename: str, filesize: int):
        self.status = "completed"
        self.progress_percent = 100.0
        self.speed = "Complete"
        self.eta = "00:00"
        self.download_token = token
        self.filename = filename
        self.filesize = filesize
        self.event_notify.set()

    def set_failed(self, error: str):
        self.status = "failed"
        self.error_message = sanitize_error_message(error)
        self.event_notify.set()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress_percent": self.progress_percent,
            "speed": self.speed,
            "eta": self.eta,
            "error_message": self.error_message,
            "download_token": self.download_token,
            "filename": self.filename,
            "filesize": self.filesize,
        }


class DownloadManager:
    def __init__(self):
        self.jobs: Dict[str, DownloadJob] = {}
        self._lock = asyncio.Lock()

    async def create_job(
        self,
        url: str,
        client_ip: str,
        quality_label: str,
        format_id: str,
        is_audio_only: bool = False,
        target_format: str = "mp4",
    ) -> DownloadJob:
        job_id = uuid.uuid4().hex
        job = DownloadJob(
            job_id=job_id,
            url=url,
            client_ip=client_ip,
            quality_label=quality_label,
            format_id=format_id,
            is_audio_only=is_audio_only,
            target_format=target_format,
        )

        async with self._lock:
            self.jobs[job_id] = job

        # Launch background task for execution
        asyncio.create_task(self._execute_download_job(job))
        return job

    async def get_job(self, job_id: str) -> Optional[DownloadJob]:
        async with self._lock:
            return self.jobs.get(job_id)

    async def _execute_download_job(self, job: DownloadJob):
        # Acquire concurrency lock
        acquired = await concurrent_jobs_tracker.acquire(job.client_ip)
        if not acquired:
            job.set_failed("Concurrent download limit exceeded. Please wait for previous job to finish.")
            return

        try:
            # Re-verify URL SSRF defense
            is_valid, clean_url, err = validate_url_ssrf(job.url)
            if not is_valid:
                job.set_failed(f"Security violation: {err}")
                return

            if job.format_id.startswith("direct"):
                await self._download_direct_media(job, clean_url)
            else:
                await self._download_ytdlp_media(job, clean_url)
        except Exception as e:
            job.set_failed(f"Download failed: {sanitize_error_message(e)}")
        finally:
            await concurrent_jobs_tracker.release(job.client_ip)

    async def _download_direct_media(self, job: DownloadJob, url: str):
        """Streams and saves direct media files with chunk-by-chunk SSRF safety."""
        job.update_progress(1.0, "Connecting...", "--:--", status="downloading")

        ext = "mp3" if job.is_audio_only else (job.target_format or "mp4")
        storage_filename = generate_storage_key(ext)
        dest_path = settings.STORAGE_DIR / storage_filename

        client_headers = {"User-Agent": "MediaGrabAI-Bot/1.0"}
        start_time = time.time()
        downloaded_bytes = 0

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=False) as client:
            resp = await safe_http_request("GET", url, headers=client_headers)
            if resp.status_code not in (200, 206):
                job.set_failed(f"Server returned HTTP status {resp.status_code}")
                return

            total_bytes = int(resp.headers.get("content-length", 0))

            with open(dest_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    f.write(chunk)
                    downloaded_bytes += len(chunk)

                    # Enforce max file size
                    if downloaded_bytes > settings.MAX_FILE_SIZE_BYTES:
                        if dest_path.exists():
                            dest_path.unlink(missing_ok=True)
                        job.set_failed(f"File exceeded maximum permitted download limit ({settings.MAX_FILE_SIZE_BYTES // (1024*1024)} MB).")
                        return

                    now = time.time()
                    elapsed = max(0.1, now - start_time)
                    speed_val = downloaded_bytes / elapsed / 1024.0  # KB/s
                    speed_str = f"{speed_val / 1024.0:.1f} MB/s" if speed_val > 1024 else f"{speed_val:.0f} KB/s"

                    if total_bytes > 0:
                        pct = min(99.0, (downloaded_bytes / total_bytes) * 100.0)
                        remaining_bytes = max(0, total_bytes - downloaded_bytes)
                        eta_seconds = int(remaining_bytes / max(1.0, (downloaded_bytes / elapsed)))
                        eta_str = f"{eta_seconds // 60}:{eta_seconds % 60:02d}"
                    else:
                        pct = 50.0
                        eta_str = "--:--"

                    job.update_progress(pct, speed_str, eta_str)

        # Register completed download
        token = uuid.uuid4().hex
        rec = await storage_manager.register_download(
            token=token,
            storage_key=storage_filename,
            original_title="direct_download",
            extension=ext,
            filesize=downloaded_bytes,
            client_ip=job.client_ip,
        )
        job.set_completed(token=token, filename=rec["filename"], filesize=downloaded_bytes)

    async def _download_ytdlp_media(self, job: DownloadJob, url: str):
        """Spawns sandboxed yt-dlp to stream download and parse real-time progress."""
        job.update_progress(2.0, "Starting...", "--:--", status="downloading")

        ext = "mp3" if job.is_audio_only else "mp4"
        storage_base = uuid.uuid4().hex
        output_template = str(settings.STORAGE_DIR / f"{storage_base}.%(ext)s")

        # Configure extra arguments for audio conversion or video merging
        extra_args: list[str] = []
        if job.is_audio_only:
            extra_args.extend([
                "-x",                      # Extract audio
                "--audio-format", "mp3",    # Convert to MP3
                "--audio-quality", "0",     # Best VBR quality
            ])
            format_selector = "bestaudio/best"
        else:
            format_selector = job.format_id or "bestvideo+bestaudio/best"
            extra_args.extend([
                "--merge-output-format", "mp4"
            ])

        cmd_args = build_sandboxed_ytdlp_args(
            target_url=url,
            output_template=output_template,
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

        async def read_stdout():
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()

                # Check custom progress template
                match = PROGRESS_REGEX.search(line)
                if match:
                    pct = float(match.group(1))
                    speed = match.group(2).strip()
                    eta = match.group(3).strip()
                    job.update_progress(pct, speed, eta)
                    continue

                # Check generic progress output
                match_gen = GENERIC_PROGRESS_REGEX.search(line)
                if match_gen:
                    pct = float(match_gen.group(1))
                    speed = match_gen.group(3).strip()
                    eta = match_gen.group(4).strip()
                    job.update_progress(pct, speed, eta)

        # Start reading stdout concurrently
        stdout_task = asyncio.create_task(read_stdout())

        try:
            _, stderr_bytes = await asyncio.wait_for(
                asyncio.gather(proc.wait(), proc.stderr.read()),
                timeout=settings.DOWNLOAD_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            try:
                proc.terminate()
                await asyncio.sleep(1.0)
                proc.kill()
            except Exception:
                pass
            job.set_failed("Download timed out after exceeding 10 minutes.")
            return
        finally:
            if not stdout_task.done():
                stdout_task.cancel()

        retcode = proc.returncode
        stderr_str = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

        if retcode != 0:
            job.set_failed(f"Extractor process failed: {stderr_str[:200]}")
            return

        # Find the output file generated on disk matching storage_base
        matching_files = list(settings.STORAGE_DIR.glob(f"{storage_base}.*"))
        if not matching_files:
            job.set_failed("Output file could not be located after extraction.")
            return

        target_file = matching_files[0]
        actual_ext = target_file.suffix.lstrip(".")
        filesize = target_file.stat().st_size

        token = uuid.uuid4().hex
        rec = await storage_manager.register_download(
            token=token,
            storage_key=target_file.name,
            original_title=f"mediagrab_{job.quality_label}",
            extension=actual_ext,
            filesize=filesize,
            client_ip=job.client_ip,
        )
        job.set_completed(token=token, filename=rec["filename"], filesize=filesize)


download_manager = DownloadManager()
