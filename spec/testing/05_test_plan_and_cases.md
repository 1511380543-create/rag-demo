# 测试计划与用例清单

> 本文档沉淀 RAG 服务测试策略、覆盖目标与回归用例。  
> 适用场景：测试设计、发布前验收、缺陷回归。

## 1. 测试分层

- 单元测试：切分（`tests/test_chunk_pipeline.py`：结构路径 / 回退 / 表格表头）、参数校验、召回结果格式化逻辑、评测指标计算（`eval_metrics.py`）
- 契约/集成测试：`extract → chunks → index/build → query` 链路（`tests/test_rag_api.py`）
- 回归测试：固定问答样例集合，迭代后必须全通过

### 1.0 运行环境与 Mock 边界（重要）

- **运行环境**：必须在 conda `rag-demo` 下执行（`conftest` 会校验解释器路径）
  - 命令：`conda activate rag-demo && pytest tests/ -q`
- **Mock 仅隔离外部链路**：DashScope Embedding HTTP（本地稳定哈希向量）
- **内部依赖不 mock**：真实抽取引擎（v0.7 起为 MinerU）、真实 `ChunkPipeline`、真实 MySQL Store
- **数据隔离**：测试写入独立库 `rag_demo_test`（不污染业务库 `rag_demo`）；每条用例前后 `TRUNCATE`
- **抽取性能**：session 级真实抽取缓存；`/rag/extract` 成功用例仍走完整 HTTP 抽取路径

### 1.1 抽取相关测试边界

| 层级 | 测什么 | 当前状态 |
|------|--------|----------|
| 集成（pytest） | `/rag/extract` 入参、错误码；MinerU 真实抽取 + 清洗门禁 | **待随 v0.7 代码落地**；仅 mock Embedding |
| 单元 | 清洗规则（半截重复/碎片/乱码）、表格质量门禁 | **待补** |
| 手工验收 | 业务库 OBD 等 PDF：无半截残留、无可读乱码表 | 见 `08` §10 |

### 1.2 切块相关测试边界

| 层级 | 测什么 | 当前状态 |
|------|--------|----------|
| 单元（pytest） | 文本块先拼再切、表格行组 + 表头附着、空输入报错 | **已实现**（`tests/test_chunk_pipeline.py`） |
| 集成 | `/rag/chunks` 入参与错误码 + 真实切块写库 | **已实现**（见 §3.0） |

切块算法权威文档：`spec/architecture/09_document_chunking.md`。

## 2. 覆盖目标

- 接口覆盖（已实现）：`/rag/extract`、`/rag/chunks`（`doc_ids`）、`/rag/index/build`、`/rag/query`、`/rag/health`
- 抽取契约覆盖（已实现）：空 documents、非 PDF、文件不存在、双文档真实抽取成功、`DOCUMENT_NOT_EXTRACTED`
- 抽取实现：默认 pytest 已走真实 Unstructured（测试库）；业务库手工 curl 仍见操作手册
- 监控接口覆盖：`/rag/metrics`（真实 MySQL `rag_query_logs`）
- 测评接口覆盖：`/rag/eval/dataset`、`/rag/eval/run`、`/rag/eval/runs`（真实 MySQL）
- 规则覆盖：空输入、非法 `top_k`、非法 `window_minutes`、索引未初始化、召回为空、评测集为空、`enabled` 样本筛选、`case_ids` 精确匹配
- 结果覆盖：召回结构完整、上下文数量与质量符合约束、监控指标聚合正确、评测指标计算正确、测评不污染在线监控日志

## 3. 测试用例清单

> 覆盖结论（当前代码）：真实抽取/切块/MySQL + Embedding mock + 切块单元 + 监控/测评已覆盖。  
> 最近一次执行结果（2026-07-20）：共 42 条；执行命令：`conda activate rag-demo && pytest tests/ -q`。

### 3.0 抽取与切块用例（已实现，集成层）

> 说明：以下用例写入 `tests/test_rag_api.py`。  
> 测试环境：conda `rag-demo`；真实 Unstructured + 真实切块 + MySQL `rag_demo_test`；仅 mock Embedding。

| case_id | 类型 | 场景 | 输入 | 期望 | 执行状态 | 备注 |
|---|---|---|---|---|---|---|
| `rag_extract_ok_001` | integration | 双文档真实抽取成功 | `documents=[{doc_id,file_path}, ...]`（2 份 PDF） | `200`；`extracted_doc_count=2`；`total_page_count>0`；`total_char_count>0` | 已执行-通过 | 真实 Unstructured |
| `rag_extract_fail_empty_001` | contract | 空文档数组抽取 | `documents=[]` | `422` | 已执行-通过 | 边界校验 |
| `rag_extract_fail_non_pdf_001` | contract | 非 PDF 路径抽取 | `file_path="docs/a.txt"` | `422` | 已执行-通过 | 仅支持 PDF |
| `rag_extract_fail_file_not_found_001` | contract | 本地文件不存在 | `file_path="docs/not_exist.pdf"` | `422` | 已执行-通过 | 文件存在性校验 |
| `rag_chunks_ok_001` | integration | 真实抽取结果切块 | 写入真实 blocks 后 `doc_ids=[...]` | `200`；`stored_doc_count=2`；`stored_chunk_count>0` | 已执行-通过 | 真实 ChunkPipeline |
| `rag_chunks_fail_empty_001` | contract | 空 doc_ids 切块 | `doc_ids=[]` | `422` | 已执行-通过 | 边界校验 |
| `rag_chunks_fail_not_extracted_001` | contract | 未抽取直接切块 | `doc_ids=["missing-doc"]` | `400` + `DOCUMENT_NOT_EXTRACTED` | 已执行-通过 | 阶段解耦约束 |

### 3.0.1 切块单元用例（已实现）

> 说明：写入 `tests/test_chunk_pipeline.py`，不依赖 MySQL / HTTP。

| case_id | 类型 | 场景 | 输入 | 期望 | 执行状态 | 备注 |
|---|---|---|---|---|---|---|
| `rag_chunk_unit_blocks_path_001` | unit | 有 blocks | paragraph + table | 含 `paragraph`/`table_rows` | 已执行-通过 | 段落先拼再切 |
| `rag_chunk_unit_merge_short_paragraphs_001` | unit | 连续短段含标题 | 6 个短 paragraph | 合并为 1 个 chunk，含全部标题与正文 | 已执行-通过 | 修复标题碎块 |
| `rag_chunk_unit_paragraph_flush_before_table_001` | unit | 段落夹表格 | 段-表-段 | 段落与表格分块，不混 HTML | 已执行-通过 | 表前 flush |
| `rag_chunk_unit_fallback_001` | unit | 无 blocks 回退 | `blocks=[]` + full_text | 全部 `chunk_kind=full_text_fallback` | 已执行-通过 | 回退 |
| `rag_chunk_unit_table_header_001` | unit | 表格表头附着 | 多行表 + 小 chunk_size | 每个 chunk 为 **Markdown** 且含表头 | 已执行-通过 | |
| `rag_chunk_unit_table_fallback_001` | unit | 无行表格降级 | 无法解析的 table | `table_fallback`；仍非 HTML 乱码 | 已执行-通过 | |
| `rag_chunk_unit_empty_input_001` | unit | 输入皆空 | blocks 与 full_text 皆空 | `EmptyChunkInputError` | 已执行-通过 | 异常 |
| `rag_chunk_unit_metadata_enterprise_001` | unit | 企业级 metadata | 带页码/章节 title | 含路径/页码/token/链表等 | 已执行-通过 | `09` §3.6 |
| `rag_chunk_unit_section_path_numbering_over_flat_level_001` | unit | 扁平 text_level | 手册标题+1.+1.1 | `full_section_path` 含中间层 | 已执行-通过 | 编号优先 |
| `rag_chunk_unit_table_section_follows_prefix_001` | unit | 表前 title | 7.1 正文后 7.2+表 | 表 `section_title=7.2` 与前缀一致 | 已执行-通过 | 表章节同步 |
| `rag_chunk_unit_metadata_table_cols_001` | unit | 表格列数 | 标准 HTML 表 | `table_cols` 与页码正确 | 已执行-通过 | |

### 3.1 索引 / 查询 / 回归用例（已实现）

| case_id | 类型 | 场景 | 输入 | 期望 | 执行状态 | 备注 |
|---|---|---|---|---|---|---|
| `rag_index_build_fail_no_chunks_001` | integration | 未入库 chunk 直接构建索引 | `force_rebuild=true` | `400` + `NO_CHUNKS_FOR_INDEX` | 已执行-通过 | 返回 `400`，错误码正确 |
| `rag_index_build_fail_invalid_doc_ids_001` | integration | 构建索引参数非法 | `doc_ids=["ok","   "]` | `422` | 已执行-通过 | 返回 `422`，与预期一致 |
| `rag_index_build_ok_001` | integration | 正常构建索引 | extract+chunks 后 `force_rebuild=true` | `200`；`indexed_doc_count=2`；`indexed_chunk_count>0` | 已执行-通过 | 返回 `200`，字段值与预期一致 |
| `rag_query_fail_empty_001` | integration | 空查询 | `query=""` | `422` | 已执行-通过 | 返回 `422`，与预期一致 |
| `rag_query_fail_no_index_001` | integration | 未建索引直接查询 | `query="什么是RAG"` | `400` + `INDEX_NOT_READY` | 已执行-通过 | 返回 `400`，错误码正确 |
| `rag_query_ok_001` | integration | 正常查询并返回证据 | `query="..." , top_k=3` | `200`；`contexts` 长度 `<=3` | 已执行-通过 | 返回 `200`，`contexts` 数量不超过 `3` |
| `rag_query_ok_topk_001` | integration | 自定义 top_k 生效 | `query="..." , top_k=5` | `200`；`contexts` 长度 `<=5` | 已执行-通过 | 返回 `200`，`contexts` 数量不超过 `5` |
| `rag_query_fail_topk_001` | integration | 非法 top_k | `top_k=0` 或负数 | `422` | 已执行-通过 | 返回 `422`，与预期一致 |
| `rag_health_ok_001` | integration | 健康检查 | `GET /rag/health` | `200`；`status=ok`；含 `extracted_docs` / `indexed_docs` / `indexed_chunks` | 已执行-通过 | 返回 `200`，统计字段有效 |
| `rag_retrieval_reg_001` | regression | 关键问答命中验证 | 固定 query + 固定语料 | 命中期望证据片段（关键词命中） | 已执行-通过 | 返回 `200`，召回文本命中 `11009` 与 `30s/30秒` 关键线索 |
| `rag_retrieval_empty_reg_001` | regression | 低相关查询返回空召回 | 固定低相关 query + 固定语料 | `contexts=[]` | 已执行-预期失败 | 实际返回非空 `contexts`，当前实现缺少低相关阈值过滤（已在测试中 xfail 标记） |

### 3.2 监控用例（已实现）

> 说明：监控接口代码已落地（`monitoring_store.py`），以下用例已写入 `tests/test_rag_api.py` 并通过执行。  
> 测试环境：真实 MySQL `rag_demo_test.rag_query_logs`；仅 mock Embedding。

| case_id | 类型 | 场景 | 输入 | 期望 | 执行状态 | 备注 |
|---|---|---|---|---|---|---|
| `rag_query_score_record_001` | integration | 查询分数被记录 | 正常查询后查内存监控日志 | `top_score/avg_score` 已写入 | 已执行-通过 | 本轮只记录不过滤 |
| `rag_metrics_ok_001` | integration | 监控指标聚合 | 若干次查询后 `GET /rag/metrics` | `200`；`total_queries>0`；`empty_recall_rate` 在 `0-1` | 已执行-通过 | 校验聚合正确性 |
| `rag_metrics_window_001` | integration | 时间窗口过滤 | 注入 10 分钟前日志 + 2 次近期查询；`GET /rag/metrics?window_minutes=5` | 全量 `total_queries=3`；窗口内 `total_queries=2` | 已执行-通过 | 窗口边界 |
| `rag_metrics_fail_window_001` | integration | 非法窗口参数 | `window_minutes=0` 或负数 | `422` | 已执行-通过 | 边界校验 |

### 3.3 测评用例（已实现）

> 说明：测评接口代码已落地（`eval_store.py`、`eval_metrics.py`），以下用例已写入测试代码并通过执行。  
> 集成/回归用例：`tests/test_rag_api.py`；评测指标单元用例：`tests/test_eval_metrics.py`。  
> 测试环境：真实 MySQL `rag_demo_test` 评测表；仅 mock Embedding。

| case_id | 类型 | 场景 | 输入 | 期望 | 执行状态 | 备注 |
|---|---|---|---|---|---|---|
| `rag_eval_dataset_upsert_001` | integration | 评测样本批量 upsert | `cases=[{case_id,query_text,expected_keywords}]` | `200`；`upserted_count>0` | 已执行-通过 | 同 `case_id` 覆盖 |
| `rag_eval_dataset_list_001` | integration | 评测样本列表与 upsert 一致 | upsert 后 `GET /rag/eval/dataset` | `200`；`total` 与 `cases` 条数一致；字段与 upsert 请求一致 | 已执行-通过 | 覆盖读路径；同 `case_id` 覆盖后列表反映最新值 |
| `rag_eval_dataset_fail_empty_001` | integration | 空样本数组 | `cases=[]` | `422` | 已执行-通过 | 边界校验 |
| `rag_eval_dataset_fail_no_gt_001` | integration | 缺少 ground truth | 两类标注均缺失 | `422` | 已执行-通过 | 至少提供其一 |
| `rag_eval_run_ok_001` | integration | 正常执行测评（固定语料） | OBD 单文档入库 + 建索引；样本 query 与 `rag_retrieval_reg_001` 一致；`expected_keywords=["11009","30s","30秒"]`；样本级 `top_k=10` | `200`；`run_id>0`；`avg_hit=1.0`；`avg_recall/avg_mrr` 在 `0-1`；`avg_latency_ms>=0`；`items` 逐条含 `retrieved_chunk_ids` | 已执行-通过 | 测试环境 hash 向量下关键线索需更大 top_k；`latency_ms` 不以 `0-1` 约束 |
| `rag_eval_run_enabled_filter_001` | integration | 禁用样本默认不参与 | 写入 `enabled=true` 与 `enabled=false` 各 1 条；`POST /rag/eval/run` 不传 `case_ids` | `200`；`dataset_size=1`；仅执行 enabled 样本 | 已执行-通过 | 对应 `07` §3.2 样本筛选规则 |
| `rag_eval_run_case_ids_override_001` | integration | 指定 case_ids 忽略 enabled | 写入 `enabled=false` 样本；`POST /rag/eval/run` 传对应 `case_ids` | `200`；`dataset_size=1`；该样本被执行 | 已执行-通过 | 传 `case_ids` 时不受 `enabled` 限制 |
| `rag_eval_run_no_monitor_pollution_001` | integration | 测评不写入监控日志 | 记录 run 前监控计数；执行 `POST /rag/eval/run` | `GET /rag/metrics` 的 `total_queries` 不增加 | 已执行-通过 | 架构约束：测评复用检索但不经过 `/rag/query` 埋点 |
| `rag_eval_run_fail_no_index_001` | integration | 未建索引执行测评 | 未 build 索引 | `400` + `INDEX_NOT_READY` | 已执行-通过 | 状态校验 |
| `rag_eval_run_fail_empty_dataset_001` | integration | 空评测集执行测评 | 评测集为空 | `400` + `EVAL_DATASET_EMPTY` | 已执行-通过 | 状态校验 |
| `rag_eval_runs_list_001` | integration | 评测历史查询 | 执行测评后 `GET /rag/eval/runs?limit=10` | `200`；`total>=1`；最新轮次 `run_id/avg_hit/note` 与 run 响应一致 | 已执行-通过 | 支持迭代前后对比 |
| `rag_eval_metrics_unit_keyword_001` | unit | 仅 expected_keywords 命中 | 固定 `retrieved_texts` 含关键词 | `hit=1`；`recall=0.0`；`mrr>0` | 已执行-通过 | 仅 keyword 模式不计算 recall |
| `rag_eval_metrics_unit_chunk_001` | unit | 仅 relevant_chunk_ids 命中 | 固定 `retrieved_chunk_ids` 含标注 ID | `hit=1`；`recall` 按命中比例；`mrr` 按首个命中排名 | 已执行-通过 | chunk 级精确标注 |
| `rag_eval_metrics_unit_dual_or_001` | unit | 双标注 OR 判定 | chunk 未命中但 keyword 命中 | `hit=1`；`mrr>0` | 已执行-通过 | 对应 `07` §3.3 OR 规则 |
| `rag_eval_metrics_unit_keyword_all_001` | unit | keyword_match_mode=all | 多词仅部分命中 | `hit=0` | 已执行-通过 | 多词共现约束 |

### 3.4 业务测评集验收（离线，非 pytest）

> 说明：本节与 §3.3 互补——§3.3 验证测评**系统**正确性（TDD）；本节定义业务**检索质量**验收（SDD 第一层）。  
> **构建高质量测评集第一轮**（同域干扰 + 异域噪声）已完成：方向与优化见 `07` §3.4.1，门禁见 `06` §5.1。  
> **构建高质量测评集第二轮**为 TODO，见 `07` §3.4.2 / `06` §5.2。

| 验收项 | 执行方式 | 期望 | 备注 |
|---|---|---|---|
| 种子集导入 | 十份 PDF 入库后 `POST /rag/eval/dataset` | `upserted_count=50` | 种子 `spec/eval/eval_dataset.json` |
| 全量离线测评 | `POST /rag/eval/run`（**不传**请求级 `top_k`） | 回显 `top_k=10`；返回 hit/mrr/latency | 主口径样本 `top_k=10` |
| P0 核心样本 | 见 `06` §5.1 | 逐条 `hit=1` | 发布前必查 |
| 全量质量门槛 | 对比 `run_id=8` baseline | `avg_hit`、`avg_mrr` 不低于 0.98 / 0.910 | 语料或标注变更后须重标定 |
| 迭代记录 | 更新 `06` §5 / §6 | 记录 run_id 与指标 | |

- 本验收**不纳入** `pytest` 默认门禁（依赖真实 embedding 与全量语料，执行成本高）
- 检索链路变更（切分、embedding、top_k 策略）后必须重跑并更新 `06` baseline

### 3.5 抽取实现层验收（业务库）

> 对应 `08_document_extraction.md`（MinerU，`extract_version=mineru-v1`）。

| 验收项 | 执行方式 | 期望 | 备注 |
|---|---|---|---|
| MinerU 抽取 | conda `rag-demo`；`POST /rag/extract` | `200`；`extract_version=mineru-v1` | 依赖本地 MinerU |
| 结构类型 | 查 `rag_documents.blocks` | 含 `title`（若文档有标题） | 不得「全是 paragraph」 |
| 无半截残留 | 抽 OBD 手册 | 无「完整句 + 后缀碎片」成对 | 清洗 C5 |
| 表格可读 | 查 blocks HTML + chunks Markdown | blocks 可读 HTML；chunks 为 MD 管道表 | `08` §6 / `09` §3.2 |
| 阶段解耦 | extract 后不调 chunks 直接 query | 不可检索 | |

## 4. 测试沉淀规则

- 每新增一个功能点，至少新增 1 条成功用例 + 1 条失败用例
- 每修复一个缺陷，必须新增对应回归用例
- 回归用例按 `case_id` 长期保留，不允许随意删除
- 任何发布前，回归集必须全量通过
- **Mock 仅用于外部链路**（如 Embedding HTTP）；内部依赖（抽取、切块、MySQL）禁止用 mock 绕过核心逻辑

## 5. 变更同步要求

- 接口变更后，必须同步更新本页覆盖目标与用例清单
- 流程变更后，必须新增阶段间联动测试用例
- 抽取引擎变更后，必须同步更新 §1.0/§1.1 边界、§3.0 用例与 §3.5 业务库验收
- Mock 边界变更后，必须同步更新 §1.0