"""
文件服务：处理文件相关的业务逻辑
"""
import os
import uuid
import logging
from pathlib import Path
from typing import Optional, List, Tuple
from fastapi import UploadFile

from database.models import File
from services.file_repository import FileRepository
from services.project_repository import ProjectRepository
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class FileService:
    """文件服务类"""
    
    @classmethod
    def get_project_upload_dir(cls, namespace: str) -> Path:
        """
        获取项目的文件上传目录
        
        Args:
            namespace: 项目命名空间
            
        Returns:
            Path: 项目上传目录路径
        """
        # 文件保存到 ./data/{namespace}/builder/data/ 目录
        project_dir = Path("data") / namespace / "builder" / "data"
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir
    
    @classmethod
    async def upload_file(
        cls,
        session: AsyncSession,
        project_id: int,
        file: UploadFile,
    ) -> Tuple[File, Path]:
        """
        上传文件
        
        Args:
            session: 数据库会话
            project_id: 项目ID
            file: 上传的文件对象
            
        Returns:
            Tuple[File, Path]: (文件对象, 文件存储路径)
            
        Raises:
            ValueError: 如果项目不存在
        """
        # 检查项目是否存在并获取namespace
        project = await ProjectRepository.get_by_id(session, project_id)
        if not project:
            raise ValueError(f"项目不存在: project_id={project_id}")
        
        namespace = project.namespace
        
        # 生成唯一文件名
        file_ext = Path(file.filename).suffix if file.filename else ""
        unique_filename = f"{uuid.uuid4().hex}{file_ext}"
        
        # 获取项目上传目录（使用namespace）
        upload_dir = cls.get_project_upload_dir(namespace)
        file_path = upload_dir / unique_filename
        
        # 保存文件
        try:
            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)
            
            file_size = os.path.getsize(file_path)
            
            # 获取MIME类型
            mime_type = file.content_type
            
            # 保存文件记录到数据库
            file_record = await FileRepository.create(
                session=session,
                project_id=project_id,
                filename=unique_filename,
                original_filename=file.filename or "unknown",
                file_path=str(file_path),
                file_size=file_size,
                mime_type=mime_type,
            )
            
            return file_record, file_path
            
        except Exception as e:
            # 如果保存失败，删除已创建的文件
            if file_path.exists():
                file_path.unlink()
            raise Exception(f"文件上传失败: {str(e)}")
    
    @classmethod
    async def delete_file(
        cls,
        session: AsyncSession,
        project_id: int,
        file_id: int,
    ) -> bool:
        """
        删除文件
        
        Args:
            session: 数据库会话
            project_id: 项目ID
            file_id: 文件ID
            
        Returns:
            bool: 是否删除成功
            
        Raises:
            ValueError: 如果文件不存在或不属于该项目
        """
        # 获取文件记录
        file_record = await FileRepository.get_by_id(session, file_id)
        if not file_record:
            raise ValueError(f"文件不存在: file_id={file_id}")
        
        # 验证文件属于该项目
        if file_record.project_id != project_id:
            raise ValueError(f"文件不属于该项目: file_id={file_id}, project_id={project_id}")
        
        # 删除物理文件
        file_path = Path(file_record.file_path)
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception as e:
                logger.warning(f"删除物理文件失败: {file_path}, error: {e}")
        
        # 删除数据库记录
        await FileRepository.delete(session, file_id)
        
        return True
    
    @classmethod
    async def list_files(
        cls,
        session: AsyncSession,
        project_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> List[File]:
        """
        获取项目的文件列表
        
        Args:
            session: 数据库会话
            project_id: 项目ID
            skip: 跳过的记录数
            limit: 返回的最大记录数
            
        Returns:
            List[File]: 文件列表
        """
        # 检查项目是否存在
        project = await ProjectRepository.get_by_id(session, project_id)
        if not project:
            raise ValueError(f"项目不存在: project_id={project_id}")
        
        return await FileRepository.list_by_project(session, project_id, skip, limit)

