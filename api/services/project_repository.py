"""
项目数据访问层（Repository）
"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.models import Project


class ProjectRepository:
    """项目数据访问类"""
    
    @staticmethod
    async def create(
        session: AsyncSession,
        namespace: str,
        tmpl: str,
        config_path: Optional[str] = None,
    ) -> Project:
        """
        创建项目记录
        
        Args:
            session: 数据库会话
            namespace: 项目命名空间
            tmpl: 项目模板
            config_path: 配置文件路径
            
        Returns:
            Project: 创建的项目对象
        """
        project = Project(
            namespace=namespace,
            tmpl=tmpl,
            config_path=config_path,
        )
        session.add(project)
        await session.flush()  # 刷新以获取自增ID
        await session.refresh(project)  # 刷新对象以获取数据库生成的值
        return project
    
    @staticmethod
    async def get_by_id(session: AsyncSession, project_id: int) -> Optional[Project]:
        """
        根据ID获取项目
        
        Args:
            session: 数据库会话
            project_id: 项目ID
            
        Returns:
            Project: 项目对象，如果不存在返回None
        """
        result = await session.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_by_namespace(session: AsyncSession, namespace: str) -> Optional[Project]:
        """
        根据命名空间获取项目
        
        Args:
            session: 数据库会话
            namespace: 项目命名空间
            
        Returns:
            Project: 项目对象，如果不存在返回None
        """
        result = await session.execute(select(Project).where(Project.namespace == namespace))
        return result.scalar_one_or_none()
    
    @staticmethod
    async def list_all(session: AsyncSession, skip: int = 0, limit: int = 100):
        """
        获取所有项目列表
        
        Args:
            session: 数据库会话
            skip: 跳过的记录数
            limit: 返回的最大记录数
            
        Returns:
            List[Project]: 项目列表
        """
        result = await session.execute(
            select(Project).offset(skip).limit(limit).order_by(Project.created_at.desc())
        )
        return result.scalars().all()

