"""
项目服务：处理项目相关的业务逻辑
"""
import logging
import re
import json
import os
from pathlib import Path
from ruamel.yaml import YAML
from typing import Optional, Tuple

from knext.project.client import ProjectClient
from knext.common.env import env
from kag.common.llm.llm_config_checker import LLMConfigChecker
from kag.common.vectorize_model.vectorize_model_config_checker import (
    VectorizeModelConfigChecker,
)
from utils.template_utils import render_template
from knext.command.sub_command.project import update_project

yaml = YAML()
yaml.default_flow_style = False
yaml.indent(mapping=2, sequence=4, offset=2)

logger = logging.getLogger(__name__)


class ProjectService:
    """项目服务类"""
    
    @staticmethod
    def validate_namespace(namespace: str) -> None:
        """
        验证命名空间格式
        
        Args:
            namespace: 命名空间
            
        Raises:
            ValueError: 如果命名空间格式不正确
        """
        if not re.match(r"^[A-Z][A-Za-z0-9]{0,15}$", namespace):
            raise ValueError(
                f"Invalid namespace: {namespace}."
                f" Must start with an uppercase letter, only contain letters and numbers, and have a maximum length of 16."
            )
    
    @staticmethod
    def validate_config(config: dict) -> None:
        """
        验证配置文件中的LLM和向量化模型配置
        
        Args:
            config: 配置字典
            
        Raises:
            ValueError: 如果配置验证失败
        """
        llm_config_checker = LLMConfigChecker()
        vectorize_model_config_checker = VectorizeModelConfigChecker()
        llm_config = config.get("chat_llm", {})
        vectorize_model_config = config.get("vectorizer", {})
        
        try:
            llm_config_checker.check(json.dumps(llm_config))
            dim = vectorize_model_config_checker.check(json.dumps(vectorize_model_config))
            config["vectorizer"]["vector_dimensions"] = dim
        except Exception as e:
            raise ValueError(f"配置验证失败: {e}")
    
    @staticmethod
    def load_config(config_path: str) -> dict:
        """
        加载配置文件
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            config: 配置字典
            
        Raises:
            FileNotFoundError: 如果配置文件不存在
        """
        if not Path(config_path).exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        
        return yaml.load(Path(config_path).read_text() or "{}")
    
    @staticmethod
    def create_project_on_server(
        name: str,
        namespace: str,
        config: dict,
        host_addr: str,
    ) -> Optional[str]:
        """
        在服务器上创建项目
        
        Args:
            name: 项目名称
            namespace: 命名空间
            config: 配置字典
            host_addr: 服务器地址
            
        Returns:
            project_id: 项目ID，如果创建失败返回None
            
        Raises:
            ValueError: 如果host_addr为空
        """
        if not host_addr:
            raise ValueError("host_addr is required in config file.")
        
        client = ProjectClient(host_addr=host_addr)
        project = client.create(
            name=name,
            namespace=namespace,
            config=config,
            visibility=env.project_config.get("visibility", "PRIVATE"),
            tag=env.project_config.get("tag", "LOCAL"),
            userNo=env.project_config.get("userNo", "openspg"),
        )
        
        if project and project.id:
            return project.id
        return None
    
    async def create_project(
        self,
        config_path: str,
        namespace: str,
        tmpl: Optional[str] = None,
        delete_cfg: bool = False,
        db_session = None,
    ) -> Tuple[Path, int]:
        """
        创建项目
        
        Args:
            config_path: 配置文件路径
            namespace: 项目命名空间
            tmpl: 项目模板，默认为"default"
            delete_cfg: 是否删除配置文件
            db_session: 数据库会话（可选）
            
        Returns:
            tuple[Path, int]: (项目目录路径, 数据库项目ID)
            
        Raises:
            FileNotFoundError: 如果配置文件不存在
            ValueError: 如果参数验证失败
        """
        self.validate_namespace(namespace)

        if not tmpl:
            tmpl = "default"
        

        db_project_id = None
        if db_session:
            from services.project_repository import ProjectRepository
            db_project = await ProjectRepository.create(
                session=db_session,
                namespace=namespace,
                tmpl=tmpl,
                config_path=config_path,
            )
            db_project_id = db_project.id
        
        config = self.load_config(config_path)
        
        if "project" not in config:
            config["project"] = {}
        
        if db_project_id:
            config["project"]["id"] = str(db_project_id)
        config["project"]["namespace"] = namespace
        
        project_config = config.get("project", {})
        name = namespace  
        host_addr = project_config.get("host_addr", None)

        self.validate_config(config)
        
        project_id_from_server = self.create_project_on_server(
            name=name,
            namespace=namespace,
            config=config,
            host_addr=host_addr,
        )
        
        # 渲染模板
        project_dir = render_template(
            namespace=namespace,
            tmpl=tmpl,
            id=project_id_from_server,
            with_server=(host_addr is not None),
            host_addr=host_addr,
            name=name,
            config_path=config_path,
            config=config,  # 传递修改后的配置对象
            delete_cfg=delete_cfg,
        )
        
        # 更新项目
        current_dir = os.getcwd()
        os.chdir(project_dir)
        try:
            update_project(project_dir)
        finally:
            os.chdir(current_dir)
        
        # 删除配置文件（如果需要）
        if delete_cfg and os.path.exists(config_path):
            os.remove(config_path)
        
        return project_dir, db_project_id if db_project_id else 0

