# 任务级 config 与多进程 worker 读 config

本文梳理 **任务级配置（KAG_QA_TASK_CONFIG / set_task_config / get_config）** 的设计与用法，以及 **BuilderChainStreamRunner 多进程 worker** 下读 config 的现状与问题。与 [kag_design_and_conf.md](./kag_design_and_conf.md) 中的 conf / init_env 说明配合阅读。

---

## 一、任务级 config 设计

### 1.1 目的

- **多任务并存**：同一进程内可能同时服务多路「任务」（如多 KB 问答、多项目构建），各自使用不同 `kag_config`（namespace、ckpt_dir、vectorize_model、llm 等）。
- **避免全局互踩**：若只靠 `KAG_CONFIG` 单例，多任务会争用同一份配置，无法隔离。
- **任务级存储**：`KAG_QA_TASK_CONFIG`（LinkCache）按 **task_id** 存 `KAGConfigMgr`，`KAGConfigAccessor.set_task_config` / `get_config(task_id)` 做存取。

### 1.2 核心机制

| 机制 | 说明 |
|------|------|
| **task_id** | 字符串，唯一标识一路任务。如 solver 侧 `kb_task_project_id = f"{task_id}_{kb_project_id}"`，按「会话 + KB」维度。 |
| **KAG_QA_TASK_CONFIG_KEY** | 常量 `"kag_qa_task_config_key"`。在配置或 `kwargs` 里传 task_id 时使用的 key。 |
| **set_task_config(task_id, cfg)** | 将 `KAGConfigMgr` 实例 `cfg` 存入 `KAG_QA_TASK_CONFIG`，key 为 `task_id`。 |
| **get_config(task_id)** | `task_id` 非空 → `KAG_QA_TASK_CONFIG.get(task_id)`；否则 → `get_default_config()`（见 [kag_design_and_conf.md](./kag_design_and_conf.md)）。 |

### 1.3 组件侧用法

多数需要 config 的组件（Builder 的 base、Reader/Splitter/Extractor…，Solver 的 Retriever/Executor/Generator/Prompt，以及 tools、indexer 等）统一采用：

```python
task_id = kwargs.get(KAGConstants.KAG_QA_TASK_CONFIG_KEY, None)
kag_config = KAGConfigAccessor.get_config(task_id)
# 后续用 kag_config.global_config（project_id、ckpt_dir、namespace…）或 kag_config.all_config
```

即：**从 kwargs 拿 task_id，再用 get_config 取该任务的配置**。若构造时未传 `kag_qa_task_config_key`，则 `task_id=None`，走 `get_default_config()`（通常即 `KAG_CONFIG`）。

### 1.4 task_id 的注入与传递

- **配置注入**：在 YAML 或 `config` dict 里为某组件（或整条 pipeline）加上 `kag_qa_task_config_key: <task_id>`。`from_config` → `create_kwargs` 时，该 key 会进入对应构造函数的 `**kwargs`，从而被 `kwargs.get(KAG_QA_TASK_CONFIG_KEY)` 拿到。
- **显式传递**：调用 `X.from_config(...)` 时，在 config 里塞入 `kag_qa_task_config_key`；或实例化后通过 `kwargs` 传。
- **链式传递**：如 `KAGIndexManager.build_retriever_config(..., kag_qa_task_config_key=kb_task_project_id)`，构建出的 retriever 配置里带上 `kag_qa_task_config_key`，下游 `from_config` 时继续传给子组件。

### 1.5 典型使用场景

- **main_solver 多 KB QA**（`kag.solver.main_solver`）：  
  - 为每个 KB 构造 `kb_conf = KAGConfigMgr()`，填好 `global_config`、`llm`、`vectorize_model` 等。  
  - `kb_task_project_id = f"{task_id}_{kb_project_id}"`，`KAGConfigAccessor.set_task_config(kb_task_project_id, kb_conf)`。  
  - `do_qa_pipeline` 里 `get_config(kb_task_project_id)` 取该 KB 配置，再构建 `KAGIndexManager` / retriever 等，并把 `kag_qa_task_config_key=kb_task_project_id` 传下去。
- **Indexer**（`KAGIndexManager` 等）：构建各类 index / retriever config 时，把 `kag_qa_task_config_key` 写入嵌套 config，便于检索端按任务取 config。

### 1.6 与全局 KAG_CONFIG 的关系

- **任务级优先**：有 `task_id` 时，组件一律用 `get_config(task_id)`，即 `KAG_QA_TASK_CONFIG` 里的任务配置。
- **兜底**：`task_id` 为空或 `get_config(None)` 时走 `get_default_config()`，通常返回 `KAG_CONFIG`（或 cache 里任意一项）。
- **init_env 只改 KAG_CONFIG**：`init_env(config_file)` 只初始化/覆盖全局 `KAG_CONFIG`，**不会**往 `KAG_QA_TASK_CONFIG` 里 `set_task_config`。任务级配置由业务逻辑（如 main_solver、api 层）按需 `set_task_config`。

---

## 二、多进程 worker 与 config

### 2.1 涉及代码

- **BuilderChainStreamRunner**（`kag.builder.runner`）：  
  - 使用 `ProcessPoolExecutor` 多进程执行 builder chain。  
  - `invoke` 时取 `chain_config = self.chain.to_config()`，然后：

    ```python
    ProcessPoolExecutor(
        max_workers=self.num_chains,
        initializer=self._init_worker,
        initargs=(chain_config, self.num_threads_per_chain, self.register_path),
    )
    ```

  - 每个 worker 进程启动时调用 `_init_worker(chain_config, num_threads, register_path)`。

- **_init_worker 当前逻辑**：  
  - `import_modules_from_path(register_path)`；  
  - `process_chain = KAGBuilderChain.from_config(chain_config)`，在 **当前 worker 进程** 内重新构建 chain；  
  - `process_num_threads = num_threads` 供后续 `process()` 使用。

### 2.2 进程隔离导致的现象

- **内存不共享**：子进程由 `ProcessPoolExecutor` 创建（Windows 上多为 spawn），有独立内存空间。  
  - 主进程里对 `KAG_CONFIG` 的修改、对 `KAG_QA_TASK_CONFIG` 的 `set_task_config`，**子进程均不可见**。  
  - 子进程中的 `KAG_CONFIG`、`KAG_QA_TASK_CONFIG` 是 import `kag.common.conf` 时在本进程内新初始化的对象。

- **子进程何时初始化 conf**：  
  - worker 里会 `import` 到 `kag`（例如通过 `import_modules_from_path` 或 `KAGBuilderChain.from_config` 的调用链）。  
  - `kag/__init__.py` 里执行 `init_env()`，**无参**，即 `config_file=None`。  
  - 于是 `load_config(False, None)` → `_closest_cfg()` 从 **当前工作目录** 向上找 `kag_config.yaml`，用找到的（或空）配置初始化 **该 worker 进程** 的 `KAG_CONFIG`。  
  - 没有任何 `set_task_config` 在 worker 里被调用，故 **worker 进程的 `KAG_QA_TASK_CONFIG` 始终为空**。

### 2.3 chain_config 里有没有 task_id？

- `chain_config` 来源于主进程 `self.chain.to_config()`。  
- `Registrable.to_config()` 只序列化 `__constructor_called__.keywords` 里出现的 **具名构造参数**，**不**包含 `**kwargs`（即不包含 `__from_config_kwargs__` 里那些 key，如 `kag_qa_task_config_key`）。  
- 因此，即令主进程构建 chain 时注入了 `kag_qa_task_config_key`，**serialize 成的 `chain_config` 里也没有 task_id**。  
- worker 里 `from_config(chain_config)` 构造 chain 及其子组件时，`kwargs.get(KAG_QA_TASK_CONFIG_KEY)` 恒为 `None`，组件只会走 `get_config(None)`。

### 2.4 worker 里实际用的是哪份 config？

- 组件侧：`task_id=None` → `get_config(None)` → `get_default_config()`。  
- `get_default_config()`：  
  - 若 `KAG_CONFIG.global_config.project_id` 有值 → 返回 `KAG_CONFIG`；  
  - 否则若 `KAG_QA_TASK_CONFIG.cache` 非空 → 返回其中一项；  
  - 否则 → 返回 `KAG_CONFIG`。  
- worker 内 `KAG_QA_TASK_CONFIG` 为空，因此 **永远落到 `KAG_CONFIG`**。  
- 而该 `KAG_CONFIG` 是由 worker 进程里 `init_env()` 无参、按 `_closest_cfg()` 初始化得到的，**并非**主进程为本次构建任务准备的（例如 `init_env(config_file)` 或 `set_task_config` 用的）那份配置。

### 2.5 若传入 task_id 会怎样？（主进程 set_task_config 的假设）

- 即便我们通过某种方式在 `chain_config` 里带上 `kag_qa_task_config_key`（例如扩展 `to_config` 序列化 `__from_config_kwargs__`），worker 里组件会 `get_config(task_id)`。  
- 但 **worker 从未 `set_task_config(task_id, ...)`**，`KAG_QA_TASK_CONFIG.get(task_id)` 为 `None`。  
- 组件若直接使用 `kag_config.global_config` 等，就会出现 **`'NoneType' object has no attribute 'global_config'`** 这类错误。  
- 根因仍是：**任务级 config 只存在于主进程，多进程 worker 无法访问**。

### 2.6 小结：多进程 worker 读 config 的现状

| 项目 | 说明 |
|------|------|
| **config 来源** | worker 内 `KAG_CONFIG` 由本进程 `init_env()` 无参 + `_closest_cfg()` 初始化得到。 |
| **任务级 cache** | worker 的 `KAG_QA_TASK_CONFIG` 恒为空，从未 `set_task_config`。 |
| **chain_config** | `to_config` 不序列化 `kag_qa_task_config_key`，worker 侧 chain 构造时 `task_id` 恒为 `None`。 |
| **组件取 config** | 一律 `get_config(None)` → `get_default_config()` → worker 的 `KAG_CONFIG`。 |
| **与主进程是否一致** | 否。主进程可能用 `init_env(config_file)` 或任务级 `set_task_config` 指定项目/任务配置；worker 用的是 `_closest_cfg()` 的默认 config，且拿不到任务级配置。 |

因此，**在现有实现下，多进程 worker 既拿不到主进程的任务级 config，也拿不到主进程为本次构建专门初始化的 KAG_CONFIG**；若再依赖 `get_config(task_id)`，还会出现 `NoneType` 问题。

---

## 三、import_modules_from_path 的作用

### 3.1 功能说明

`import_modules_from_path(path)`（`kag.common.registry.utils`）用于 **按路径扫描并 import 该路径下的所有子模块**，从而把用户自定义的类加载进来并完成 **Registrable 注册**。这样后续 `from_config` 里 `type: "my_custom_scanner"` 等才能解析到对应实现。

### 3.2 实现要点（逻辑简述）

- 将 `path` 转为绝对路径，调用 `importlib.invalidate_caches()` 清一下 import 缓存。  
- 按最后一级目录拆成「父目录」与「包名」：父目录加入 `sys.path`，再 `importlib.import_module(package_name)` 导入顶层包。  
- 用 `pkgutil.walk_packages` 遍历该包的 `__path__`，只处理路径匹配的子包，**递归**调用 `import_modules_from_path` 导入所有子模块。

因此，传给 `path` 的应是一个 **可被当作 Python 包** 的目录（含 `__init__.py` 或为隐式 namespace package），且该目录已在 `sys.path` 的某个父路径下，或通过函数内 `append_python_path` 被加入。

### 3.3 典型用途

- **注册自定义组件**：项目在 `data/<namespace>/`、`examples/baike/` 等目录下定义自己的 scanner、reader、indexer、prompt、extractor 等，并 `@Registrable.register("builder")` 等装饰。这些模块**不会**被 `kag` 包默认 import。若在跑 builder / indexer / solver 前不调用 `import_modules_from_path`，则 `from_config` 时 `type` 指向这些自定义类会 **找不到**，报错。  
- **多进程 worker 内**：`BuilderChainStreamRunner._init_worker` 里会 `import_modules_from_path(register_path)`。每个 worker 进程有独立 `sys.path` 与 import 状态，**必须在 worker 内再调一次**，才能在该进程中注册这些自定义类；否则 `KAGBuilderChain.from_config(chain_config)` 时 chain 里引用到的自定义 `type` 会解析失败。  
- **API / 服务入口**：`builder_service`、`retriever_service`、`api_builder` 等在处理请求前 `import_modules_from_path(".")`，即把**当前工作目录**当作包根，扫入自定义组件，确保后续构建/检索用到的 `type` 都已注册。

### 3.4 常见调用方式

| 调用 | 含义 |
|------|------|
| `import_modules_from_path(".")` | 以当前工作目录为包根，加载其下所有子模块。常见于 api、examples 的 indexer/qa 入口。 |
| `import_modules_from_path(register_path)` | 以配置里的 `register_path`（如 `./data/Test8`、项目根）为包根加载。StreamRunner 的 `_init_worker` 用此路径，与 `kag_builder_pipeline` 里配置的 `register_path` 一致。 |
| `import_modules_from_path("./prompt")` | 只加载 `./prompt` 下的子模块，多见于 solver 的 eval/qa 脚本，注册自定义 prompt。 |

### 3.5 与 conf / init_env 的关系

- `import_modules_from_path` **只做 import，不读、不改** `KAG_CONFIG` 或 `KAG_QA_TASK_CONFIG`。  
- 但 import 过程中会间接执行 `kag` 的包初始化（若尚未导入），从而执行 `init_env()`，进而初始化 **当前进程** 的 `KAG_CONFIG`。在 **多进程 worker** 里，这就是 worker 进程首次碰到 `kag` 的时机，`init_env()` 无参，用 `_closest_cfg()` 初始化 worker 的全局 config（见本文 2.2、2.4）。  
- 因此，**在 worker 里先 `import_modules_from_path` 再 `from_config`** 时，自定义组件已被注册，但此时 `KAG_CONFIG` / `KAG_QA_TASK_CONFIG` 已是该 worker 进程自己的状态，与主进程无关。

### 3.6 小结

| 项目 | 说明 |
|------|------|
| **作用** | 按路径递归 import 子模块，使自定义类完成 Registrable 注册，`from_config` 能解析对应 `type`。 |
| **谁需要调** | 使用自定义 scanner/reader/indexer/prompt 等组件的入口（api、examples、CLI）及 **每个** 多进程 worker。 |
| **不做的** | 不加载或修改 conf；config 的初始化仍由 `init_env` / `set_task_config` 等完成。 |
| **与 worker** | worker 必须在本进程内自己调一次，否则 `from_config(chain_config)` 里引用的自定义 `type` 无法解析。 |

---

## 四、可选改造方向（供后续实现参考）

不改变现有行为，仅列思路，便于后续设计「任务级 config + 多进程 worker」的改造方案。

1. **通过 initargs 把任务 config 传给 worker**  
   - 主进程在创建 `ProcessPoolExecutor` 前，把当前任务的 `KAGConfigMgr`（或可序列化的 dict + ckpt_dir 等）放进 `initargs`。  
   - `_init_worker` 在 **每个 worker 进程内** 根据这些参数构造一个本地的 `KAGConfigMgr`，并调用 `set_task_config(task_id, cfg)` 塞入该 worker 的 `KAG_QA_TASK_CONFIG`。  
   - 同时需保证 `chain_config` 或下游构造路径里带有 `kag_qa_task_config_key`，组件才能 `get_config(task_id)` 拿到这份配置。

2. **在 worker 内显式初始化 KAG_CONFIG**  
   - 若希望 worker 不依赖任务级 cache，可把「当前任务用的 config」通过 initargs 传入，在 `_init_worker` 里写 `KAG_CONFIG.config` / `global_config` 等，让 `get_config(None)` 直接落在正确的 config 上。  
   - 需注意并发：同一进程池多任务复用 worker 时，若共享 `KAG_CONFIG`，要考虑覆盖与互斥。

3. **扩展 to_config 序列化 task_id**  
   - 若坚持用任务级 config，需在 `to_config`（或 `to_config_with_constructor`）中把 `kag_qa_task_config_key` 等 `__from_config_kwargs__` 一并序列化进 `chain_config`，worker 里 `from_config` 才能把 `task_id` 传给组件。  
   - 再结合 1，在 worker 内 `set_task_config(task_id, cfg)`，否则 `get_config(task_id)` 仍为 `None`。

4. **worker 内 patch get_config**  
   - 在 `_init_worker` 里，根据传入的 `task_id` 与任务 config，patch `KAGConfigAccessor.get_config`（或 `get_default_config`），使 `get_config(None)` / `get_config(task_id)` 在 **该 worker 进程** 内均返回传入的任务 config。  
   - 可避免依赖 `KAG_QA_TASK_CONFIG` 的 cache，但需保证 patch 作用域仅限当前 worker，且与 1 或 2 的 config 来源一致。

5. **避免多进程，改用线程**  
   - 若 builder 链路可接受 GIL，用 `ThreadPoolExecutor` 替代 `ProcessPoolExecutor`，则所有线程共享同一进程的 `KAG_CONFIG`、`KAG_QA_TASK_CONFIG`。  
   - 主线程 `set_task_config` 或 `init_env(config_file)` 后，worker 线程可直接 `get_config(task_id)` 或 `get_config(None)`。  
   - 需评估 builder 的 IO/CPU 比例及对并发度的需求。

上述方向可单独或组合使用，具体取舍取决于是否必须用多进程、是否统一走任务级 config、以及能否接受对 `to_config` / `_init_worker` 的改动。

---

## 五、与现有 doc 的衔接

- **conf / init_env / KAG_CONFIG / KAG_QA_TASK_CONFIG**：见 [kag_design_and_conf.md](./kag_design_and_conf.md)。  
- **Builder 链路**：组件类型、执行流程、配置结构，见 [builder_chain.md](./builder_chain.md)。  
- **任务级 config**：本文 1；**多进程 worker 读 config**：本文 2；**import_modules_from_path**：本文 3；**改造方向**：本文 4。  
- builder 的 **api 层**（如 `builder_service`）若只用 `init_env(config_file)` + 全局 `KAG_CONFIG`，而不用 `set_task_config`，则与「任务级 config」无关；一旦引入 `BuilderChainStreamRunner` 等多进程执行，即落入本文 2 的 worker 读 config 问题，需要按 4 的思路做针对性设计。
