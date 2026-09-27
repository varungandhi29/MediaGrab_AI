from fastapi import APIRouter
from pydantic import BaseModel
from ..models.schemas import (
    AiRecommendationRequest,
    AiRecommendationResponse,
    AiErrorExplanationRequest,
    AiErrorExplanationResponse,
)
from ..services.ai_assistant import ai_assistant, detect_platform_from_url

router = APIRouter(prefix="/api/ai", tags=["ai"])


class PlatformDetectionRequest(BaseModel):
    url: str


@router.post("/detect")
async def detect_platform(payload: PlatformDetectionRequest):
    return detect_platform_from_url(payload.url)


@router.post("/recommend", response_model=AiRecommendationResponse)
async def recommend_format(payload: AiRecommendationRequest):
    return await ai_assistant.get_recommendation(
        url=payload.url,
        use_case=payload.use_case,
        available_qualities=payload.available_qualities,
    )


@router.post("/explain-error", response_model=AiErrorExplanationResponse)
async def explain_error(payload: AiErrorExplanationRequest):
    return await ai_assistant.explain_error(
        url=payload.url,
        raw_error=payload.raw_error,
    )
