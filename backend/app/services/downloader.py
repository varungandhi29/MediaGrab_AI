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
from .media_validator import transfer_complete


async def download_direct(
    client: httpx.AsyncClient, url: str, dest: Path, headers: Optional[dict] = None
) -> dict:
    """Stream a direct file to disk and report what happened."""
    async with client.stream("GET", url, headers=headers) as resp:
        with open(dest, "wb") as f:
            async for chunk in resp.aiter_bytes():
                f.write(chunk)
        complete = transfer_complete(resp.headers, resp.num_bytes_downloaded, resp.status_code)
        return {
            "status_code": resp.status_code,
            "content_type": resp.headers.get("content-type"),
            "complete": complete,
            "debug": (
                f"status={resp.status_code} type={resp.headers.get('content-type')} "
                f"content-length={resp.headers.get('content-length')} "
                f"encoding={resp.headers.get('content-encoding')} "
                f"raw_bytes={resp.num_bytes_downloaded} file_bytes={dest.stat().st_size}"
            ),
        }


class DownloadJob:
    def __init__(
        self,
        job_id: str,
        url: str,
        client_ip: str,
        quality_label: str,
        format_id: str,
        is_audio_only: bool,
        target_format: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ):
        self.job_id = job_id
        self.id = job_id
        self.url = url
        self.client_ip = client_ip
        self.quality_label = quality_label
        self.format_id = format_id
        self.is_audio_only = is_audio_only
        self.target_format = target_format
        self.start_time = start_time
        self.end_time = end_time
        self.status = "pending"  # pending, downloading, converting, ready, completed, failed
        self.progress_percent = 0.0
        self.speed = "0 KB/s"
        self.eta = "--:--"
        self.error_message: Optional[str] = None
        self.output_path: Optional[str] = None
        self.error_class: Optional[str] = None
        self.user_message: Optional[str] = None
        self.debug: Optional[str] = None
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
        self.status = "ready"
        self.progress_percent = 100.0
        self.speed = "Complete"
        self.eta = "00:00"
        self.download_token = token
        self.filename = filename
        self.filesize = filesize
        self.event_notify.set()

    def set_failed(self, error: str, cls=None, debug: Optional[str] = None):
        from ..resilience.media_errors import classify_error, user_message
        self.status = "failed"
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
            "status": self.status,
            "progress_percent": self.progress_percent,
            "speed": self.speed,
            "eta": self.eta,
            "error_message": self.error_message,
            "download_token": self.download_token,
            "filename": self.filename,
            "filesize": self.filesize,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "output_path": self.output_path,
            "error_class": self.error_class,
            "user_message": self.user_message,
            "debug": self.debug,
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
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
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
            start_time=start_time,
            end_time=end_time,
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

            if "flezen.com" in clean_url.lower():
                job.set_failed(
                    "Flezen protects files behind an Android app locker and ad monetization wall. "
                    "Use the direct 'Open in Flezen App' or 'Telegram Bot Bypass' options on the card to access this file."
                )
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
        """Streams and saves direct media files with chunk-by-chunk SSRF safety and one retry."""
        from .job_finalize import finalize_download, mark_failed, run_with_one_retry
        from ..resilience.media_errors import ErrorClass
        from ..security.ssrf_validator import create_safe_client

        ext = "mp3" if job.is_audio_only else (job.target_format or "mp4")
        headers = {"User-Agent": "MediaGrabAI-Bot/1.0"}

        async def attempt_fn(j):
            tmp_path = settings.STORAGE_DIR / generate_storage_key(ext)
            async with create_safe_client(url) as client:
                meta = await download_direct(client, url, tmp_path, headers)
                if not meta["complete"]:
                    tmp_path.unlink(missing_ok=True)
                    mark_failed(j, ErrorClass.DOWNLOAD_INCOMPLETE, meta["debug"])
                    return
                await finalize_download(
                    j, tmp_path,
                    content_type=meta["content_type"],
                    status_code=meta["status_code"],
                    # do NOT pass expected_length here: transfer_complete already checked it
                )
                if j.status == "ready" and j.output_path:
                    token = uuid.uuid4().hex
                    filesize = Path(j.output_path).stat().st_size
                    rec = await storage_manager.register_download(
                        token=token,
                        storage_key=Path(j.output_path).name,
                        original_title="direct_download",
                        extension=ext,
                        filesize=filesize,
                        client_ip=j.client_ip,
                    )
                    j.download_token = token
                    j.filename = rec["filename"]
                    j.filesize = filesize

        await run_with_one_retry(job, attempt_fn)

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

        # Configure clip trimming if start_time or end_time is specified
        if job.start_time or job.end_time:
            def clean_ts(ts: Optional[str]) -> Optional[str]:
                if not ts:
                    return None
                cleaned = ts.strip()
                if re.match(r'^[0-9]+(:[0-9]{2})?(:[0-9]{2})?(\.[0-9]+)?$', cleaned):
                    return cleaned
                return None

            st = clean_ts(job.start_time) or "0"
            et = clean_ts(job.end_time) or "inf"
            extra_args.extend([
                "--download-sections", f"*{st}-{et}",
                "--force-keyframes-at-cuts"
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

                # Check custom progress template with pipe delimiter: download:[PROGRESS]|pct|speed|eta
                if "[PROGRESS]|" in line:
                    parts = line.strip().split("|")
                    if len(parts) >= 4:
                        clean_line_parts = [re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', p).strip() for p in parts]
                        pct_raw = clean_line_parts[1].replace("%", "").strip()
                        speed_raw = clean_line_parts[2].strip()
                        eta_raw = clean_line_parts[3].strip()
                        try:
                            pct = float(pct_raw)
                        except ValueError:
                            pct = job.progress_percent
                        clean_speed = speed_raw if speed_raw and speed_raw.lower() not in ("unknown", "na", "none", "") else job.speed
                        clean_eta = eta_raw if eta_raw and eta_raw.lower() not in ("unknown", "na", "none", "") else job.eta
                        job.update_progress(pct, clean_speed, clean_eta)
                        continue

                # Check generic progress output as fallback
                clean_generic_line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line)
                match_gen = GENERIC_PROGRESS_REGEX.search(clean_generic_line)
                if match_gen:
                    pct = float(match_gen.group(1))
                    speed = match_gen.group(3).strip()
                    eta = match_gen.group(4).strip()
                    job.update_progress(pct, speed, eta)
                    continue

                if "[download]" in line and "Destination:" in line:
                    job.update_progress(job.progress_percent, "Starting download...", job.eta, status="downloading")
                    continue

                if "[Merger]" in line or "ffmpeg" in line.lower() or "postprocessing" in line.lower():
                    job.update_progress(job.progress_percent, "Merging streams...", job.eta, status="converting")
                    continue

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
            from ..resilience.media_errors import classify_error
            from .job_finalize import mark_failed
            cls = classify_error(stderr_str, tiers_found_media=True)
            mark_failed(job, cls, stderr_str)
            return

        # Find the output file generated on disk matching storage_base
        matching_files = list(settings.STORAGE_DIR.glob(f"{storage_base}.*"))
        if not matching_files:
            from ..resilience.media_errors import ErrorClass
            from .job_finalize import mark_failed
            mark_failed(job, ErrorClass.INVALID_MEDIA, "Output file could not be located after extraction.")
            return

        target_file = matching_files[0]
        from .job_finalize import finalize_download
        await finalize_download(job, target_file, tiers_found_media=True)

        if job.status == "ready" and job.output_path:
            token = uuid.uuid4().hex
            filesize = Path(job.output_path).stat().st_size
            rec = await storage_manager.register_download(
                token=token,
                storage_key=Path(job.output_path).name,
                original_title=f"mediagrab_{job.quality_label}",
                extension="mp4",
                filesize=filesize,
                client_ip=job.client_ip,
            )
            job.download_token = token
            job.filename = rec["filename"]
            job.filesize = filesize


download_manager = DownloadManager()
