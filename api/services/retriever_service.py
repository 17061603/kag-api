import copy
import logging
import threading
from typing import Dict, Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from kag.common.conf import KAG_CONFIG, KAGConstants, init_env
from kag.common.registry import import_modules_from_path
from services.project_repository import ProjectRepository

logger = logging.getLogger(__name__)


class RetrieverService:
    """知识库检索服务"""

    async def retrieve(
        self,
        session: AsyncSession,
        project_id: int,
        query: str,
    ) -> Dict[str, Any]:
        """
        针对指定项目执行知识库检索
        """
        # 加载项目配置
        project = await ProjectRepository.get_by_id(session, project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project with id={project_id} not found")

        namespace = project.namespace
        config_file=f"./data/{namespace}/kag_config.yaml"

        # 确保相关模块可用（例如 prompt、executor 等）
        import_modules_from_path(".")

        # 延迟导入，避免循环依赖
        from kag.interface import ExecutorABC, Task, Context

        # 在全局配置上加锁，防止并发请求互相干扰
        config_lock = threading.Lock()
        with config_lock:
            original_config = copy.deepcopy(KAG_CONFIG.all_config) if KAG_CONFIG._is_initialized else None

            init_env(config_file)

            try:
                # 从项目配置中读取混合检索执行器配置
                executor_config = KAG_CONFIG.all_config.get("kag_hybrid_executor")
                if not executor_config:
                    raise HTTPException(
                        status_code=500,
                        detail="未在配置中找到 kag_hybrid_executor 配置",
                    )

                executor = ExecutorABC.from_config(executor_config)
                executor_schema = executor.schema()
                executor_name = executor_schema["name"]

                task = Task(
                    executor=executor_name,
                    arguments={"query": query},
                )
                context = Context()

                await executor.ainvoke(query=query, task=task, context=context)

                if not getattr(task, "result", None):
                    raise HTTPException(status_code=500, detail="执行器未返回结果")
                
                print("task:",task)

                data = {
                    "summary": task.result.summary,
                    "references": task.result.to_dict(),
                }
                return data
            finally:
                if original_config is not None:
                    KAG_CONFIG.config = original_config
                    global_config = original_config.get(KAGConstants.PROJECT_CONFIG_KEY, {})
                    KAG_CONFIG.global_config.initialize(**global_config)
                else:
                    KAG_CONFIG.initialize(False, None)


retriever_service = RetrieverService()

