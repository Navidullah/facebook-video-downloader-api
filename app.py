from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import requests
import re
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Facebook Video Downloader API",
    description="API to download videos from Facebook",
    version="1.0.0"
)

# Rate limiting (simple in-memory store)
rate_limit_store = defaultdict(list)

def rate_limit_check(client_ip: str, max_requests: int = 10, time_window: int = 60):
    """Rate limiting: max_requests per time_window seconds"""
    now = time.time()
    window_start = now - time_window
    
    # Clean old requests
    rate_limit_store[client_ip] = [
        req_time for req_time in rate_limit_store[client_ip] 
        if req_time > window_start
    ]
    
    if len(rate_limit_store[client_ip]) >= max_requests:
        return False
    
    rate_limit_store[client_ip].append(now)
    return True

# Production CORS configuration
ALLOWED_ORIGINS = [
    "https://www.shopyor.com",
    "https://shopyor.com",
    "https://shopyor.onrender.com",  # If you use Render
    "http://localhost:3000",  # Local Next.js development
    "http://localhost:8000",   # Local API development
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],  # Only GET for downloading
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    max_age=3600,
)

# Optional: Add API key authentication
security = HTTPBearer(auto_error=False)

async def verify_api_key(credentials: Optional[HTTPAuthorizationCredentials] = None):
    """Optional API key verification"""
    api_key = os.getenv("API_KEY")
    if not api_key:  # If no API key is set, allow all requests
        return True
    
    if not credentials:
        return False
    
    return credentials.credentials == api_key

# Your existing video extraction functions here...
# (Keep all the extraction functions from previous code)

def extract_video_from_facebook(url: str) -> Dict[str, Any]:
    """Extract video URL from Facebook using multiple methods"""
    # ... (keep your existing implementation)
    pass

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses"""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Apply rate limiting"""
    client_ip = request.client.host if request.client else "unknown"
    
    # Skip rate limiting for health check
    if request.url.path == "/health":
        return await call_next(request)
    
    if not rate_limit_check(client_ip):
        return JSONResponse(
            status_code=429,
            content={
                "success": False,
                "message": "Too many requests. Please try again later.",
                "error": "Rate limit exceeded"
            }
        )
    
    return await call_next(request)

@app.get("/")
async def root():
    return {
        "message": "Facebook Video Downloader API",
        "version": "1.0.0",
        "endpoints": {
            "/download": "GET - Download video info",
            "/health": "GET - Health check",
            "/extract-info": "GET - Extract basic info"
        },
        "documentation": "/docs",
        "allowed_origins": ALLOWED_ORIGINS
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "facebook-video-downloader",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/download")
async def download_video(
    request: Request,
    url: str = Query(..., description="Facebook video URL"),
    quality: Optional[str] = Query(None, description="Video quality (hd/sd)")
):
    """
    Download Facebook video from URL
    """
    # Log request origin
    origin = request.headers.get("origin")
    logger.info(f"Download request from origin: {origin}, URL: {url}")
    
    # Validate origin (optional additional check)
    if origin and origin not in ALLOWED_ORIGINS and not origin.startswith("http://localhost"):
        logger.warning(f"Request from unauthorized origin: {origin}")
        # Still process but log warning (or you can block if needed)
    
    try:
        # Validate URL
        if not url or 'facebook.com' not in url.lower():
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "Invalid Facebook URL",
                    "error": "URL must contain facebook.com"
                }
            )
        
        # Extract video
        result = extract_video_from_facebook(url)
        
        if result.get('success'):
            response_data = {
                'title': result['title'],
                'video_url': result['video_url'],
                'thumbnail': result.get('thumbnail'),
                'duration': result.get('duration'),
                'selected_quality': quality or 'best'
            }
            
            return JSONResponse(content={
                "success": True,
                "message": "Video retrieved successfully",
                "data": response_data
            })
        else:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "message": "Failed to extract video",
                    "error": result.get('error', 'Unknown error')
                }
            )
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "Internal server error",
                "error": str(e)
            }
        )

# Keep your other endpoints (direct download, extract-info, etc.)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)