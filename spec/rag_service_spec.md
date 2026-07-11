# RAG 服务规格（含测试沉淀）

> 本文档用于当前项目的 RAG 服务开发。  
> 约束：先做 spec 探讨与确认，再进入实现；所有工作产出必须同步沉淀测试用例。

## 1. 目标与范围

### 1.1 目标

构建一个可本地运行的基础 RAG 检索服务，能力包括：
- 文档入库（解析、切分、向量化、索引）
- 查询检索（召回最相关片段）

### 1.2 技术栈约定

- 开发语言：`Python`
- 索引构建：`Python + LlamaIndex`（用于文档切分、索引构建、检索流程编排）
- 服务接口：`Python + FastAPI`（用于对外 HTTP API 暴露）

### 1.3 本阶段范围

- 文档类型：`pdf`
- 检索方式：向量召回 `Top-K`
- 存储方式：本地向量索引（具体实现阶段选型）

### 1.4 非目标范围

- 暂不支持多租户与鉴权
- 暂不支持复杂重排（rerank）
- 暂不支持在线增量热更新索引
- 暂不做前端页面
- 暂不做答案生成

## 2. 服务接口规格

### 2.1 文档入库 `POST /rag/index`

#### 请求模型（FastAPI / Pydantic）

- `IndexDocument`
  - `doc_id: str`（必填，去空白后非空，长度 `1-128`）
  - `content: str`（必填，去空白后非空）
  - `metadata: dict[str, Any] | None = None`（可选）
- `IndexRequest`
  - `documents: list[IndexDocument]`（必填，最少 `1` 条）

#### 成功响应 `200`

- `IndexResponse`
  - `indexed_count: int`（成功入库文档数）
  - `chunk_count: int`（总切分 chunk 数）
  - `index_name: str`（当前索引名称）

#### 失败响应

- `422`：文档数组为空、字段缺失、`doc_id/content` 非法
- `500`：索引构建过程异常

### 2.2 查询召回 `POST /rag/query`

#### 请求模型（FastAPI / Pydantic）

- `QueryRequest`
  - `query: str`（必填，去空白后非空）
  - `top_k: int = 3`（可选，必须 `>=1` 且 `<=20`）
  - `filters: dict[str, Any] | None = None`（可选，元数据过滤）

#### 成功响应 `200`

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
  - `trace: dict[str, Any] | None`（可选调试信息）

#### 失败响应

- `422`：`query` 为空、`top_k` 非法
- `400`：索引未初始化
- `500`：检索过程异常

### 2.3 健康检查 `GET /rag/health`

#### 成功响应 `200`

- `HealthResponse`
  - `status: str`（固定为 `ok`）
  - `index_ready: bool`（索引是否可用）
  - `indexed_docs: int`（已入库文档数）
  - `indexed_chunks: int`（已入库 chunk 数）

### 2.4 错误响应统一结构

- `ErrorResponse`
  - `error_code: str`（如 `VALIDATION_ERROR`、`INDEX_NOT_READY`）
  - `message: str`（错误说明）
  - `detail: dict[str, Any] | None`（可选详情）

### 2.5 字段级校验规则（Pydantic 对齐）

> 本节用于约束实现阶段的 Pydantic `Field` 校验，不满足规则时统一返回 `422`。

#### `IndexDocument` 字段校验

| 字段 | 类型 | 必填 | 校验规则 | 错误示例 |
|---|---|---|---|---|
| `doc_id` | `str` | 是 | `strip` 后长度 `1-128` | 空字符串、全空白、长度超限 |
| `content` | `str` | 是 | `strip` 后长度 `>=1` | 空字符串、全空白 |
| `metadata` | `dict[str, Any]` | 否 | 若传入必须是对象类型 | 传入数组、字符串、数字 |

#### `IndexRequest` 字段校验

| 字段 | 类型 | 必填 | 校验规则 | 错误示例 |
|---|---|---|---|---|
| `documents` | `list[IndexDocument]` | 是 | 列表长度 `>=1` | 空数组、缺失字段 |

#### `QueryRequest` 字段校验

| 字段 | 类型 | 必填 | 校验规则 | 错误示例 |
|---|---|---|---|---|
| `query` | `str` | 是 | `strip` 后长度 `>=1` | 空字符串、全空白 |
| `top_k` | `int` | 否 | 默认 `3`，范围 `1-20` | `0`、负数、超过上限、非整数 |
| `filters` | `dict[str, Any]` | 否 | 若传入必须是对象类型 | 传入数组、字符串、数字 |

#### `RetrievedContext` 字段校验

| 字段 | 类型 | 必填 | 校验规则 | 说明 |
|---|---|---|---|---|
| `doc_id` | `str` | 是 | 非空 | 来源文档标识 |
| `chunk_id` | `str` | 是 | 非空 | chunk 标识 |
| `chunk_text` | `str` | 是 | 非空 | 召回文本 |
| `score` | `float` | 是 | 有限浮点数 | 相似度分数 |
| `metadata` | `dict[str, Any]` | 否 | 可为空对象 | 透传元信息 |

#### `ErrorResponse` 字段校验

| 字段 | 类型 | 必填 | 校验规则 | 说明 |
|---|---|---|---|---|
| `error_code` | `str` | 是 | 非空，推荐大写下划线风格 | 如 `VALIDATION_ERROR` |
| `message` | `str` | 是 | 非空 | 人可读错误信息 |
| `detail` | `dict[str, Any]` | 否 | 可为空对象 | 字段级错误详情 |

## 3. 核心处理流程

1. 接收文档并做基础清洗（去除无效空白）
2. 按固定策略切分为 chunk
3. 对 chunk 进行向量化并写入索引
4. 查询时对问题向量化并召回 `Top-K`
5. 返回召回片段与检索轨迹信息

## 4. 关键规则与边界

- `query` 去除首尾空白后不能为空
- `top_k` 必须为正整数，默认 `3`
- 当召回为空时，返回空 `contexts` 数组
- 返回的 `contexts` 数量不超过 `top_k`
- 同一 `doc_id` 重复入库按“覆盖旧索引”处理（实现阶段保持一致）

## 5. 测试策略（新增）

### 5.1 测试分层

- 单元测试：切分、参数校验、召回结果格式化逻辑
- 集成测试：入库 -> 查询的端到端检索链路
- 回归测试：固定问答样例集合，迭代后必须全通过

### 5.2 覆盖目标

- 接口覆盖：`/rag/index`、`/rag/query`、`/rag/health`
- 规则覆盖：空输入、非法 `top_k`、索引未初始化、召回为空
- 结果覆盖：召回结构完整、上下文数量与质量符合约束

## 6. 测试用例清单（新增）

| case_id | 类型 | 场景 | 输入 | 期望 |
|---|---|---|---|---|
| `rag_index_ok_001` | integration | 正常入库 2 篇文档 | `documents=[...]` | `200`；`indexed_count=2`；`chunk_count>0` |
| `rag_index_fail_empty_001` | integration | 空文档数组入库 | `documents=[]` | `422` |
| `rag_query_fail_empty_001` | integration | 空查询 | `query=""` | `422` |
| `rag_query_fail_no_index_001` | integration | 未建索引直接查询 | `query="什么是RAG"` | `400` |
| `rag_query_ok_001` | integration | 正常查询并返回证据 | `query="..." , top_k=3` | `200`；`contexts` 长度 `<=3` |
| `rag_query_ok_topk_001` | integration | 自定义 top_k 生效 | `query="..." , top_k=5` | `200`；`contexts` 长度 `<=5` |
| `rag_query_fail_topk_001` | integration | 非法 top_k | `top_k=0` 或负数 | `422` |
| `rag_health_ok_001` | integration | 健康检查 | `GET /rag/health` | `200`；`status=ok` |
| `rag_retrieval_reg_001` | regression | 关键问答命中验证 | 固定 query + 固定语料 | 命中期望证据片段（关键词命中） |
| `rag_retrieval_empty_reg_001` | regression | 低相关查询返回空召回 | 固定低相关 query + 固定语料 | `contexts=[]` |

## 7. 测试沉淀规则（新增）

- 每新增一个功能点，至少新增 1 条成功用例 + 1 条失败用例
- 每修复一个缺陷，必须新增对应回归用例
- 回归用例按 `case_id` 长期保留，不允许随意删除
- 任何发布前，回归集必须全量通过

## 8. 开发流程约束

每次迭代严格执行：
1. 先在 spec 补充需求与验收标准
2. 先补测试设计，再写实现
3. 完成后执行测试并记录结果
4. 把新增用例纳入回归集

## 9. 当前状态

- 当前为 spec 阶段，尚未开始具体代码实现
- 下一步先确认：向量库选型、Embedding 模型、召回测评数据集来源

