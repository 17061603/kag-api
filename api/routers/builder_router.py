import logging
from models.builder_schemas import (

    BuildResponse,
    TaskStatusResponse
)
from services.builder_service import builder_service
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession


from database.connection import get_session
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/build", tags=["知识库构建"])


@router.post("/{project_id}", response_model=BuildResponse, summary="构建知识库")
async def build_kb(
    project_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    构建知识库接口
    返回:
    - task_id: 任务ID
    - status: 任务状态
    - message: 消息
    """
    try:
        task_id = await builder_service.build_knowledge_base(
            session=session,
            project_id=project_id
        )
        return BuildResponse(
            task_id=task_id,
            status="started",
            message="知识库构建任务已启动"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in build_kb: {e}")
        raise HTTPException(status_code=500, detail=f"内部服务器错误: {e}")


@router.get("/status/{task_id}", response_model=TaskStatusResponse, summary="获取任务状态")
async def get_build_status(task_id: str):
    """
    获取任务状态接口
    
    参数说明:
    - task_id: 任务ID
    
    返回:
    - status: 任务状态（running/completed/failed）
    - message: 状态消息
    - progress: 进度（0-100）
    """
    try:
        status_info = builder_service.get_task_status(task_id)
        return TaskStatusResponse(**status_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_task_status: {e}")
        raise HTTPException(status_code=500, detail=f"内部服务器错误: {e}")
