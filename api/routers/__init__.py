"""
路由模块
"""
from .project_router import router as project_router
from .file_router import router as file_router
from .schema_router import router as schema_router
from .builder_router import router as builder_router

__all__ = ["project_router", "file_router", "schema_router", "builder_router"]

