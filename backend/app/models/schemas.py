from typing import List, Optional
from pydantic import BaseModel, Field


class UrlMetadataRequest(BaseModel):
    url: str = Field(..., max_length=2048, description="URL of the media to extract")


class MediaQualityOption(BaseModel):
    quality_label: str = Field(..., description="e.g. 480p, 720p, 1080p, 1440p (2K), 2160p (4K), Audio Only (MP3)")
    format_id: str = Field(..., description="Internal format selector id")
    ext: str = Field(default="mp4", description="Output file extension")
    filesize_approx: Optional[int] = Field(default=None, description="Filesize in bytes if known")
    filesize_display: Optional[str] = Field(default=None, description="Human readable filesize (e.g. 24.5 MB)")
    resolution: Optional[str] = Field(default=None, description="Resolution (e.g. 1920x1080)")
    is_audio_only: bool = Field(default=False)
    vcodec: Optional[str] = None
    acodec: Optional[str] = None


class MediaMetadataResponse(BaseModel):
    url: str
    platform: str
    title: str
    thumbnail: Optional[str] = None
    duration_seconds: Optional[float] = None
    duration_formatted: Optional[str] = None
    uploader: Optional[str] = None
    description: Optional[str] = None
    available_qualities: List[MediaQualityOption]
    source_type: str  # 'ytdlp', 'direct', or 'scraped'
    extraction_tier: int  # 1, 2, or 3


class DownloadRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    quality_label: str
    format_id: str
    is_audio_only: bool = False
    target_format: str = "mp4"


class DownloadJobResponse(BaseModel):
    job_id: str
    status: str  # pending, downloading, converting, completed, failed
    progress_percent: float = 0.0
    speed: str = "0 KB/s"
    eta: str = "--:--"
    error_message: Optional[str] = None
    download_token: Optional[str] = None
    filename: Optional[str] = None
    filesize: Optional[int] = None


class AiRecommendationRequest(BaseModel):
    url: str
    use_case: str = Field(..., description="e.g. 'mobile', 'archive', 'editing', 'podcast', 'low_data'")
    available_qualities: List[str] = []


class AiRecommendationResponse(BaseModel):
    detected_platform: str
    recommended_quality: str
    reason: str
    tips: List[str] = []


class AiErrorExplanationRequest(BaseModel):
    url: str
    raw_error: str


class AiErrorExplanationResponse(BaseModel):
    human_summary: str
    category: str  # e.g. "Private Video", "Geo-Blocked", "Rate Limited", "Unsupported", "SSRF Blocked"
    suggested_action: str
