# 监控与测评设计

> 检索链路监控与离线测评规范。接口见 `01`，表结构见 `02`，baseline 见 `06`。

## 1. 目标与边界

- **监控**：观察 `/rag/query` 的延迟、召回量、分数分布
- **测评**：离线量化检索质量，支持迭代对比
- **范围**：仅检索链路；不含答案生成、低相关空召回过滤
- **约束**：测评复用内部检索逻辑，不经过 `/rag/query`，不写入 `rag_query_logs`

## 2. 监控

- **采集**：每次 `/rag/query` 同步写入 `rag_query_logs`（成功与失败均记录）
- **字段**：`query_text`、`top_k`、延迟拆分（`embed_ms`/`retrieve_ms`/`total_ms`）、召回数量、分数统计（`top_score`/`min_score_value`/`avg_score`）、`error_code`
- **规则**：分数仅记录，不参与过滤；写库失败不影响查询响应
- **聚合**：`GET /rag/metrics`（可选 `window_minutes`）

## 3. 测评

### 3.1 数据与接口

| 表 | 用途 |
|---|---|
| `rag_eval_dataset` | 评测样本 |
| `rag_eval_runs` / `rag_eval_run_items` | 轮次汇总与明细 |

接口：`POST/GET /rag/eval/dataset`、`POST /rag/eval/run`、`GET /rag/eval/runs`（详见 `01`）。

### 3.2 样本约束

- `relevant_chunk_ids` 与 `expected_keywords` 至少提供其一
- `keyword_match_mode`：`any`（默认）或 `all`
- 默认仅执行 `enabled=true` 样本；传 `case_ids` 时不受 `enabled` 限制

### 3.3 命中与指标

- **chunk 标注**：召回 `chunk_id` 命中即相关
- **关键词标注**：在召回文本中子串匹配（`any`/`all`）
- **双标注并存**：`hit@k`/`mrr@k` 取 OR；`recall@k` 仅基于 chunk 标注

| 指标 | 含义 |
|---|---|
| `hit@k` | top_k 内至少命中 1 条 |
| `mrr@k` | 首个相关结果的倒数排名 |
| `recall@k` | 命中相关 chunk 数 / 标注总数（仅 chunk 标注） |
| `latency_ms` | 单条检索耗时 |

`top_k` 优先级：请求级 > 样本级 > 默认 `3`。

## 4. 非目标

- 分数阈值过滤（`rag_retrieval_empty_reg_001` 仍为已知差距）
- `nDCG`、外部可观测框架（OpenTelemetry / Prometheus 等）
- 自动化定时评测

## 5. 验收标准

- `/rag/query` 每次请求写入监控日志；`/rag/eval/run` 不污染监控计数
- 评测集 upsert、执行、历史查询可用
- 指标计算符合 §3.3；自动化用例见 `05`
- 离线 baseline 与发布门禁见 `06` §4
