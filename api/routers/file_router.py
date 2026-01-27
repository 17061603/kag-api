"""
文件相关路由
"""
import logging
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File as FastAPIFile
from sqlalchemy.ext.asyncio import AsyncSession

from models.file_schemas import (
    FileListResponse,
    FileUploadResponse,
    FileDeleteResponse,
    FileInfo,
)
from services.file_service import FileService
from database.connection import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/project/{project_id}/file", tags=["文件管理"])


@router.post("/upload", response_model=FileUploadResponse, summary="上传文件")
async def upload_file(
    project_id: int,
    file: UploadFile = FastAPIFile(...),
    session: AsyncSession = Depends(get_session),
):
    """
    为项目上传文件
    
    参数说明:
    - project_id: 项目ID（路径参数）
    - file: 上传的文件（表单数据）
    """
    try:
        file_record, file_path = await FileService.upload_file(
            session=session,
            project_id=project_id,
            file=file,
        )
        
        return FileUploadResponse(
            success=True,
            message=f"文件上传成功: {file_record.original_filename}",
            file=FileInfo.model_validate(file_record),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"上传文件时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"上传文件失败: {str(e)}")


@router.delete("/{file_id}", response_model=FileDeleteResponse, summary="删除文件")
async def delete_file(
    project_id: int,
    file_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    删除项目的文件
    
    参数说明:
    - project_id: 项目ID（路径参数）
    - file_id: 文件ID（路径参数）
    """
    try:
        await FileService.delete_file(
            session=session,
            project_id=project_id,
            file_id=file_id,
        )
        
        return FileDeleteResponse(
            success=True,
            message=f"文件删除成功: file_id={file_id}",
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"删除文件时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"删除文件失败: {str(e)}")


@router.get("/list", response_model=FileListResponse, summary="查询文件列表")
async def list_files(
    project_id: int,
    skip: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
):
    """
    查询项目的文件列表
    
    参数说明:
    - project_id: 项目ID（路径参数）
    - skip: 跳过的记录数（查询参数，默认0）
    - limit: 返回的最大记录数（查询参数，默认100）
    """
    try:
        files = await FileService.list_files(
            session=session,
            project_id=project_id,
            skip=skip,
            limit=limit,
        )
        
        return FileListResponse(
            success=True,
            message=f"查询成功，共 {len(files)} 个文件",
            files=[FileInfo.model_validate(f) for f in files],
            total=len(files),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"查询文件列表时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"查询文件列表失败: {str(e)}")

