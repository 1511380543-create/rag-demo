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

## 5. 与 SQL 文件映射

- 建表脚本：`spec/sql/mysql_schema.sql`
- 本文档是逻辑说明，SQL 文件是可执行定义

## 6. 数据质量约束

- `doc_id` 必须非空且长度不超过 128
- `chunk_index` 从 0 开始递增，不允许重复
- `chunk_text` 必须非空
- `metadata` 为可选 JSON 对象，不允许写入非 JSON 对象类型
