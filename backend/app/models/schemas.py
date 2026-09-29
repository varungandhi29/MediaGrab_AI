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
    height: Optional[int] = Field(default=None, description="Numeric height for player quality selection e.g. 720, 1080")
    is_audio_only: bool = Field(default=False)
    is_hls: bool = Field(default=False, description="True if stream is HLS manifest")
    stream_url: Optional[str] = Field(default=None, description="Backend proxy URL for in-browser streaming")
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    is_browser_compatible: bool = Field(default=True, description="False if codec or container requires transcoding for in-browser playback")
    mime_type: Optional[str] = None


class SubtitleTrack(BaseModel):
    lang: str = Field(..., description="ISO language code, e.g. 'en', 'es', 'ja'")
    name: str = Field(..., description="Human-readable language name, e.g. 'English', 'Spanish'")
    ext: str = Field(default="vtt", description="Subtitle format, typically 'vtt' or 'srt'")
    url: str = Field(..., description="Source subtitle URL")
    proxy_url: Optional[str] = Field(default=None, description="CORS-safe proxy URL for in-browser video player tracks")


class MediaMetadataResponse(BaseModel):
    url: str
    platform: str
    title: str
    thumbnail: Optional[str] = None
    thumbnail_proxy: Optional[str] = None
    duration_seconds: Optional[float] = None
    duration_formatted: Optional[str] = None
    uploader: Optional[str] = None
    description: Optional[str] = None
    available_qualities: List[MediaQualityOption]
    subtitles: List[SubtitleTrack] = []
    source_type: str  # 'ytdlp', 'direct', 'scraped', or 'headless_browser'
    extraction_tier: int  # 1, 2, 3, or 4
    stream_session_id: Optional[str] = None
    is_hls: bool = Field(default=False)


class DownloadRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    quality_label: str
    format_id: str
    is_audio_only: bool = False
    target_format: str = "mp4"
    start_time: Optional[str] = Field(default=None, description="Clip start timestamp (e.g. '00:00:10')")
    end_time: Optional[str] = Field(default=None, description="Clip end timestamp (e.g. '00:01:15')")


class DownloadJobResponse(BaseModel):
    job_id: str
    id: Optional[str] = None
    status: str  # pending, downloading, converting, completed, ready, failed
    progress_percent: float = 0.0
    speed: str = "0 KB/s"
    eta: str = "--:--"
    error_message: Optional[str] = None
    download_token: Optional[str] = None
    filename: Optional[str] = None
    filesize: Optional[int] = None
    output_path: Optional[str] = None
    error_class: Optional[str] = None
    user_message: Optional[str] = None
    debug: Optional[str] = None


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
    error_class: Optional[str] = None
    what_happened: Optional[str] = None
    what_to_try: Optional[List[str]] = None
    can_retry: Optional[bool] = None
    debug_info: Optional[dict] = None


class MediaPrepareRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    quality_label: Optional[str] = "Best"
    format_id: Optional[str] = None
    height: Optional[int] = None
    is_audio_only: bool = False
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class MediaPrepareJobResponse(BaseModel):
    job_id: str
    id: Optional[str] = None
    stage: str  # resolving, downloading, preparing, ready, failed
    status: Optional[str] = None
    progress_percent: float = 0.0
    speed: str = "0 KB/s"
    eta: str = "--:--"
    error_message: Optional[str] = None
    token: Optional[str] = None
    stream_url: Optional[str] = None
    download_url: Optional[str] = None
    filename: Optional[str] = None
    filesize: Optional[int] = None
    title: Optional[str] = None
    quality_label: Optional[str] = None
    duration_seconds: Optional[float] = None
    output_path: Optional[str] = None
    error_class: Optional[str] = None
    user_message: Optional[str] = None
    debug: Optional[str] = None
    quality_label: Optional[str] = None
    duration_seconds: Optional[float] = None


class LinkPreCheckRequest(BaseModel):
    url: str = Field(..., max_length=2048)


class LinkPreCheckResponse(BaseModel):
    url: str
    domain: str
    status: str  # "supported_site", "direct_media", "unsupported_file_sharing", "unsupported_drm", "invalid"
    label: str   # "Supported site", "Direct video file", "Probably unsupported (file-sharing page)", "Not a valid link"
    platform_name: str
    can_extract: bool
    explanation: str
    alternatives: List[str] = []
    error_class: Optional[str] = None


class LinkReportRequest(BaseModel):
    domain: str
    url: Optional[str] = None
    error_class: str
    job_id: Optional[str] = None
    tier_results: Optional[dict] = None
    comment: Optional[str] = None


class RatingFeedbackRequest(BaseModel):
    job_id: Optional[str] = None
    domain: str
    rating: str  # "up" or "down"
    action: str = "play"  # "play" or "download"


