import pytest
from app.security.sanitizer import (
    sanitize_for_logging,
    sanitize_download_filename,
    generate_storage_key,
    sanitize_error_message
)


def test_sanitize_for_logging_removes_crlf_and_ansi():
    dirty = "user_input\r\nSET-COOKIE: malicious=1\x1b[31mRed Alert\x00"
    cleaned = sanitize_for_logging(dirty)
    assert "\r" not in cleaned
    assert "\n" not in cleaned
    assert "\x1b" not in cleaned
    assert "\x00" not in cleaned
    assert "user_input" in cleaned


def test_sanitize_download_filename():
    assert sanitize_download_filename("My Cool Video! 2026", "mp4") == "My_Cool_Video_2026.mp4"
    # Path traversal attack in filename
    traversal = "../../../etc/passwd"
    clean_trav = sanitize_download_filename(traversal, "mp4")
    assert ".." not in clean_trav
    assert "/" not in clean_trav
    assert "\\" not in clean_trav

    # Dangerous extension override
    danger = sanitize_download_filename("payload", "exe")
    assert danger.endswith(".mp4")


def test_generate_storage_key_is_uuid_and_safe():
    k1 = generate_storage_key("mp4")
    k2 = generate_storage_key("mp4")
    assert k1 != k2
    assert k1.endswith(".mp4")
    assert len(k1) > 20
