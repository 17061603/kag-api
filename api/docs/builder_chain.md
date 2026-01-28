# Builder 链路（Builder Chain）说明

Builder 链路是 KAG 框架中用于**从原始数据构建知识库**的核心执行流程，由多个组件按顺序连接成有向无环图（DAG），逐阶段处理数据。

---

## 一、基本概念

### 1.1 什么是 Builder 链路

- **定义**：一个由多个 `BuilderComponent` 组成的**有向无环图（DAG）**，每个节点是一个组件实例，边表示数据流向。
- **作用**：将原始数据（文件、目录、数据库等）经过扫描、读取、切分、抽取、向量化、后处理、写入等步骤，最终构建成知识库（图数据库、向量库等）。
- **配置驱动**：通过 YAML 配置中的 `kag_builder_pipeline` 描述整个链路的结构与参数。

### 1.2 链路类型

| 类型 | 注册名 | 用途 | 典型组件顺序 |
|------|--------|------|--------------|
| **非结构化链路** | `unstructured_builder_chain` | 处理文本、PDF、Markdown 等非结构化数据 | scanner → reader → splitter → extractor → vectorizer → post_processor → writer |
| **结构化链路** | `structured_builder_chain` | 处理 CSV、JSON、表等结构化数据 | scanner → mapping → vectorizer → writer |
| **领域知识注入链路** | `domain_kg_inject_chain` | 从外部图加载并注入知识 | external_graph → vectorizer → writer |

---

## 二、组件类型与职责

### 2.1 Scanner（扫描器）

- **职责**：扫描数据源，生成待处理的文件路径列表。
- **输入**：数据源路径（目录、文件、数据库连接等）。
- **输出**：文件路径列表（`List[str]`）。
- **典型实现**：
  - `directory_scanner` / `dir_file_scanner`：扫描目录下所有文件
  - `file_scanner`：扫描单个文件
  - `csv_scanner`、`json_scanner`：扫描特定格式文件
  - `odps_scanner`、`sls_scanner`：扫描数据库/日志流

### 2.2 Reader（读取器）

- **职责**：读取文件内容，解析成文档对象（`Doc`）。
- **输入**：文件路径（`str`）。
- **输出**：文档列表（`List[Doc]`）。
- **典型实现**：
  - `txt_reader`：读取纯文本
  - `pdf_reader`：读取 PDF
  - `markdown_reader`：读取 Markdown
  - `docx_reader`：读取 Word
  - `mix_reader`：混合格式读取
  - `dict_reader`：从字典/JSON 读取

### 2.3 Splitter（切分器）

- **职责**：将长文档切分成更小的 chunk（块），便于后续处理。
- **输入**：文档（`Doc`）。
- **输出**：chunk 列表（`List[Chunk]`）。
- **典型实现**：
  - `length_splitter`：按长度切分（`split_length`、`window_length`）
  - `pattern_splitter`：按正则模式切分
  - `semantic_splitter`：语义切分
  - `outline_splitter`：按大纲切分

### 2.4 Extractor（抽取器）

- **职责**：从 chunk 中抽取知识（实体、关系、三元组等），生成子图（`SubGraph`）。
- **输入**：chunk（`Chunk`）。
- **输出**：子图列表（`List[SubGraph]`）。
- **典型实现**：
  - `knowledge_unit_extractor`：抽取知识单元（实体+关系）
  - `schema_free_extractor`：无模式抽取
  - `schema_constraint_extractor`：有模式约束抽取
  - `chunk_extractor`：chunk 级别抽取（用于 RAG）
  - `table_extractor`：表格抽取
  - `atomic_query_extractor`：原子查询抽取
  - `summary_extractor`、`outline_extractor`：摘要/大纲抽取

### 2.5 Vectorizer（向量化器）

- **职责**：将 chunk 或子图向量化，用于后续检索。
- **输入**：chunk 或子图。
- **输出**：带向量信息的 chunk 或子图。
- **典型实现**：
  - `batch_vectorizer`：批量向量化（`batch_size` 可配）

### 2.6 PostProcessor（后处理器）

- **职责**：对抽取结果做后处理（对齐、去重、标准化等）。
- **输入**：子图列表。
- **输出**：处理后的子图列表。
- **典型实现**：
  - `kag_post_processor`：KAG 标准后处理（对齐、合并等）

### 2.7 Writer（写入器）

- **职责**：将最终结果写入知识库（图数据库、向量库等）。
- **输入**：子图列表。
- **输出**：写入结果（通常为空或状态信息）。
- **典型实现**：
  - `kg_writer`：写入 Neo4j 等图数据库
  - `memory_graph_writer`：写入内存图（测试/调试用）

### 2.8 Mapping（映射器，仅结构化链路）

- **职责**：将结构化数据映射成图结构。
- **输入**：结构化数据（CSV 行、JSON 对象等）。
- **输出**：子图列表。
- **典型实现**：
  - `spg_type_mapping`：SPG 类型映射
  - `relation_mapping`：关系映射
  - `spo_mapping`：SPO 三元组映射

---

## 三、链路执行流程

### 3.1 配置示例

```yaml
kag_builder_pipeline:
  chain:
    type: unstructured_builder_chain
    reader:
      type: txt_reader
    splitter:
      type: length_splitter
      split_length: 300
      window_length: 1
    extractor:
      type: knowledge_unit_extractor
      llm: *openie_llm
      ner_prompt:
        type: knowledge_unit_ner
      triple_prompt:
        type: knowledge_unit_triple
    vectorizer:
      type: batch_vectorizer
      vectorize_model: *vectorize_model
    writer:
      type: kg_writer
      neo4j:
        uri: "neo4j://..."
        username: "neo4j"
        password: "..."
  scanner:
    type: dir_file_scanner
  num_chains: 20
  num_threads_per_chain: 2
```

### 3.2 执行步骤

1. **构建链路**：`KAGBuilderChain.from_config(config["chain"])` 根据配置实例化链类型（如 `DefaultUnstructuredBuilderChain`），并调用 `build()` 方法用 `>>` 操作符连接各组件，形成 DAG。
2. **扫描数据源**：`scanner.generate(file_path)` 生成文件路径列表。
3. **按 DAG 拓扑序执行**：
   - 无前驱节点（如 scanner）→ 输入为 `file_path`。
   - 有前驱节点 → 输入为前驱节点的输出列表。
   - 每个节点内部可并行处理（`ThreadPoolExecutor` 或 `ProcessPoolExecutor`）。
4. **收集输出**：DAG 中出度为 0 的节点（通常是 writer）的输出作为最终结果。

### 3.3 并行执行

- **节点级并行**：同一节点的多个输入项可并行处理（`max_workers`）。
- **链路级并行**：`BuilderChainStreamRunner` 使用 `ProcessPoolExecutor`，多个 worker 进程各自运行一条链路实例，处理 scanner 流式产生的数据。
- **配置参数**：
  - `num_chains`：进程数（`ProcessPoolExecutor` 的 `max_workers`）。
  - `num_threads_per_chain`：每个进程内的线程数（节点内并行度）。

---

## 四、数据流转

### 4.1 非结构化链路示例

```
file_path (str)
    ↓
[Scanner] → [file1, file2, ...]
    ↓
[Reader] → [Doc1, Doc2, ...]
    ↓
[Splitter] → [Chunk1, Chunk2, ...]
    ↓
[Extractor] → [SubGraph1, SubGraph2, ...]
    ↓
[Vectorizer] → [SubGraph1(with vector), ...]
    ↓
[PostProcessor] → [SubGraph1(processed), ...]
    ↓
[Writer] → (写入 Neo4j/向量库)
```

### 4.2 结构化链路示例

```
file_path (str)
    ↓
[Scanner] → [row1, row2, ...]
    ↓
[Mapping] → [SubGraph1, SubGraph2, ...]
    ↓
[Vectorizer] → [SubGraph1(with vector), ...]
    ↓
[Writer] → (写入图数据库)
```

---

## 五、与 Runner 的关系

- **BuilderChainRunner**（`type: base`）：单进程执行，使用 `ThreadPoolExecutor` 做节点内并行。
- **BuilderChainStreamRunner**（`type: stream`）：多进程执行，使用 `ProcessPoolExecutor`，适合大规模数据流式处理。
- **配置中的 `type`**：`kag_builder_pipeline` 里可指定 `type: stream`，否则默认 `base`。

---

## 六、常见配置模式

### 6.1 简单文本抽取

```yaml
kag_builder_pipeline:
  chain:
    type: unstructured_builder_chain
    reader:
      type: txt_reader
    splitter:
      type: length_splitter
      split_length: 500
    extractor:
      type: chunk_extractor  # 只做 chunk 级别抽取，用于 RAG
    vectorizer:
      type: batch_vectorizer
    writer:
      type: kg_writer
  scanner:
    type: dir_file_scanner
```

### 6.2 多抽取器并行

```yaml
kag_builder_pipeline:
  chain:
    type: unstructured_builder_chain
    extractor:
      - type: chunk_extractor
      - type: atomic_query_extractor
      - type: summary_extractor
    # ... 其他组件
```

### 6.3 结构化数据导入

```yaml
kag_builder_pipeline:
  chain:
    type: structured_builder_chain
    mapping:
      type: spg_type_mapping
    writer:
      type: kg_writer
  scanner:
    type: csv_scanner
```

---

## 七、与文档的衔接

- **DAG 与链式处理流程汇总**：Builder Chain 与其他 DAG/链式流程（Solver Pipeline、Task DAG）的对比，见 [dag_and_chain_flows.md](./dag_and_chain_flows.md)。
- **Runner 方法差异**：`BuilderChainRunner.invoke`（同步）与 `ainvoke`（异步）的详细对比，见 [builder_runner_invoke_vs_ainvoke.md](./builder_runner_invoke_vs_ainvoke.md)。
- **配置管理**：`kag_builder_pipeline` 配置通过 `KAG_CONFIG.all_config["kag_builder_pipeline"]` 读取，见 [kag_design_and_conf.md](./kag_design_and_conf.md)。
- **任务级 config**：若使用任务级配置，需在 `chain` 或各组件配置里注入 `kag_qa_task_config_key`，见 [task_config_and_multiprocess_worker.md](./task_config_and_multiprocess_worker.md)。
- **多进程 worker**：`BuilderChainStreamRunner` 的 worker 进程内会重新 `from_config(chain_config)` 构建链路，需确保 worker 能访问到正确的 config 和自定义组件，见 [task_config_and_multiprocess_worker.md](./task_config_and_multiprocess_worker.md) 第二节、第三节。
