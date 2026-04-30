from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
import requests
import re
import os
import logging
import time
from datetime import datetime
from urllib.parse import urlparse, parse_qs

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

def normalize_facebook_url(url: str) -> str:
    """Convert different Facebook URL formats to a standard watch URL"""
    
    # Handle share URLs
    share_match = re.search(r'facebook\.com/share/v/([a-zA-Z0-9]+)', url)
    if share_match:
        video_id = share_match.group(1)
        return f"https://www.facebook.com/watch?v={video_id}"
    
    # Handle reel URLs
    reel_match = re.search(r'facebook\.com/reel/(\d+)', url)
    if reel_match:
        video_id = reel_match.group(1)
        return f"https://www.facebook.com/watch?v={video_id}"
    
    # Handle short URLs (fb.watch)
    if 'fb.watch' in url:
        try:
            # Follow redirect to get the actual URL
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, allow_redirects=True, timeout=10)
            return response.url
        except:
            pass
    
    return url

def extract_video_from_facebook(url: str) -> Dict[str, Any]:
    """Extract video URL from Facebook - Supports multiple URL formats"""
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
    }
    
    try:
        # First, normalize the URL
        original_url = url
        url = normalize_facebook_url(url)
        if url != original_url:
            logger.info(f"Normalized URL: {original_url} -> {url}")
        
        # Use session to handle redirects
        session = requests.Session()
        response = session.get(url, headers=headers, timeout=15, allow_redirects=True)
        response.raise_for_status()
        
        final_url = response.url
        html_content = response.text
        
        logger.info(f"Final URL after redirects: {final_url}")
        logger.info(f"HTML content length: {len(html_content)} characters")
        
        video_url = None
        
        # Method 1: Look for HD/SD source in JavaScript (most reliable)
        patterns = [
            r'"hd_src":"([^"]+)"',
            r'"sd_src":"([^"]+)"',
            r'"browser_native_hd_url":"([^"]+)"',
            r'"browser_native_sd_url":"([^"]+)"',
            r'"playable_url":"([^"]+)"',
            r'"playable_url_quality_hd":"([^"]+)"',
            r'hd_src_no_ratelimit:"([^"]+)"',
            r'sd_src_no_ratelimit:"([^"]+)"',
            r'video_url:"([^"]+)"',
            r'"downloadable_urls":\["([^"]+)"',
            r'https?://[^\s"\'<>]+\.fbcdn\.net[^\s"\'<>]+\.mp4',
            r'https?://video-[^\s"\'<>]+\.fbcdn\.net[^\s"\'<>]+',
            r'https?://[^\s"\'<>]+\.cdn\.facebook\.com[^\s"\'<>]+\.mp4',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html_content)
            if matches:
                video_url = matches[0] if isinstance(matches[0], str) else matches[0]
                video_url = video_url.replace('\\/', '/')
                # Clean up URL if it has escape sequences
                video_url = re.sub(r'\\(.)', r'\1', video_url)
                logger.info(f"Found video URL with pattern: {pattern[:50]}")
                break
        
        # Method 2: Look for og:video meta tag
        if not video_url:
            og_video = re.search(r'<meta property="og:video" content="([^"]+)"', html_content)
            if og_video:
                video_url = og_video.group(1)
                logger.info("Found video URL from og:video meta tag")
        
        # Method 3: Look for video elements in page
        if not video_url:
            video_tags = re.findall(r'<video[^>]+>(.*?)</video>', html_content, re.DOTALL)
            for video_tag in video_tags:
                src_match = re.search(r'<source[^>]+src="([^"]+)"', video_tag)
                if src_match:
                    video_url = src_match.group(1)
                    logger.info("Found video URL from video source tag")
                    break
                # Also check for src attribute on video tag itself
                video_src_match = re.search(r'<video[^>]+src="([^"]+)"', video_tag)
                if video_src_match:
                    video_url = video_src_match.group(1)
                    logger.info("Found video URL from video src attribute")
                    break
        
        # Method 4: Look for video in page data
        if not video_url:
            # Look for video ID and construct URL
            video_id_patterns = [
                r'video_id["\']\s*:\s*["\'](\d+)["\']',
                r'page_id["\']\s*:\s*["\'](\d+)["\'].*?video_id["\']\s*:\s*["\'](\d+)["\']',
                r'"video":{"id":"(\d+)"',
            ]
            
            for pattern in video_id_patterns:
                matches = re.findall(pattern, html_content, re.DOTALL)
                if matches:
                    if isinstance(matches[0], tuple):
                        video_id = matches[0][-1]  # Get last match if tuple
                    else:
                        video_id = matches[0]
                    logger.info(f"Found video ID: {video_id}")
                    # This is a fallback - the actual video URL should be found above
                    break
        
        # Extract title with better patterns
        title_patterns = [
            r'<meta property="og:title" content="([^"]+)"',
            r'<title>([^<]+)</title>',
            r'"title":"([^"]+)"',
        ]
        
        title = "Facebook Video"
        for pattern in title_patterns:
            match = re.search(pattern, html_content)
            if match:
                title = match.group(1)
                # Clean up title
                title = title.replace('&#xb7;', '·').replace('&#x202f;', ' ')
                title = title.replace('&#39;', "'").replace('&amp;', '&')
                break
        
        # Try to extract thumbnail
        thumbnail_patterns = [
            r'<meta property="og:image" content="([^"]+)"',
            r'"thumbnail_url":"([^"]+)"',
            r'"thumbnail":"([^"]+)"',
        ]
        
        thumbnail = None
        for pattern in thumbnail_patterns:
            match = re.search(pattern, html_content)
            if match:
                thumbnail = match.group(1)
                break
        
        if video_url:
            # Validate the video URL is accessible
            try:
                head_response = requests.head(video_url, timeout=5)
                if head_response.status_code == 200:
                    logger.info(f"Video URL is accessible (Status: {head_response.status_code})")
                else:
                    logger.warning(f"Video URL returned status: {head_response.status_code}")
            except:
                logger.warning("Could not verify video URL accessibility")
            
            return {
                'success': True,
                'title': title,
                'video_url': video_url,
                'thumbnail': thumbnail,
            }
        else:
            # Save debug HTML for analysis (only in development)
            if ENVIRONMENT == "development":
                debug_filename = f'debug_{int(time.time())}.html'
                with open(debug_filename, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                logger.info(f"Saved debug HTML to {debug_filename} for inspection")
            
            return {
                'success': False,
                'error': "Could not extract video URL. The video might be private, removed, or the URL format is not supported."
            }
            
    except requests.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return {
            'success': False,
            'error': f"Failed to fetch video page: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
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
        if not url or 'facebook.com' not in url.lower() and 'fb.watch' not in url.lower():
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "Invalid Facebook URL",
                    "error": "URL must contain facebook.com or fb.watch"
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
                    'thumbnail': result.get('thumbnail'),
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
    
    if isinstance(result, dict) and result.get('success') and result.get('data', {}).get('video_url'):
        video_url = result['data']['video_url']
        if redirect:
            return RedirectResponse(url=video_url)
        else:
            return {"download_url": video_url, "title": result['data'].get('title')}
    else:
        error_msg = result.get('message', 'Failed to get video') if isinstance(result, dict) else 'Failed to get video'
        raise HTTPException(status_code=400, detail=error_msg)

@app.get("/extract-info")
async def extract_video_info(url: str = Query(..., description="Facebook video URL")):
    """Extract basic video information"""
    try:
        # Try to extract video ID from various URL formats
        video_id = None
        
        # Pattern for share URLs
        share_match = re.search(r'share/v/([a-zA-Z0-9]+)', url)
        if share_match:
            video_id = share_match.group(1)
        
        # Pattern for reel URLs
        reel_match = re.search(r'reel[/=](\d+)', url)
        if reel_match:
            video_id = reel_match.group(1)
        
        # Pattern for videos
        video_match = re.search(r'videos[/=](\d+)', url)
        if video_match:
            video_id = video_match.group(1)
        
        # Pattern for watch URLs
        watch_match = re.search(r'watch\?v=(\d+)', url)
        if watch_match:
            video_id = watch_match.group(1)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        # Extract title
        title_match = re.search(r'<title>([^<]+)</title>', response.text)
        title = title_match.group(1) if title_match else "Facebook Video"
        title = title.replace('Facebook', '').strip()
        
        # Extract thumbnail if available
        thumbnail_match = re.search(r'<meta property="og:image" content="([^"]+)"', response.text)
        thumbnail = thumbnail_match.group(1) if thumbnail_match else None
        
        return {
            "success": True,
            "video_id": video_id,
            "title": title or "Facebook Video",
            "thumbnail": thumbnail,
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