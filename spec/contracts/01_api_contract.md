# API 契约说明

> 本文档定义 RAG 服务的 HTTP 接口契约。  
> 适用场景：后端实现、联调验收、接口测试。

## 1. 接口总览

- `POST /rag/extract`：文档抽取入库（本地 PDF -> 清洗/续表 -> MySQL `rag_documents`）
- `POST /rag/chunks`：文档切块入库（`rag_documents.full_text` -> MySQL `rag_chunks`）
- `POST /rag/index/build`：索引构建（MySQL -> 向量索引）
- `POST /rag/query`：查询召回
- `GET /rag/health`：健康检查
- `GET /rag/metrics`：查询监控指标聚合
- `POST /rag/eval/dataset`：批量新增/更新评测样本
- `GET /rag/eval/dataset`：列出评测样本
- `POST /rag/eval/run`：执行一轮检索测评
- `GET /rag/eval/runs`：查看历史评测轮次

## 2. 文档抽取入库 `POST /rag/extract`

### 2.1 请求模型

- `IndexDocument`
  - `doc_id: str`（必填，去空白后非空，长度 `1-128`）
  - `file_path: str`（必填，去空白后非空，本地 PDF 文件路径）
  - `metadata: dict[str, Any] | None = None`（可选）
- `ExtractRequest`
  - `documents: list[IndexDocument]`（必填，最少 `1` 条）

### 2.2 成功响应 `200`

- `ExtractResponse`
  - `extracted_doc_count: int`（成功抽取并写入的文档数）
  - `total_page_count: int`（有效页数合计）
  - `total_char_count: int`（`full_text` 字符数合计）
  - `reports: list[ExtractReport] | None`（可选，逐文档统计）

- `ExtractReport`
  - `doc_id: str`
  - `dropped_elements: int`（清洗丢弃的元素数）
  - `table_count: int`（表格块数量）
  - `merged_continuations: int`（续表合并次数）

### 2.3 失败响应

- `422`：文档数组为空、字段非法、`file_path` 非 PDF、文件不存在、抽取结果为空
- `500`：抽取或 MySQL 写入异常（错误码 `DOCUMENT_EXTRACT_ERROR`）

## 3. 文档切块入库 `POST /rag/chunks`

### 3.1 请求模型

- `ChunkRequest`
  - `doc_ids: list[str]`（必填，最少 `1` 条；去空白后非空）

### 3.2 成功响应 `200`

- `ChunkIngestResponse`
  - `stored_doc_count: int`（成功切块的文档数）
  - `stored_chunk_count: int`（写入 MySQL 的 chunk 总数）

### 3.3 失败响应

- `422`：`doc_ids` 为空、含空字符串
- `400`：文档尚未抽取（错误码 `DOCUMENT_NOT_EXTRACTED`）
- `500`：切块或 MySQL 写入异常（错误码 `CHUNK_INGEST_ERROR`）

## 4. 索引构建 `POST /rag/index/build`

### 4.1 请求模型

- `BuildIndexRequest`
  - `doc_ids: list[str] | None = None`（可选；为空时表示基于 MySQL 全量 chunk 构建索引）
  - `force_rebuild: bool = True`（可选；是否强制全量重建目标索引）

### 4.2 成功响应 `200`

- `BuildIndexResponse`
  - `indexed_doc_count: int`（参与索引构建的文档数）
  - `indexed_chunk_count: int`（参与索引构建的 chunk 数）
  - `index_name: str`（当前索引名称）

### 4.3 失败响应

- `422`：`doc_ids` 字段格式非法（非字符串数组、空字符串等）
- `400`：MySQL 无可用 chunk（无法构建索引，错误码 `NO_CHUNKS_FOR_INDEX`）
- `500`：索引构建过程异常

## 5. 查询召回 `POST /rag/query`

### 5.1 请求模型

- `QueryRequest`
  - `query: str`（必填，去空白后非空）
  - `top_k: int = 3`（可选，必须 `>=1` 且 `<=20`）
  - `filters: dict[str, Any] | None = None`（可选，元数据过滤）

### 5.2 成功响应 `200`

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

### 5.3 失败响应

- `422`：`query` 为空、`top_k` 非法
- `400`：索引未初始化
- `500`：检索过程异常

## 6. 健康检查 `GET /rag/health`

### 6.1 成功响应 `200`

- `HealthResponse`
  - `status: str`（固定为 `ok`）
  - `index_ready: bool`（索引是否可用）
  - `extracted_docs: int`（已抽取文档数，来自 `rag_documents`）
  - `indexed_docs: int`（已切块文档数，来自 `rag_chunks`）
  - `indexed_chunks: int`（已入库 chunk 数）

## 7. 统一错误响应结构

- `ErrorResponse`
  - `error_code: str`（如 `VALIDATION_ERROR`、`INDEX_NOT_READY`、`NO_CHUNKS_FOR_INDEX`、`DOCUMENT_NOT_EXTRACTED`、`DOCUMENT_EXTRACT_ERROR`、`EVAL_DATASET_EMPTY`）
  - `message: str`（错误说明）
  - `detail: dict[str, Any] | None`（可选详情）

## 8. 字段级校验规则

### 8.1 `IndexDocument`

| 字段 | 类型 | 必填 | 校验规则 | 错误示例 |
|---|---|---|---|---|
| `doc_id` | `str` | 是 | `strip` 后长度 `1-128` | 空字符串、全空白、长度超限 |
| `file_path` | `str` | 是 | `strip` 后长度 `>=1`，且必须是本地 `.pdf` 文件路径 | 空字符串、全空白、非 PDF 路径 |
| `metadata` | `dict[str, Any]` | 否 | 若传入必须是对象类型 | 传入数组、字符串、数字 |

### 8.2 `ExtractRequest`

| 字段 | 类型 | 必填 | 校验规则 | 错误示例 |
|---|---|---|---|---|
| `documents` | `list[IndexDocument]` | 是 | 列表长度 `>=1` | 空数组、缺失字段 |

### 8.3 `ChunkRequest`

| 字段 | 类型 | 必填 | 校验规则 | 错误示例 |
|---|---|---|---|---|
| `doc_ids` | `list[str]` | 是 | 列表长度 `>=1`，元素去空白后非空 | 空数组、空字符串 |

### 8.4 `BuildIndexRequest`

| 字段 | 类型 | 必填 | 校验规则 | 错误示例 |
|---|---|---|---|---|
| `doc_ids` | `list[str]` | 否 | 若传入则元素必须为非空字符串 | 空字符串、非字符串元素 |
| `force_rebuild` | `bool` | 否 | 默认 `True` | 非布尔值 |

### 8.5 `QueryRequest`

| 字段 | 类型 | 必填 | 校验规则 | 错误示例 |
|---|---|---|---|---|
| `query` | `str` | 是 | `strip` 后长度 `>=1` | 空字符串、全空白 |
| `top_k` | `int` | 否 | 默认 `3`，范围 `1-20` | `0`、负数、超过上限、非整数 |
| `filters` | `dict[str, Any]` | 否 | 若传入必须是对象类型 | 传入数组、字符串、数字 |

## 9. 监控指标 `GET /rag/metrics`

### 9.1 请求参数

- `window_minutes: int | None = None`（可选，查询窗口分钟数；为空表示全量统计）

### 9.2 成功响应 `200`

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

### 9.3 失败响应

- `422`：`window_minutes` 非法（非正整数）
- `500`：监控数据读取异常（错误码 `METRICS_READ_ERROR`）

> 说明：无查询记录时各聚合字段返回 `0`，`window_minutes` 原样回显。

## 10. 评测样本管理 `POST /rag/eval/dataset`

### 10.1 请求模型

- `EvalCase`
  - `case_id: str`（必填，去空白后非空，长度 `1-128`）
  - `query_text: str`（必填，去空白后非空）
  - `relevant_chunk_ids: list[str] | None = None`（可选，chunk 级标注）
  - `expected_keywords: list[str] | None = None`（可选，关键词命中标注）
  - `keyword_match_mode: "any" | "all" = "any"`（可选，关键词匹配模式）
  - `top_k: int | None = None`（可选，样本级 `top_k`，范围 `1-20`）
  - `enabled: bool = True`（可选，是否参与评测）
- `EvalDatasetUpsertRequest`
  - `cases: list[EvalCase]`（必填，最少 `1` 条）

约束：`relevant_chunk_ids` 与 `expected_keywords` 至少提供其一。

### 10.2 成功响应 `200`

- `EvalDatasetUpsertResponse`
  - `upserted_count: int`（新增或更新的样本数）

### 10.3 失败响应

- `422`：样本数组为空、字段非法、两类标注均缺失
- `500`：写库异常（错误码 `EVAL_DATASET_UPSERT_ERROR`）

## 11. 评测样本列表 `GET /rag/eval/dataset`

### 11.1 成功响应 `200`

- `EvalDatasetListResponse`
  - `cases: list[EvalCase]`
  - `total: int`

### 11.2 失败响应

- `500`：评测样本读取异常（错误码 `EVAL_DATASET_READ_ERROR`）

## 12. 执行测评 `POST /rag/eval/run`

### 12.1 请求模型

- `EvalRunRequest`
  - `case_ids: list[str] | None = None`（可选；为空时执行全部 `enabled=true` 样本；传入时按 ID 匹配，不受 `enabled` 限制）
  - `top_k: int | None = None`（可选；覆盖样本级 `top_k`，范围 `1-20`）
  - `note: str | None = None`（可选，本轮备注）

> 单条样本实际检索 `top_k` 优先级：请求级 `top_k` > 样本级 `top_k` > 默认 `3`。

### 12.2 成功响应 `200`

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
  - `top_k: int`（响应回显字段；未传请求级 `top_k` 时固定为 `3`）
  - `avg_hit: float`
  - `avg_recall: float`
  - `avg_mrr: float`
  - `avg_latency_ms: float`
  - `items: list[EvalMetricItem]`

### 12.3 失败响应

- `422`：`case_ids`、`top_k` 字段格式非法
- `400`：索引未初始化（`INDEX_NOT_READY`）或评测集为空（`EVAL_DATASET_EMPTY`）
- `500`：评测执行异常（错误码 `EVAL_RUN_ERROR`）

> 说明：测评复用内部检索逻辑，不经过 `/rag/query`，不写入 `rag_query_logs`。

## 13. 评测历史 `GET /rag/eval/runs`

### 13.1 请求参数

- `limit: int = 20`（可选，返回条数，范围 `1-100`）

### 13.2 成功响应 `200`

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

### 13.3 失败响应

- `422`：`limit` 非法
- `500`：评测历史读取异常（错误码 `EVAL_RUNS_READ_ERROR`）
