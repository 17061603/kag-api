"""
文件数据访问层（Repository）
"""
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from database.models import File


class FileRepository:
    """文件数据访问类"""
    
    @staticmethod
    async def create(
        session: AsyncSession,
        project_id: int,
        filename: str,
        original_filename: str,
        file_path: str,
        file_size: int,
        mime_type: Optional[str] = None,
    ) -> File:
        """
        创建文件记录
        
        Args:
            session: 数据库会话
            project_id: 项目ID
            filename: 文件名（存储后的文件名）
            original_filename: 原始文件名
            file_path: 文件存储路径
            file_size: 文件大小（字节）
            mime_type: MIME类型
            
        Returns:
            File: 创建的文件对象
        """
        file = File(
            project_id=project_id,
            filename=filename,
            original_filename=original_filename,
            file_path=file_path,
            file_size=file_size,
            mime_type=mime_type,
        )
        session.add(file)
        await session.flush()
        await session.refresh(file)
        return file
    
    @staticmethod
    async def get_by_id(session: AsyncSession, file_id: int) -> Optional[File]:
        """
        根据ID获取文件
        
        Args:
            session: 数据库会话
            file_id: 文件ID
            
        Returns:
            File: 文件对象，如果不存在返回None
        """
        result = await session.execute(select(File).where(File.id == file_id))
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_by_project_and_filename(
        session: AsyncSession,
        project_id: int,
        filename: str,
    ) -> Optional[File]:
        """
        根据项目ID和文件名获取文件
        
        Args:
            session: 数据库会话
            project_id: 项目ID
            filename: 文件名
            
        Returns:
            File: 文件对象，如果不存在返回None
        """
        result = await session.execute(
            select(File).where(
                and_(File.project_id == project_id, File.filename == filename)
            )
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def list_by_project(
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
        result = await session.execute(
            select(File)
            .where(File.project_id == project_id)
            .offset(skip)
            .limit(limit)
            .order_by(File.created_at.desc())
        )
        return result.scalars().all()
    
    @staticmethod
    async def delete(session: AsyncSession, file_id: int) -> bool:
        """
        删除文件记录
        
        Args:
            session: 数据库会话
            file_id: 文件ID
            
        Returns:
            bool: 是否删除成功
        """
        result = await session.execute(select(File).where(File.id == file_id))
        file = result.scalar_one_or_none()
        if file:
            await session.delete(file)
            await session.flush()
            return True
        return False

