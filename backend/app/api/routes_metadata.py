import json
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse
from ..models.schemas import UrlMetadataRequest, MediaMetadataResponse
from ..security.ssrf_validator import SSRFValidationError
from ..security.rate_limiter import check_metadata_rate_limit, get_client_ip
from ..security.sanitizer import sanitize_for_logging
from ..services.extractor import media_extractor

logger = logging.getLogger("mediagrab.metadata")
router = APIRouter(prefix="/api", tags=["metadata"])


@router.post(
    "/metadata",
    response_model=MediaMetadataResponse,
    dependencies=[Depends(check_metadata_rate_limit)],
    summary="Extract metadata and available formats for a URL (REST)"
)
async def extract_url_metadata(payload: UrlMetadataRequest, request: Request):
    client_ip = get_client_ip(request)
    clean_url_log = sanitize_for_logging(payload.url)
    logger.info(f"Metadata request from {client_ip} for URL: {clean_url_log}")

    try:
        metadata = await media_extractor.extract_metadata(payload.url)
        return metadata
    except SSRFValidationError as e:
        logger.warning(f"SSRF violation blocked for IP {client_ip}: {sanitize_for_logging(str(e))}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Security Alert: {str(e)}"
        )
    except TimeoutError as e:
        logger.warning(f"Extraction timeout for IP {client_ip}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(e)
        )
    except ValueError as e:
        logger.info(f"Extraction failed for IP {client_ip}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Internal extraction error for IP {client_ip}: {sanitize_for_logging(str(e))}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the media stream."
        )


@router.get(
    "/metadata/stream",
    dependencies=[Depends(check_metadata_rate_limit)],
    summary="Stream extraction stages and metadata via Server-Sent Events (SSE)"
)
async def stream_metadata_extraction(url: str, request: Request):
    """
    Real-time SSE stream providing stage-by-stage status as each extraction tier executes.
    Shows the user:
    - Tier 1: Trying standard extraction (yt-dlp)...
    - Tier 2: Checking direct media headers...
    - Tier 3: Scanning page HTML for embedded media...
    - Tier 4: Launching headless browser render (Playwright)...
    """
    client_ip = get_client_ip(request)
    clean_url_log = sanitize_for_logging(url)
    logger.info(f"Streaming metadata request from {client_ip} for URL: {clean_url_log}")

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()

        async def status_callback(tier: int, stage: str, message: str):
            await queue.put({
                "type": "stage",
                "tier": tier,
                "stage": stage,
                "message": message,
            })

        async def worker():
            try:
                meta = await media_extractor.extract_metadata(url, status_callback=status_callback)
                await queue.put({
                    "type": "result",
                    "metadata": meta.model_dump()
                })
            except SSRFValidationError as e:
                await queue.put({
                    "type": "error",
                    "error": f"Security Alert: {str(e)}",
                    "is_ssrf": True,
                })
            except TimeoutError as e:
                await queue.put({
                    "type": "error",
                    "error": str(e),
                    "is_timeout": True,
                })
            except ValueError as e:
                await queue.put({
                    "type": "error",
                    "error": str(e),
                })
            except Exception as e:
                await queue.put({
                    "type": "error",
                    "error": "An error occurred while processing the media stream.",
                })
            finally:
                await queue.put(None)

        task = asyncio.create_task(worker())

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
