"""
media_normalizer.py -- turn any valid download into ONE browser-safe file:
H.264 video + AAC audio in MP4 with faststart (fast seeking).
Copies streams when they are already compatible (no quality loss, less CPU).
"""
import subprocess
from pathlib import Path

from ..config import settings
from .media_validator import MediaInfo, MediaValidationError, probe_media


class NormalizeError(Exception):
    def __init__(self, message: str, stderr_tail: str = ""):
        super().__init__(message)
        self.stderr_tail = stderr_tail


def build_command(src: Path, dst: Path, info: MediaInfo, target_height: int = None) -> list:
    ffmpeg_exe = settings.FFMPEG_LOCATION or "ffmpeg"
    cmd = [ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src)]

    if info.video_codec:
        cmd += ["-map", "0:v:0"]
    cmd += ["-map", "0:a:0?"]  # the ? makes audio optional

    if info.video_codec:
        if target_height and info.height and info.height > target_height:
            cmd += ["-vf", f"scale=-2:min(ih\\,{target_height})", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p"]
        elif info.video_codec == "h264" and info.pix_fmt == "yuv420p":
            cmd += ["-c:v", "copy"]
        else:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]

    if info.audio_codec:
        if info.audio_codec == "aac":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", "aac", "-b:a", "192k"]

    cmd += ["-movflags", "+faststart", str(dst)]
    return cmd


def normalize_to_mp4(src: Path, dst: Path, timeout: int = 3600, target_height: int = None) -> MediaInfo:
    """Validate with ffprobe, then convert. Returns info about the SOURCE file."""
    src, dst = Path(src), Path(dst)
    info = probe_media(src)  # raises MediaValidationError if not real media
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_command(src, dst, info, target_height=target_height)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        dst.unlink(missing_ok=True)
        raise NormalizeError("ffmpeg timed out")
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        tail = "\n".join(r.stderr.strip().splitlines()[-30:])  # LAST 30 lines, not the banner
        dst.unlink(missing_ok=True)
        raise NormalizeError("ffmpeg could not convert the file", tail)
    return info
