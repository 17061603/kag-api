"""
Builder相关路由
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from models.builder_schemas import BuildKBResponse
from services.builder_service import BuilderService
from database.connection import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/project/{project_id}/builder", tags=["知识库构建"])


@router.post("/build", response_model=BuildKBResponse, summary="构建知识库")
async def build_kb(
    project_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    为项目构建知识库
    
    参数说明:
    - project_id: 项目ID（路径参数）
    
    工作流程:
    1. 根据项目ID查询项目信息，获取namespace
    2. 读取项目的 kag_config.yaml 配置文件
    3. 从配置中获取 kag_builder_pipeline 配置
    4. 使用 BuilderChainRunner.from_config() 创建 runner
    5. 调用 runner.invoke(file_path) 执行构建
    6. file_path 为 ./data/{namespace}/builder/data/ 目录
    """
    try:
        namespace, data_dir = await BuilderService.build_kb(
            session=session,
            project_id=project_id,
        )
        
        return BuildKBResponse(
            success=True,
            message=f"知识库构建成功: project_id={project_id}, namespace={namespace}",
            file_path=data_dir,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"构建知识库时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"构建知识库失败: {str(e)}")
