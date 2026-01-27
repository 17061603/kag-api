"""
项目相关路由
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import (
    ProjectCreateRequest,
    ProjectCreateResponse,
    ProjectListResponse,
    ProjectInfo,
)
from services.project_service import ProjectService
from services.project_repository import ProjectRepository
from database.connection import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/project", tags=["项目"])

# 创建服务实例
project_service = ProjectService()


@router.post("/create", response_model=ProjectCreateResponse, summary="创建项目")
async def create_project(
    request: ProjectCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    创建新项目的API接口
    
    参数说明:
    - config_path: 配置文件路径（可选，默认为"kag_config.yaml"）
    - namespace: 项目命名空间（会覆盖配置文件中的namespace）
    - tmpl: 项目模板，默认为"default"
    - delete_cfg: 是否删除配置文件，默认为False
    
    注意: id 字段已移除，现在使用数据库自增ID
    """
    try:
        project_dir, db_project_id = await project_service.create_project(
            config_path=request.config_path or "kag_config.yaml",
            namespace=request.namespace,
            tmpl=request.tmpl,
            delete_cfg=request.delete_cfg,
            db_session=session,
        )
        
        return ProjectCreateResponse(
            success=True,
            message=f"Project with namespace [{request.namespace}] was successfully created (ID: {db_project_id})",
            project_dir=str(project_dir.resolve()),
            namespace=request.namespace,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"创建项目时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"创建项目失败: {str(e)}")


@router.get("/list", response_model=ProjectListResponse, summary="查询项目列表")
async def list_projects(
    skip: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
):
    """
    查询项目列表
    
    参数说明:
    - skip: 跳过的记录数（查询参数，默认0）
    - limit: 返回的最大记录数（查询参数，默认100）
    """
    try:
        projects = await ProjectRepository.list_all(
            session=session,
            skip=skip,
            limit=limit,
        )
        
        return ProjectListResponse(
            success=True,
            message=f"查询成功，共 {len(projects)} 个项目",
            projects=[ProjectInfo.model_validate(p) for p in projects],
            total=len(projects),
        )
    except Exception as e:
        logger.exception(f"查询项目列表时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"查询项目列表失败: {str(e)}")

