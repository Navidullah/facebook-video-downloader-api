from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class VideoFormat(BaseModel):
    quality: str
    url: Optional[str] = None
    filesize: Optional[int] = None


class VideoData(BaseModel):
    title: str
    video_url: str
    thumbnail: Optional[str] = None
    duration: Optional[float] = None
    quality: str


class DownloadResponse(BaseModel):
    success: bool
    message: str
    data: VideoData


class InfoResponse(BaseModel):
    success: bool
    title: str
    thumbnail: Optional[str] = None
    duration: Optional[float] = None
    available_qualities: List[VideoFormat] = Field(default_factory=list)


class RootResponse(BaseModel):
    message: str
    version: str
    endpoints: Dict[str, str]


class ErrorResponse(BaseModel):
    success: bool = False
    error_type: str
    message: str
