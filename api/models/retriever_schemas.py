"""
Retriever 请求和响应模型
"""
from typing import Any, Dict
from pydantic import BaseModel, Field


class RetrieveRequest(BaseModel):
    """知识库检索请求"""

    query: str = Field(..., description="查询问题")


class RetrieveResponse(BaseModel):
    """知识库检索响应"""

    summary: str = Field(..., description="答案摘要")
    references: Dict[str, Any] = Field(
        ..., description="检索到的参考信息（文档片段、SPO 等）"
    )

