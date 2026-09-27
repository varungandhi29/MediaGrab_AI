import os
import time
import asyncio
from pathlib import Path
from typing import Dict, Optional, Any
from ..config import settings
from ..security.sanitizer import generate_storage_key, sanitize_download_filename


class StorageManager:
    """
    Manages temporary media file storage, token mapping, and automatic TTL deletion.
    All files are stored under unguessable UUIDs with zero user-supplied pathing.
    """
    def __init__(self):
        self._tokens: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def get_storage_path(self, storage_key: str) -> Path:
        return settings.STORAGE_DIR / storage_key

    async def register_download(
        self,
        token: str,
        storage_key: str,
        original_title: str,
        extension: str,
        filesize: int,
        client_ip: str,
    ) -> Dict[str, Any]:
        filepath = self.get_storage_path(storage_key)
        safe_filename = sanitize_download_filename(original_title, extension)

        record = {
            "token": token,
            "storage_key": storage_key,
            "filepath": str(filepath),
            "filename": safe_filename,
            "extension": extension,
            "filesize": filesize,
            "client_ip": client_ip,
            "created_at": time.time(),
        }

        async with self._lock:
            self._tokens[token] = record

        return record

    async def get_download(self, token: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            record = self._tokens.get(token)
            if not record:
                return None

            # Verify file exists on disk
            filepath = Path(record["filepath"])
            if not filepath.exists():
                del self._tokens[token]
                return None

            return record

    async def cleanup_expired_files(self):
        """
        Deletes files older than FILE_TTL_SECONDS from both disk and memory records.
        """
        now = time.time()
        ttl = settings.FILE_TTL_SECONDS
        cutoff = now - ttl

        async with self._lock:
            expired_tokens = []
            for token, record in self._tokens.items():
                if record["created_at"] < cutoff:
                    expired_tokens.append(token)
                    try:
                        filepath = Path(record["filepath"])
                        if filepath.exists():
                            filepath.unlink(missing_ok=True)
                    except Exception:
                        pass

            for token in expired_tokens:
                del self._tokens[token]

        # Also scan storage directory for any orphaned temporary files
        try:
            for item in settings.STORAGE_DIR.iterdir():
                if item.is_file():
                    stat = item.stat()
                    if stat.st_mtime < cutoff:
                        try:
                            item.unlink(missing_ok=True)
                        except Exception:
                            pass
        except Exception:
            pass


storage_manager = StorageManager()


async def start_cleanup_worker():
    """Background task running continuously to clean up expired media files."""
    while True:
        try:
            await asyncio.sleep(settings.CLEANUP_INTERVAL_SECONDS)
            await storage_manager.cleanup_expired_files()
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(60)
