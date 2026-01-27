"""
Builder服务：处理知识库构建相关的业务逻辑
"""
import os
import logging
from pathlib import Path
from typing import Tuple
from ruamel.yaml import YAML

from kag.builder.runner import BuilderChainRunner
from kag.common.registry import import_modules_from_path
from services.project_repository import ProjectRepository
from sqlalchemy.ext.asyncio import AsyncSession

yaml = YAML()
yaml.default_flow_style = False
yaml.indent(mapping=2, sequence=4, offset=2)

logger = logging.getLogger(__name__)


class BuilderService:
    """Builder服务类"""
    
    @staticmethod
    def get_project_data_dir(namespace: str) -> Path:
        """
        获取项目的数据目录
        
        Args:
            namespace: 项目命名空间
            
        Returns:
            Path: 项目数据目录路径
        """
        # 文件路径为 ./data/{namespace}/builder/data/
        data_dir = Path("data") / namespace / "builder" / "data"
        return data_dir
    
    @staticmethod
    def get_project_config_path(namespace: str) -> Path:
        """
        获取项目的配置文件路径
        
        Args:
            namespace: 项目命名空间
            
        Returns:
            Path: 配置文件路径
        """
        # 配置文件路径为 ./data/{namespace}/kag_config.yaml
        config_path = Path("data") / namespace / "kag_config.yaml"
        return config_path
    
    @staticmethod
    def load_config(config_path: Path) -> dict:
        """
        加载配置文件
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            dict: 配置字典
            
        Raises:
            FileNotFoundError: 如果配置文件不存在
        """
        if not config_path.exists():
            raise FileNotFoundError(f"项目配置文件不存在: {config_path}")
        
        # 使用 ruamel.yaml 加载配置，支持 YAML 锚点引用
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.load(f)
        
        if config is None:
            return {}
        
        # 确保配置中的数值类型正确（递归转换）
        config = BuilderService._ensure_types(config)
        
        return config
    
    @staticmethod
    def _ensure_types(obj):
        """
        递归地确保配置对象中的数值类型正确
        只转换明显是数字的字符串，避免破坏其他字符串值
        
        Args:
            obj: 配置对象（dict, list 或基本类型）
            
        Returns:
            转换后的对象
        """
        if isinstance(obj, dict):
            return {k: BuilderService._ensure_types(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [BuilderService._ensure_types(item) for item in obj]
        elif isinstance(obj, str):
            # 只转换纯数字字符串（包括负号）
            stripped = obj.strip()
            if not stripped:
                return obj
            
            # 尝试转换为整数（纯数字，可能有负号）
            try:
                if stripped.isdigit() or (stripped.startswith('-') and stripped[1:].isdigit()):
                    return int(stripped)
            except (ValueError, AttributeError):
                pass
            
            # 尝试转换为浮点数（包含小数点或科学计数法）
            try:
                # 检查是否是有效的浮点数格式
                if '.' in stripped or 'e' in stripped.lower() or 'E' in stripped:
                    # 尝试转换，如果失败则保持原样
                    float_val = float(stripped)
                    # 如果转换后的值可以表示为整数，返回整数
                    if float_val.is_integer():
                        return int(float_val)
                    return float_val
            except (ValueError, AttributeError):
                pass
            
            return obj
        else:
            return obj
    
    @classmethod
    async def build_kb(
        cls,
        session: AsyncSession,
        project_id: int,
    ) -> Tuple[str, str]:
        """
        构建知识库
        
        Args:
            session: 数据库会话
            project_id: 项目ID
            
        Returns:
            Tuple[str, str]: (项目命名空间, 数据目录路径)
            
        Raises:
            ValueError: 如果项目不存在或配置错误
            FileNotFoundError: 如果配置文件不存在
        """
        # 检查项目是否存在并获取namespace
        project = await ProjectRepository.get_by_id(session, project_id)
        if not project:
            raise ValueError(f"项目不存在: project_id={project_id}")
        
        namespace = project.namespace
        
        # 获取项目目录和数据目录的绝对路径
        project_dir = Path("data") / namespace
        project_dir_abs = project_dir.resolve()
        data_dir = cls.get_project_data_dir(namespace)
        data_dir_abs = data_dir.resolve()
        data_dir_str = str(data_dir_abs)
        
        # 确保数据目录存在
        data_dir_abs.mkdir(parents=True, exist_ok=True)
        
        # 获取配置文件的绝对路径
        config_path = cls.get_project_config_path(namespace)
        config_path_abs = config_path.resolve()
        
        # 在切换目录之前加载配置（使用绝对路径）
        config = cls.load_config(config_path_abs)
        
        # 检查配置中是否包含 kag_builder_pipeline
        if "kag_builder_pipeline" not in config:
            raise ValueError("项目配置中缺少 kag_builder_pipeline")
        
        # 导入模块（如果需要）
        if project_dir_abs.exists():
            import_modules_from_path(str(project_dir_abs))
        
        # 创建runner并执行构建
        # 注意：需要切换到项目目录，以便正确加载配置和模块
        current_dir = os.getcwd()
        try:
            # 切换到项目目录
            if project_dir_abs.exists():
                os.chdir(str(project_dir_abs))
            
            runner = BuilderChainRunner.from_config(config["kag_builder_pipeline"])
            runner.invoke(data_dir_str)
            
            logger.info(f"构建知识库成功: project_id={project_id}, namespace={namespace}, data_dir={data_dir_str}")
            
            return namespace, data_dir_str
            
        except Exception as e:
            logger.exception(f"构建知识库失败: project_id={project_id}, error={e}")
            raise Exception(f"构建知识库失败: {str(e)}")
        finally:
            # 恢复工作目录
            os.chdir(current_dir)
