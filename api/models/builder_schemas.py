"""
Builder相关的请求和响应模型
"""
from typing import Optional
from pydantic import BaseModel


class BuildKBResponse(BaseModel):
    """构建知识库响应模型"""
    success: bool
    message: str
    file_path: str


class BuildRequest(BaseModel):
    """构建知识库请求模型"""
    file_path: str
    namespace: str
    host_addr: Optional[str] = None
    num_processes: int = 2
    config_file: Optional[str] = "kag_config.yaml"


class BuildResponse(BaseModel):
    """构建知识库响应模型"""
    task_id: str
    status: str
    message: str


class TaskStatusResponse(BaseModel):
    """任务状态响应模型"""
    status: str
    message: str
    progress: int

