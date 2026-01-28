# KAG 设计思路与 conf / init_env 说明

## 一、kag 目录的设计思路

### 1. 整体定位

`kag` 是 **知识增强生成（Knowledge Augmented Generation）** 框架，围绕两条主线：

| 主线 | 作用 | 核心模块 |
|------|------|----------|
| **Builder** | 知识库构建：从原始数据 → 抽取 → 写入图/向量 | `kag.builder` |
| **Solver** | 问答/推理：问题 → 规划 → 检索 → 生成答案 | `kag.solver` |

二者共用 **interface** 中的抽象、**conf** 中的配置、以及 **common** 里的向量/重排/LLM/工具等能力。

### 2. 组件化与注册机制

- **Registrable**：`kag.common.registry` 提供 `from_config` + 按 `type` 注册。配置里写 `type: "xxx"` 即从注册表解析并实例化。
- **Builder 组件**：继承 `BuilderComponent`，用 `@Registrable.register("builder")` 注册（如 `txt_reader`、`length_splitter`、`directory_scanner`）。`kag.builder.component` 的 import 会触发这些注册。
- **Builder 链**：`KAGBuilderChain` 子类（如 `DefaultUnstructuredBuilderChain`）用 `@KAGBuilderChain.register("unstructured")` 等注册，`default_chain`、`runner` 等 import 时完成注册。
- **Solver**：Planner、Executor、Generator、Pipeline、Prompt 等 likewise 注册；`kag.solver`、`kag.solver.prompt` 等 import 时拉入。
- **自定义组件**：项目在 `data/<namespace>/`、`examples/xxx/` 等目录下定义的 scanner、reader、prompt、indexer 等，**不会**被 `kag` 包默认 import。需要在运行前调用 **`import_modules_from_path(path)`**（`kag.common.registry`），按路径递归 import 子模块，使这些类完成注册；否则 `from_config` 里 `type` 指向自定义类会找不到。API / examples 入口及多进程 worker 内均需在构建 chain 或 indexer 前调用。详见 [task_config_and_multiprocess_worker.md](./task_config_and_multiprocess_worker.md) 第三节「import_modules_from_path 的作用」。

因此，**`kag/__init__.py` 里大量 `import kag.xxx` 的主要目的**是：**触发这些子模块加载，从而完成各类组件的注册**，方便后续 `from_config` 根据 YAML 里的 `type` 反序列化出实例。

### 3. 配置驱动

- 运行时的 DAG（scanner → reader → splitter → extractor → …）、solver 的 pipeline/planner/executor 等，通常由 **YAML 配置** 描述。
- `KAGConfigMgr` 存 `config`（原始字典）和 `global_config`（项目级：project_id、namespace、ckpt_dir、language 等），供组件通过 `KAGConfigAccessor.get_config(...)` 按 **task_id** 或 **全局** 取用。

---

## 二、conf 是干什么用的

`kag.common.conf` 负责 **全局与任务级配置** 的存储、加载和访问。

### 1. 核心对象

| 名字 | 类型 | 含义 |
|------|------|------|
| `KAGConstants` | 类 | 常量：配置 key、env 变量名、文件名等 |
| `KAGGlobalConf` | 类 | 项目级配置：project_id、host_addr、namespace、ckpt_dir、language、biz_scene 等 |
| `KAGConfigMgr` | 类 | 配置管理器：`config`（全量 dict）、`global_config`（KAGGlobalConf）、`load_config` / `initialize` / `update_conf` |
| `KAG_CONFIG` | 全局单例 | `KAGConfigMgr()`，**默认/全局** 使用的配置实例 |
| `KAG_PROJECT_CONF` | 全局 | `KAG_CONFIG.global_config` 的简写 |
| `KAG_QA_TASK_CONFIG` | 全局 | `LinkCache`，**按 task_id 存任务级** `KAGConfigMgr`，供多任务场景 |
| `KAGConfigAccessor` | 类 | 静态方法：`get_config(task_id)`、`set_task_config(task_id, cfg)`、`get_default_config()` |

### 2. 配置加载（`load_config`）

- **prod=True**：用 `KAG_PROJECT_ID`、`KAG_PROJECT_HOST_ADDR` 从 **ProjectClient** 拉项目配置（远程）。
- **prod=False**：用 **本地 YAML**：
  - 若传入 `config_file` 且存在，则读该文件；
  - 否则 `_closest_cfg()` 从当前目录向上找最近的 `kag_config.yaml`。
- 本地 YAML 支持 Jinja2，可 `{{ env.XXX }}` 等引用环境变量。

### 3. 配置访问（`KAGConfigAccessor`）

- `get_config(task_id)`：  
  - 有 `task_id` → `KAG_QA_TASK_CONFIG.get(task_id)`；  
  - 否则 → `get_default_config()`。
- `get_default_config()`：  
  - 若 `KAG_CONFIG.global_config.project_id` 存在 → 返回 `KAG_CONFIG`；  
  - 否则若 task cache 有 key → 返回任一项；  
  - 否则 → 返回 `KAG_CONFIG`。
- `set_task_config(task_id, config)`：往 `KAG_QA_TASK_CONFIG` 里存该任务的 `KAGConfigMgr`。

组件（如 `BuilderComponent`）里常见的用法：`task_id = kwargs.get(KAG_QA_TASK_CONFIG_KEY)`，然后 `kag_config = KAGConfigAccessor.get_config(task_id)`，再用 `kag_config.global_config` 取 project_id、ckpt_dir 等。

---

## 三、init_env() 初始化谁

**`init_env(config_file=None)` 只做一件事：初始化全局单例 `KAG_CONFIG`。**

### 1. 具体逻辑

1. **prod 判定**：  
   `KAG_PROJECT_ID` 和 `KAG_PROJECT_HOST_ADDR` 均存在，且 **没有** 提供有效的本地 `config_file` → `prod=True`，否则 `prod=False`。
2. **调用 `KAG_CONFIG.initialize(prod, config_file)`**：  
   - `prod=True`：`load_config` 从 ProjectClient 拉配置；  
   - `prod=False`：`load_config` 从本地 `config_file` 或 `_closest_cfg()` 找到的 `kag_config.yaml` 加载。
3. **回写环境变量**（可选）：  
   若 `KAG_CONFIG.global_config` 里设置了 `project_id` / `host_addr`，则写回 `os.environ`，便于后续逻辑或子进程使用。
4. **调试**：  
   `KAG_DEBUG_DUMP_CONFIG=1` 时 pprint 完整配置。

### 2. 谁在调 init_env

- **`kag/__init__.py`**：`import kag` 时**无参**调用 `init_env()`，即用 `_closest_cfg()` 找最近的 `kag_config.yaml` 初始化 `KAG_CONFIG`。
- **api 层**：`builder_service`、`retriever_service`、`api_builder` 等，在**有明确 config 路径**时传 `config_file` 调用 `init_env(config_file)`，从而覆盖为**项目级/任务级**使用的配置文件。
- **CLI / 其它**：如 `kag bin` 命令、 benchmark、spg bridge 等，在需要时同样传 `config_file` 调用。

因此：**init_env 初始化的是全局的 `KAG_CONFIG`**；多任务场景下，任务级配置另存 `KAG_QA_TASK_CONFIG`，通过 `set_task_config` / `get_config(task_id)` 使用。

---

## 四、kag/__init__.py 里各 import 在干什么

```python
from kag.common.conf import init_env
init_env()
```

- **先**执行 `init_env()`，用默认（最近）`kag_config.yaml` 初始化 `KAG_CONFIG`，后续所有未显式传 config 的逻辑都依赖这份全局配置。

```python
import kag.interface
import kag.interface.solver.execute
import kag.interface.solver.plan
import kag.builder.component
import kag.builder.default_chain
import kag.builder.runner
import kag.builder.prompt
import kag.solver.prompt
import kag.common.vectorize_model
import kag.common.rerank_model
import kag.common.llm
import kag.common.rate_limiter
import kag.common.checkpointer
import kag.solver
import kag.bin.commands
import kag.common.tools
import kag.indexer
```

| import | 作用 |
|--------|------|
| `kag.interface` | 暴露 ABC（Prompt、LLM、Retriever、Builder 的 Scanner/Reader/Splitter/…、Solver 的 Planner/Executor/Generator 等）及通用数据结构。 |
| `kag.interface.solver.execute` / `plan` | 拉入 solver 的 execute/plan 子模块（可能含 LF 执行、规划等），完成相关注册。 |
| `kag.builder.component` | 注册所有内置 builder 组件（scanner、reader、splitter、extractor、mapping、writer、vectorizer 等）。 |
| `kag.builder.default_chain` | 注册 `DefaultStructuredBuilderChain`、`DefaultUnstructuredBuilderChain` 等链类型。 |
| `kag.builder.runner` | 注册 `BuilderChainRunner`（含 base、stream），供 builder 执行入口使用。 |
| `kag.builder.prompt` | 注册 builder 用到的 prompt（如 NER、triple、table 等）。 |
| `kag.solver.prompt` | 注册 solver 用到的各类 prompt。 |
| `kag.common.vectorize_model` | 注册/暴露向量化模型（BGE、OpenAI、Ollama、Mock 等）。 |
| `kag.common.rerank_model` | 注册/暴露重排序模型。 |
| `kag.common.llm` | 注册/暴露 LLM 客户端等。 |
| `kag.common.rate_limiter` | 限流相关能力。 |
| `kag.common.checkpointer` | 断点续跑、checkpoint 管理。 |
| `kag.solver` | 注册 pipeline、planner、executor、generator 等 solver 实现。 |
| `kag.bin.commands` | 注册 CLI 命令（builder 提交、benchmark、mcp server、info 等）。 |
| `kag.common.tools` | 注册各类工具（ graph/search API、算法工具等）。 |
| `kag.indexer` | 暴露 ChunkIndex、GraphIndex、KAGIndexManager 等索引能力。 |

```python
try:
    import kag_ant
except ImportError:
    pass
```

- 可选扩展 `kag_ant`，有则加载（如额外组件或优化），没有则忽略。

---

## 五、小结

- **设计**：Builder + Solver 双主线，Registrable 注册 + 配置驱动；interface 定抽象，各子模块 import 时完成注册。
- **conf**：维护 `KAG_CONFIG`（全局）与 `KAG_QA_TASK_CONFIG`（按 task_id），提供 `load_config`、`KAGConfigAccessor` 等，统一配置来源与访问方式。
- **init_env**：**只初始化全局 `KAG_CONFIG`**；根据 env 与 `config_file` 选择 prod/本地配置并 `initialize`，必要时回写 env。
- **`kag/__init__.py`**：先 `init_env()`，再通过一系列 `import` **拉齐** 配置、**注册** 所有内置组件与链，方便 `from_config` 和后续 builder/solver 运行。

把这几块理清后，再看「任务级 config」「多进程 worker 读 config」等，就都在同一套 conf/init_env 体系下，方便后续改设计或修 bug。

---

## 六、延伸阅读

- **DAG 与链式处理流程**：KAG 框架中所有使用 DAG/链式处理的流程汇总（Builder Chain、Solver Pipeline、Task DAG 等），见 [dag_and_chain_flows.md](./dag_and_chain_flows.md)。
- **Builder 链路**：组件类型、执行流程、配置示例，见 [builder_chain.md](./builder_chain.md)。
- **Runner 方法差异**：`BuilderChainRunner.invoke` vs `ainvoke` 的详细对比，见 [builder_runner_invoke_vs_ainvoke.md](./builder_runner_invoke_vs_ainvoke.md)。
- **任务级 config**、**多进程 worker 读 config**、**import_modules_from_path 的作用** 的详细梳理与可选改造方向，见 [task_config_and_multiprocess_worker.md](./task_config_and_multiprocess_worker.md)。
