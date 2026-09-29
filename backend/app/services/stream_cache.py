import time
import uuid
import asyncio
from typing import Dict, Any, Optional
from ..security.ssrf_validator import validate_url_ssrf, SSRFValidationError


class StreamCacheManager:
    """
    Caches extracted format stream URLs and proxies them safely.
    Prevents leaking raw third-party CDN URLs to the browser and handles
    stream token refresh/expiration.
    """
import json
import logging
from pathlib import Path
from ..config import settings

logger = logging.getLogger("mediagrab.stream_cache")


class StreamCacheManager:
    """
    Caches extracted format stream URLs and proxies them safely.
    Prevents leaking raw third-party CDN URLs to the browser and handles
    stream token refresh/expiration.
    Persists sessions to disk so server restarts/reloads do not invalidate active streams.
    """
    def __init__(self, default_ttl_seconds: int = 3600):  # 60 mins default
        self.default_ttl = default_ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._source_url_index: Dict[str, str] = {}  # token -> source_url (permanent)
        self._lock = asyncio.Lock()
        self._storage_file = settings.STORAGE_DIR / "stream_sessions.json"
        self._load_from_disk()

    def _load_from_disk(self):
        try:
            if self._storage_file.exists():
                with open(self._storage_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    now = time.time()
                    for token, rec in data.get("cache", {}).items():
                        # Keep sessions that are not older than 24 hours
                        if rec.get("created_at", 0) > (now - 86400):
                            self._cache[token] = rec
                    self._source_url_index = data.get("source_urls", {})
        except Exception as e:
            logger.warning(f"Could not load stream sessions from disk: {e}")

    def _save_to_disk(self):
        try:
            settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            with open(self._storage_file, "w", encoding="utf-8") as f:
                json.dump({
                    "cache": self._cache,
                    "source_urls": self._source_url_index,
                }, f)
        except Exception as e:
            logger.warning(f"Could not persist stream sessions to disk: {e}")

    async def register_stream_session(
        self,
        source_url: str,
        streams_by_quality: Dict[str, Dict[str, Any]],
        title: str = "Media Stream"
    ) -> str:
        """
        Registers a stream session mapping quality keys to sanitized stream endpoints.
        """
        token = uuid.uuid4().hex
        now = time.time()

        record = {
            "token": token,
            "source_url": source_url,
            "title": title,
            "created_at": now,
            "expires_at": now + self.default_ttl,
            "streams": streams_by_quality,
        }

        async with self._lock:
            # Clean expired tokens periodically (keep last 2 hours)
            cutoff = now - 7200
            expired = [t for t, rec in self._cache.items() if rec["expires_at"] < cutoff]
            for t in expired:
                del self._cache[t]

            self._cache[token] = record
            self._source_url_index[token] = source_url
            self._save_to_disk()

        return token

    async def get_stream_target(
        self,
        token: str,
        quality_key: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves the verified upstream stream URL and headers for a specific quality.
        Validates target against SSRF before returning.
        Gracefully falls back to closest available quality so playback never breaks.
        """
        async with self._lock:
            record = self._cache.get(token)
            if not record:
                # Try reloading from disk in case another worker saved it
                self._load_from_disk()
                record = self._cache.get(token)

            if not record:
                return None

            now = time.time()
            # If expired, check if we can still try or fallback
            if record["expires_at"] < now - 3600:
                # Truly obsolete (> 1 hr expired)
                return None

            stream_info = record["streams"].get(quality_key)
            if not stream_info:
                # Fallback to key without 'p' or with 'p'
                alt_key = quality_key[:-1] if quality_key.endswith("p") else f"{quality_key}p"
                stream_info = record["streams"].get(alt_key)

            if not stream_info:
                is_audio_req = quality_key == "audio"
                if is_audio_req:
                    # Look for audio stream
                    stream_info = record["streams"].get("audio")
                else:
                    # Look for closest video stream (never fall back to audio-only stream for video)
                    video_candidates = [
                        (k, s) for k, s in record["streams"].items()
                        if k != "audio" and not s.get("is_audio_only")
                    ]
                    if video_candidates:
                        # Try to match closest height if quality_key has numeric height
                        numeric_target = int(quality_key[:-1]) if (quality_key.endswith("p") and quality_key[:-1].isdigit()) else (int(quality_key) if quality_key.isdigit() else None)
                        if numeric_target:
                            # Sort by distance to numeric_target
                            def dist(item):
                                h = item[1].get("height")
                                return abs(h - numeric_target) if (h and isinstance(h, int)) else 9999
                            video_candidates.sort(key=dist)
                        stream_info = video_candidates[0][1]

            if not stream_info and record["streams"]:
                stream_info = next(iter(record["streams"].values()))

            if not stream_info:
                return None

            target_url = stream_info.get("url")
            if not target_url:
                return None

            # Enforce SSRF validation on upstream stream URL
            is_valid, clean_target, err = validate_url_ssrf(target_url)
            if not is_valid:
                raise SSRFValidationError(f"Stream target violates SSRF policy: {err}")

            clean_audio_url = None
            raw_audio_url = stream_info.get("audio_url")
            if raw_audio_url:
                a_valid, clean_a_target, _ = validate_url_ssrf(raw_audio_url)
                if a_valid:
                    clean_audio_url = clean_a_target

            return {
                "target_url": clean_target,
                "headers": stream_info.get("headers", {}),
                "mime": stream_info.get("mime", "video/mp4"),
                "is_hls": stream_info.get("is_hls", False),
                "source_url": record.get("source_url"),
                "title": record.get("title"),
                "created_at": record.get("created_at"),
                "expires_at": record.get("expires_at"),
                "has_audio": stream_info.get("has_audio", True),
                "audio_url": clean_audio_url,
                "audio_headers": stream_info.get("audio_headers", {}),
                "vcodec": stream_info.get("vcodec"),
                "acodec": stream_info.get("acodec"),
                "height": stream_info.get("height"),
            }

    async def get_session_source_url(self, token: str) -> Optional[str]:
        """Returns the original media page URL associated with this stream session."""
        async with self._lock:
            record = self._cache.get(token)
            if record and record.get("source_url"):
                return record.get("source_url")
            if token in self._source_url_index:
                return self._source_url_index[token]
            self._load_from_disk()
            record = self._cache.get(token)
            if record and record.get("source_url"):
                return record.get("source_url")
            return self._source_url_index.get(token)

    async def update_stream_session(
        self,
        token: str,
        streams_by_quality: Dict[str, Dict[str, Any]],
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """
        Updates the upstream stream targets for an existing session token.
        Extends TTL to give playback a fresh expiration window.
        """
        now = time.time()
        ttl = ttl_seconds or self.default_ttl
        async with self._lock:
            if token not in self._cache:
                self._load_from_disk()
            if token not in self._cache:
                return False
            self._cache[token]["streams"] = streams_by_quality
            self._cache[token]["expires_at"] = now + ttl
            self._save_to_disk()
            return True

    async def is_fresh(self, token: str, margin_seconds: int = 60) -> bool:
        """Checks if the stream session has at least margin_seconds before expiry."""
        async with self._lock:
            record = self._cache.get(token)
            if not record:
                self._load_from_disk()
                record = self._cache.get(token)
            if not record:
                return False
            return (record["expires_at"] - time.time()) > margin_seconds

    async def get_session_info(self, token: str) -> Optional[Dict[str, Any]]:
        """Returns session health and expiry information."""
        async with self._lock:
            record = self._cache.get(token)
            if not record:
                self._load_from_disk()
                record = self._cache.get(token)
            if not record:
                return None
            now = time.time()
            return {
                "token": token,
                "is_expired": record["expires_at"] <= now,
                "seconds_remaining": max(0.0, record["expires_at"] - now),
                "created_at": record.get("created_at"),
                "available_qualities": list(record.get("streams", {}).keys()),
                "source_url": record.get("source_url"),
            }


stream_cache = StreamCacheManager()
