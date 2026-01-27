"""
Builder相关的请求和响应模型
"""
from pydantic import BaseModel


class BuildKBResponse(BaseModel):
    """构建知识库响应模型"""
    success: bool
    message: str
    file_path: str

