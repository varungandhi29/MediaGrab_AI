import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from ..services.rum_collector import rum_collector

logger = logging.getLogger("mediagrab.rum_api")
router = APIRouter(prefix="/api/system/rum", tags=["rum"])


class PlaybackTelemetryPayload(BaseModel):
    session_id: str
    browser: Optional[str] = "Other"
    os: Optional[str] = "Other"
    is_mobile: bool = False
    strategy: str = "native"
    ttff_ms: int = 0
    buffering_count: int = 0
    buffering_duration_ms: int = 0
    quality_switches: int = 0
    success: bool = True
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    source_domain: Optional[str] = "unknown"


@router.post(
    "/playback",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest anonymized in-browser playback telemetry (RUM)"
)
async def ingest_playback_telemetry(payload: PlaybackTelemetryPayload):
    """
    Ingests client playback telemetry to detect real-time browser playback breakages,
    buffering hotspots, and codec failure spikes without storing any PII.
    """
    await rum_collector.record_session(payload.model_dump())
    return {"status": "recorded"}


@router.get(
    "/summary",
    summary="Get aggregated playback health and RUM metrics"
)
async def get_rum_summary():
    """Returns aggregated playback statistics for operations dashboard."""
    return await rum_collector.get_summary()
