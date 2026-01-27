"""
文件相关的请求和响应模型
"""
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


class FileInfo(BaseModel):
    """文件信息模型"""
    id: int
    project_id: int
    filename: str
    original_filename: str
    file_path: str
    file_size: int
    mime_type: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}


class FileListResponse(BaseModel):
    """文件列表响应模型"""
    success: bool
    message: str
    files: List[FileInfo]
    total: int


class FileUploadResponse(BaseModel):
    """文件上传响应模型"""
    success: bool
    message: str
    file: FileInfo


class FileDeleteResponse(BaseModel):
    """文件删除响应模型"""
    success: bool
    message: str

