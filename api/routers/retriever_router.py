"""
知识库检索路由
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from models.retriever_schemas import RetrieveRequest, RetrieveResponse
from services.retriever_service import retriever_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/retriever", tags=["知识库检索"])


@router.post("/{project_id}", response_model=RetrieveResponse, summary="知识库检索")
async def retrieve(
    project_id: int,
    request: RetrieveRequest,
    session: AsyncSession = Depends(get_session),
) -> RetrieveResponse:
    """
    针对指定项目执行知识库检索。

    - **project_id**: 项目 ID（路径参数）
    - **query**: 查询问题（请求体）
    """
    try:
        data = await retriever_service.retrieve(
            session=session,
            project_id=project_id,
            query=request.query,
        )
        return RetrieveResponse(**data)
    except HTTPException:
        # 已包装过的异常直接抛出
        raise
    except Exception as e:
        logger.exception(f"知识库检索时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"检索失败: {e}")

