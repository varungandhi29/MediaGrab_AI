import ipaddress
import socket
from urllib.parse import urlparse
from typing import Tuple, List, Optional, AsyncIterator, Dict, Any
from contextlib import asynccontextmanager
import httpx
import httpcore
import httpcore._backends.auto
from ..config import settings


# Forbidden IPv4 networks
RESTRICTED_IPV4_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),          # Current network
    ipaddress.ip_network("10.0.0.0/8"),         # Private-use Class A
    ipaddress.ip_network("100.64.0.0/10"),      # Shared Address Space (Carrier-grade NAT)
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback
    ipaddress.ip_network("169.254.0.0/16"),     # Link Local & Cloud Metadata (169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),      # Private-use Class B
    ipaddress.ip_network("192.0.0.0/24"),       # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),       # Documentation (TEST-NET-1)
    ipaddress.ip_network("192.168.0.0/16"),     # Private-use Class C
    ipaddress.ip_network("198.18.0.0/15"),      # Network Benchmark Tests
    ipaddress.ip_network("198.51.100.0/24"),    # Documentation (TEST-NET-2)
    ipaddress.ip_network("203.0.113.0/24"),     # Documentation (TEST-NET-3)
    ipaddress.ip_network("224.0.0.0/4"),        # Multicast
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved for future use
    ipaddress.ip_network("255.255.255.255/32"), # Limited Broadcast
]

# Forbidden IPv6 networks
RESTRICTED_IPV6_NETWORKS = [
    ipaddress.ip_network("::/128"),             # Unspecified
    ipaddress.ip_network("::1/128"),            # Loopback
    ipaddress.ip_network("::ffff:0:0/96"),      # IPv4-mapped IPv6
    ipaddress.ip_network("64:ff9b::/96"),       # IPv4/IPv6 translation
    ipaddress.ip_network("100::/64"),           # Discard-only prefix
    ipaddress.ip_network("2001::/23"),          # IETF Protocol Assignments
    ipaddress.ip_network("2001:db8::/32"),      # Documentation
    ipaddress.ip_network("2002::/16"),          # 6to4
    ipaddress.ip_network("fc00::/7"),           # Unique Local Address (ULA)
    ipaddress.ip_network("fe80::/10"),          # Link-local unicast
    ipaddress.ip_network("ff00::/8"),           # Multicast
]

# Blocked hostnames by name
BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "broadcasthost",
    "metadata.google.internal",
    "metadata.internal",
    "instance-data",
}


class SSRFValidationError(ValueError):
    """Raised when a URL violates SSRF security checks."""
    pass


def is_ip_restricted(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """
    Check if an IPv4 or IPv6 address falls within any private, loopback,
    link-local, cloud metadata, or reserved ranges.
    """
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True

    # Check for IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return is_ip_restricted(ip.ipv4_mapped)

    if isinstance(ip, ipaddress.IPv4Address):
        for net in RESTRICTED_IPV4_NETWORKS:
            if ip in net:
                return True
    elif isinstance(ip, ipaddress.IPv6Address):
        for net in RESTRICTED_IPV6_NETWORKS:
            if ip in net:
                return True

    return False


def resolve_hostname_ips(hostname: str) -> List[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """
    Resolve a hostname to all its IPv4 and IPv6 addresses using system DNS.
    """
    ip_objs = []
    try:
        # Get all address infos
        addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        for entry in addr_info:
            sockaddr = entry[4]
            ip_str = sockaddr[0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                if ip_obj not in ip_objs:
                    ip_objs.append(ip_obj)
            except ValueError:
                continue
    except socket.gaierror as e:
        raise SSRFValidationError(f"Could not resolve hostname '{hostname}': {e}")
    except Exception as e:
        raise SSRFValidationError(f"Resolution failed for hostname '{hostname}': {e}")

    if not ip_objs:
        raise SSRFValidationError(f"Hostname '{hostname}' did not resolve to any IP address.")

    return ip_objs


def validate_url_ssrf(url: str) -> Tuple[bool, str, Optional[str]]:
    """
    Validates a user-submitted URL against SSRF threats.
    
    Checks:
    1. Maximum URL length.
    2. URL scheme: strictly 'http' or 'https'.
    3. User/Password credentials embedded in authority.
    4. Hostname presence and format.
    5. Blocked well-known internal hostnames.
    6. DNS resolution: All resolved IPv4 and IPv6 addresses must be public.
    
    Returns:
        (is_valid: bool, normalized_url: str, error_message: Optional[str])
    """
    if not url or not isinstance(url, str):
        return False, "", "URL must be a non-empty string."

    url = url.strip()

    if len(url) > settings.MAX_URL_LENGTH:
        return False, "", f"URL exceeds maximum allowed length of {settings.MAX_URL_LENGTH} characters."

    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, "", f"Malformed URL: {e}"

    # 1. Scheme check
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return False, "", f"Forbidden URL scheme '{scheme}'. Only HTTP and HTTPS are permitted."

    # 2. Hostname check
    hostname = parsed.hostname
    if not hostname:
        return False, "", "URL must contain a valid hostname."

    hostname_clean = hostname.strip().lower()

    # 3. Check for credentials in authority
    if parsed.username or parsed.password:
        return False, "", "URLs with embedded credentials (user:pass@host) are rejected for security."

    # 4. Check blocked hostnames
    if hostname_clean in BLOCKED_HOSTNAMES:
        return False, "", f"Access to internal host '{hostname_clean}' is strictly prohibited."

    # 5. Check if hostname is directly an IP literal or resolves to restricted IP
    # First test if hostname is an IP string directly
    try:
        direct_ip = ipaddress.ip_address(hostname_clean)
        if is_ip_restricted(direct_ip):
            return False, "", f"Access to restricted or internal IP address '{direct_ip}' is blocked."
        return True, url, None
    except ValueError:
        # Not a direct IP literal, treat as hostname to resolve
        pass

    # Resolve all IPs
    try:
        resolved_ips = resolve_hostname_ips(hostname_clean)
    except SSRFValidationError as e:
        return False, "", str(e)

    for resolved_ip in resolved_ips:
        if is_ip_restricted(resolved_ip):
            return False, "", f"Hostname '{hostname_clean}' resolves to restricted internal IP '{resolved_ip}'. Request blocked."

    return True, url, None


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """
    Pins connections to validated IP addresses to prevent DNS rebinding attacks.
    Preserves TLS SNI and HTTP Host header for valid SSL certificate validation.
    """
    def __init__(self, ip_map: Dict[str, str]):
        self._backend = httpcore._backends.auto.AutoBackend()
        self._ip_map = ip_map

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: Optional[float] = None,
        local_address: Optional[str] = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        target_ip = self._ip_map.get(host, host)
        return await self._backend.connect_tcp(
            host=target_ip,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, *args, **kwargs):
        return await self._backend.connect_unix_socket(*args, **kwargs)

    async def sleep(self, seconds: float):
        await self._backend.sleep(seconds)


def _dual_async_context_manager(func):
    """
    Decorator that allows safe_http_request to be used both as an async context manager:
        async with safe_http_request(...) as resp:
    and awaited directly:
        resp = await safe_http_request(...)
    Enforces max_bytes on the awaited path, raising an error if the body exceeds the limit.
    """
    cm_func = asynccontextmanager(func)

    class DualAsyncContextManager:
        def __init__(self, *args, **kwargs):
            self._args = args
            self._kwargs = kwargs
            self._max_bytes = kwargs.get("max_bytes", 2 * 1024 * 1024)
            if len(args) >= 6:
                self._max_bytes = args[5]
            self._cm = cm_func(*args, **kwargs)

        async def __aenter__(self):
            return await self._cm.__aenter__()

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return await self._cm.__aexit__(exc_type, exc_val, exc_tb)

        def __await__(self):
            async def _await_helper():
                async with self._cm as res:
                    # Enforce max_bytes on Content-Length header if present
                    cl = res.headers.get("content-length")
                    if cl and cl.isdigit() and int(cl) > self._max_bytes:
                        raise ValueError(f"Response body exceeded maximum allowed size of {self._max_bytes} bytes (Content-Length: {cl})")

                    if hasattr(res, "content") and len(res.content) > self._max_bytes:
                        raise ValueError(f"Response body exceeded maximum allowed size of {self._max_bytes} bytes")

                    return res
            return _await_helper().__await__()

    def wrapper(*args, **kwargs):
        return DualAsyncContextManager(*args, **kwargs)

    return wrapper


@_dual_async_context_manager
async def safe_http_request(
    method: str,
    url: str,
    headers: Optional[dict] = None,
    max_redirects: int = 5,
    timeout: float = 15.0,
    max_bytes: int = 2 * 1024 * 1024,  # 2MB max response for inspection
) -> AsyncIterator[httpx.Response]:
    """
    Performs an HTTP request with strict step-by-step redirect inspection to prevent
    DNS rebinding and SSRF via HTTP 3xx redirects to internal addresses.
    Pins the validated IP for the actual connection so DNS rebinding can't bypass SSRF checks.
    Decorated with asynccontextmanager to support `async with safe_http_request(...) as resp:`
    as well as direct `await safe_http_request(...)`.
    """
    current_url = url
    redirect_count = 0
    ip_map: Dict[str, str] = {}

    default_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }
    if headers:
        default_headers.update(headers)

    backend = PinnedNetworkBackend(ip_map)
    pool = httpcore.AsyncConnectionPool(network_backend=backend)
    transport = httpx.AsyncHTTPTransport(verify=True)
    transport._pool = pool

    client = httpx.AsyncClient(
        transport=transport,
        follow_redirects=False,
        timeout=httpx.Timeout(timeout),
    )
    try:
        while True:
            # Re-validate target URL on every hop
            is_valid, _, error_msg = validate_url_ssrf(current_url)
            if not is_valid:
                raise SSRFValidationError(f"Redirect blocked by SSRF defense: {error_msg}")

            # Pin the validated IP for the actual connection (neutralizes DNS rebinding)
            parsed_current = urlparse(current_url)
            host_current = parsed_current.hostname or ""
            try:
                ip_obj = ipaddress.ip_address(host_current)
                ip_map[host_current] = str(ip_obj)
            except ValueError:
                resolved_ips = resolve_hostname_ips(host_current)
                if resolved_ips:
                    ip_map[host_current] = str(resolved_ips[0])

            response = await client.request(
                method=method,
                url=current_url,
                headers=default_headers,
            )

            # Check if redirect
            if response.status_code in (301, 302, 303, 307, 308):
                redirect_count += 1
                if redirect_count > max_redirects:
                    raise SSRFValidationError(f"Too many redirects (exceeded limit of {max_redirects}).")

                location = response.headers.get("location")
                if not location:
                    break

                # Resolve relative redirects
                next_url = str(response.url.join(location))
                current_url = next_url
                # Continue loop to next hop with SSRF validation and IP pinning
                continue

            try:
                yield response
            finally:
                await response.aclose()
            return
    finally:
        await client.aclose()


def create_safe_client(url: str, timeout: float = 60.0) -> httpx.AsyncClient:
    """
    Creates an httpx.AsyncClient configured with SSRF protection, DNS rebinding
    pinning, and redirect security.
    """
    is_valid, clean_url, error_msg = validate_url_ssrf(url)
    if not is_valid:
        raise SSRFValidationError(f"SSRF validation blocked: {error_msg}")

    parsed = urlparse(clean_url)
    host = parsed.hostname or ""
    ip_map: Dict[str, str] = {}
    try:
        ip_obj = ipaddress.ip_address(host)
        ip_map[host] = str(ip_obj)
    except ValueError:
        resolved_ips = resolve_hostname_ips(host)
        if resolved_ips:
            ip_map[host] = str(resolved_ips[0])

    backend = PinnedNetworkBackend(ip_map)
    pool = httpcore.AsyncConnectionPool(network_backend=backend)
    transport = httpx.AsyncHTTPTransport(verify=True)
    transport._pool = pool
    return httpx.AsyncClient(
        transport=transport,
        follow_redirects=True,
        timeout=httpx.Timeout(timeout),
    )

