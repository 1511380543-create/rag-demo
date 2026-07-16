# 监控与测评设计

> RAG 服务检索链路的监控与离线测评规范。  
> 接口细节见 `01`，数据表见 `02`，流程见 `03`，迭代记录见 `06`。

## 1. 目标与边界

- **监控**：在线观察 `/rag/query` 的延迟、召回量、分数分布
- **测评**：离线量化检索质量，支持迭代前后对比
- **范围**：仅检索链路，不含答案生成、doc_id 级命中、低相关空召回
- **存储**：MySQL；监控同步写库，测评离线触发
- **约束**：测评复用内部 `_retrieve()`，不经过 `/rag/query`，不写入 `rag_query_logs`

## 2. 监控

### 2.1 采集（`/rag/query`）

单次查询记录：`query_text`、`top_k`、`filters_applied`、`embed_ms`、`retrieve_ms`、`total_ms`、`retrieved_before_filter`、`retrieved_after_filter`、`is_empty_recall`、`top_score`、`min_score_value`、`avg_score`、`error_code`、`created_at`。

分数仅记录，不参与过滤或降级。

### 2.2 存储与聚合

- 表：`rag_query_logs`
- 写库失败不影响查询响应
- 聚合接口：`GET /rag/metrics`（支持 `window_minutes`）

## 3. 测评

### 3.1 数据模型

| 表 | 用途 |
|---|---|
| `rag_eval_dataset` | 评测样本 |
| `rag_eval_runs` | 轮次汇总 |
| `rag_eval_run_items` | 逐条明细（含 `retrieved_chunk_ids`） |

### 3.2 接口

- `POST /rag/eval/dataset`：按 `case_id` upsert
- `GET /rag/eval/dataset`：列出样本
- `POST /rag/eval/run`：执行一轮测评
- `GET /rag/eval/runs`：历史轮次

### 3.3 样本字段

| 字段 | 说明 |
|---|---|
| `case_id` | 业务用例 ID |
| `query_text` | 评测查询 |
| `relevant_chunk_ids` | chunk 级标注（可选，精确） |
| `expected_keywords` | 关键词标注（可选） |
| `keyword_match_mode` | `any`（默认）或 `all` |
| `top_k` | 样本级 top_k（可选） |
| `enabled` | 是否参与默认测评 |

`relevant_chunk_ids` 与 `expected_keywords` 至少提供其一。

### 3.4 命中判定

均在单次 query 的 `top_k` 召回结果内判定，二值相关度（相关=1 / 不相关=0）。

- **chunk 标注**：`chunk_id` 在 `relevant_chunk_ids` 中即相关
- **关键词标注**：
  - `any`：chunk 文本包含列表中任一关键词（大小写不敏感、子串匹配）
  - `all`：chunk 文本须包含列表中全部关键词
- **双标注并存**：`hit@k` / `mrr@k` 采用 OR（chunk 或 keyword 任一命中）；`recall@k` 仅基于 `relevant_chunk_ids`

`top_k` 优先级：请求级 > 样本级 > 默认 `3`。

### 3.5 指标

| 指标 | 含义 |
|---|---|
| `hit@k` | top_k 内至少命中 1 条相关 chunk |
| `mrr@k` | 首个相关结果的倒数排名 |
| `recall@k` | 命中相关 chunk 数 / 标注相关 chunk 总数（仅 chunk 标注） |
| `latency_ms` | 单条检索耗时 |

轮次汇总为逐条平均值：`avg_hit`、`avg_mrr`、`avg_recall`、`avg_latency_ms`。

当前种子集全为 `expected_keywords`，**不以 `avg_recall` 作验收门禁**。

## 4. 检索测评标准（当前阶段）

> 适用：纯检索、三份领域 PDF、无生成层。实现见 `app/eval_metrics.py`、`app/rag_service.py` `run_eval()`。

### 4.1 语料与种子集

- 语料：`docs/` 下三份 PDF（OBD 809 协议 / 国三报废 / 重型柴油车免年检）
- 种子文件：`spec/eval/eval_dataset.json`（18 条）
- 前置：PDF 入库 + 建索引后，调用 `POST /rag/eval/dataset` 导入（body 为 `{"cases": [...]}`）
- 库表迁移：若缺 `keyword_match_mode` 列，执行 `spec/sql/mysql_schema.sql` 中对应 `ALTER`

### 4.2 标注规范

1. **单事实型**（端口、报文 ID、数值）：用语料内**唯一锚点短语**，避免 `"2026"`、`"TCP"`、`"OBD"` 等短词单独标注
2. **条款型**（适用范围、合规条件）：用章节标题或完整条件短语
3. **多词共现**：设 `keyword_match_mode=all`（当前 4 条：`eval-obd-port-heartbeat`、`eval-emission-force-scrap-age-operating`、`eval-emission-danger-truck-age`）
4. **多证据型**：改用 `relevant_chunk_ids`，以启用 `recall@k`（当前种子集未使用）

### 4.3 核心指标与对比方式

| 指标 | 角色 |
|---|---|
| `avg_hit` | **主指标**：是否召到正确证据 |
| `avg_mrr` | **辅指标**：正确证据排序位置 |
| `avg_latency_ms` | 性能观测，仅做环比 |

每次检索链路变更后执行 `POST /rag/eval/run`，通过 `GET /rag/eval/runs` 与 baseline 对比。

**默认对比配置**：请求级 `top_k=3`；个别样本设样本级 `top_k`（如 `eval-obd-port-heartbeat` 为 `10`）。

### 4.4 当前 baseline

| 项 | 值 |
|---|---|
| `run_id` | 3 |
| 样本数 | 18（`enabled=true`） |
| `avg_hit` | 0.333 |
| `avg_mrr` | 0.333 |
| `avg_latency_ms` | 186.5 |
| 备注 | 标注收紧后首轮；旧版宽松标注 `run_id=1` 为 `avg_hit=1.0`（含假阳性） |

**已通过（6）**：`eval-obd-fault-report-id`、`eval-obd-heartbeat-msg-id`、`eval-obd-offline-cache`、`eval-obd-work-data-report`、`eval-heavy-diesel-scope-mass`、`eval-heavy-diesel-data-rate`

**未通过（12）**：OBD 3 条、国三报废 6 条、免年检 3 条（详见 `run_id=3` 的 `rag_eval_run_items`）

### 4.5 P0 核心样本

发布前须逐条 `hit=1`（可通过 `case_ids` 单独跑测）：

| case_id | baseline `hit` |
|---|---|
| `eval-obd-port-heartbeat` | 0 |
| `eval-obd-fault-report-id` | 1 |
| `eval-emission-scope` | 0 |
| `eval-heavy-diesel-obd-terminal` | 0 |
| `eval-heavy-diesel-data-rate` | 1 |

### 4.6 验收标准

> 由人工或脚本检查 `POST /rag/eval/run` 响应；未达标仍返回 `200`。

1. **迭代不退化**：`avg_hit`、`avg_mrr` 不低于 baseline（`run_id=3`）
2. **P0 门禁**：五条 P0 样本逐条 `hit=1`
3. **性能观测**：`avg_latency_ms` 较 baseline 增幅不超过 20%（不单独阻断）
4. **TDD 门禁**：`pytest tests/ -q` 全量通过（见 `05` §3.2）

## 5. 范围外

- 分数阈值过滤、低相关空召回（`rag_retrieval_empty_reg_001`）
- `nDCG`、分级相关度标注
- 外部可观测框架（OpenTelemetry / Prometheus / Langfuse 等）

## 6. 实现映射

| 能力 | 模块 |
|---|---|
| 查询埋点 | `app/rag_service.py` `_record_query_trace` |
| 监控聚合 | `app/monitoring_store.py` |
| 评测指标 | `app/eval_metrics.py` |
| 评测存储 | `app/eval_store.py` |
| HTTP 入口 | `app/main.py` |
