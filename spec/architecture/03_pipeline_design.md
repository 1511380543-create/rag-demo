# 流程设计说明

> 本文档定义 RAG 处理链路。  
> 适用场景：流程实现、模块拆分、联调排错。  
> 抽取细节见 `08_document_extraction.md`。

## 1. 目标

- 将「文档抽取」「文档切块」「索引构建」拆成独立阶段
- 建立稳定的数据中间层（MySQL：`rag_documents` + `rag_chunks`）
- 保证索引构建不依赖本地文件读取

## 2. 阶段拆分

### 阶段一：文档抽取入库

输入：

- `doc_id`
- `file_path`（本地 PDF）
- `metadata`（可选）

处理：

1. 原生 `unstructured.partition_pdf` 加载 PDF 元素（`hi_res` + 表格结构推断）
2. `Element[]` → 内部节点（段落 / 表格）
3. TextCleaner 清洗链（段落过滤，Table 跳过文本清洗）
4. 跨页续表合并（Table HTML）
5. 渲染 `full_text` 与 `blocks`，覆盖写入 `rag_documents`

输出：

- `extracted_doc_count`
- `total_page_count` / `total_char_count`
- `extract_report`（可选，逐文档统计）

对应接口：

- `POST /rag/extract`

### 阶段二：文档切块入库

输入：

- `doc_ids`

处理：

1. 从 `rag_documents` 读取 `full_text`（**不读本地 PDF**）
2. 沿用现有 `SentenceSplitter` 切分
3. 覆盖写入 `rag_chunks`

输出：

- `stored_doc_count`
- `stored_chunk_count`

对应接口：

- `POST /rag/chunks`

### 阶段三：索引构建

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

### 阶段四：查询召回

输入：

- `query`
- `top_k`
- `filters`（可选）

处理：

1. 对查询文本向量化
2. 在当前索引中召回 `Top-K`
3. 返回 `contexts` 与可选 `trace`
4. 查询结束后写入一条监控日志（见阶段五）

对应接口：

- `POST /rag/query`

### 阶段五：查询监控埋点

- 埋点内嵌于 `POST /rag/query`
- 聚合暴露：`GET /rag/metrics`

### 阶段六：检索测评

- 评测集管理：`POST /rag/eval/dataset`、`GET /rag/eval/dataset`
- 执行与查看：`POST /rag/eval/run`、`GET /rag/eval/runs`

> 测评不写入 `rag_query_logs`，不影响 `GET /rag/metrics` 的在线查询统计。

## 3. 关键解耦约束

| 阶段 | 数据来源 | 禁止行为 |
|------|---------|---------|
| 抽取 | 本地 PDF | — |
| 切块 | `rag_documents.full_text` | 不得读取本地 PDF |
| 索引构建 | `rag_chunks` | 不得读取本地 PDF / `rag_documents` 以外的来源 |

- 抽取成功 ≠ 可检索，必须完成切块 + 索引构建
- 续表合并仅在抽取阶段执行（见 `08` §3.3）

## 4. 异常处理建议

- 抽取写库异常：返回 `500`（`DOCUMENT_EXTRACT_ERROR`）
- 未抽取直接切块：返回 `400`（`DOCUMENT_NOT_EXTRACTED`）
- 切块写库异常：返回 `500`（`CHUNK_INGEST_ERROR`）
- 无可用 chunk 构建索引：返回 `400`（`NO_CHUNKS_FOR_INDEX`）
- 索引未就绪查询：返回 `400`（`INDEX_NOT_READY`）

## 5. 验收标准

- 可在不变更本地文件的前提下，基于 MySQL 重建索引
- 同一 `doc_id` 重复抽取/切块后，索引构建使用最新数据
- 查询结果中的 `chunk_id` 与 `rag_chunks.id` 一致（字符串形式）
- 表格以 HTML 形式存在于 `rag_documents.blocks`，并进入 `full_text`
