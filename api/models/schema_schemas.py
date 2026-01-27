"""
Schema相关的请求和响应模型
"""
from pydantic import BaseModel


class SchemaCommitResponse(BaseModel):
    """Schema提交响应模型"""
    success: bool
    message: str
    is_altered: bool

