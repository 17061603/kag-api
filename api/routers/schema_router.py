import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from models.schema_schemas import SchemaCommitResponse
from services.schema_service import SchemaService
from database.connection import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/project/{project_id}/schema", tags=["Schema管理"])


@router.post("/commit", response_model=SchemaCommitResponse, summary="提交Schema")
async def commit_schema(
    project_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    提交项目的Schema到服务器
    
    参数说明:
    - project_id: 项目ID（路径参数）
    
    注意: Schema文件位置为 data/{项目名}/schema/{项目名}.schema
    """
    try:
        result = await SchemaService.commit_schema(
            session=session,
            project_id=project_id,
        )
        
        return SchemaCommitResponse(
            success=True,
            message=result["message"],
            is_altered=result["is_altered"],
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"提交Schema时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"提交Schema失败: {str(e)}")

