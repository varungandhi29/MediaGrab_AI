import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .api import routes_metadata, routes_download, routes_ai, routes_system
from .services.storage_manager import start_cleanup_worker

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
    # Startup: spawn storage cleanup background worker
    logger.info("Initializing MediaGrab AI server with SSRF protection and isolated subprocesses.")
    cleanup_task = asyncio.create_task(start_cleanup_worker())
    yield
    # Shutdown
    logger.info("Shutting down MediaGrab AI server...")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
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
    expose_headers=["Content-Disposition", "Content-Length", "Retry-After"],
)

# Include API Routers
app.include_router(routes_metadata.router)
app.include_router(routes_download.router)
app.include_router(routes_ai.router)
app.include_router(routes_system.router)


from pathlib import Path
from fastapi.staticfiles import StaticFiles

# Check for production built frontend assets
frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
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
