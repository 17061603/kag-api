import copy
import logging
import time
import yaml
from typing import Dict, Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from kag.common.conf import KAGConfigMgr, KAGConstants, KAGConfigAccessor
from kag.common.registry import import_modules_from_path
from services.project_repository import ProjectRepository

logger = logging.getLogger(__name__)


class RetrieverService:
    """知识库检索服务（使用任务级 config，支持并发）"""

    def _inject_task_id(self, config: Dict[str, Any], task_id: str):
        """
        递归地将 task_id 注入到配置的所有嵌套字典中。
        确保所有组件（retriever、executor 等）都能拿到 task_id。
        """
        if not isinstance(config, dict):
            return
        
        # 在顶层注入
        config[KAGConstants.KAG_QA_TASK_CONFIG_KEY] = task_id
        
        # 递归处理所有嵌套字典
        for key, value in config.items():
            if isinstance(value, dict):
                # 如果嵌套字典有 "type" 键（表示是一个组件配置），也注入 task_id
                if "type" in value:
                    value[KAGConstants.KAG_QA_TASK_CONFIG_KEY] = task_id
                # 继续递归
                self._inject_task_id(value, task_id)
            elif isinstance(value, list):
                # 处理列表中的字典
                for item in value:
                    if isinstance(item, dict):
                        self._inject_task_id(item, task_id)

    async def retrieve(
        self,
        session: AsyncSession,
        project_id: int,
        query: str,
    ) -> Dict[str, Any]:
        """
        针对指定项目执行知识库检索（使用任务级 config）
        """
        # 1. 获取项目信息
        project = await ProjectRepository.get_by_id(session, project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project with id={project_id} not found")

        namespace = project.namespace
        config_file = f"./data/{namespace}/kag_config.yaml"

        # 2. 确保相关模块可用（例如 prompt、executor 等）
        import_modules_from_path(".")

        # 3. 延迟导入，避免循环依赖
        from kag.interface import ExecutorABC, Task, Context

        # 4. 生成唯一 task_id
        task_id = f"{namespace}_retrieve_{int(time.time() * 1000000)}"
        
        try:
            # 5. 加载配置文件
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            # 6. 创建任务级 config（不修改全局 KAG_CONFIG）
            task_cfg = KAGConfigMgr()
            task_cfg.update_conf(config)
            
            global_config = config.get(KAGConstants.PROJECT_CONFIG_KEY, {})
            global_config['namespace'] = namespace
            project_id_val = global_config.get('id')
            if project_id_val:
                global_config['project_id'] = project_id_val
            
            task_cfg.global_config.initialize(**global_config)
            task_cfg.prod = False
            task_cfg._is_initialized = True
            
            # 7. 设置任务级 config
            KAGConfigAccessor.set_task_config(task_id, task_cfg)
            
            # 8. 准备 executor_config 并注入 task_id
            executor_config = copy.deepcopy(config.get("kag_hybrid_executor"))
            if not executor_config:
                raise HTTPException(
                    status_code=500,
                    detail="未在配置中找到 kag_hybrid_executor 配置",
                )
            
            # 注入 task_id 到配置的所有嵌套组件
            self._inject_task_id(executor_config, task_id)
            
            # 9. 构建 executor（会通过 get_config(task_id) 获取任务配置）
            executor = ExecutorABC.from_config(executor_config)
            executor_schema = executor.schema()
            executor_name = executor_schema["name"]

            # 10. 执行检索
            task = Task(
                executor=executor_name,
                arguments={"query": query},
            )
            context = Context()

            await executor.ainvoke(query=query, task=task, context=context)

            if not getattr(task, "result", None):
                raise HTTPException(status_code=500, detail="执行器未返回结果")

            data = {
                "summary": task.result.summary,
                "references": task.result.to_dict(),
            }
            return data
            
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"知识库检索时发生错误: {e}")
            raise HTTPException(status_code=500, detail=f"检索失败: {e}")


retriever_service = RetrieverService()

