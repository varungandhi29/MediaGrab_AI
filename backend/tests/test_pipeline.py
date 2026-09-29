import subprocess
from pathlib import Path
import pytest
from app.services.media_validator import (
    sniff, validate_download, probe_media, MediaValidationError)
from app.services.media_normalizer import normalize_to_mp4, NormalizeError
from app.resilience.media_errors import classify_error, user_message, ErrorClass


def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                   check=True, capture_output=True)

@pytest.fixture(scope="module")
def h264_mp4(tmp_path_factory):
    p = tmp_path_factory.mktemp("m") / "good.mp4"
    ff("-f","lavfi","-i","testsrc=duration=3:size=320x240:rate=15","-f","lavfi","-i","sine=duration=3",
       "-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-shortest",str(p))
    return p

@pytest.fixture(scope="module")
def vp9_webm(tmp_path_factory):
    p = tmp_path_factory.mktemp("m") / "vp9.webm"
    ff("-f","lavfi","-i","testsrc=duration=2:size=320x240:rate=15","-f","lavfi","-i","sine=duration=2",
       "-c:v","libvpx-vp9","-b:v","200k","-c:a","libopus","-shortest",str(p))
    return p

# ---- sniff / validate --------------------------------------------------
def test_sniff_html_and_json():
    assert sniff(b"<!DOCTYPE html><html>...") == "html"
    assert sniff(b"\xef\xbb\xbf  <html>") == "html"
    assert sniff(b'{"error": "expired"}') == "json"

def test_html_named_mp4_is_rejected(tmp_path):
    p = tmp_path / "fake.mp4"
    p.write_bytes(b"<!DOCTYPE html><html><body>Please log in</body></html>" + b" " * 20000)
    with pytest.raises(MediaValidationError) as e:
        validate_download(p)
    assert e.value.code == "INVALID_MEDIA"

def test_bad_content_type_rejected(tmp_path, h264_mp4):
    with pytest.raises(MediaValidationError) as e:
        validate_download(h264_mp4, content_type="text/html; charset=utf-8")
    assert e.value.code == "INVALID_MEDIA"

def test_bad_status_rejected(h264_mp4):
    with pytest.raises(MediaValidationError):
        validate_download(h264_mp4, status_code=403)

def test_tiny_file_rejected(tmp_path):
    p = tmp_path / "tiny.mp4"; p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 100)
    with pytest.raises(MediaValidationError) as e:
        validate_download(p)
    assert e.value.code == "TOO_SMALL"

def test_truncated_download_detected(h264_mp4):
    size = h264_mp4.stat().st_size
    with pytest.raises(MediaValidationError) as e:
        validate_download(h264_mp4, expected_length=size + 5000)
    assert e.value.code == "DOWNLOAD_INCOMPLETE"

def test_valid_mp4_passes(h264_mp4):
    assert validate_download(h264_mp4, content_type="video/mp4", status_code=200,
                             expected_length=h264_mp4.stat().st_size) == "mp4"

def test_ffprobe_rejects_garbage(tmp_path):
    p = tmp_path / "garbage.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x99" * 50000)
    with pytest.raises(MediaValidationError) as e:
        probe_media(p)
    assert e.value.code == "INVALID_MEDIA"

# ---- normalize ---------------------------------------------------------
def test_h264_source_is_copied_and_faststart(h264_mp4, tmp_path):
    out = tmp_path / "out.mp4"
    info = normalize_to_mp4(h264_mp4, out)
    assert info.video_codec == "h264"
    o = probe_media(out)
    assert (o.video_codec, o.audio_codec, o.pix_fmt) == ("h264", "aac", "yuv420p")
    head = out.read_bytes()[:4096]
    assert head.find(b"moov") != -1  # faststart: moov atom near the start

def test_vp9_webm_is_converted_to_h264_aac(vp9_webm, tmp_path):
    out = tmp_path / "from_webm.mp4"
    normalize_to_mp4(vp9_webm, out)
    o = probe_media(out)
    assert (o.video_codec, o.audio_codec) == ("h264", "aac")
    assert o.duration > 1.5

def test_normalize_rejects_html_file(tmp_path):
    p = tmp_path / "page.mp4"; p.write_bytes(b"<html>login</html>" * 2000)
    with pytest.raises(MediaValidationError):
        normalize_to_mp4(p, tmp_path / "x.mp4")
    assert not (tmp_path / "x.mp4").exists()

# ---- error classification ---------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("ERROR: Unsupported URL: https://www.diskwala.com/app/x", ErrorClass.UNSUPPORTED_URL),
    ("ERROR: [youtube] abc: Sign in to confirm you're not a bot", ErrorClass.BOT_CHECK),
    ("HTTP Error 403: Forbidden", ErrorClass.BOT_CHECK),
    ("ERROR: Private video. Sign in if you've been granted access", ErrorClass.LOGIN_REQUIRED),
    ("The uploader has not made this video available in your country", ErrorClass.GEO_BLOCKED),
    ("Video unavailable. This video has been removed by the uploader", ErrorClass.PRIVATE_OR_DELETED),
    ("Requested format is not available", ErrorClass.OUTDATED_EXTRACTOR),
    ("Widevine license required", ErrorClass.DRM),
    ("Error opening input: Invalid data found when processing input", ErrorClass.INVALID_MEDIA),
    ("DOWNLOAD_INCOMPLETE: got 10 bytes, expected 99", ErrorClass.DOWNLOAD_INCOMPLETE),
    ("extraction timed out after 45s", ErrorClass.TIMEOUT),
    ("something totally unexpected", ErrorClass.INTERNAL_ERROR),
])
def test_classify(text, expected):
    assert classify_error(text) == expected

def test_file_host_when_no_tier_found_media():
    assert classify_error("Unsupported URL: https://terabox.com/s/x",
                          tiers_found_media=False) == ErrorClass.FILE_HOST_UNSUPPORTED
    assert classify_error("Invalid data found", tiers_found_media=False) == ErrorClass.FILE_HOST_UNSUPPORTED
    # a real bot check must NOT be relabelled as a file host
    assert classify_error("HTTP Error 429", tiers_found_media=False) == ErrorClass.BOT_CHECK

def test_every_class_has_a_message():
    for c in ErrorClass:
        assert user_message(c)


from app.services.media_validator import transfer_complete


def test_bigger_than_announced_is_not_incomplete(h264_mp4):
    # e.g. gzip: Content-Length was the compressed size, file on disk is bigger
    assert validate_download(h264_mp4, expected_length=1000) == "mp4"


def test_encoded_response_skips_size_check(h264_mp4):
    size = h264_mp4.stat().st_size
    assert validate_download(h264_mp4, expected_length=size + 9999, content_encoding="gzip") == "mp4"


def test_transfer_complete_cases():
    assert transfer_complete({"content-length": "1000"}, 1000, 200)
    assert transfer_complete({"content-length": "1000"}, 1200, 200)
    assert not transfer_complete({"content-length": "1000"}, 400, 200)
    assert transfer_complete({"content-length": "1000"}, 400, 206)
    assert transfer_complete({"transfer-encoding": "chunked"}, 400, 200)
    assert transfer_complete({}, 400, 200)
