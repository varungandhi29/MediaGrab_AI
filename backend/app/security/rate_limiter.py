import time
import math
import asyncio
from collections import defaultdict
from typing import Dict, List, Tuple
from fastapi import Request, HTTPException, status
from ..config import settings


class SlidingWindowRateLimiter:
    """
    In-memory Sliding Window Rate Limiter tracking timestamps per IP.
    Thread-safe and async-safe with automatic pruning.
    """
    def __init__(self, max_requests: int, window_seconds: int, name: str = "default"):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.name = name
        self._history: Dict[str, List[float]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._last_prune = time.time()

    async def is_allowed(self, client_ip: str) -> Tuple[bool, int, int]:
        """
        Checks whether client_ip is allowed under the sliding window.
        Returns:
            (allowed: bool, remaining: int, retry_after: int)
        """
        now = time.time()
        cutoff = now - self.window_seconds

        async with self._lock:
            # Prune ancient keys periodically (every 60 seconds)
            if now - self._last_prune > 60:
                self._prune_stale(cutoff)
                self._last_prune = now

            timestamps = self._history[client_ip]
            # Keep only timestamps in current sliding window
            valid_timestamps = [t for t in timestamps if t > cutoff]
            self._history[client_ip] = valid_timestamps

            if len(valid_timestamps) >= self.max_requests:
                # Calculate how long until the oldest timestamp slides out
                oldest = valid_timestamps[0]
                retry_after = max(1, math.ceil(oldest + self.window_seconds - now))
                return False, 0, retry_after

            # Record this hit
            valid_timestamps.append(now)
            remaining = self.max_requests - len(valid_timestamps)
            return True, remaining, 0

    def _prune_stale(self, cutoff: float):
        empty_keys = []
        for ip, t_list in self._history.items():
            self._history[ip] = [t for t in t_list if t > cutoff]
            if not self._history[ip]:
                empty_keys.append(ip)
        for ip in empty_keys:
            del self._history[ip]


class ConcurrentJobTracker:
    """
    Tracks and limits concurrent active media download jobs per IP.
    """
    def __init__(self, max_concurrent: int):
        self.max_concurrent = max_concurrent
        self._active: Dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def acquire(self, client_ip: str) -> bool:
        async with self._lock:
            current = self._active[client_ip]
            if current >= self.max_concurrent:
                return False
            self._active[client_ip] = current + 1
            return True

    async def release(self, client_ip: str):
        async with self._lock:
            if client_ip in self._active:
                self._active[client_ip] = max(0, self._active[client_ip] - 1)
                if self._active[client_ip] == 0:
                    del self._active[client_ip]

    async def get_active_count(self, client_ip: str) -> int:
        async with self._lock:
            return self._active.get(client_ip, 0)


# Initialize global limiters
metadata_limiter = SlidingWindowRateLimiter(
    max_requests=settings.METADATA_RATE_LIMIT_REQUESTS,
    window_seconds=settings.METADATA_RATE_LIMIT_WINDOW_SECONDS,
    name="metadata"
)

download_limiter = SlidingWindowRateLimiter(
    max_requests=settings.DOWNLOAD_RATE_LIMIT_REQUESTS,
    window_seconds=settings.DOWNLOAD_RATE_LIMIT_WINDOW_SECONDS,
    name="download"
)

concurrent_jobs_tracker = ConcurrentJobTracker(
    max_concurrent=settings.MAX_CONCURRENT_DOWNLOADS_PER_IP
)


def get_client_ip(request: Request) -> str:
    """
    Extracts client IP. Prioritizes X-Forwarded-For if behind a trusted proxy,
    falling back to client host.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take the leftmost untrusted IP
        client_ip = forwarded.split(",")[0].strip()
        return client_ip

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    if request.client and request.client.host:
        return request.client.host

    return "127.0.0.1"


async def check_metadata_rate_limit(request: Request):
    """FastAPI Dependency for Metadata Rate Limiting."""
    client_ip = get_client_ip(request)
    allowed, remaining, retry_after = await metadata_limiter.is_allowed(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for metadata requests. Please wait {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)}
        )


async def check_download_rate_limit(request: Request):
    """FastAPI Dependency for Download Rate Limiting & Concurrency."""
    client_ip = get_client_ip(request)

    # 1. Check concurrent jobs limit
    active = await concurrent_jobs_tracker.get_active_count(client_ip)
    if active >= settings.MAX_CONCURRENT_DOWNLOADS_PER_IP:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Maximum concurrent downloads ({settings.MAX_CONCURRENT_DOWNLOADS_PER_IP}) reached for your IP. Please wait for an existing download to finish."
        )

    # 2. Check sliding window limit
    allowed, remaining, retry_after = await download_limiter.is_allowed(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for downloads. Please wait {retry_after} seconds before starting new downloads.",
            headers={"Retry-After": str(retry_after)}
        )
