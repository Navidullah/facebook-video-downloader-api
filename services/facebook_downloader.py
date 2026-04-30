from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
import os
import time
import yt_dlp


QUALITY_HEIGHT_LIMITS = {
    "360p": 360,
    "480p": 480,
    "720p": 720,
    "1080p": 1080,
    "best": None,
}

FACEBOOK_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "mbasic.facebook.com",
    "fb.watch",
}


class DownloaderError(Exception):
    def __init__(self, message: str, error_type: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.status_code = status_code


class FacebookDownloader:
    def __init__(self) -> None:
        self._ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "noplaylist": True,
            "socket_timeout": 30,
        }
        self._cache_enabled = os.getenv("ENABLE_METADATA_CACHE", "true").lower() == "true"
        self._cache_ttl_seconds = int(os.getenv("METADATA_CACHE_TTL_SECONDS", "180"))
        self._metadata_cache: Dict[str, Tuple[float, Dict]] = {}

    def extract(self, url: str, quality: str = "best") -> Dict:
        normalized_url = self._normalize_facebook_url(url)
        info = self._extract_info_dict(normalized_url)
        formats = self._collect_formats(info)
        selected = self._select_best_format(formats, quality)

        if not selected or not selected.get("url"):
            raise DownloaderError(
                "No downloadable video stream found for this URL.",
                error_type="NO_DOWNLOADABLE_STREAM",
                status_code=404,
            )

        return {
            "title": info.get("title", "Facebook Video"),
            "video_url": selected["url"],
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "quality": selected["quality"],
        }

    def extract_info(self, url: str) -> Dict:
        normalized_url = self._normalize_facebook_url(url)
        info = self._get_cached_info(normalized_url)
        formats = self._collect_formats(info)
        return {
            "title": info.get("title", "Facebook Video"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "available_qualities": formats,
        }

    def _get_cached_info(self, normalized_url: str) -> Dict:
        if self._cache_enabled:
            cached = self._metadata_cache.get(normalized_url)
            if cached:
                cached_at, payload = cached
                if time.time() - cached_at <= self._cache_ttl_seconds:
                    return payload

        info = self._extract_info_dict(normalized_url)
        if self._cache_enabled:
            self._metadata_cache[normalized_url] = (time.time(), info)
        return info

    def _extract_info_dict(self, url: str) -> Dict:
        try:
            with yt_dlp.YoutubeDL(self._ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:
            raise DownloaderError(
                f"Extraction failed: {exc}",
                error_type="EXTRACTION_FAILED",
                status_code=502,
            ) from exc

        # Some links resolve into entries; pick the first playable entry.
        if info and info.get("entries"):
            entries = [entry for entry in info["entries"] if entry]
            if not entries:
                raise DownloaderError(
                    "Facebook link resolved but had no playable entries.",
                    error_type="NO_PLAYABLE_ENTRIES",
                    status_code=404,
                )
            info = entries[0]

        if not info:
            raise DownloaderError(
                "Could not extract media metadata from URL.",
                error_type="METADATA_NOT_FOUND",
                status_code=404,
            )
        return info

    def _normalize_facebook_url(self, raw_url: str) -> str:
        if not raw_url or not raw_url.strip():
            raise DownloaderError(
                "URL is required.",
                error_type="URL_REQUIRED",
                status_code=400,
            )

        parsed = urlparse(raw_url.strip())
        if parsed.scheme not in {"http", "https"}:
            raise DownloaderError(
                "URL must start with http:// or https://.",
                error_type="INVALID_URL_SCHEME",
                status_code=400,
            )

        host = parsed.netloc.lower()
        if host not in FACEBOOK_HOSTS:
            raise DownloaderError(
                "Only Facebook URLs are supported in this API.",
                error_type="UNSUPPORTED_HOST",
                status_code=422,
            )

        # Keep only useful params (e.g., story_fbid/id or v)
        query = parse_qs(parsed.query)
        safe_query = {
            key: values
            for key, values in query.items()
            if key in {"v", "story_fbid", "id"}
        }

        return urlunparse(
            (
                "https",
                host,
                parsed.path,
                "",
                urlencode(safe_query, doseq=True),
                "",
            )
        )

    def _collect_formats(self, info: Dict) -> List[Dict]:
        formats: List[Dict] = []
        seen: set[Tuple[str, str]] = set()

        for item in info.get("formats", []):
            url = item.get("url")
            if not url or item.get("vcodec") == "none":
                continue

            height = item.get("height")
            quality = f"{height}p" if height else "unknown"
            key = (quality, url)
            if key in seen:
                continue
            seen.add(key)

            formats.append(
                {
                    "quality": quality,
                    "url": url,
                    "filesize": item.get("filesize") or item.get("filesize_approx"),
                    "_height": height or 0,
                    "_has_audio": item.get("acodec") != "none",
                }
            )

        # Prefer higher quality first; audio-present formats rank first for same height.
        formats.sort(key=lambda f: (f["_height"], f["_has_audio"]), reverse=True)
        for item in formats:
            item.pop("_height", None)
            item.pop("_has_audio", None)
        return formats

    def _select_best_format(self, formats: List[Dict], quality: str) -> Optional[Dict]:
        normalized_quality = quality.lower().strip()
        if normalized_quality not in QUALITY_HEIGHT_LIMITS:
            normalized_quality = "best"

        max_height = QUALITY_HEIGHT_LIMITS[normalized_quality]
        if not formats:
            return None

        if max_height is None:
            return formats[0]

        for item in formats:
            height_str = item["quality"].replace("p", "")
            if height_str.isdigit() and int(height_str) <= max_height:
                return item

        # Fallback: return best available if lower/equal quality was not found.
        return formats[0]
