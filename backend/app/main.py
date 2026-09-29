import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .api import routes_metadata, routes_download, routes_stream, routes_ai, routes_system, routes_resilience, routes_rum, media_routes, routes_auth
from .services.storage_manager import start_cleanup_worker
from .resilience import start_self_healing_scheduler, start_worker_supervisor_loop
from .resilience.synthetic_playback_monitor import synthetic_playback_monitor

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
)
logger = logging.getLogger("mediagrab.main")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Applies security headers to every HTTP response:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - Strict-Transport-Security
    - Content-Security-Policy
    - Referrer-Policy
    """
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        
        # CSP allows frontend assets while restricting dangerous sinks
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data: https: blob:; "
            "media-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self' ws: wss:;"
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: spawn storage cleanup, self-healing scheduler, worker supervisor, and synthetic playback monitor
    logger.info("Initializing MediaGrab AI server with SSRF protection, isolated subprocesses, self-healing resilience, and synthetic playback monitoring.")
    cleanup_task = asyncio.create_task(start_cleanup_worker())
    self_heal_task = asyncio.create_task(start_self_healing_scheduler())
    supervisor_task = asyncio.create_task(start_worker_supervisor_loop())
    synthetic_playback_task = asyncio.create_task(synthetic_playback_monitor.start_background_schedule())
    yield
    # Shutdown
    logger.info("Shutting down MediaGrab AI server...")
    cleanup_task.cancel()
    self_heal_task.cancel()
    supervisor_task.cancel()
    synthetic_playback_task.cancel()
    try:
        await asyncio.gather(cleanup_task, self_heal_task, supervisor_task, synthetic_playback_task, return_exceptions=True)
    except Exception:
        pass


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Universal media downloader with SSRF protection, subprocess sandboxing, and AI assistant.",
    lifespan=lifespan,
)

# Apply Security Headers
app.add_middleware(SecurityHeadersMiddleware)

# Apply CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Content-Length", "Retry-After", "Content-Range", "Accept-Ranges"],
)

# Include API Routers
app.include_router(routes_metadata.router)
app.include_router(routes_download.router)
app.include_router(routes_stream.router)
app.include_router(routes_ai.router)
app.include_router(routes_system.router)
app.include_router(routes_resilience.router)
app.include_router(routes_rum.router)
app.include_router(media_routes.router)
app.include_router(routes_auth.router)


@app.get("/jobs/{job_id}")
async def get_job_by_id(job_id: str):
    from .services.downloader import download_manager
    job = await download_manager.get_job(job_id)
    if not job:
        from .services.media_pipeline import media_pipeline
        job = await media_pipeline.get_job(job_id)
    if not job:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Job not found.")
    return job.to_dict()


@app.get("/api/jobs/{job_id}")
async def get_api_job_by_id(job_id: str):
    return await get_job_by_id(job_id)


import os
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# Check for production built frontend assets
frontend_dist_env = os.getenv("FRONTEND_DIST_DIR")
if frontend_dist_env:
    frontend_dist = Path(frontend_dist_env)
else:
    frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if frontend_dist.exists() and (frontend_dist / "index.html").exists():
    @app.exception_handler(404)
    async def spa_404_handler(request: Request, exc: StarletteHTTPException):
        if not request.url.path.startswith("/api") and (frontend_dist / "index.html").exists():
            return FileResponse(frontend_dist / "index.html")
        return JSONResponse(status_code=404, content={"detail": exc.detail or "Not Found"})

    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static_frontend")
else:
    @app.get("/")
    async def root():
        return {
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "operational",
            "ssrf_protection": "active",
            "docs_url": "/docs",
        }
