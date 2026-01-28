# KAG 框架中的 DAG 与链式处理流程

KAG 框架中多处使用**有向无环图（DAG）**或**链式处理**来组织执行流程。本文汇总所有相关流程，说明其结构、执行方式与适用场景。

---

## 一、概览

| 流程类型 | 层级 | DAG/链式结构 | 主要用途 |
|---------|------|--------------|----------|
| **Builder Chain** | 组件级 | DAG（组件依赖） | 知识库构建：scanner → reader → splitter → extractor → ... |
| **Solver Pipeline** | 任务级 | Task DAG（任务依赖） | 问答/推理：planning → execution → generation |
| **Task DAG** | 任务内 | DAG（任务依赖） | Planner 生成的任务执行计划 |
| **KAGBuilderChain 内部 DAG** | 组件内 | DAG（节点依赖） | 组件之间的数据流转 |

---

## 二、Builder Chain（知识库构建链路）

### 2.1 结构

- **类型**：组件级 DAG
- **节点**：BuilderComponent（Scanner、Reader、Splitter、Extractor、Vectorizer、PostProcessor、Writer 等）
- **边**：数据流向（`>>` 操作符连接）
- **执行**：按拓扑序执行，每个节点内部可并行处理

### 2.2 典型流程

```
文件路径 → Scanner → Reader → Splitter → Extractor → Vectorizer → PostProcessor → Writer → 知识库
```

### 2.3 配置示例

```yaml
kag_builder_pipeline:
  chain:
    type: unstructured_builder_chain
    reader: ...
    splitter: ...
    extractor: ...
  scanner: ...
```

### 2.4 详细说明

见 [builder_chain.md](./builder_chain.md)。

---

## 三、Solver Pipeline（问答/推理流程）

### 3.1 结构

- **类型**：任务级 DAG
- **节点**：Task（由 Planner 生成）
- **边**：任务依赖（`dependent_task_ids`）
- **执行**：按拓扑序执行任务组，同组任务可并行

### 3.2 核心组件

| 组件 | 作用 |
|------|------|
| **Planner** | 生成任务 DAG（Task 列表及其依赖） |
| **Executor** | 执行单个任务（检索、推理、计算等） |
| **Generator** | 根据执行结果生成最终答案 |
| **Context** | 管理任务依赖关系，提供 DAG 构建与拓扑排序 |

### 3.3 Pipeline 类型

#### 3.3.1 KAGStaticPipeline（静态规划）

- **注册名**：`kag_static_pipeline`
- **特点**：
  - 一次性规划所有任务（Planner 生成完整 Task DAG）
  - 按 DAG 拓扑序执行任务组
  - 支持迭代重试（`max_iteration`）
- **流程**：
  ```
  1. Planning: Planner 生成 Task DAG
  2. Execution: 按拓扑序执行任务组（同组并行）
  3. Generation: Generator 生成答案
  4. 若答案不满足，可重试（迭代）
  ```
- **适用场景**：问题可一次性分解为多个独立/有依赖的任务

#### 3.3.2 KAGIterativePipeline（迭代规划）

- **注册名**：`kag_iterative_pipeline`
- **特点**：
  - 每次迭代只规划一个任务
  - 执行后根据结果决定下一步
  - 直到 `finish_executor` 或达到 `max_iteration`
- **流程**：
  ```
  while num_iteration < max_iteration:
      1. Planning: Planner 生成下一个 Task
      2. Execution: 执行该 Task
      3. 若为 finish_executor，则结束
  4. Generation: Generator 生成答案
  ```
- **适用场景**：需要逐步探索、动态调整策略的复杂问题

#### 3.3.3 IndexPipeline（索引检索）

- **注册名**：`index_pipeline`
- **特点**：
  - 无 Planner，直接执行检索任务
  - 主要用于索引构建与检索测试
- **流程**：
  ```
  1. Planning: 生成检索任务（无依赖）
  2. Execution: 执行检索
  3. Generation: 生成结果
  ```

#### 3.3.4 NaiveRAGPipeline（简单 RAG）

- **注册名**：`naive_rag_pipeline`
- **特点**：
  - 固定流程：检索 → 生成
  - 无 Planner，直接创建检索任务
- **流程**：
  ```
  1. Planning: 创建单个检索任务（无依赖）
  2. Execution: 执行检索
  3. Generation: 基于检索结果生成答案
  ```
- **适用场景**：简单问答，无需复杂规划

#### 3.3.5 NaiveGenerationPipeline（简单生成）

- **注册名**：`naive_generation_pipeline`
- **特点**：
  - 无检索，直接生成
  - 适用于无需知识库的生成任务

#### 3.3.6 SelfCognitionPipeline（自我认知）

- **注册名**：`self_cognition_pipeline`
- **特点**：
  - 判断问题是否为「自我认知」类（关于系统自身的问题）
  - 若是，返回系统信息；否则返回 False
- **流程**：
  ```
  1. 判断是否为自我认知问题
  2. 若是，返回系统信息；否则返回 False
  ```

#### 3.3.7 MCPPipeline（MCP 工具调用）

- **注册名**：`mcp_pipeline`
- **特点**：
  - 支持 MCP（Model Context Protocol）工具调用
  - 可调用外部工具/服务

### 3.4 Task DAG 结构

#### 3.4.1 Task 定义

```python
class Task:
    def __init__(self, executor, arguments, id, parents=[], ...):
        self.executor = executor  # 执行器名称
        self.arguments = arguments  # 执行参数
        self.id = id  # 任务 ID
        self.parents = parents  # 依赖的父任务列表
        self.result = None  # 执行结果
```

#### 3.4.2 DAG 格式示例

```python
task_dag = {
    "0": {
        "executor": "call_kg_retriever",
        "dependent_task_ids": [],  # 无依赖
        "arguments": {"query": "张学友出演过的电影列表"},
    },
    "1": {
        "executor": "call_kg_retriever",
        "dependent_task_ids": ["0"],  # 依赖任务 0
        "arguments": {"query": "刘德华出演过的电影列表"},
    },
    "2": {
        "executor": "call_deduce_executor",
        "dependent_task_ids": ["0", "1"],  # 依赖任务 0 和 1
        "arguments": {"operation": "intersection"},
    },
}
```

#### 3.4.3 Context 的 DAG 管理

- **`Context.get_dag()`**：构建 NetworkX DiGraph，表示任务依赖关系
- **`Context.gen_task(group=True)`**：按拓扑代（topological generations）生成任务组，同组任务可并行
- **`Context.gen_task(group=False)`**：按拓扑序生成单个任务，顺序执行

### 3.5 执行流程（以 KAGStaticPipeline 为例）

```python
async def ainvoke(self, query, **kwargs):
    context = Context()
    
    # 1. Planning: Planner 生成 Task DAG
    tasks = await self.planning(query, context, **kwargs)
    for task in tasks:
        context.add_task(task)
    
    # 2. Execution: 按拓扑代执行任务组
    for task_group in context.gen_task(group=True):
        await asyncio.gather(*[
            self.execute_task(query, task, context, **kwargs)
            for task in task_group
        ])
    
    # 3. Generation: 生成最终答案
    answer = await self.generator.ainvoke(query, context, **kwargs)
    return answer
```

### 3.6 配置示例

```yaml
solver_pipeline:
  type: kag_static_pipeline
  planner:
    type: kag_static_planner
  executors:
    - type: kag_hybrid_executor
    - type: py_based_math_executor
  generator:
    type: llm_generator
  max_iteration: 1
```

---

## 四、KAGBuilderChain 内部 DAG

### 4.1 结构

- **类型**：组件内 DAG
- **节点**：BuilderComponent 实例（Reader、Splitter、Extractor 等）
- **边**：通过 `>>` 操作符连接，表示数据流向
- **执行**：`KAGBuilderChain.invoke` / `ainvoke` 按拓扑序执行节点

### 4.2 构建方式

```python
# DefaultUnstructuredBuilderChain.build()
chain = self.reader >> self.splitter
if self.extractor:
    chain = chain >> self.extractor
if self.vectorizer:
    chain = chain >> self.vectorizer
if self.post_processor:
    chain = chain >> self.post_processor
if self.writer:
    chain = chain >> self.writer
return chain
```

### 4.3 执行方式

- **`invoke`**：同步执行，使用 `ThreadPoolExecutor` 做节点内并行
- **`ainvoke`**：异步执行，使用 `asyncio` 协程，按拓扑代并行执行节点

详见 [builder_chain.md](./builder_chain.md) 和 [builder_runner_invoke_vs_ainvoke.md](./builder_runner_invoke_vs_ainvoke.md)。

---

## 五、对比总结

### 5.1 层级对比

| 层级 | Builder Chain | Solver Pipeline | Task DAG |
|------|---------------|-----------------|----------|
| **粒度** | 组件级（Scanner、Reader 等） | 任务级（Task） | 任务内（子任务） |
| **DAG 节点** | BuilderComponent | Task | Task（由 Planner 生成） |
| **DAG 边** | 数据流向（`>>`） | 任务依赖（`dependent_task_ids`） | 任务依赖（`parents`） |
| **执行器** | BuilderChainRunner | SolverPipeline | Executor |
| **用途** | 知识库构建 | 问答/推理 | 任务分解与执行 |

### 5.2 执行方式对比

| 流程 | 拓扑排序 | 并行方式 | 迭代/重试 |
|------|----------|----------|-----------|
| **Builder Chain** | `nx.topological_sort(dag)` | 节点内并行（线程/进程池） | 无 |
| **Solver Pipeline** | `context.gen_task(group=True)` | 任务组并行（`asyncio.gather`） | 支持（KAGStaticPipeline） |
| **Task DAG** | `context.topological_generations(dag)` | 同代任务并行 | 无（但 Pipeline 可重试） |

### 5.3 数据流转对比

| 流程 | 输入 | 输出 | 中间数据 |
|------|------|------|----------|
| **Builder Chain** | 文件路径 | 知识库（图/向量） | Doc → Chunk → SubGraph |
| **Solver Pipeline** | 用户查询 | 答案文本 | Task.result（检索结果、推理结果等） |
| **Task DAG** | Task.arguments | Task.result | Context 中存储 |

---

## 六、常见使用场景

### 6.1 Builder Chain

- **场景**：从原始数据构建知识库
- **配置**：`kag_builder_pipeline`
- **执行**：`BuilderChainRunner.invoke` / `ainvoke`

### 6.2 Solver Pipeline

- **场景**：问答、推理、检索
- **配置**：`solver_pipeline` 或 `chat.ename`（如 `think_pipeline`、`index_pipeline`）
- **执行**：`SolverPipelineABC.ainvoke(query)`

### 6.3 Task DAG

- **场景**：复杂问题分解（如多跳推理、多步骤计算）
- **生成**：Planner（如 `KAGStaticPlanner`、`KAGIterativePlanner`）
- **执行**：Pipeline 的 `execute_task` 方法

---

## 七、与文档的衔接

- **Builder Chain**：详细说明见 [builder_chain.md](./builder_chain.md)
- **Builder Runner**：`invoke` vs `ainvoke` 见 [builder_runner_invoke_vs_ainvoke.md](./builder_runner_invoke_vs_ainvoke.md)
- **配置管理**：Pipeline 配置通过 `KAG_CONFIG` 读取，见 [kag_design_and_conf.md](./kag_design_and_conf.md)
- **任务级 config**：Pipeline 执行时可能使用任务级配置，见 [task_config_and_multiprocess_worker.md](./task_config_and_multiprocess_worker.md)

---

## 八、扩展阅读

- **NetworkX**：KAG 使用 NetworkX 进行 DAG 操作（`topological_sort`、`topological_generations`）
- **Registrable**：所有 Pipeline、Chain、Planner、Executor 都通过 Registrable 注册，支持 `from_config` 动态构建
- **异步执行**：Solver Pipeline 主要使用 `async`/`await`，Builder Chain 支持同步和异步两种方式
