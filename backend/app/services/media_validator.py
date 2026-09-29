"""
media_validator.py -- validate a downloaded file BEFORE ffmpeg touches it.

Fixes: "FFmpeg faststart normalization failed ... Invalid data found"
(usually a web page or a truncated file saved with an .mp4 name).
"""
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

MIN_BYTES = 10 * 1024  # anything smaller than ~10 KB is suspicious


class MediaValidationError(Exception):
    """code is one of: INVALID_MEDIA, DOWNLOAD_INCOMPLETE, TOO_SMALL, FFPROBE_MISSING"""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def sniff(head: bytes) -> str:
    """Identify a file by its first bytes. Returns 'html', 'json', 'mp4', 'webm',
    'hls', 'mp3', 'ogg', 'flac', 'riff', 'flv', 'ts' or 'unknown'."""
    if head[4:8] == b"ftyp":
        return "mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if head[:7] == b"#EXTM3U":
        return "hls"
    if head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return "mp3"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"RIFF":
        return "riff"
    if head[:3] == b"FLV":
        return "flv"
    if len(head) > 188 and head[0] == 0x47 and head[188] == 0x47:
        return "ts"
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n")[:200].lower()
    if text.startswith((b"<!doctype", b"<html", b"<head", b"<body", b"<?xml", b"<")):
        return "html"
    if text.startswith((b"{", b"[")):
        return "json"
    return "unknown"


BAD_CONTENT_TYPES = ("text/", "application/json", "application/xml")


def validate_download(
    path: Path,
    content_type: Optional[str] = None,
    status_code: Optional[int] = None,
    expected_length: Optional[int] = None,
    content_encoding: Optional[str] = None,
) -> str:
    """Raise MediaValidationError if the file is not real media. Returns the sniffed kind."""
    path = Path(path)
    if status_code is not None and status_code not in (200, 206):
        raise MediaValidationError("INVALID_MEDIA", f"HTTP status {status_code}")

    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct.startswith(BAD_CONTENT_TYPES):
            raise MediaValidationError("INVALID_MEDIA", f"Content-Type is {ct}")

    size = path.stat().st_size
    with open(path, "rb") as f:
        head = f.read(512)

    kind = sniff(head)
    if kind in ("html", "json"):
        raise MediaValidationError("INVALID_MEDIA", f"file is {kind}, not media")

    if size < MIN_BYTES:
        raise MediaValidationError("TOO_SMALL", f"{size} bytes")

    # Only flag a file that is SMALLER than promised, and only when the bytes on disk
    # should equal Content-Length (no compression). A bigger or re-encoded file is fine.
    encoded = (content_encoding or "").strip().lower() not in ("", "identity")
    if expected_length is not None and not encoded and size < expected_length:
        raise MediaValidationError(
            "DOWNLOAD_INCOMPLETE", f"got {size} bytes, expected {expected_length}"
        )
    return kind


def transfer_complete(headers, raw_bytes: int, status_code: int) -> bool:
    """
    True unless the server promised more bytes than we actually received.
    raw_bytes must be the RAW bytes read from the network (httpx: resp.num_bytes_downloaded),
    not the size of the file on disk, so compression can't cause a false alarm.
    """
    if status_code == 206:  # partial by design: Content-Length is only the slice size
        return True
    if str(headers.get("transfer-encoding", "")).lower() == "chunked":
        return True  # no reliable Content-Length
    cl = str(headers.get("content-length", "")).strip()
    if not cl.isdigit():
        return True
    return raw_bytes >= int(cl)


@dataclass
class MediaInfo:
    video_codec: Optional[str]
    audio_codec: Optional[str]
    pix_fmt: Optional[str]
    duration: float


def probe_media(path: Path, timeout: int = 30) -> MediaInfo:
    """Run ffprobe. Raises INVALID_MEDIA if ffmpeg cannot read the file."""
    if not shutil.which("ffprobe"):
        raise MediaValidationError("FFPROBE_MISSING", "ffprobe is not installed")
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise MediaValidationError("INVALID_MEDIA", "ffprobe timed out")
    if r.returncode != 0:
        tail = "\n".join(r.stderr.strip().splitlines()[-5:])
        raise MediaValidationError("INVALID_MEDIA", f"ffprobe failed: {tail}")
    data = json.loads(r.stdout or "{}")
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None and a is None:
        raise MediaValidationError("INVALID_MEDIA", "no audio or video streams found")
    try:
        duration = float(data.get("format", {}).get("duration") or 0)
    except ValueError:
        duration = 0.0
    return MediaInfo(
        video_codec=v.get("codec_name") if v else None,
        audio_codec=a.get("codec_name") if a else None,
        pix_fmt=v.get("pix_fmt") if v else None,
        duration=duration,
    )
