from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
import requests
import re
import os
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Facebook Video Downloader API",
    description="API to download videos from Facebook",
    version="1.0.0"
)

# Read CORS origins from environment variable
ALLOWED_ORIGINS_ENV = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000")
ALLOWED_ORIGINS = [origin.strip() for origin in ALLOWED_ORIGINS_ENV.split(",")]

# Get environment
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

logger.info(f"Running in {ENVIRONMENT} mode")
logger.info(f"Allowed origins: {ALLOWED_ORIGINS}")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

def extract_video_from_facebook(url: str) -> Dict[str, Any]:
    """Extract video URL from Facebook"""
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        html_content = response.text
        
        # Look for video URLs
        patterns = [
            r'"hd_src":"([^"]+)"',
            r'"sd_src":"([^"]+)"',
            r'"browser_native_hd_url":"([^"]+)"',
            r'"browser_native_sd_url":"([^"]+)"',
            r'"playable_url":"([^"]+)"',
            r'video_url:"([^"]+)"',
        ]
        
        video_url = None
        for pattern in patterns:
            matches = re.findall(pattern, html_content)
            if matches:
                video_url = matches[0]
                video_url = video_url.replace('\\/', '/')
                logger.info(f"Found video URL with pattern: {pattern[:50]}")
                break
        
        # Extract title
        title_patterns = [
            r'<meta property="og:title" content="([^"]+)"',
            r'<title>([^<]+)</title>'
        ]
        
        title = "Facebook Video"
        for pattern in title_patterns:
            match = re.search(pattern, html_content)
            if match:
                title = match.group(1)
                break
        
        if video_url:
            return {
                'success': True,
                'title': title,
                'video_url': video_url,
            }
        else:
            # Save HTML for debugging (only in development)
            if ENVIRONMENT == "development":
                with open('debug.html', 'w', encoding='utf-8') as f:
                    f.write(html_content)
                logger.info("Saved debug.html for inspection")
            
            return {
                'success': False,
                'error': "Could not extract video URL. The video might be private or the page structure has changed."
            }
            
    except requests.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return {
            'success': False,
            'error': f"Failed to fetch video page: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

@app.get("/")
async def root():
    return {
        "message": "Facebook Video Downloader API",
        "version": "1.0.0",
        "status": "running",
        "environment": ENVIRONMENT,
        "allowed_origins": ALLOWED_ORIGINS,
        "endpoints": {
            "/download": "GET - Download video info",
            "/health": "GET - Health check",
            "/extract-info": "GET - Extract basic info"
        }
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "facebook-video-downloader",
        "environment": ENVIRONMENT,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/download")
async def download_video(
    request: Request,
    url: str = Query(..., description="Facebook video URL"),
):
    """Download Facebook video from URL"""
    
    # Log request details
    client_ip = request.client.host if request.client else "unknown"
    origin = request.headers.get("origin", "unknown")
    logger.info(f"Download request - IP: {client_ip}, Origin: {origin}, URL: {url[:100]}")
    
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
            return {
                "success": True,
                "message": "Video retrieved successfully",
                "data": {
                    'title': result['title'],
                    'video_url': result['video_url'],
                }
            }
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

@app.get("/download/direct")
async def direct_download(
    url: str = Query(..., description="Facebook video URL"),
    redirect: bool = Query(True, description="Redirect to video URL")
):
    """Direct download endpoint"""
    result = await download_video(url)
    
    if result.get('success') and result.get('data', {}).get('video_url'):
        video_url = result['data']['video_url']
        if redirect:
            return RedirectResponse(url=video_url)
        else:
            return {"download_url": video_url, "title": result['data'].get('title')}
    else:
        raise HTTPException(status_code=400, detail=result.get('message', 'Failed to get video'))

@app.get("/extract-info")
async def extract_video_info(url: str = Query(..., description="Facebook video URL")):
    """Extract basic video information"""
    try:
        video_id_match = re.search(r'videos[/=](\d+)', url)
        if not video_id_match:
            video_id_match = re.search(r'reel[/=](\d+)', url)
        
        video_id = video_id_match.group(1) if video_id_match else None
        
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        
        title_match = re.search(r'<title>([^<]+)</title>', response.text)
        title = title_match.group(1) if title_match else "Facebook Video"
        
        return {
            "success": True,
            "video_id": video_id,
            "title": title,
            "url": url
        }
        
    except Exception as e:
        logger.error(f"Extract info error: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)