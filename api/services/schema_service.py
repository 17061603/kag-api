import logging
from pathlib import Path
from knext.schema.marklang.schema_ml import SPGSchemaMarkLang
from kag.indexer import KAGIndexManager
from services.project_repository import ProjectRepository
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class SchemaService:
    """Schema服务类"""
    
    @staticmethod
    def get_schema_file_path(project_namespace: str) -> Path:
        """
        获取项目的schema文件路径
        
        Args:
            project_namespace: 项目命名空间
            
        Returns:
            Path: schema文件路径
        """
        return Path("data") / project_namespace / "schema" / f"{project_namespace}.schema"
    
    @staticmethod
    async def commit_schema(
        session: AsyncSession,
        project_id: int,
    ) -> dict:
        """
        提交项目的schema到服务器
        """
        project = await ProjectRepository.get_by_id(session, project_id)
        if not project:
            raise ValueError(f"项目不存在: project_id={project_id}")
        
        project_namespace = project.namespace

        schema_file = SchemaService.get_schema_file_path(project_namespace)

        if not schema_file.exists():
            raise ValueError(f"Schema文件不存在: {schema_file}")
        
        project_dir = Path("data") / project_namespace
        config_file = project_dir / "kag_config.yaml"
        
        if not config_file.exists():
            raise ValueError(f"项目配置文件不存在: {config_file}")
        
        from ruamel.yaml import YAML
        yaml = YAML()
        with open(config_file) as f:
            config = yaml.load(f)
        
        project_config = config.get("project", {})
        host_addr = project_config.get("host_addr")
        server_project_id = project_config.get("id")
        namespace = project_config.get("namespace")
        
        if not host_addr:
            raise ValueError("项目配置中缺少 host_addr")
        
        if not server_project_id:
            raise ValueError("项目配置中缺少 id")
        
        if not namespace:
            raise ValueError("项目配置中缺少 namespace")
        
        # 读取schema文件
        ml = SPGSchemaMarkLang(
            str(schema_file.resolve()),
            host_addr=host_addr,
            project_id=server_project_id
        )
        
        # 处理索引管理器的schema
        index_managers = KAGIndexManager.list_available()
        index_ml = None
        for index_manager_name in index_managers:
            config_dict = {
                "type": index_manager_name,
                "llm_config": None,
                "vectorize_model_config": None,
            }
            
            try:
                index_mgr = KAGIndexManager.from_config(config_dict)
                schema_str = index_mgr.schema
                if not schema_str:
                    continue
                schema_str = f"namespace {namespace}\n" + schema_str
                cur_index_ml = SPGSchemaMarkLang(
                    filename="",
                    script_data_str=schema_str,
                    host_addr=host_addr,
                    project_id=server_project_id,
                )
                if index_ml is None:
                    index_ml = cur_index_ml
                else:
                    index_ml.types.update(cur_index_ml.types)
            except Exception as e:
                logger.warning(f"处理索引管理器 {index_manager_name} 时出错: {e}")
                continue

        if index_ml is not None:
            ml.types.update(index_ml.types)

        is_altered = ml.sync_schema()
        
        if is_altered:
            message = "Schema is successfully committed."
        else:
            message = "There is no diff between local and server-side schema."
        
        return {
            "is_altered": is_altered,
            "message": message,
        }

