import sys
import os
import asyncio
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from ..config import settings
from .sanitizer import sanitize_for_logging


def get_sandboxed_environment() -> Dict[str, str]:
    """
    Constructs a stripped, minimal environment for yt-dlp execution.
    Removes all API keys, secrets, database credentials, and cloud metadata tokens.
    """
    # Keys that are strictly safe and needed for Python/FFmpeg subprocess execution
    safe_keys = {
        "PATH",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "TEMP",
        "TMP",
        "COMSPEC",
        "PATHEXT",
        "WINDIR",
        "LANG",
        "LC_ALL",
        "PYTHONIOENCODING",
        "PYTHONUTF8",
    }
    
    clean_env: Dict[str, str] = {}
    for key, value in os.environ.items():
        if key.upper() in safe_keys:
            clean_env[key] = value

    # Force UTF-8 and no Python buffering
    clean_env["PYTHONUTF8"] = "1"
    clean_env["PYTHONUNBUFFERED"] = "1"

    return clean_env


def build_sandboxed_ytdlp_args(
    target_url: str,
    output_template: Optional[str] = None,
    format_selector: Optional[str] = None,
    is_metadata_only: bool = False,
    extra_safe_args: Optional[List[str]] = None,
) -> List[str]:
    """
    Generates a secure, locked-down argument list for yt-dlp.
    Disables local config, local cache, post-exec scripts, playlist explosions,
    and sets strict socket timeouts and size ceilings.
    """
    args = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-config",             # Ignore any local or user configuration files
        "--no-cache-dir",          # Do not write or read from local disk cache
        "--no-warnings",
        "--no-playlist",           # Reject playlist mass-downloads (DDoS prevention)
        "--socket-timeout", "15",  # Network socket timeout
        "--geo-bypass",            # Attempt geo-bypass safely
        "--prefer-free-formats",
        "--restrict-filenames",
    ]

    # Add ffmpeg location if available
    if settings.FFMPEG_LOCATION and os.path.exists(settings.FFMPEG_LOCATION):
        args.extend(["--ffmpeg-location", settings.FFMPEG_LOCATION])

    if is_metadata_only:
        args.extend([
            "--dump-json",          # Extract metadata JSON to stdout
            "--skip-download",      # Do not download media
            "--no-write-thumbnail",
            "--no-write-description",
        ])
    else:
        # Enforce maximum filesize
        max_bytes = settings.MAX_FILE_SIZE_BYTES
        args.extend(["--max-filesize", str(max_bytes)])

        if output_template:
            args.extend(["-o", output_template])

        if format_selector:
            args.extend(["-f", format_selector])

        # Report progress in machine-parseable format
        args.extend([
            "--newline",
            "--progress-template", "download:[PROGRESS]:%(progress._percent_str)s:%(progress._speed_str)s:%(progress._eta_str)s"
        ])

    if extra_safe_args:
        args.extend(extra_safe_args)

    # Finally append the user target URL
    args.append(target_url)

    return args


async def run_sandboxed_subprocess(
    cmd_args: List[str],
    timeout_seconds: int = 30,
    cwd: Optional[Path] = None,
    max_output_bytes: int = 15 * 1024 * 1024,  # 15MB limit
) -> Tuple[int, str, str]:
    """
    Executes a subprocess in isolation without shell=True, applying a hard timeout
    and sanitizing environment variables.
    """
    env = get_sandboxed_environment()
    work_dir = str(cwd) if cwd else str(settings.STORAGE_DIR)

    proc = await asyncio.create_subprocess_exec(
        *cmd_args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=work_dir,
        env=env,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        # Process hung or exceeded duration limit — forcefully terminate
        try:
            proc.terminate()
            await asyncio.sleep(1.0)
            if proc.returncode is None:
                proc.kill()
        except Exception:
            pass
        raise TimeoutError(f"Process exceeded maximum time allocation ({timeout_seconds}s) and was terminated.")

    # Guard against memory explosion
    if len(stdout_bytes) > max_output_bytes:
        stdout_str = stdout_bytes[:max_output_bytes].decode("utf-8", errors="replace") + "\n[OUTPUT TRUNCATED]"
    else:
        stdout_str = stdout_bytes.decode("utf-8", errors="replace")

    stderr_str = stderr_bytes.decode("utf-8", errors="replace")
    return proc.returncode or 0, stdout_str, stderr_str
