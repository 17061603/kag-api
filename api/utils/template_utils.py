"""
模板渲染工具函数
"""
from pathlib import Path
from ruamel.yaml import YAML
import click

yaml = YAML()
yaml.default_flow_style = False
yaml.indent(mapping=2, sequence=4, offset=2)


def render_template(namespace: str, tmpl: str, **kwargs):
    """
    渲染项目模板
    
    Args:
        namespace: 项目命名空间
        tmpl: 模板名称
        **kwargs: 其他参数，包括：
            - config_path: 配置文件路径
            - config: 配置对象（如果提供，将使用此配置而不是从文件读取）
            - id: 项目ID
            - 其他模板渲染所需的参数
    
    Returns:
        project_dir: 项目目录路径
    """
    config_path = kwargs.get("config_path", None)
    # 如果提供了config对象，使用它；否则从文件读取
    config = kwargs.get("config", None)
    if config is None and config_path:
        config = yaml.load(Path(config_path).read_text() or "{}")
    elif config is None:
        config = {}
    
    # 创建 data 目录（如果不存在）
    data_dir = Path("data")
    if not data_dir.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
    
    # 项目目录放在 data 目录下
    project_dir = data_dir / namespace
    if not project_dir.exists():
        project_dir.mkdir(parents=True, exist_ok=True)

    import kag.templates.project
    from knext.common.utils import copytree, copyfile

    src = Path(kag.templates.project.__path__[0])
    copytree(
        src,
        project_dir.resolve(),
        namespace=namespace,
        root=namespace,
        tmpl=tmpl,
        **kwargs,
    )

    import kag.templates.schema

    src = Path(kag.templates.schema.__path__[0]) / f"{{{{{tmpl}}}}}.schema.tmpl"
    if not src.exists():
        click.secho(
            f"ERROR: No such schema template: {tmpl}.schema.tmpl",
            fg="bright_red",
        )
    dst = project_dir.resolve() / "schema" / f"{{{{{tmpl}}}}}.schema.tmpl"
    copyfile(src, dst, namespace=namespace, **{tmpl: namespace})
    
    # 保存配置文件到项目目录
    project_id = kwargs.get("id", None)
    if "project" not in config:
        config["project"] = {}
    config["project"]["id"] = project_id
    config_file_path = project_dir.resolve() / "kag_config.yaml"
    with open(config_file_path, "w", encoding="utf-8", newline="\n") as config_file:
        yaml.dump(config, config_file)
    
    return project_dir

