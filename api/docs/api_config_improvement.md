# API 接口 config 使用改进方案

当前 `builder_router` 和 `retriever_router` 使用全局 `KAG_CONFIG` 并加锁，导致并发问题。本文基于任务级 config 设计提出改进方案。

---

## 一、当前问题分析

### 1.1 现状

**builder_service.py**：
```python
config_lock = threading.Lock()
with config_lock:
    original_config = copy.deepcopy(KAG_CONFIG.all_config) if KAG_CONFIG._is_initialized else None
    init_env(config_file)  # 覆盖全局 KAG_CONFIG
    KAG_CONFIG.global_config.ckpt_dir = ckpt_dir
    try:
        runner = BuilderChainRunner.from_config(builder_config)
        await loop.run_in_executor(None, runner.invoke, file_path)
    finally:
        # 恢复原始配置
        if original_config is not None:
            KAG_CONFIG.config = original_config
            KAG_CONFIG.global_config.initialize(**global_config)
```

**retriever_service.py**：
```python
config_lock = threading.Lock()
with config_lock:
    original_config = copy.deepcopy(KAG_CONFIG.all_config) if KAG_CONFIG._is_initialized else None
    init_env(config_file)  # 覆盖全局 KAG_CONFIG
    try:
        executor = ExecutorABC.from_config(executor_config)
        await executor.ainvoke(...)
    finally:
        # 恢复原始配置
        if original_config is not None:
            KAG_CONFIG.config = original_config
            KAG_CONFIG.global_config.initialize(**global_config)
```

### 1.2 问题

| 问题 | 说明 |
|------|------|
| **锁导致串行化** | `threading.Lock()` 使所有请求串行执行，无法真正并发 |
| **配置互相覆盖** | 即使有锁，多个请求的配置会互相覆盖全局 `KAG_CONFIG` |
| **恢复配置风险** | `finally` 中恢复配置时，若异常可能导致配置状态不一致 |
| **多进程 worker 问题** | `BuilderChainStreamRunner` 的 worker 进程无法访问主进程的任务级配置（见 [task_config_and_multiprocess_worker.md](./task_config_and_multiprocess_worker.md)） |
| **不符合设计** | KAG 框架设计了任务级 config（`KAG_QA_TASK_CONFIG`），但 API 层未使用 |

---

## 二、改进方案

### 2.1 核心思路

1. **使用任务级 config**：为每个请求生成 `task_id`，创建任务级 `KAGConfigMgr`，调用 `set_task_config(task_id, cfg)`
2. **注入 task_id**：在 runner / executor 配置中注入 `kag_qa_task_config_key`
3. **移除全局修改**：不再修改全局 `KAG_CONFIG`，移除锁
4. **避免多进程**：使用 `BuilderChainRunner`（base，线程池）而非 `BuilderChainStreamRunner`（stream，进程池），避免进程隔离问题

### 2.2 改进后的流程

#### Builder Service 改进

```python
async def build_knowledge_base(self, session, project_id) -> str:
    # 1. 获取项目信息
    project = await ProjectRepository.get_by_id(session, project_id)
    namespace = project.namespace
    config_file = f"./data/{namespace}/kag_config.yaml"
    file_path = f"./data/{namespace}/builder/data"
    
    # 2. 生成唯一 task_id
    import time
    task_id = f"{namespace}_{int(time.time() * 1000000)}"
    
    # 3. 加载配置并创建任务级 config
    config = self._load_config(config_file)
    task_cfg = KAGConfigMgr()
    task_cfg.update_conf(config)
    
    global_config = config.get(KAGConstants.PROJECT_CONFIG_KEY, {})
    global_config['namespace'] = namespace
    global_config['ckpt_dir'] = f"./data/{namespace}/builder/ckpt"
    if global_config.get('id'):
        global_config['project_id'] = global_config['id']
    task_cfg.global_config.initialize(**global_config)
    
    # 4. 设置任务级 config（不再修改全局 KAG_CONFIG）
    KAGConfigAccessor.set_task_config(task_id, task_cfg)
    
    # 5. 注入 task_id 到 builder_config
    builder_config = copy.deepcopy(config.get("kag_builder_pipeline", {}))
    builder_config[KAGConstants.KAG_QA_TASK_CONFIG_KEY] = task_id
    
    # 6. 递归注入到所有嵌套组件配置
    self._inject_task_id(builder_config, task_id)
    
    # 7. 确保使用 base runner（线程池），而非 stream runner（进程池）
    # 若配置中指定了 type: stream，需要改为 base 或移除 type
    if builder_config.get("type") == "stream":
        builder_config["type"] = "base"  # 或直接删除 type，默认就是 base
    
    # 8. 构建 runner（组件会通过 get_config(task_id) 获取任务配置）
    runner = BuilderChainRunner.from_config(builder_config)
    
    # 9. 执行方式选择：
    # 方式 A：使用异步 ainvoke（推荐，不阻塞事件循环）
    await runner.ainvoke(file_path)
    
    # 方式 B：使用同步 invoke + run_in_executor（放入线程池，避免阻塞）
    # loop = asyncio.get_event_loop()
    # await loop.run_in_executor(None, runner.invoke, file_path)
    
    # 10. 清理（可选，KAG_QA_TASK_CONFIG 有 TTL 300 秒，会自动清理）
    # 若需要立即清理，可调用：
    # from kag.common.conf import KAG_QA_TASK_CONFIG
    # KAG_QA_TASK_CONFIG.cache.pop(task_id, None)
```

#### Retriever Service 改进

```python
async def retrieve(self, session, project_id, query) -> Dict[str, Any]:
    # 1. 获取项目信息
    project = await ProjectRepository.get_by_id(session, project_id)
    namespace = project.namespace
    config_file = f"./data/{namespace}/kag_config.yaml"
    
    # 2. 生成唯一 task_id
    import time
    task_id = f"{namespace}_retrieve_{int(time.time() * 1000000)}"
    
    # 3. 加载配置并创建任务级 config
    config = self._load_config(config_file)
    task_cfg = KAGConfigMgr()
    task_cfg.update_conf(config)
    
    global_config = config.get(KAGConstants.PROJECT_CONFIG_KEY, {})
    global_config['namespace'] = namespace
    if global_config.get('id'):
        global_config['project_id'] = global_config['id']
    task_cfg.global_config.initialize(**global_config)
    
    # 4. 设置任务级 config
    KAGConfigAccessor.set_task_config(task_id, task_cfg)
    
    # 5. 注入 task_id 到 executor_config
    executor_config = copy.deepcopy(config.get("kag_hybrid_executor", {}))
    executor_config[KAGConstants.KAG_QA_TASK_CONFIG_KEY] = task_id
    self._inject_task_id(executor_config, task_id)
    
    # 6. 构建 executor（会通过 get_config(task_id) 获取任务配置）
    executor = ExecutorABC.from_config(executor_config)
    
    # 7. 执行
    task = Task(executor=executor.schema()["name"], arguments={"query": query})
    context = Context()
    await executor.ainvoke(query=query, task=task, context=context)
    
    return {"summary": task.result.summary, "references": task.result.to_dict()}
```

### 2.3 辅助方法：递归注入 task_id

```python
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
```

---

## 三、Runner 类型选择：避免多进程

### 3.1 为什么不用多进程

| 问题 | 说明 |
|------|------|
| **进程隔离** | worker 进程无法访问主进程的 `KAG_QA_TASK_CONFIG`，需要序列化传递配置 |
| **配置传递复杂** | 需要通过 `initargs` 传递，pickle 序列化，worker 内重建，容易出错 |
| **调试困难** | 多进程环境下调试、日志追踪更复杂 |
| **开销大** | 进程创建、IPC 通信开销比线程大 |
| **FastAPI 异步** | FastAPI 是异步框架，使用线程池或协程更合适 |

### 3.2 推荐方案

**使用 `BuilderChainRunner`（base，默认）**：
- 使用 `ThreadPoolExecutor`（线程池）
- 线程共享进程内存，可直接访问 `KAG_QA_TASK_CONFIG`
- 无需额外配置传递
- 适合 FastAPI 异步框架

**执行方式**：
- **推荐**：`await runner.ainvoke(file_path)`（异步，不阻塞事件循环）
- **备选**：`await loop.run_in_executor(None, runner.invoke, file_path)`（同步 invoke 放入线程池）

### 3.3 配置调整

若 YAML 配置中指定了 `type: stream`，需要改为 `base` 或移除 `type`（默认就是 base）：

```python
# 在构建 runner 前
if builder_config.get("type") == "stream":
    builder_config["type"] = "base"  # 或 builder_config.pop("type", None)
```

---

## 四、改进效果

### 4.1 优势

| 优势 | 说明 |
|------|------|
| **真正并发** | 移除锁，多个请求可并发处理，互不干扰 |
| **配置隔离** | 每个请求使用独立的任务级 config，不会互相覆盖 |
| **符合设计** | 使用 KAG 框架设计的任务级 config 机制 |
| **无需恢复** | 不再需要保存/恢复全局配置，避免状态不一致 |
| **避免进程隔离** | 使用线程池而非进程池，无需处理进程间配置传递 |

### 4.2 注意事项

1. **task_id 唯一性**：确保每个请求的 `task_id` 唯一（可用时间戳 + 随机数）
2. **内存管理**：`KAG_QA_TASK_CONFIG` 有 TTL（300 秒），过期自动清理；也可手动清理
3. **向后兼容**：若组件未传 `task_id`，会走 `get_default_config()`，仍可用全局 `KAG_CONFIG`
4. **Runner 类型**：使用 `BuilderChainRunner`（base，线程池）而非 `BuilderChainStreamRunner`（stream，进程池），避免进程隔离问题

---

## 五、实施步骤

1. **修改 builder_service.py**：
   - 移除 `config_lock` 和全局 `KAG_CONFIG` 的修改
   - 实现任务级 config 创建与 `set_task_config`
   - 实现 `_inject_task_id` 方法
   - 在 `builder_config` 中注入 `task_id`

2. **修改 retriever_service.py**：
   - 移除 `config_lock` 和全局 `KAG_CONFIG` 的修改
   - 实现任务级 config 创建与 `set_task_config`
   - 在 `executor_config` 中注入 `task_id`

3. **确保使用 base runner**：
   - 检查 `kag_builder_pipeline` 配置，若 `type: stream` 改为 `base` 或移除
   - 使用 `runner.ainvoke()`（异步）或 `run_in_executor(None, runner.invoke, ...)`（线程池）

4. **测试**：
   - 并发请求多个项目的构建/检索，验证配置隔离
   - 验证任务级 config 正确传递到所有组件

---

## 六、与文档的衔接

- **任务级 config 设计**：见 [task_config_and_multiprocess_worker.md](./task_config_and_multiprocess_worker.md) 第一节
- **多进程 worker 问题**（了解即可，本方案不使用）：见 [task_config_and_multiprocess_worker.md](./task_config_and_multiprocess_worker.md) 第二节
- **Runner 方法差异**：`invoke` vs `ainvoke` 见 [builder_runner_invoke_vs_ainvoke.md](./builder_runner_invoke_vs_ainvoke.md)
- **conf / init_env 说明**：见 [kag_design_and_conf.md](./kag_design_and_conf.md)
