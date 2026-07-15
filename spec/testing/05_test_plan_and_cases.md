# 测试计划与用例清单

> 本文档沉淀 RAG 服务测试策略、覆盖目标与回归用例。  
> 适用场景：测试设计、发布前验收、缺陷回归。

## 1. 测试分层

- 单元测试：切分、参数校验、召回结果格式化逻辑、评测指标计算（`eval_metrics.py`）
- 集成测试：切分入库 -> 索引构建 -> 查询召回链路
- 回归测试：固定问答样例集合，迭代后必须全通过

## 2. 覆盖目标

- 接口覆盖：`/rag/chunks`、`/rag/index/build`、`/rag/query`、`/rag/health`
- 监控接口覆盖：`/rag/metrics`
- 测评接口覆盖：`/rag/eval/dataset`、`/rag/eval/run`、`/rag/eval/runs`
- 规则覆盖：空输入、非法 `top_k`、非法 `window_minutes`、索引未初始化、召回为空、评测集为空、`enabled` 样本筛选、`case_ids` 精确匹配
- 结果覆盖：召回结构完整、上下文数量与质量符合约束、监控指标聚合正确、评测指标计算正确、测评不污染在线监控日志

## 3. 测试用例清单

> 覆盖结论（当前代码）：核心链路 + 监控 + 测评用例已全覆盖（接口、边界、回归、指标计算均有）。  
> 最近一次执行结果（2026-07-15）：共 32 条，`通过 31`，`预期失败 1`（已知差距）。  
> 执行命令：`pytest tests/ -q`（监控子集：`pytest tests/ -q -k metrics`；测评子集：`pytest tests/ -q -k eval`）。

| case_id | 类型 | 场景 | 输入 | 期望 | 执行状态 | 备注 |
|---|---|---|---|---|---|---|
| `rag_chunks_ok_001` | integration | 正常切分入库 2 个本地 PDF | `documents=[{doc_id,file_path}, ...]` | `200`；`stored_doc_count=2`；`stored_chunk_count>0` | 已执行-通过 | 返回 `200`，字段值与预期一致 |
| `rag_chunks_fail_empty_001` | integration | 空文档数组切分入库 | `documents=[]` | `422` | 已执行-通过 | 返回 `422`，与预期一致 |
| `rag_chunks_fail_non_pdf_001` | integration | 非 PDF 路径切分入库 | `file_path="docs/a.txt"` | `422` | 已执行-通过 | 返回 `422`，与预期一致 |
| `rag_chunks_fail_file_not_found_001` | integration | 本地文件不存在 | `file_path="docs/not_exist.pdf"` | `422` | 已执行-通过 | 返回 `422`，与预期一致 |
| `rag_index_build_fail_no_chunks_001` | integration | 未入库 chunk 直接构建索引 | `force_rebuild=true` | `400` + `NO_CHUNKS_FOR_INDEX` | 已执行-通过 | 返回 `400`，错误码正确 |
| `rag_index_build_fail_invalid_doc_ids_001` | integration | 构建索引参数非法 | `doc_ids=["ok","   "]` | `422` | 已执行-通过 | 返回 `422`，与预期一致 |
| `rag_index_build_ok_001` | integration | 正常构建索引 | 已入库 chunks + `force_rebuild=true` | `200`；`indexed_doc_count=2`；`indexed_chunk_count>0` | 已执行-通过 | 返回 `200`，字段值与预期一致 |
| `rag_query_fail_empty_001` | integration | 空查询 | `query=""` | `422` | 已执行-通过 | 返回 `422`，与预期一致 |
| `rag_query_fail_no_index_001` | integration | 未建索引直接查询 | `query="什么是RAG"` | `400` | 已执行-通过 | 返回 `400`，错误码 `INDEX_NOT_READY` |
| `rag_query_ok_001` | integration | 正常查询并返回证据 | `query="..." , top_k=3` | `200`；`contexts` 长度 `<=3` | 已执行-通过 | 返回 `200`，`contexts` 数量不超过 `3` |
| `rag_query_ok_topk_001` | integration | 自定义 top_k 生效 | `query="..." , top_k=5` | `200`；`contexts` 长度 `<=5` | 已执行-通过 | 返回 `200`，`contexts` 数量不超过 `5` |
| `rag_query_fail_topk_001` | integration | 非法 top_k | `top_k=0` 或负数 | `422` | 已执行-通过 | 返回 `422`，与预期一致 |
| `rag_health_ok_001` | integration | 健康检查 | `GET /rag/health` | `200`；`status=ok`；`indexed_docs/chunks` 有效 | 已执行-通过 | 返回 `200`，统计字段有效 |
| `rag_retrieval_reg_001` | regression | 关键问答命中验证 | 固定 query + 固定语料 | 命中期望证据片段（关键词命中） | 已执行-通过 | 返回 `200`，召回文本命中 `11009` 与 `30s/30秒` 关键线索 |
| `rag_retrieval_empty_reg_001` | regression | 低相关查询返回空召回 | 固定低相关 query + 固定语料 | `contexts=[]` | 已执行-预期失败 | 实际返回非空 `contexts`，当前实现缺少低相关阈值过滤（已在测试中 xfail 标记） |

## 3.1 监控用例（已实现）

> 说明：监控接口代码已落地（`monitoring_store.py`），以下用例已写入 `tests/test_rag_api.py` 并通过执行。  
> 测试环境：使用 InMemory `MonitoringStore` mock，支持时间窗口过滤；不依赖真实 MySQL 已有数据。

| case_id | 类型 | 场景 | 输入 | 期望 | 执行状态 | 备注 |
|---|---|---|---|---|---|---|
| `rag_query_score_record_001` | integration | 查询分数被记录 | 正常查询后查内存监控日志 | `top_score/avg_score` 已写入 | 已执行-通过 | 本轮只记录不过滤 |
| `rag_metrics_ok_001` | integration | 监控指标聚合 | 若干次查询后 `GET /rag/metrics` | `200`；`total_queries>0`；`empty_recall_rate` 在 `0-1` | 已执行-通过 | 校验聚合正确性 |
| `rag_metrics_window_001` | integration | 时间窗口过滤 | 注入 10 分钟前日志 + 2 次近期查询；`GET /rag/metrics?window_minutes=5` | 全量 `total_queries=3`；窗口内 `total_queries=2` | 已执行-通过 | 窗口边界 |
| `rag_metrics_fail_window_001` | integration | 非法窗口参数 | `window_minutes=0` 或负数 | `422` | 已执行-通过 | 边界校验 |

## 3.2 测评用例（已实现）

> 说明：测评接口代码已落地（`eval_store.py`、`eval_metrics.py`），以下用例已写入测试代码并通过执行。  
> 集成/回归用例：`tests/test_rag_api.py`；评测指标单元用例：`tests/test_eval_metrics.py`。  
> 测试环境：使用 InMemory 存储 mock（`MySQLChunkStore` / `EvalStore` / `MonitoringStore`），不依赖真实 MySQL 已有数据。

| case_id | 类型 | 场景 | 输入 | 期望 | 执行状态 | 备注 |
|---|---|---|---|---|---|---|
| `rag_eval_dataset_upsert_001` | integration | 评测样本批量 upsert | `cases=[{case_id,query_text,expected_keywords}]` | `200`；`upserted_count>0` | 已执行-通过 | 同 `case_id` 覆盖 |
| `rag_eval_dataset_list_001` | integration | 评测样本列表与 upsert 一致 | upsert 后 `GET /rag/eval/dataset` | `200`；`total` 与 `cases` 条数一致；字段与 upsert 请求一致 | 已执行-通过 | 覆盖读路径；同 `case_id` 覆盖后列表反映最新值 |
| `rag_eval_dataset_fail_empty_001` | integration | 空样本数组 | `cases=[]` | `422` | 已执行-通过 | 边界校验 |
| `rag_eval_dataset_fail_no_gt_001` | integration | 缺少 ground truth | 两类标注均缺失 | `422` | 已执行-通过 | 至少提供其一 |
| `rag_eval_run_ok_001` | integration | 正常执行测评（固定语料） | OBD 单文档入库 + 建索引；样本 query 与 `rag_retrieval_reg_001` 一致；`expected_keywords=["11009","30s","30秒"]`；样本级 `top_k=10` | `200`；`run_id>0`；`avg_hit=1.0`；`avg_recall/avg_mrr` 在 `0-1`；`avg_latency_ms>=0`；`items` 逐条含 `retrieved_chunk_ids` | 已执行-通过 | 测试环境 hash 向量下关键线索需更大 top_k；`latency_ms` 不以 `0-1` 约束 |
| `rag_eval_run_enabled_filter_001` | integration | 禁用样本默认不参与 | 写入 `enabled=true` 与 `enabled=false` 各 1 条；`POST /rag/eval/run` 不传 `case_ids` | `200`；`dataset_size=1`；仅执行 enabled 样本 | 已执行-通过 | 对应 `07` §4.1 样本筛选规则 |
| `rag_eval_run_case_ids_override_001` | integration | 指定 case_ids 忽略 enabled | 写入 `enabled=false` 样本；`POST /rag/eval/run` 传对应 `case_ids` | `200`；`dataset_size=1`；该样本被执行 | 已执行-通过 | 传 `case_ids` 时不受 `enabled` 限制 |
| `rag_eval_run_no_monitor_pollution_001` | integration | 测评不写入监控日志 | 记录 run 前监控计数；执行 `POST /rag/eval/run` | `GET /rag/metrics` 的 `total_queries` 不增加 | 已执行-通过 | 架构约束：测评复用检索但不经过 `/rag/query` 埋点 |
| `rag_eval_run_fail_no_index_001` | integration | 未建索引执行测评 | 未 build 索引 | `400` + `INDEX_NOT_READY` | 已执行-通过 | 状态校验 |
| `rag_eval_run_fail_empty_dataset_001` | integration | 空评测集执行测评 | 评测集为空 | `400` + `EVAL_DATASET_EMPTY` | 已执行-通过 | 状态校验 |
| `rag_eval_runs_list_001` | integration | 评测历史查询 | 执行测评后 `GET /rag/eval/runs?limit=10` | `200`；`total>=1`；最新轮次 `run_id/avg_hit/note` 与 run 响应一致 | 已执行-通过 | 支持迭代前后对比 |
| `rag_eval_metrics_unit_keyword_001` | unit | 仅 expected_keywords 命中 | 固定 `retrieved_texts` 含关键词 | `hit=1`；`recall=0.0`；`mrr>0` | 已执行-通过 | 仅 keyword 模式不计算 recall |
| `rag_eval_metrics_unit_chunk_001` | unit | 仅 relevant_chunk_ids 命中 | 固定 `retrieved_chunk_ids` 含标注 ID | `hit=1`；`recall` 按命中比例；`mrr` 按首个命中排名 | 已执行-通过 | chunk 级精确标注 |
| `rag_eval_metrics_unit_dual_or_001` | unit | 双标注 OR 判定 | chunk 未命中但 keyword 命中 | `hit=1`；`mrr>0` | 已执行-通过 | 对应 `07` §4.1 OR 规则 |

## 4. 测试沉淀规则

- 每新增一个功能点，至少新增 1 条成功用例 + 1 条失败用例
- 每修复一个缺陷，必须新增对应回归用例
- 回归用例按 `case_id` 长期保留，不允许随意删除
- 任何发布前，回归集必须全量通过

## 5. 变更同步要求

- 接口变更后，必须同步更新本页覆盖目标与用例清单
- 流程变更后，必须新增阶段间联动测试用例
