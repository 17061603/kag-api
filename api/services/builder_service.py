import logging
import time
from typing import Optional, Dict, Any
import yaml
import copy
from sqlalchemy.ext.asyncio import AsyncSession
from kag.common.registry import import_modules_from_path
from kag.common.conf import KAGConfigMgr, KAGConstants, KAGConfigAccessor
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

    def _inject_task_id(self, config: Dict[str, Any], task_id: str):
        """
        递归地将 task_id 注入到配置的所有嵌套字典中。
        确保所有组件（scanner、reader、splitter、extractor 等）都能拿到 task_id。
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
                # 处理列表中的字典（如多个 extractor）
                for item in value:
                    if isinstance(item, dict):
                        self._inject_task_id(item, task_id)

    async def start_build(
        self,   
        session: AsyncSession,
        project_id: int
    ) -> str:
        """
        启动构建任务（准备配置，返回 task_id，不执行构建）
        实际构建在后台任务中执行
        """
        import_modules_from_path(".")

        project = await ProjectRepository.get_by_id(session, project_id)
        namespace = project.namespace
        config_file = f"./data/{namespace}/kag_config.yaml"
        
        task_id = f"{namespace}_{int(time.time() * 1000000)}"
        
        try:
            # 3. 初始化任务状态
            task_status[task_id] = {
                "status": "pending",
                "message": "任务已创建，等待执行",
                "progress": 0
            }

            # 4. 加载配置文件
            config = self._load_config(config_file)
            host_addr = config.get('project', {}).get('host_addr')
            
            # 5. 创建任务级 config
            task_cfg = KAGConfigMgr()
            task_cfg.update_conf(config)
            
            global_config = config.get(KAGConstants.PROJECT_CONFIG_KEY, {})
            global_config['namespace'] = namespace
            global_config['ckpt_dir'] = f"./data/{namespace}/builder/ckpt"
            if host_addr:
                global_config['host_addr'] = host_addr
            project_id_val = global_config.get('id')
            if project_id_val:
                global_config['project_id'] = project_id_val
            
            task_cfg.global_config.initialize(**global_config)
            task_cfg.prod = False
            task_cfg._is_initialized = True
            KAGConfigAccessor.set_task_config(task_id, task_cfg)
            builder_config = copy.deepcopy(config.get("kag_builder_pipeline", {}))
            if not builder_config:
                raise HTTPException(status_code=500, detail="配置中缺少 kag_builder_pipeline")
            if builder_config.get("type") == "stream":
                builder_config["type"] = "base"
 
            self._inject_task_id(builder_config, task_id)
 
            task_status[task_id]["builder_config"] = builder_config
            task_status[task_id]["file_path"] = f"./data/{namespace}/builder/data"
            task_status[task_id]["namespace"] = namespace
            
            logger.info(f"Build task {task_id} prepared for namespace: {namespace}")
            return task_id

        except HTTPException:
            raise
        except Exception as e:
            # 更新任务状态为失败
            task_status[task_id] = {
                "status": "failed",
                "message": f"任务准备失败: {str(e)}",
                "progress": 0
            }
            logger.exception(f"Failed to prepare build task for namespace {namespace}: {e}")
            raise HTTPException(status_code=500, detail=f"任务准备失败: {e}")

    def run_build_task(self, task_id: str):
        """
        后台执行构建任务
        """
        try:
            # 1. 更新任务状态为运行中
            if task_id not in task_status:
                logger.error(f"Task {task_id} not found in task_status")
                return
            
            task_status[task_id].update({
                "status": "running",
                "message": "开始构建知识库",
                "progress": 0
            })
            
            # 2. 获取保存的配置信息
            task_info = task_status[task_id]
            builder_config = task_info.get("builder_config")
            file_path = task_info.get("file_path")
            namespace = task_info.get("namespace")
            
            if not builder_config or not file_path:
                raise ValueError(f"Task {task_id} missing builder_config or file_path")
            runner = BuilderChainRunner.from_config(builder_config)

            runner.invoke(file_path)
            
            logger.info(f"Processing file_path: {file_path}")

            # 5. 更新任务状态为完成
            task_status[task_id].update({
                "status": "completed",
                "message": "知识库构建完成",
                "progress": 100
            })

            logger.info(f"Successfully built knowledge base for namespace: {namespace}")

        except Exception as e:
            # 更新任务状态为失败
            if task_id in task_status:
                task_status[task_id].update({
                    "status": "failed",
                    "message": f"构建失败: {str(e)}",
                    "progress": 0
                })
            logger.exception(f"Failed to build knowledge base for task {task_id}: {e}")

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """获取任务状态（只返回客户端需要的字段）"""
        if task_id not in task_status:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        task_info = task_status[task_id]
        # 只返回客户端需要的字段，过滤掉内部配置信息
        return {
            "status": task_info.get("status", "unknown"),
            "message": task_info.get("message", ""),
            "progress": task_info.get("progress", 0),
        }


# 初始化服务实例
builder_service = KAGBuilderService()
