from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import requests
import re
import json
import os
from urllib.parse import urlparse, parse_qs
import logging

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Facebook Video Downloader API",
    description="API to download videos from Facebook",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class DownloadResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# Simplified video extraction that works
def extract_video_from_facebook(url: str) -> Dict[str, Any]:
    """Extract video URL from Facebook using multiple methods"""
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    try:
        # First, get the page content
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        html_content = response.text
        logger.debug(f"Got HTML content length: {len(html_content)}")
        
        # Method 1: Look for HD/SD source in JavaScript
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
        ]
        
        video_url = None
        for pattern in patterns:
            matches = re.findall(pattern, html_content)
            if matches:
                video_url = matches[0]
                # Clean the URL
                video_url = video_url.replace('\\/', '/')
                logger.info(f"Found video URL with pattern: {pattern}")
                break
        
        # Method 2: Look for video elements
        if not video_url:
            video_pattern = r'<meta property="og:video" content="([^"]+)"'
            match = re.search(video_pattern, html_content)
            if match:
                video_url = match.group(1)
                logger.info("Found video URL from og:video meta tag")
        
        # Method 3: Look for video URLs in page source
        if not video_url:
            mp4_patterns = [
                r'https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*',
                r'https?://video-[^\s"\'<>]+\.fbcdn\.net[^\s"\'<>]+',
                r'https?://[^\s"\'<>]+fbcdn\.net[^\s"\'<>]+\.mp4[^\s"\'<>]*'
            ]
            
            for pattern in mp4_patterns:
                matches = re.findall(pattern, html_content)
                if matches:
                    video_url = matches[0]
                    logger.info(f"Found video URL from mp4 pattern: {pattern}")
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
                'thumbnail': None,
                'duration': None
            }
        else:
            # Save HTML for debugging (optional)
            with open('debug.html', 'w', encoding='utf-8') as f:
                f.write(html_content)
            logger.error("No video URL found in HTML")
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
            'error': f"Error processing video: {str(e)}"
        }

@app.get("/")
async def root():
    return {
        "message": "Facebook Video Downloader API",
        "version": "1.0.0",
        "endpoints": {
            "/download": "GET - Download video info",
            "/health": "GET - Health check",
            "/extract-info": "GET - Extract basic info"
        }
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "facebook-video-downloader"}

@app.get("/download", response_model=DownloadResponse)
async def download_video(
    url: str = Query(..., description="Facebook video URL"),
    quality: Optional[str] = Query(None, description="Video quality (hd/sd)")
):
    """
    Download Facebook video from URL
    """
    logger.info(f"Download request for URL: {url}")
    
    try:
        # Validate URL
        if not url or 'facebook.com' not in url.lower():
            return DownloadResponse(
                success=False,
                message="Invalid Facebook URL",
                error="URL must contain facebook.com"
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
            
            return DownloadResponse(
                success=True,
                message="Video retrieved successfully",
                data=response_data
            )
        else:
            return DownloadResponse(
                success=False,
                message="Failed to extract video",
                error=result.get('error', 'Unknown error')
            )
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return DownloadResponse(
            success=False,
            message="Internal server error",
            error=str(e)
        )

@app.get("/download/direct")
async def direct_download(
    url: str = Query(..., description="Facebook video URL"),
    redirect: bool = Query(True, description="Redirect to video URL")
):
    """
    Direct download endpoint
    """
    result = await download_video(url)
    
    if result.success and result.data and result.data.get('video_url'):
        if redirect:
            return RedirectResponse(url=result.data['video_url'])
        else:
            return {"download_url": result.data['video_url'], "title": result.data.get('title')}
    else:
        raise HTTPException(status_code=400, detail=result.message)

@app.get("/extract-info")
async def extract_video_info(url: str = Query(..., description="Facebook video URL")):
    """
    Extract video information without download URL
    """
    try:
        # Extract video ID
        video_id_match = re.search(r'videos[/=](\d+)', url)
        if not video_id_match:
            video_id_match = re.search(r'reel[/=](\d+)', url)
        
        video_id = video_id_match.group(1) if video_id_match else None
        
        # Get page title
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title = soup.find('meta', property='og:title')
        thumbnail = soup.find('meta', property='og:image')
        
        return {
            "success": True,
            "video_id": video_id,
            "title": title.get('content') if title else "Facebook Video",
            "thumbnail": thumbnail.get('content') if thumbnail else None,
            "url": url
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)