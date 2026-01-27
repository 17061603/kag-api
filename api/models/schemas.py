"""
API 请求和响应模型定义
"""
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


class ProjectCreateRequest(BaseModel):
    """创建项目请求模型"""
    config_path: Optional[str] = Field(default="kag_config.yaml", description="配置文件路径")
    namespace: str = Field(..., description="项目命名空间")
    tmpl: Optional[str] = Field(default="default", description="项目模板，默认为default")
    delete_cfg: Optional[bool] = Field(default=False, description="是否删除配置文件")


class ProjectCreateResponse(BaseModel):
    """创建项目响应模型"""
    success: bool
    message: str
    project_dir: Optional[str] = None
    namespace: Optional[str] = None


class ProjectInfo(BaseModel):
    """项目信息模型"""
    id: int
    namespace: str
    tmpl: str
    config_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    """项目列表响应模型"""
    success: bool
    message: str
    projects: List[ProjectInfo]
    total: int

