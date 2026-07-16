# MySQL 数据模型说明

> 本文档定义 RAG 项目中 chunk 与 metadata 的 MySQL 存储模型。  
> 适用场景：建表、数据写入、索引构建读取。

## 1. 设计原则

- MySQL 只存储 `chunk_text` 与 `metadata`
- 不存储原始文档内容，不维护文档主表
- 通过 `doc_id + chunk_index` 保证文档内分片唯一性
- 索引构建必须以 MySQL 为数据源

## 2. 连接配置

- 数据库类型：`MySQL 8.0+`
- 地址：`127.0.0.1:3306`
- 账号：`root`
- 密码：`root`
- 库名：`rag_demo`
- 字符集：`utf8mb4`
- 排序规则：`utf8mb4_0900_ai_ci`

建议环境变量：

```bash
export MYSQL_HOST="127.0.0.1"
export MYSQL_PORT="3306"
export MYSQL_USER="root"
export MYSQL_PASSWORD="root"
export MYSQL_DATABASE="rag_demo"
```

## 3. 表结构

### 3.1 `rag_chunks`

- `id`: bigint 主键，自增
- `doc_id`: varchar(128)，来源文档业务 ID
- `chunk_index`: int，无符号，文档内分片序号（从 0 开始）
- `chunk_text`: longtext，分片原文
- `metadata`: json，分片级元数据
- `created_at`: datetime(3)，创建时间

索引约束：

- 唯一索引：`uk_doc_chunk_index(doc_id, chunk_index)`
- 查询索引：`idx_doc_id(doc_id)`

### 3.2 `rag_query_logs`（监控）

- `id`: bigint 主键，自增
- `query_text`: text，查询文本
- `top_k`: int，本次查询 `top_k`
- `filters_applied`: tinyint，是否启用元数据过滤（`0/1`）
- `embed_ms`: int，向量化耗时（毫秒）
- `retrieve_ms`: int，检索耗时（毫秒）
- `total_ms`: int，总耗时（毫秒）
- `retrieved_before_filter`: int，过滤前召回数
- `retrieved_after_filter`: int，过滤后召回数
- `is_empty_recall`: tinyint，是否空召回（`0/1`）
- `top_score`: double，最高分（可空，仅记录不参与过滤）
- `min_score_value`: double，最低分（可空，仅记录不参与过滤）
- `avg_score`: double，平均分（可空，仅记录不参与过滤）
- `error_code`: varchar(64)，失败错误码（成功为空）
- `created_at`: datetime(3)，创建时间

索引约束：

- 查询索引：`idx_created_at(created_at)`

### 3.3 `rag_eval_dataset`（评测集）

- `id`: bigint 主键，自增
- `case_id`: varchar(128)，评测用例业务 ID
- `query_text`: text，评测查询文本
- `relevant_chunk_ids`: json，chunk 级标注（可空）
- `expected_keywords`: json，关键词命中标注（可空）
- `keyword_match_mode`: varchar(8)，关键词匹配模式（`any`/`all`，默认 `any`）
- `top_k`: int，样本级 `top_k`（可空）
- `enabled`: tinyint，是否参与评测（`0/1`）
- `created_at`: datetime(3)，创建时间
- `updated_at`: datetime(3)，更新时间

索引约束：

- 唯一索引：`uk_case_id(case_id)`

### 3.4 `rag_eval_runs`（评测轮次汇总）

- `id`: bigint 主键，自增（即 `run_id`）
- `dataset_size`: int，参与评测样本数
- `top_k`: int，本轮实际 `top_k`
- `avg_hit`: double，平均命中率
- `avg_recall`: double，平均召回率
- `avg_mrr`: double，平均 MRR
- `avg_latency_ms`: double，平均检索延迟
- `note`: varchar(255)，本轮备注（可空）
- `created_at`: datetime(3)，创建时间

### 3.5 `rag_eval_run_items`（评测逐条明细）

- `id`: bigint 主键，自增
- `run_id`: bigint，关联 `rag_eval_runs.id`
- `case_id`: varchar(128)，评测用例业务 ID
- `query_text`: text，评测查询文本
- `hit`: tinyint，是否命中（`0/1`）
- `recall`: double，单条召回率
- `mrr`: double，单条 MRR
- `latency_ms`: int，单条检索耗时（毫秒）
- `retrieved_chunk_ids`: json，实际召回的 chunk_id 列表
- `created_at`: datetime(3)，创建时间

索引约束：

- 查询索引：`idx_run_id(run_id)`

## 4. 数据生命周期规则

- 新文档入库：
  - 从本地 PDF 读取并切分
  - 将每个 chunk 写入 `rag_chunks`
- 文档覆盖入库（同 `doc_id`）：
  - 先按 `doc_id` 删除历史 chunk
  - 再批量写入新 chunk
- 索引构建：
  - 按 `doc_ids`（可选）读取 chunk 数据
  - 读取字段至少包含：`doc_id`、`chunk_text`、`metadata`
- 监控日志：
  - 每次 `/rag/query` 处理结束后写入一条 `rag_query_logs`（成功与失败均写入）
  - 仅追加写入，不做更新与删除
  - `/rag/eval/run` 不写入 `rag_query_logs`（测评复用检索逻辑，但不经过 `/rag/query` 埋点）
- 评测集：
  - 按 `case_id` upsert 到 `rag_eval_dataset`
- 评测执行：
  - 每次 `/rag/eval/run` 写入一条 `rag_eval_runs` 汇总
  - 同时按样本写入多条 `rag_eval_run_items` 明细

## 5. 与 SQL 文件映射

- 建表脚本：`spec/sql/mysql_schema.sql`
- 本文档是逻辑说明，SQL 文件是可执行定义

## 6. 数据质量约束

- `doc_id` 必须非空且长度不超过 128
- `chunk_index` 从 0 开始递增，不允许重复
- `chunk_text` 必须非空
- `metadata` 为可选 JSON 对象，不允许写入非 JSON 对象类型
