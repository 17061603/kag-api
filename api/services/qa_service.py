"""
QA 问答服务（使用任务级 config，参考 retriever config 模式）
"""
import copy
import logging
import time
import yaml
from typing import Dict, Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from kag.common.conf import KAGConfigMgr, KAGConstants, KAGConfigAccessor
from kag.common.registry import import_modules_from_path
from kag.interface import SolverPipelineABC
from kag.solver.reporter.trace_log_reporter import TraceLogReporter

from services.project_repository import ProjectRepository

logger = logging.getLogger(__name__)


class QAService:
    """问答服务（使用任务级 config，支持按项目加载 kag_config）"""

    def _inject_task_id(self, config: Dict[str, Any], task_id: str):
        """
        递归地将 task_id 注入到配置的所有嵌套字典中。
        确保 pipeline 及其组件（planner、executor、generator 等）都能拿到 task_id。
        """
        if not isinstance(config, dict):
            return
        config[KAGConstants.KAG_QA_TASK_CONFIG_KEY] = task_id

        for key, value in config.items():
            if isinstance(value, dict):
                if "type" in value:
                    value[KAGConstants.KAG_QA_TASK_CONFIG_KEY] = task_id
                self._inject_task_id(value, task_id)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        self._inject_task_id(item, task_id)

    async def qa(
        self,
        session: AsyncSession,
        project_id: int,
        query: str,
    ) -> Dict[str, Any]:
        """
        针对指定项目执行问答（参考 qa.py：SolverPipeline + TraceLogReporter）。
        """
        project = await ProjectRepository.get_by_id(session, project_id)
        if not project:
            raise HTTPException(
                status_code=404, detail=f"Project with id={project_id} not found"
            )

        namespace = project.namespace
        config_file = f"./data/{namespace}/kag_config.yaml"
        import_modules_from_path(".")
        task_id = f"{namespace}_qa_{int(time.time() * 1000000)}"

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            task_cfg = KAGConfigMgr()
            task_cfg.update_conf(config)

            global_config = config.get(KAGConstants.PROJECT_CONFIG_KEY, {})
            global_config["namespace"] = namespace
            project_id_val = global_config.get("id")
            if project_id_val:
                global_config["project_id"] = project_id_val

            task_cfg.global_config.initialize(**global_config)
            task_cfg.prod = False
            task_cfg._is_initialized = True

            KAGConfigAccessor.set_task_config(task_id, task_cfg)

            pipeline_config = copy.deepcopy(config.get("kag_solver_pipeline"))
            if not pipeline_config:
                raise HTTPException(
                    status_code=500,
                    detail="未在配置中找到 kag_solver_pipeline 配置",
                )

            self._inject_task_id(pipeline_config, task_id)
            # Pipeline 根配置不消费 kag_qa_task_config_key，from_config 会将其当 kwargs 传入导致警告；仅子配置（planner/executors/generator）需要
            pipeline_config.pop(KAGConstants.KAG_QA_TASK_CONFIG_KEY, None)

            pipeline = SolverPipelineABC.from_config(pipeline_config)
            reporter = TraceLogReporter()
            answer = await pipeline.ainvoke(query, reporter=reporter)

            # info, status = reporter.generate_report_data()
            # trace = info.to_dict()

            return {"answer": answer}

        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"问答执行时发生错误: {e}")
            raise HTTPException(status_code=500, detail=f"问答失败: {e}")


qa_service = QAService()
