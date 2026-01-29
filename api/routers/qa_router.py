"""
问答（QA）路由
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from models.qa_schemas import QARequest, QAResponse
from services.qa_service import qa_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/qa", tags=["问答"])


@router.post("/{project_id}", response_model=QAResponse, summary="问答")
async def qa(
    project_id: int,
    request: QARequest,
    session: AsyncSession = Depends(get_session),
) -> QAResponse:
    """
    针对指定项目执行问答。

    - **project_id**: 项目 ID（路径参数）
    - **query**: 用户问题（请求体）
    """
    try:
        data = await qa_service.qa(
            session=session,
            project_id=project_id,
            query=request.query,
        )
        return QAResponse(**data)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"问答时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"问答失败: {e}")
