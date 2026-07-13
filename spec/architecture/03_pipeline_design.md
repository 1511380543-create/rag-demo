# 流程设计说明

> 本文档定义 RAG 处理链路，重点说明“切分入库”与“索引构建”解耦。  
> 适用场景：流程实现、模块拆分、联调排错。

## 1. 目标

- 将“文档切分”与“索引构建”拆成两个独立阶段
- 建立稳定的数据中间层（MySQL）
- 保证索引构建不依赖本地文件读取

## 2. 阶段拆分

### 阶段一：文档切分入库

输入：

- `doc_id`
- `file_path`
- `metadata`（可选）

处理：

1. 读取本地 PDF 文本
2. 按固定策略切分 chunk
3. 执行文档覆盖写入（按 `doc_id` 删除旧 chunk）
4. 将新 chunk 与 metadata 写入 MySQL

输出：

- `stored_doc_count`
- `stored_chunk_count`

对应接口：

- `POST /rag/chunks`

### 阶段二：索引构建

输入：

- `doc_ids`（可选，为空表示全量）
- `force_rebuild`（可选）

处理：

1. 从 MySQL 读取 `chunk_text` 与 `metadata`
2. 对 chunk 进行向量化
3. 构建或重建向量索引

输出：

- `indexed_doc_count`
- `indexed_chunk_count`
- `index_name`

对应接口：

- `POST /rag/index/build`

### 阶段三：查询召回

输入：

- `query`
- `top_k`
- `filters`（可选）

处理：

1. 对查询文本向量化
2. 在当前索引中召回 `Top-K`
3. 返回 `contexts` 与可选 `trace`（本轮不做基于分数的过滤，仅记录分数）
4. 查询结束后写入一条监控日志（见阶段四）

对应接口：

- `POST /rag/query`

### 阶段四：查询监控埋点

输入：

- 单次查询的请求参数与检索结果

处理：

1. 采集延迟拆分（`embed_ms`/`retrieve_ms`/`total_ms`）
2. 采集召回情况（过滤前后数量、是否空召回）
3. 采集分数分布（`top_score`/`min_score_value`/`avg_score`）
4. 写入 `rag_query_logs`（追加写，失败不影响查询响应）

输出：

- 一条监控日志记录

对应接口：

- 埋点内嵌于 `POST /rag/query`
- 聚合暴露：`GET /rag/metrics`

### 阶段五：检索测评

输入：

- 评测集样本（`query_text` + ground truth + 可选 `top_k`）

处理：

1. 逐条样本调用检索链路（读取当前内存索引，不触发重建）
2. 按 ground truth 计算 `hit@k`/`recall@k`/`mrr@k`/`ndcg@k` 与 `latency_ms`
3. 写入 `rag_eval_runs` 汇总与 `rag_eval_run_items` 明细

输出：

- 一轮评测的汇总指标与逐条明细

对应接口：

- 评测集管理：`POST /rag/eval/dataset`、`GET /rag/eval/dataset`
- 执行与查看：`POST /rag/eval/run`、`GET /rag/eval/runs`

## 3. 关键解耦约束

- 阶段二不读取本地 `file_path`
- 阶段二只依赖 MySQL 作为构建数据源
- 阶段一成功不等于可检索，必须执行阶段二后才进入可查询状态

## 4. 异常处理建议

- 阶段一写库异常：返回 `500`，并保留错误原因
- 阶段二无可用 chunk：返回 `400`（业务状态错误）
- 查询阶段索引未就绪：返回 `400`（`INDEX_NOT_READY`）
- 阶段四监控写库异常：不影响查询响应，仅记录日志
- 阶段五评测集为空：返回 `400`（`EVAL_DATASET_EMPTY`）
- 阶段五索引未就绪：返回 `400`（`INDEX_NOT_READY`）

## 5. 验收标准

- 可在不变更本地文件的前提下，基于 MySQL 重建索引
- 同一文档重复入库后，索引构建使用最新 chunk 数据
- 查询结果中的 `chunk_id` 与 MySQL `rag_chunks.id` 一致（字符串形式）
