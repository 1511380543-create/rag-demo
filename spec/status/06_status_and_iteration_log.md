# 状态与迭代记录

> 本文档记录当前实现状态、已知差距与迭代轨迹。  
> 适用场景：版本评估、排期沟通、上线前核对。

## 1. 当前状态

- 核心接口已实现：`/rag/extract`、`/rag/chunks`（`doc_ids`）、`/rag/index/build`、`/rag/query`、`/rag/health` 及监控/测评接口
- **抽取**：MinerU + 企业级清洗 + 表格门禁；`blocks` 含 `title`/`paragraph`/`list_item`/`table` 及 `page_idx`/`bbox`/`text_level`（见 `08`）
- **切块正文**：长度约束 + 递归切分 + 标题粘性 + 表格 Markdown（见 `09`）
- **切块 metadata**：`09` §3.6 已落地（编号优先章节栈、表前 title 同步；本地 PDF `category=pdf`）
- 自动化测试：须在 conda `rag-demo` 执行；仅 mock Embedding；测试库 `rag_demo_test`（见 `05`）
- 业务库手工 curl 验收见操作手册

## 2. 目标状态（spec 目标 v0.7）

- 目标接口：`/rag/extract`、`/rag/chunks`、`/rag/index/build`、`/rag/query`、`/rag/health`
- 目标流程：
  - 阶段一：MinerU 解析 → 企业级清洗 → 表格门禁 → `rag_documents`（`extract_version=mineru-v1`）
  - 阶段二：文本块先拼再切；表格 HTML→Markdown 行组 → `rag_chunks`（含企业级 metadata）
  - 阶段三：从 `rag_chunks` 构建向量索引
- 目标存储：
  - `rag_documents`：blocks（含 title/list_item + 溯源字段）+ full_text，表格为可读 HTML
  - `rag_chunks`：文本纯文本；表格为 Markdown；metadata 见 `09` §3.6
  - 原始 PDF 不入 MySQL

## 3. 已知差距

- 当前向量索引为内存态（服务重启后需重新调用 `/rag/index/build`）
- 回归用例 `rag_retrieval_empty_reg_001` 仍为已知差距（低相关结果过滤未实现）
- 跨 block 合并时 `bbox` 常为 `null`（单块坐标策略）；高亮溯源能力有限
- 旧文档若未重切，章节路径可能仍为扁平 2 层；改完代码后需再调 `/rag/chunks`
- pytest 默认仅 mock Embedding；业务库手工联调见操作手册

## 4. 监控与测评（已实现）

- 设计状态：以 `spec/architecture/07_observability_and_eval.md` 为准
- 监控（已实现）：
  - 接口：`GET /rag/metrics`
  - 数据表：`rag_query_logs`
  - 能力：`/rag/query` 请求内同步埋点、失败查询同样写库、监控写库异常不影响查询响应
- 测评（已实现）：
  - 接口：`POST /rag/eval/dataset`、`GET /rag/eval/dataset`、`POST /rag/eval/run`、`GET /rag/eval/runs`
  - 数据表：`rag_eval_dataset`、`rag_eval_runs`、`rag_eval_run_items`
  - 能力：评测集 upsert、离线批量检索测评、历史轮次查看
  - 种子集：`spec/eval/eval_dataset.json`（18 条）
- 测试状态：
  - 抽取/切块契约：7 条自动化用例已实现并通过（见 `05` §3.0）
  - 监控：4 条自动化用例已实现并通过（见 `05` §3.2）
  - 测评：15 条自动化用例已实现并通过（见 `05` §3.3，含 `keyword_match_mode=all`）

## 5. 测评 baseline 与门禁

- **语料**：`docs/` 下三份 PDF；种子集 `spec/eval/eval_dataset.json`（18 条）
- **导入**：`/rag/extract` → `/rag/chunks` → `/rag/index/build` 后，`POST /rag/eval/dataset` 导入 JSON
- **baseline**（`run_id=3`）：`avg_hit=0.333`，`avg_mrr=0.333`，`avg_latency_ms=186.5`
- **主指标**：`avg_hit`；辅指标：`avg_mrr`；性能观测：`avg_latency_ms`（环比，不单独阻断）
- **迭代门禁**：`avg_hit`、`avg_mrr` 不低于 baseline
- **P0 样本**（发布前逐条 `hit=1`）：`eval-obd-port-heartbeat`、`eval-obd-fault-report-id`、`eval-emission-scope`、`eval-heavy-diesel-obd-terminal`、`eval-heavy-diesel-data-rate`
- **标注要点**：用语料内唯一锚点短语；多词共现设 `keyword_match_mode=all`

## 6. 迭代记录

- 2026-07-22（chunk 章节栈 P0 修复）：
  - 标题编号启发优先于扁平 `text_level`；无编号标题作文档根
  - 表前 title：先 flush 再入栈，`section_title` 与 `chunk_text` 前缀一致
  - 本地 PDF `category` 统一为 `pdf`；spec `09`/`02`/`08`/`06`/`05` 与实现对齐整理
- 2026-07-22（chunk metadata 落地）：
  - 抽取：`blocks` 落盘 `page_idx` / `bbox` / `text_level`（`08` 映射表已对齐）
  - 切块：按 `09` §3.6 写入企业级 metadata（页码、章节路径、长度、链表、文档属性、表列数等）
- 2026-07-21（chunk metadata 企业级约定）：
  - `09` §3.6：对齐推荐命名；保留 `chunk_kind`；补齐 `page_end`/`char_count`/`create_time`/index 链表/`table_cols`
  - `02` / `08`：blocks 溯源字段；文档级版本/权限
  - （历史）当时代码未 enrichment；现已落地，见上条
- 2026-07-20（抽取推倒重做 spec v0.7）：
  - 引擎：Unstructured → MinerU（本地）
  - 清洗：半截重复 / 垃圾碎片 / 乱码行 / NFKC；表格质量门禁，乱码表禁止入库
  - blocks 保留 `title` / `paragraph` / `list_item` / `table`（表为 HTML）
  - **chunks 内表格改为 Markdown**（HTML→MD 在切块层完成）
  - 同步 `08`/`01`/`02`/`03`/`09`/`05`/`06` 与主文档；**抽取与表 MD 切块代码待开发**
- 2026-07-20（测试 Mock 边界收紧）：
  - pytest 强制 conda `rag-demo`；仅 mock Embedding HTTP
  - 真实抽取 / ChunkPipeline / MySQL（独立库 `rag_demo_test`）
  - 去掉 InMemory Store 与 pypdf 伪抽取
- 2026-07-20（文档切块重设计 v0.6）：
  - 决策：1C（优先 `blocks`，回退 `full_text`）+ 2B（表格按行组切，chunk 携带 caption/thead）
  - 新增 `09_document_chunking.md`；同步 `01`/`02`/`03`/`04`/`08` 与主文档版本
  - 代码：`app/chunk/` 结构感知切块模块，接入 `rag_service.chunk_documents`
- 2026-07-19（测试 spec 同步）：
  - 更新 `05_test_plan_and_cases.md`：补充抽取契约用例、切块 `doc_ids`、契约/实现层边界；执行结果更新为 37 条（36 通过 / 1 xfail）
  - 同步本页当前状态：抽取/切块代码已落地，差距改为「实现层自动化未补」
- 2026-07-19（抽取引擎调整）：
  - 抽取加载改为原生 `unstructured.partition_pdf`，移除 LlamaIndex `UnstructuredReader` 依赖（`llama-index-readers-file`）
  - `extract_version` 更新为 `unstructured-v1`；依赖固定 `unstructured==0.18.32` + `unstructured-inference` 1.5–1.6
  - 同步更新 `08`/`03`/`02`/`requirements.txt` 与操作手册；代码已落地
- 2026-07-17（文档抽取 spec v0.5）：
  - 新增 `08_document_extraction.md`：Unstructured 抽取、TextCleaner 清洗、表格 HTML、续表合并
  - 流程拆为三阶段：抽取（`rag_documents`）→ 切块（`full_text`）→ 索引（`rag_chunks`）
  - 同步更新 `01`/`02`/`03`/`04` API 与数据模型；切块逻辑 spec 明确保持不变
  - （历史记录）当时代码尚未实现；现已落地，见上条
- 2026-07-16（标注收紧）：
  - 种子集改用语料内唯一锚点短语，减少 OR 关键词误命中
  - 新增 `keyword_match_mode`（`any`/`all`），支持多词共现约束
  - 已有库需执行：`ALTER TABLE rag_eval_dataset ADD COLUMN keyword_match_mode ...`（本机已执行）
  - 首轮 baseline：`run_id=3`，`avg_hit=0.333`，`avg_mrr=0.333`，`avg_latency_ms=186.5`
- 2026-07-15（测评标准补充）：
  - 补充 `07` §4.6–§4.8：第一层检索测评标准、种子集引用、标注规范、流程层验收门槛
  - 新增 `05` §3.3：业务测评集离线验收（与 TDD §3.2 互补）
  - 新增种子集 `spec/eval/eval_dataset.json`（18 条，收紧关键词锚点 + `keyword_match_mode`）
  - eval baseline：`run_id=3`，`avg_hit=0.333`，`avg_mrr=0.333`，`avg_latency_ms=186.5`（18 条种子集，标注收紧后；旧版宽松标注 `run_id=1` 为 `avg_hit=1.0`）
- 2026-07-15：
  - 监控与测评能力完成代码实现，spec 同步更新为已实现状态
  - 监控：`rag_query_logs` 写入与 `GET /rag/metrics` 聚合已落地
  - 测评：评测集管理、`POST /rag/eval/run` 执行与 `GET /rag/eval/runs` 历史查询已落地
  - 监控与测评自动化测试全部落地：监控 4 条 + 测评 13 条（`pytest tests/ -q`，32 通过 / 1 xfail）
- 2026-07-13：
  - 明确 MySQL 只存 chunk 与 metadata，不存原始文档
  - 明确切分入库与索引构建必须拆分为两个阶段
  - spec 重构为主文档 + 子文档结构，支持渐进式披露
  - 新增监控与测评能力设计（子文档 `07`），同步更新接口、数据模型、流程、非功能与测试计划
