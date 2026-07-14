# 监控与测评设计

> 本文档定义 RAG 服务的监控（Monitoring）与测评（Evaluation）能力设计。
> 适用场景：可观测性建设、检索质量量化、迭代前后效果对比。
> 本页是监控与测评的权威设计文档，接口细节见 `01`，数据表见 `02`，流程见 `03`。

## 1. 设计目标

- 监控：在线持续观察检索行为，暴露延迟、召回、分数分布等关键指标
- 测评：离线量化检索质量，基于评测集计算标准检索指标，支持迭代对比
- 二者共同支撑核心诉求：提高检索质量

## 2. 能力边界

- 监控与测评均只针对检索链路（`/rag/query` 及其底层检索），不涉及答案生成
- 存储统一落 MySQL，与现有 `rag_chunks` 存储风格保持一致
- 监控写入采用请求内同步写库，不引入异步队列与降级逻辑
- 评测为离线主动触发，不在查询链路内自动执行

## 3. 监控能力（Monitoring）

### 3.1 采集点

在 `/rag/query` 处理链路上埋点，单次查询采集以下指标：

- 请求信息：`query` 文本、`top_k`、是否启用 `filters`
- 延迟拆分（毫秒）：`embed_ms`（向量化耗时）、`retrieve_ms`（检索耗时）、`total_ms`（总耗时）
- 召回情况：`retrieved_before_filter`、`retrieved_after_filter`、`is_empty_recall`
- 分数分布：`top_score`、`min_score_value`、`avg_score`（基于召回 contexts 计算）
- 结果状态：`error_code`（成功为空，失败记录统一错误码）
- 时间戳：`created_at`

> 说明：本轮监控只“记录分数”，不做基于分数的过滤或降级（范围见 §5，后续设想见 §6）。

### 3.2 存储

- 写入表：`rag_query_logs`（见 `02`）
- 写入时机：查询处理结束后（无论成功或失败）写入一条记录
- 写入失败不得影响查询主流程的返回结果（监控写库异常仅记录日志，不改变查询响应）

### 3.3 聚合与暴露

- 接口：`GET /rag/metrics`（见 `01`）
- 支持时间窗口过滤（最近 N 分钟）
- 聚合指标：总查询数、空召回率、平均/`p95` 总延迟、平均向量化延迟、平均检索延迟、平均 `top_score`

## 4. 测评能力（Evaluation）

### 4.1 评测集

- 每条评测样本包含：`case_id`（业务用例 ID）、`query_text`、ground truth、可选 `top_k`
- ground truth 同时支持两种标注方式（可单独或同时使用）：
  - `relevant_chunk_ids`：chunk 级精确标注（严格，命中以 `chunk_id` 判定）
  - `expected_keywords`：关键词命中标注（宽松，命中以关键词是否出现在召回文本判定）
- 判定优先级：若样本同时提供两类标注，`relevant_chunk_ids` 用于计算 chunk 级指标，`expected_keywords` 用于关键词命中判定，两者独立记录

### 4.2 评测指标

以单次查询召回的 `top_k` 结果为基础，计算：

- `hit@k`：命中标注为 `1`，否则为 `0`
- `recall@k`：命中的相关 chunk 数 / 标注相关 chunk 总数（仅 `relevant_chunk_ids` 模式）
- `mrr@k`：首个命中相关结果的倒数排名
- `latency_ms`：单条样本检索耗时

轮次汇总指标为逐条指标的平均值。

> 相关度：本轮采用二值相关度（相关=1 / 不相关=0），命中通过 `relevant_chunk_ids` 或 `expected_keywords` 判定。
> 本轮不启用 `nDCG`（二值 + 小 `top_k` 下与 `mrr@k` 冗余），后续设想见 §6。

### 4.3 存储

- 评测集表：`rag_eval_dataset`
- 评测轮次汇总表：`rag_eval_runs`
- 评测逐条明细表：`rag_eval_run_items`
- 表结构详见 `02`

### 4.4 接口

- `POST /rag/eval/dataset`：批量新增/更新评测样本（按 `case_id` upsert）
- `GET /rag/eval/dataset`：列出评测样本
- `POST /rag/eval/run`：对评测集执行一轮评测，落库并返回汇总指标
- `GET /rag/eval/runs`：查看历史评测轮次，支持迭代前后对比

### 4.5 与现有回归的衔接

- 现有回归用例 `rag_retrieval_reg_001` 使用关键词命中判定，可平滑迁移为 `expected_keywords` 评测样本
- 现有已知差距 `rag_retrieval_empty_reg_001`（低相关查询应空召回）本轮不闭环（见 §5）

## 5. 本轮范围与非本轮

本轮实现：

- 监控：查询埋点写入 `rag_query_logs` + `GET /rag/metrics` 聚合；分数只记录、不参与过滤，召回仍按 `top_k` 返回
- 测评：评测集管理 + `POST /rag/eval/run` + 历史查看；指标为 `hit@k`、`recall@k`、`mrr@k`、`latency_ms`

非本轮（明确不做）：

- 分数阈值过滤、基于分数的降级
- `nDCG` 与分级相关度标注
- 外部可观测框架（OpenTelemetry/Prometheus/Langfuse 等）

## 6. 后续设想（Roadmap，非承诺）

> 本节仅记录方向，不构成本轮承诺；落地时再补充设计细节与约束。

- 分数阈值过滤 + 分数降级：基于已记录的分数分布，引入可配置阈值过滤低相关召回，闭环 `rag_retrieval_empty_reg_001`
- nDCG + 分级相关度：当需要精细区分“多相关”时，扩展评测集为 0-3 分级标注并启用 nDCG
- 外部可观测框架：触发点为“添加答案生成层”；届时优先 Langfuse（可私有化部署），在预留埋点处新增 sink 与现有 MySQL 记录并存
- 埋点解耦（为上一条铺路）：实现时可将“写一条查询监控记录”收敛到单一函数，未来接框架只改此处

## 7. 关键约束

- 监控与测评均不得修改现有 `/rag/chunks`、`/rag/index/build`、`/rag/query`、`/rag/health` 的既有成功语义
- 测评仅读取当前内存索引进行检索，不触发索引重建
