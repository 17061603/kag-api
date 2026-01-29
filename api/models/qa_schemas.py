"""
QA 请求和响应模型
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class QARequest(BaseModel):
    """问答请求（对齐 baike/solver/qa.py：仅 query）"""

    query: str = Field(..., description="用户问题")


class QAResponse(BaseModel):
    """问答响应"""

    answer: str = Field(..., description="模型生成的答案")
    trace: Optional[Dict[str, Any]] = Field(
        default=None,
        description="执行 trace（decompose、thinker、generator、reference 等）",
    )
