import os  
import asyncio  
import logging  
from typing import Optional, Dict, Any  
from pathlib import Path  
from fastapi import FastAPI, HTTPException, BackgroundTasks  
from pydantic import BaseModel  
import yaml  
import copy  
import threading

from kag.common.registry import import_modules_from_path  
from kag.common.conf import KAG_CONFIG, KAGConfigMgr, KAGConstants, KAGConfigAccessor, init_env  
from kag.builder.runner import BuilderChainRunner
from knext.project.client import ProjectClient  

# 初始化FastAPI应用  
app = FastAPI(title="KAG Knowledge Base Builder API", version="1.0.0")  

# 设置日志  
logging.basicConfig(level=logging.INFO)  
logger = logging.getLogger(__name__)  

# 请求模型  
class BuildRequest(BaseModel):  
    file_path: str  
    namespace: str  
    host_addr: Optional[str] = None  
    num_processes: int = 2  
    config_file: Optional[str] = "kag_config.yaml"  

class BuildResponse(BaseModel):  
    task_id: str  
    status: str  
    message: str  

# 全局任务状态管理  
task_status: Dict[str, Dict[str, Any]] = {}  

class KAGBuilderService:  
    """KAG知识库构建服务"""  
      
    def __init__(self):  
        # 在应用启动时导入所有模块  
        import_modules_from_path(".")  
          
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
            # 创建独立的配置管理器  
            kb_conf = KAGConfigMgr()  
            kb_conf.update_conf(config)  
            
            # 初始化全局配置，确保使用本地配置  
            global_config = config.get(KAGConstants.PROJECT_CONFIG_KEY, {})  
            global_config['namespace'] = namespace  
            if host_addr:  
                global_config['host_addr'] = host_addr  
            
            # 确保使用配置文件中的project_id  
            project_id = global_config.get('id')  
            if project_id:  
                global_config['project_id'] = project_id  
                
            kb_conf.global_config.initialize(**global_config)  
            
            return kb_conf  
        except Exception as e:  
            logger.error(f"Failed to initialize project config: {e}")  
            raise HTTPException(status_code=500, detail=f"项目配置初始化失败: {e}")
      
    async def build_knowledge_base(self, request: BuildRequest) -> str:  
        """异步构建知识库"""  
        task_id = f"{request.namespace}_{hash(request.file_path)}"  
          
        try:  
            # 更新任务状态  
            task_status[task_id] = {  
                "status": "running",  
                "message": "开始构建知识库",  
                "progress": 0  
            }  
              
            # 加载配置文件  
            config = self._load_config(request.config_file)  
              
            # 初始化项目配置  
            project_config = self._init_project_config(  
                config, request.namespace, request.host_addr  
            )  
              
            # 关键：在创建组件之前，初始化全局KAG_CONFIG
            # 这样所有组件（包括直接使用KAG_PROJECT_CONF的Prompt类）都能获取正确的配置
            # 使用线程锁确保线程安全
            config_lock = threading.Lock()
            with config_lock:
                # 保存原始配置
                original_config = copy.deepcopy(KAG_CONFIG.all_config) if KAG_CONFIG._is_initialized else None
                
                # 初始化全局配置
                init_env(request.config_file)
                
                try:
                    # 创建BuilderChainStreamRunner，使用全局KAG_CONFIG
                    

                    builder_config = copy.deepcopy(KAG_CONFIG.all_config["kag_builder_pipeline"])
                    runner = BuilderChainRunner.from_config(
                        builder_config
                    )
                    
                    # 在线程池中执行同步的invoke方法
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None,   
                        runner.invoke,   
                        request.file_path  
                    )
                    print("file_path:",request.file_path )
                    
                    # 更新任务状态  
                    task_status[task_id] = {  
                        "status": "completed",  
                        "message": "知识库构建完成",  
                        "progress": 100  
                    }  
                      
                    print(f"Successfully built knowledge base for namespace: {request.namespace}")  
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
            logger.error(f"Failed to build knowledge base for namespace {request.namespace}: {e}")  
            raise HTTPException(status_code=500, detail=f"知识库构建失败: {e}")  

# 初始化服务  
builder_service = KAGBuilderService()  

@app.post("/build", response_model=BuildResponse)  
async def build_knowledge_base(request: BuildRequest):  
    """  
    构建知识库接口  
      
    Args:  
        request: 构建请求参数  
          
    Returns:  
        BuildResponse: 构建任务响应  
    """  
    try:  
        task_id = await builder_service.build_knowledge_base(request)  
        return BuildResponse(  
            task_id=task_id,  
            status="started",  
            message="知识库构建任务已启动"  
        )  
    except HTTPException:  
        raise  
    except Exception as e:  
        logger.error(f"Unexpected error in build_knowledge_base: {e}")  
        raise HTTPException(status_code=500, detail=f"内部服务器错误: {e}")  

@app.get("/status/{task_id}")  
async def get_task_status(task_id: str):  
    """  
    获取任务状态接口  
      
    Args:  
        task_id: 任务ID  
          
    Returns:  
        Dict: 任务状态信息  
    """  
    if task_id not in task_status:  
        raise HTTPException(status_code=404, detail="任务不存在")  
      
    return task_status[task_id]  

@app.get("/health")  
async def health_check():  
    """健康检查接口"""  
    return {"status": "healthy", "service": "KAG Builder API"}  


if __name__ == "__main__":  
    import uvicorn  
    uvicorn.run(app, host="0.0.0.0", port=8000)
