import asyncio
import logging
from typing import Optional, Dict, Any
import yaml
import copy
import threading
from sqlalchemy.ext.asyncio import AsyncSession
from kag.common.registry import import_modules_from_path
from kag.common.conf import KAG_CONFIG, KAGConfigMgr, KAGConstants, init_env
from kag.builder.runner import BuilderChainRunner
from fastapi import HTTPException
from services.project_repository import ProjectRepository

logger = logging.getLogger(__name__)

# 全局任务状态管理
task_status: Dict[str, Dict[str, Any]] = {}


class KAGBuilderService:
    """KAG知识库构建服务"""

    def __init__(self):
        pass

    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load config file {config_file}: {e}")
            raise HTTPException(status_code=500, detail=f"配置文件加载失败: {e}")

    def _init_project_config(self, config: Dict[str, Any], namespace: str,
                        host_addr: str = None) -> KAGConfigMgr:
        """为指定namespace初始化项目配置"""
        try:
            kb_conf = KAGConfigMgr()
            kb_conf.update_conf(config)

            # 初始化全局配置，确保使用本地配置
            global_config = config.get(KAGConstants.PROJECT_CONFIG_KEY, {})
            global_config['namespace'] = namespace
            if host_addr:
                global_config['host_addr'] = host_addr
            project_id = global_config.get('id')
            if project_id:
                global_config['project_id'] = project_id

            kb_conf.global_config.initialize(**global_config)

            return kb_conf
        except Exception as e:
            logger.error(f"Failed to initialize project config: {e}")
            raise HTTPException(status_code=500, detail=f"项目配置初始化失败: {e}")

    async def build_knowledge_base(
        self,   
        session: AsyncSession,
        project_id: int
    ) -> str:
        """异步构建知识库"""
        import_modules_from_path(".")

        project = await ProjectRepository.get_by_id(session, project_id)
        namespace=project.namespace
        file_path=f"./data/{namespace}/builder/data"
        config_file=f"./data/{namespace}/kag_config.yaml"
        task_id = f"{namespace}_{hash(file_path)}"
        try:
            # 更新任务状态
            task_status[task_id] = {
                "status": "running",
                "message": "开始构建知识库",
                "progress": 0
            }

            config = self._load_config(config_file)
            host_addr=config['project']['host_addr']
            _ = self._init_project_config(
                config, namespace, host_addr
            )

            # 关键：在创建组件之前，初始化全局KAG_CONFIG
            # 这样所有组件（包括直接使用KAG_PROJECT_CONF的Prompt类）都能获取正确的配置
            # 使用线程锁确保线程安全
            config_lock = threading.Lock()
            with config_lock:
                # 保存原始配置
                original_config = copy.deepcopy(KAG_CONFIG.all_config) if KAG_CONFIG._is_initialized else None
                init_env(config_file)
                ckpt_dir = f"./data/{namespace}/builder/ckpt"
                KAG_CONFIG.global_config.ckpt_dir = ckpt_dir
                try:
                    builder_config = copy.deepcopy(KAG_CONFIG.all_config["kag_builder_pipeline"])
                    runner = BuilderChainRunner.from_config(
                        builder_config
                    )
                    # await runner.ainvoke(file_path)
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None,   
                        runner.invoke,   
                        file_path  
                    )
                    logger.info(f"Processing file_path: {file_path}")

                    task_status[task_id] = {
                        "status": "completed",
                        "message": "知识库构建完成",
                        "progress": 100
                    }

                    logger.info(f"Successfully built knowledge base for namespace: {namespace}")
                    return task_id
                finally:
                    # 恢复原始配置（如果存在）
                    if original_config is not None:
                        KAG_CONFIG.config = original_config
                        global_config = original_config.get(KAGConstants.PROJECT_CONFIG_KEY, {})
                        KAG_CONFIG.global_config.initialize(**global_config)
                    else:
                        # 如果没有原始配置，重新初始化默认配置
                        KAG_CONFIG.initialize(False, None)

        except Exception as e:
            # 更新任务状态为失败
            task_status[task_id] = {
                "status": "failed",
                "message": f"构建失败: {str(e)}",
                "progress": 0
            }
            logger.error(f"Failed to build knowledge base for namespace {namespace}: {e}")
            raise HTTPException(status_code=500, detail=f"知识库构建失败: {e}")

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """获取任务状态"""
        if task_id not in task_status:
            raise HTTPException(status_code=404, detail="任务不存在")
        return task_status[task_id]


# 初始化服务实例
builder_service = KAGBuilderService()
