from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import os
import logging
import time
from collections import defaultdict, deque
from schemas.api import DownloadResponse, InfoResponse, RootResponse, ErrorResponse
from services.facebook_downloader import FacebookDownloader, DownloaderError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Facebook Video Downloader API",
    description="Reliable API for downloading Facebook videos and reels",
    version="2.0.0",
)

# CORS for your website
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.shopyor.com",
        "http://localhost:3000",
        "http://localhost:8000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

downloader = FacebookDownloader()
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "60"))
request_buckets = defaultdict(deque)


@app.middleware("http")
async def request_guard(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    bucket = request_buckets[client_ip]

    while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
        return JSONResponse(
            status_code=429,
            content=ErrorResponse(
                error_type="RATE_LIMITED",
                message=f"Too many requests. Limit: {RATE_LIMIT_MAX_REQUESTS}/{RATE_LIMIT_WINDOW_SECONDS}s",
            ).model_dump(),
        )
    bucket.append(now)

    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "request path=%s status=%s ip=%s duration_ms=%.2f",
        request.url.path,
        response.status_code,
        client_ip,
        elapsed_ms,
    )
    return response

@app.get("/")
async def root() -> RootResponse:
    return RootResponse(
        message="Facebook Video Downloader API",
        version="2.0.0",
        endpoints={
            "/download": "GET - Get video download URL",
            "/info": "GET - Get video information",
            "/health": "GET - Health check",
        },
    )

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "facebook-video-downloader"}

@app.get("/download", responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 502: {"model": ErrorResponse}})
async def download_video(
    url: str = Query(..., description="Facebook video/reel/watch/share URL"),
    quality: str = Query("best", description="Quality: 360p, 480p, 720p, 1080p, best"),
) -> DownloadResponse:
    if not url.strip():
        raise HTTPException(status_code=400, detail="url is required")

    try:
        video_data = downloader.extract(url, quality)
        return DownloadResponse(
            success=True,
            message="Video retrieved successfully",
            data=video_data,
        )
    except DownloaderError as exc:
        logger.warning("Download extraction failed: %s", exc)
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error_type=exc.error_type,
                message=exc.message,
            ).model_dump(),
        )

@app.get("/info", responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 502: {"model": ErrorResponse}})
async def get_info(
    url: str = Query(..., description="Facebook video/reel/watch/share URL"),
) -> InfoResponse:
    if not url.strip():
        raise HTTPException(status_code=400, detail="url is required")

    try:
        info = downloader.extract_info(url)
        return InfoResponse(success=True, **info)
    except DownloaderError as exc:
        logger.warning("Info extraction failed: %s", exc)
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error_type=exc.error_type,
                message=exc.message,
            ).model_dump(),
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)