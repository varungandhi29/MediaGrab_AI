import pytest
from app.security.ssrf_validator import validate_url_ssrf, is_ip_restricted
import ipaddress


def test_ssrf_blocks_private_ipv4():
    blocked_ips = [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.5",
        "172.31.255.254",
        "192.168.1.1",
        "169.254.169.254",  # AWS/GCP/Azure metadata
        "0.0.0.0",
        "100.64.0.1",
        "198.18.0.1",
    ]
    for ip_str in blocked_ips:
        ip = ipaddress.ip_address(ip_str)
        assert is_ip_restricted(ip) is True, f"Failed to block restricted IP {ip_str}"

        is_valid, _, error = validate_url_ssrf(f"http://{ip_str}/test")
        assert is_valid is False, f"URL with IP {ip_str} should be invalid"
        assert "blocked" in error.lower() or "restricted" in error.lower()


def test_ssrf_blocks_private_ipv6():
    blocked_v6 = [
        "::1",
        "::ffff:127.0.0.1",
        "fc00::1",
        "fd12:3456:789a::1",
        "fe80::1",
    ]
    for ip_str in blocked_v6:
        ip = ipaddress.ip_address(ip_str)
        assert is_ip_restricted(ip) is True, f"Failed to block IPv6 {ip_str}"


def test_ssrf_blocks_localhost_and_internal_hostnames():
    blocked_hosts = [
        "http://localhost/secret",
        "http://localhost:8080/admin",
        "https://metadata.google.internal/computeMetadata/v1/",
        "http://instance-data/latest/meta-data/",
    ]
    for url in blocked_hosts:
        is_valid, _, error = validate_url_ssrf(url)
        assert is_valid is False, f"URL {url} should be blocked"


def test_ssrf_blocks_invalid_schemes():
    invalid_schemes = [
        "file:///etc/passwd",
        "file://c:/windows/system32/cmd.exe",
        "ftp://ftp.example.com/files",
        "gopher://gopher.example.com",
        "dict://dict.org",
        "data:text/html,<h1>hi</h1>",
        "javascript:alert(1)",
    ]
    for url in invalid_schemes:
        is_valid, _, error = validate_url_ssrf(url)
        assert is_valid is False, f"Scheme in {url} should be rejected"
        assert "scheme" in error.lower()


def test_ssrf_blocks_embedded_credentials():
    bad_urls = [
        "http://user:password@example.com/video",
        "https://admin:token@youtube.com/watch?v=123",
    ]
    for url in bad_urls:
        is_valid, _, error = validate_url_ssrf(url)
        assert is_valid is False
        assert "credential" in error.lower()


def test_ssrf_allows_legitimate_public_urls():
    valid_urls = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://vimeo.com/76979871",
        "https://en.wikipedia.org/wiki/Main_Page",
    ]
    for url in valid_urls:
        is_valid, clean_url, error = validate_url_ssrf(url)
        assert is_valid is True, f"Valid URL {url} was incorrectly blocked: {error}"
        assert error is None
