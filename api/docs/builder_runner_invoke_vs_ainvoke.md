# BuilderChainRunner.invoke vs ainvoke 差异说明

本文详细对比 `BuilderChainRunner` 的 `invoke`（同步）与 `ainvoke`（异步）两个方法的差异，包括执行模式、并发机制、checkpoint 处理、适用场景等。

---

## 一、核心差异概览

| 维度 | `invoke`（同步） | `ainvoke`（异步） |
|------|------------------|-------------------|
| **方法签名** | `def invoke(self, input)` | `async def ainvoke(self, input)` |
| **执行模式** | 批量提交 + 等待全部完成 | 流式处理（producer-consumer） |
| **并发机制** | `ThreadPoolExecutor`（线程池） | `asyncio` 协程 + `asyncio.Queue` |
| **数据收集** | 先收集所有 scanner 项，再提交 | 边扫描边处理（流式） |
| **Chain 调用** | `self.chain.invoke(data, max_workers=...)` | `await self.chain.ainvoke(data)` |
| **Checkpoint 检查** | 注释掉（`# if self.checkpointer.exists(item_id): continue`） | 有检查（`if not self.checkpointer.exists(item_id):`） |
| **Checkpoint 写入** | 同步 `self.checkpointer.write_to_ckpt(...)` | 异步 `await asyncio.to_thread(lambda: self.checkpointer.write_to_ckpt(...))` |
| **进度条** | `tqdm`（同步） | `tqdm.asyncio.tqdm`（异步） |
| **并发控制** | `num_chains`（线程池大小） | `max_concurrency`（消费者协程数） |
| **内存占用** | 较高（需先收集所有项） | 较低（流式，队列有上限） |
| **适用场景** | 数据量已知、可一次性加载 | 数据量大、需流式处理、支持断点续跑 |

---

## 二、invoke（同步）执行流程

### 2.1 代码结构

```python
def invoke(self, input):
    def process(data, data_id, data_abstract):
        result = self.chain.invoke(data, max_workers=self.num_threads_per_chain)
        return data, data_id, data_abstract, result
    
    futures = []
    with ThreadPoolExecutor(self.num_chains) as executor:
        # 1. 先收集所有 scanner 项
        for item in self.scanner.generate(input):
            item_id, item_abstract = generate_hash_id_and_abstract(item)
            # checkpoint 检查被注释掉
            fut = executor.submit(process, item, item_id, item_abstract)
            futures.append(fut)
        
        # 2. 等待所有任务完成
        for future in tqdm(as_completed(futures), total=len(futures)):
            result = future.result()
            if result is not None:
                # 统计并写入 checkpoint
                self.checkpointer.write_to_ckpt(...)
                success += 1
```

### 2.2 执行特点

- **批量提交**：先遍历 `scanner.generate(input)` 收集所有项，全部提交到线程池，再等待完成。
- **线程池并发**：使用 `ThreadPoolExecutor(self.num_chains)`，最多 `num_chains` 个线程并行处理。
- **同步等待**：用 `as_completed(futures)` 等待所有任务完成，阻塞主线程。
- **无 checkpoint 跳过**：代码里 `if self.checkpointer.exists(item_id): continue` 被注释，**所有项都会处理**，即使已 checkpoint。
- **内存占用**：需先收集所有 `futures`，数据量大时内存占用较高。

### 2.3 适用场景

- 数据量较小，可一次性加载到内存。
- 需要等待所有任务完成后统一处理结果。
- 不需要断点续跑（或 checkpoint 检查被禁用）。

---

## 三、ainvoke（异步）执行流程

### 3.1 代码结构

```python
async def ainvoke(self, input):
    async def process(data, data_id, data_abstract):
        result = await self.chain.ainvoke(data)
        # 统计并异步写入 checkpoint
        await asyncio.to_thread(lambda: self.checkpointer.write_to_ckpt(...))
        return 1
    
    async def producer(queue):
        # 生产者：扫描数据并放入队列
        for item in self.scanner.generate(input):
            await queue.put(item)
        # 发送结束信号
        for _ in range(self.max_concurrency):
            await queue.put(None)
    
    async def consumer(queue, pbar):
        # 消费者：从队列取数据并处理
        while True:
            item = await queue.get()
            if item is None:
                break
            item_id, item_abstract = generate_hash_id_and_abstract(item)
            # checkpoint 检查：已处理则跳过
            if not self.checkpointer.exists(item_id):
                flag = await process(item, item_id, item_abstract)
                success += flag
            else:
                checkpointed += 1
            pbar.update(1)
            queue.task_done()
    
    # 启动 producer 和多个 consumer
    queue = asyncio.Queue(maxsize=self.max_concurrency * 10)
    producer_task = asyncio.create_task(producer(queue))
    consumer_tasks = [asyncio.create_task(consumer(queue, pbar)) 
                      for _ in range(self.max_concurrency)]
    await producer_task
    await queue.join()
    results = await asyncio.gather(*consumer_tasks)
```

### 3.2 执行特点

- **流式处理（producer-consumer）**：
  - **Producer**：一个协程负责从 `scanner.generate(input)` 取数据，放入 `asyncio.Queue`。
  - **Consumer**：`max_concurrency` 个协程从队列取数据并处理，边扫描边处理，不等待全部收集完。
- **异步并发**：使用 `asyncio` 协程，非阻塞，适合 IO 密集型任务。
- **Checkpoint 检查**：每个 consumer 在处理前检查 `self.checkpointer.exists(item_id)`，**已 checkpoint 的项跳过**，支持断点续跑。
- **内存控制**：队列有上限（`maxsize=self.max_concurrency * 10`），避免内存无限增长。
- **统计信息**：区分 `total`、`checkpointed`、`success`，输出更详细。

### 3.3 适用场景

- 数据量大，需流式处理，避免一次性加载到内存。
- 需要断点续跑（支持 checkpoint 跳过已处理项）。
- IO 密集型任务（文件读取、网络请求等），异步并发效率更高。
- 在 FastAPI 等异步框架中使用，不阻塞事件循环。

---

## 四、详细对比

### 4.1 并发控制参数

| 参数 | `invoke` | `ainvoke` |
|------|----------|-----------|
| **线程/协程数** | `num_chains`（ThreadPoolExecutor 大小） | `max_concurrency`（consumer 协程数） |
| **Chain 内并行度** | `num_threads_per_chain`（传给 `chain.invoke` 的 `max_workers`） | 由 `chain.ainvoke` 内部的 `max_concurrency` 控制（默认 100） |

### 4.2 Checkpoint 处理

| 项目 | `invoke` | `ainvoke` |
|------|----------|-----------|
| **检查** | 注释掉（所有项都处理） | 有检查（跳过已 checkpoint 项） |
| **写入** | 同步 `self.checkpointer.write_to_ckpt(...)` | 异步 `await asyncio.to_thread(lambda: ...)` |
| **断点续跑** | 不支持（或需手动实现） | 支持（自动跳过已处理项） |

### 4.3 内存与性能

| 维度 | `invoke` | `ainvoke` |
|------|----------|-----------|
| **内存占用** | 较高（需先收集所有 futures） | 较低（队列有上限，流式处理） |
| **启动延迟** | 需等待 scanner 全部扫描完 | 立即开始处理（边扫描边处理） |
| **阻塞性** | 阻塞主线程 | 非阻塞（异步） |
| **IO 效率** | 线程池，适合 CPU 密集型 | 协程，适合 IO 密集型 |

### 4.4 进度显示

| 项目 | `invoke` | `ainvoke` |
|------|----------|-----------|
| **进度条** | `tqdm`（同步） | `tqdm.asyncio.tqdm`（异步） |
| **总数** | `total=len(futures)`（需先收集完） | `total=self.scanner.size(input)`（需 scanner 支持 `size()`） |
| **统计信息** | `success`、`failures` | `total`、`checkpointed`、`success`、`failures` |

---

## 五、使用建议

### 5.1 选择 invoke 的场景

- 数据量小（< 1000 项），可一次性加载。
- 需要等待全部完成后统一处理结果。
- 在同步代码中调用，不关心事件循环。
- 不需要断点续跑。

### 5.2 选择 ainvoke 的场景

- 数据量大（> 10000 项），需流式处理。
- 需要断点续跑（支持 checkpoint 跳过）。
- 在 FastAPI 等异步框架中使用，避免阻塞事件循环。
- IO 密集型任务（文件读取、网络请求多）。
- 需要更细粒度的并发控制（`max_concurrency`）。

### 5.3 注意事项

- **scanner.size()**：`ainvoke` 的进度条需要 `scanner.size(input)` 返回总数，若 scanner 不支持，进度条可能不准确。
- **checkpoint 检查**：`invoke` 的 checkpoint 检查被注释，如需断点续跑，需手动实现或改用 `ainvoke`。
- **事件循环**：`ainvoke` 必须在异步上下文中调用（`await`），不能在同步函数中直接调用。
- **chain 方法**：`invoke` 调用 `chain.invoke`（同步），`ainvoke` 调用 `chain.ainvoke`（异步），需确保 chain 实现了对应方法。

---

## 六、与 BuilderChainStreamRunner 的关系

- **BuilderChainRunner**（`type: base`）：提供 `invoke` 和 `ainvoke`，使用线程池或协程。
- **BuilderChainStreamRunner**（`type: stream`）：**只提供 `invoke`**（同步），但内部使用 `ProcessPoolExecutor` 多进程执行，适合 CPU 密集型任务。其 `invoke` 是同步阻塞的，但通过 `run_in_executor` 放入线程池执行，不阻塞事件循环。

因此，若在 FastAPI 等异步框架中使用 `BuilderChainStreamRunner`，通常：
- 用 `await loop.run_in_executor(None, runner.invoke, file_path)` 在后台线程执行，避免阻塞事件循环。
- 或改用 `BuilderChainRunner`（base）的 `ainvoke`，但需注意 `ainvoke` 内部仍是线程池/协程，不是多进程。

---

## 七、与文档的衔接

- **Builder 链路**：`invoke` / `ainvoke` 都是执行 builder chain 的入口，见 [builder_chain.md](./builder_chain.md)。
- **配置管理**：runner 的并发参数（`num_chains`、`max_concurrency`）可在 `kag_builder_pipeline` 中配置，见 [kag_design_and_conf.md](./kag_design_and_conf.md)。
- **多进程 worker**：`BuilderChainStreamRunner.invoke` 使用 `ProcessPoolExecutor`，worker 进程内会重新构建 chain，见 [task_config_and_multiprocess_worker.md](./task_config_and_multiprocess_worker.md) 第二节。
