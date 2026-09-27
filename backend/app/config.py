import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

try:
    import imageio_ffmpeg
    DEFAULT_FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    DEFAULT_FFMPEG = "ffmpeg"


class Settings(BaseSettings):
    APP_NAME: str = "MediaGrab AI"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "production"  # or development
    DEBUG: bool = False

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Storage and TTL
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    STORAGE_DIR: Path = BASE_DIR / "storage" / "downloads"
    FILE_TTL_SECONDS: int = 3600  # 1 hour
    CLEANUP_INTERVAL_SECONDS: int = 300  # Check every 5 minutes

    # Security & Resource Limits
    MAX_URL_LENGTH: int = 2048
    MAX_FILE_SIZE_BYTES: int = 1024 * 1024 * 1024  # 1 GB
    MAX_CONCURRENT_DOWNLOADS_PER_IP: int = 2
    METADATA_RATE_LIMIT_REQUESTS: int = 30
    METADATA_RATE_LIMIT_WINDOW_SECONDS: int = 300  # 30 requests / 5 mins
    DOWNLOAD_RATE_LIMIT_REQUESTS: int = 10
    DOWNLOAD_RATE_LIMIT_WINDOW_SECONDS: int = 600  # 10 downloads / 10 mins

    # Fast-fail extraction tier timeouts (seconds)
    TIER1_YTDLP_TIMEOUT_SECONDS: int = 8
    TIER2_DIRECT_TIMEOUT_SECONDS: int = 5
    TIER3_STATIC_SCRAPE_TIMEOUT_SECONDS: int = 5
    TIER4_HEADLESS_TIMEOUT_SECONDS: int = 15
    TOTAL_EXTRACTION_TIMEOUT_SECONDS: int = 30
    DOWNLOAD_TIMEOUT_SECONDS: int = 600

    # Tool paths
    FFMPEG_LOCATION: str = os.getenv("FFMPEG_PATH", DEFAULT_FFMPEG)

    # AI Configuration (Optional API key, fallback heuristic engine always available)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    REDIS_URL: str = os.getenv("REDIS_URL", "")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
# Ensure download storage directory exists
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
