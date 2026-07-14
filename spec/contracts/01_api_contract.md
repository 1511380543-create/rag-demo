# API 契约说明

> 本文档定义 RAG 服务的 HTTP 接口契约。  
> 适用场景：后端实现、联调验收、接口测试。

## 1. 接口总览

- `POST /rag/chunks`：文档切分入库（本地读取 -> 切分 -> MySQL）
- `POST /rag/index/build`：索引构建（MySQL -> 向量索引）
- `POST /rag/query`：查询召回
- `GET /rag/health`：健康检查
- `GET /rag/metrics`：查询监控指标聚合
- `POST /rag/eval/dataset`：批量新增/更新评测样本
- `GET /rag/eval/dataset`：列出评测样本
- `POST /rag/eval/run`：执行一轮检索测评
- `GET /rag/eval/runs`：查看历史评测轮次

## 2. 文档切分入库 `POST /rag/chunks`

### 2.1 请求模型

- `IndexDocument`
  - `doc_id: str`（必填，去空白后非空，长度 `1-128`）
  - `file_path: str`（必填，去空白后非空，本地 PDF 文件路径）
  - `metadata: dict[str, Any] | None = None`（可选）
- `ChunkIngestRequest`
  - `documents: list[IndexDocument]`（必填，最少 `1` 条）

### 2.2 成功响应 `200`

- `ChunkIngestResponse`
  - `stored_doc_count: int`（成功处理并写入 chunk 的文档数）
  - `stored_chunk_count: int`（写入 MySQL 的 chunk 总数）

### 2.3 失败响应

- `422`：文档数组为空、字段缺失、`doc_id/file_path` 非法、`file_path` 非 PDF、文件不存在、PDF 内容为空
- `500`：文档切分或 MySQL 写入异常

## 3. 索引构建 `POST /rag/index/build`

### 3.1 请求模型

- `BuildIndexRequest`
  - `doc_ids: list[str] | None = None`（可选；为空时表示基于 MySQL 全量 chunk 构建索引）
  - `force_rebuild: bool = True`（可选；是否强制全量重建目标索引）

### 3.2 成功响应 `200`

- `BuildIndexResponse`
  - `indexed_doc_count: int`（参与索引构建的文档数）
  - `indexed_chunk_count: int`（参与索引构建的 chunk 数）
  - `index_name: str`（当前索引名称）

### 3.3 失败响应

- `422`：`doc_ids` 字段格式非法（非字符串数组、空字符串等）
- `400`：MySQL 无可用 chunk（无法构建索引，错误码 `NO_CHUNKS_FOR_INDEX`）
- `500`：索引构建过程异常

## 4. 查询召回 `POST /rag/query`

### 4.1 请求模型

- `QueryRequest`
  - `query: str`（必填，去空白后非空）
  - `top_k: int = 3`（可选，必须 `>=1` 且 `<=20`）
  - `filters: dict[str, Any] | None = None`（可选，元数据过滤）

### 4.2 成功响应 `200`

- `RetrievedContext`
  - `doc_id: str`
  - `chunk_id: str`
  - `chunk_text: str`
  - `score: float`
  - `metadata: dict[str, Any] | None`
- `QueryResponse`
  - `query: str`
  - `top_k: int`
  - `contexts: list[RetrievedContext]`
  - `trace: dict[str, Any] | None`（可选调试信息，包含 `retrieved_before_filter`、`retrieved_after_filter`、`filters_applied`，并新增 `top_score`、`avg_score`、`embed_ms`、`retrieve_ms`、`total_ms` 等监控相关字段）

### 4.3 失败响应

- `422`：`query` 为空、`top_k` 非法
- `400`：索引未初始化
- `500`：检索过程异常

## 5. 健康检查 `GET /rag/health`

### 5.1 成功响应 `200`

- `HealthResponse`
  - `status: str`（固定为 `ok`）
  - `index_ready: bool`（索引是否可用）
  - `indexed_docs: int`（已入库文档数）
  - `indexed_chunks: int`（已入库 chunk 数）

## 6. 统一错误响应结构

- `ErrorResponse`
  - `error_code: str`（如 `VALIDATION_ERROR`、`INDEX_NOT_READY`、`NO_CHUNKS_FOR_INDEX`、`EVAL_DATASET_EMPTY`）
  - `message: str`（错误说明）
  - `detail: dict[str, Any] | None`（可选详情）

## 7. 字段级校验规则

### 7.1 `IndexDocument`

| 字段 | 类型 | 必填 | 校验规则 | 错误示例 |
|---|---|---|---|---|
| `doc_id` | `str` | 是 | `strip` 后长度 `1-128` | 空字符串、全空白、长度超限 |
| `file_path` | `str` | 是 | `strip` 后长度 `>=1`，且必须是本地 `.pdf` 文件路径 | 空字符串、全空白、非 PDF 路径 |
| `metadata` | `dict[str, Any]` | 否 | 若传入必须是对象类型 | 传入数组、字符串、数字 |

### 7.2 `ChunkIngestRequest`

| 字段 | 类型 | 必填 | 校验规则 | 错误示例 |
|---|---|---|---|---|
| `documents` | `list[IndexDocument]` | 是 | 列表长度 `>=1` | 空数组、缺失字段 |

### 7.3 `BuildIndexRequest`

| 字段 | 类型 | 必填 | 校验规则 | 错误示例 |
|---|---|---|---|---|
| `doc_ids` | `list[str]` | 否 | 若传入则元素必须为非空字符串 | 空字符串、非字符串元素 |
| `force_rebuild` | `bool` | 否 | 默认 `True` | 非布尔值 |

### 7.4 `QueryRequest`

| 字段 | 类型 | 必填 | 校验规则 | 错误示例 |
|---|---|---|---|---|
| `query` | `str` | 是 | `strip` 后长度 `>=1` | 空字符串、全空白 |
| `top_k` | `int` | 否 | 默认 `3`，范围 `1-20` | `0`、负数、超过上限、非整数 |
| `filters` | `dict[str, Any]` | 否 | 若传入必须是对象类型 | 传入数组、字符串、数字 |

## 8. 监控指标 `GET /rag/metrics`

### 8.1 请求参数

- `window_minutes: int | None = None`（可选，查询窗口分钟数；为空表示全量统计）

### 8.2 成功响应 `200`

- `MetricsResponse`
  - `window_minutes: int | None`（回显查询窗口）
  - `total_queries: int`（窗口内查询总数）
  - `empty_recall_count: int`（空召回次数）
  - `empty_recall_rate: float`（空召回率，`0-1`）
  - `avg_total_ms: float`（平均总延迟）
  - `p95_total_ms: float`（`p95` 总延迟）
  - `avg_embed_ms: float`（平均向量化延迟）
  - `avg_retrieve_ms: float`（平均检索延迟）
  - `avg_top_score: float`（平均 `top_score`）

### 8.3 失败响应

- `422`：`window_minutes` 非法（非正整数）
- `500`：监控数据读取异常

## 9. 评测样本管理 `POST /rag/eval/dataset`

### 9.1 请求模型

- `EvalCase`
  - `case_id: str`（必填，去空白后非空，长度 `1-128`）
  - `query_text: str`（必填，去空白后非空）
  - `relevant_chunk_ids: list[str] | None = None`（可选，chunk 级标注）
  - `expected_keywords: list[str] | None = None`（可选，关键词命中标注）
  - `top_k: int | None = None`（可选，样本级 `top_k`，范围 `1-20`）
  - `enabled: bool = True`（可选，是否参与评测）
- `EvalDatasetUpsertRequest`
  - `cases: list[EvalCase]`（必填，最少 `1` 条）

约束：`relevant_chunk_ids` 与 `expected_keywords` 至少提供其一。

### 9.2 成功响应 `200`

- `EvalDatasetUpsertResponse`
  - `upserted_count: int`（新增或更新的样本数）

### 9.3 失败响应

- `422`：样本数组为空、字段非法、两类标注均缺失
- `500`：写库异常

## 10. 评测样本列表 `GET /rag/eval/dataset`

### 10.1 成功响应 `200`

- `EvalDatasetListResponse`
  - `cases: list[EvalCase]`
  - `total: int`

## 11. 执行测评 `POST /rag/eval/run`

### 11.1 请求模型

- `EvalRunRequest`
  - `case_ids: list[str] | None = None`（可选；为空表示全量启用样本）
  - `top_k: int | None = None`（可选；覆盖样本级 `top_k`，范围 `1-20`）
  - `note: str | None = None`（可选，本轮备注）

### 11.2 成功响应 `200`

- `EvalMetricItem`
  - `case_id: str`
  - `query_text: str`
  - `hit: int`（`0/1`）
  - `recall: float`
  - `mrr: float`
  - `latency_ms: int`
  - `retrieved_chunk_ids: list[str]`
- `EvalRunResponse`
  - `run_id: int`（评测轮次 ID）
  - `dataset_size: int`（参与评测样本数）
  - `top_k: int`（本轮实际 `top_k`）
  - `avg_hit: float`
  - `avg_recall: float`
  - `avg_mrr: float`
  - `avg_latency_ms: float`
  - `items: list[EvalMetricItem]`

### 11.3 失败响应

- `422`：`case_ids`、`top_k` 字段格式非法
- `400`：索引未初始化（`INDEX_NOT_READY`）或评测集为空（`EVAL_DATASET_EMPTY`）
- `500`：评测执行异常

## 12. 评测历史 `GET /rag/eval/runs`

### 12.1 请求参数

- `limit: int = 20`（可选，返回条数，范围 `1-100`）

### 12.2 成功响应 `200`

- `EvalRunSummary`
  - `run_id: int`
  - `dataset_size: int`
  - `top_k: int`
  - `avg_hit: float`
  - `avg_recall: float`
  - `avg_mrr: float`
  - `avg_latency_ms: float`
  - `note: str | None`
  - `created_at: str`
- `EvalRunListResponse`
  - `runs: list[EvalRunSummary]`
  - `total: int`

### 12.3 失败响应

- `422`：`limit` 非法
- `500`：评测历史读取异常
