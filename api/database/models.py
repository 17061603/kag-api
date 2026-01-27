"""
数据库模型定义
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, BigInteger
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from datetime import datetime

from .connection import Base


class Project(Base):
    """
    项目表模型
    """
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    namespace = Column(String(16), nullable=False, unique=True, index=True, comment="项目命名空间")
    tmpl = Column(String(50), nullable=False, default="default", comment="项目模板")
    config_path = Column(String(500), nullable=True, comment="配置文件路径")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="创建时间")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")
    
    # 关联关系
    files = relationship("File", back_populates="project", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Project(id={self.id}, namespace='{self.namespace}', tmpl='{self.tmpl}')>"


class File(Base):
    """
    文件表模型
    """
    __tablename__ = "files"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True, comment="项目ID")
    filename = Column(String(255), nullable=False, comment="文件名")
    original_filename = Column(String(255), nullable=False, comment="原始文件名")
    file_path = Column(String(1000), nullable=False, comment="文件存储路径")
    file_size = Column(BigInteger, nullable=False, comment="文件大小（字节）")
    mime_type = Column(String(100), nullable=True, comment="MIME类型")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="创建时间")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间")
    
    # 关联关系
    project = relationship("Project", back_populates="files")
    
    def __repr__(self):
        return f"<File(id={self.id}, project_id={self.project_id}, filename='{self.filename}')>"

