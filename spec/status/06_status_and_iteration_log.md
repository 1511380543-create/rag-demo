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
- **TODO — 构建高质量测评集第二轮（未完成清单）**（权威明细见 `07` §3.4.2「仍待完成」表）
  - 已完成：必加 4 份语料 PDF + 生成脚本 + 手册第二轮入库 curl
  - **未完成**：
    1. L1 金标标注（P0）+ 稳定证据键；另建快照表、必要时手动打版（`07` §3.2.2，建表 DDL 已入 schema，接口未实现）
    2. 长文压测题（`pdf-emission-long`）
    3. 结构多样性题（`pdf-transport-xch`）
    4. 负样本题
    5. 多跳 / 组合证据题
    6. 层级与效力题（指导意见 vs 2026 细则）
    7. 同实体跨文档条件题
    8. 权限/类目 filters（可选）
    9. 种子扩写 + 第二轮 baseline 收口（不可与 `run_id=8` 混比）
- **测评标注缺口**：现行业务种子仍为 L0 关键词，`avg_recall` 不可用

## 4. 监控与测评（已实现）

- 设计状态：以 `spec/architecture/07_observability_and_eval.md` 为准（含 §3.4 两轮测评集建设方向）
- 监控（已实现）：
  - 接口：`GET /rag/metrics`
  - 数据表：`rag_query_logs`
  - 能力：`/rag/query` 请求内同步埋点、失败查询同样写库、监控写库异常不影响查询响应
- 测评（已实现）：
  - 接口：`POST /rag/eval/dataset`、`GET /rag/eval/dataset`、`POST /rag/eval/run`、`GET /rag/eval/runs`
  - 数据表：`rag_eval_dataset`、`rag_eval_runs`、`rag_eval_run_items`
  - 能力：评测集 upsert、离线批量检索测评、历史轮次查看
  - 种子集：`spec/eval/eval_dataset.json`（**构建高质量测评集第一轮已完成**：同域干扰 + 异域噪声；50 条 / 十份 PDF；详见 `07` §3.4.1）
- 测试状态：
  - 抽取/切块契约：7 条自动化用例已实现并通过（见 `05` §3.0）
  - 监控：4 条自动化用例已实现并通过（见 `05` §3.2）
  - 测评：15 条自动化用例已实现并通过（见 `05` §3.3，含 `keyword_match_mode=all`）

## 5. 测评 baseline 与门禁

### 5.1 构建高质量测评集第一轮（已完成）

> 设计权威说明见 `07` §3.4.1。本节只保留门禁数值与验收要点。

#### 测评方向

- **同域干扰**：近义/近场景文档挤占 top_k，检验是否串文档
- **异域噪声**：无关制度文档，检验是否污染召回窗

#### 本轮优化摘要

| 项 | 内容 |
|---|---|
| 语料 / 题量 | 3 份 18 题 → **10 份 50 题** |
| 窗口 | 样本统一 **`top_k=10`** |
| 回显 | 修复 runs.`top_k` 误记为 3 |
| 锚点 | 纠正「题其实召回对了、却因关键词与 chunk 字不完全一致被判未命中」（如空格、全角括号） |
| 切块（同期） | 章节软上限、续块带标题、软边界硬切 |
| 配套 | 生成脚本、操作手册、spec 同步 |

#### 门禁数值

- **正式 baseline**：`run_id=8`（用户重跑；与 `run_id=7` 指标一致）
  - `avg_hit=0.98`，`avg_mrr=0.910`，`avg_latency_ms=187.1`，`top_k=10`
- **历史对照**（扩容前 18 条，`run_id=3`）：`avg_hit=0.333`，`avg_mrr=0.333`（不可与现口径直接对比）
- **主指标** `avg_hit`；辅指标 `avg_mrr`；延迟环比不单独阻断
- **迭代门禁**：不低于 `run_id=8`
- **P0**（须 `hit=1`）：`eval-obd-port-heartbeat`、`eval-obd-fault-report-id`、`eval-emission-scope`、`eval-heavy-diesel-obd-terminal`、`eval-heavy-diesel-data-rate`、`eval-guosi-subsidy-heavy`、`eval-nev-heartbeat`、`eval-danger-scrap-age`（`run_id=8` 已全中）
- **已知未命中（非 P0）**：`eval-obd-data-encoding`
- **标注口径**：L0 关键词；须与 chunk **逐字一致**；非企业金标（L1 属第二轮）

### 5.2 构建高质量测评集第二轮（进行中 · 出题未完）

- **已完成**：必加 4 份语料（长文 / 报表结构 / 原则 / 2026 细则），见 `07` §3.4.2 语料表
- **未完成（TODO）**：与 `07` §3.4.2「仍待完成」表一致——L1 金标、各类出题（长文/结构/负样本/多跳/效力/同实体）、可选 filters、种子与 **第二轮 baseline** 收口
- **当前仍沿用第一轮门禁**：`run_id=8`（§5.1）；第二轮未收口前不得宣称第二轮完成
- **完成定义**：`07` 待办表清空 + 本节写入第二轮 baseline + §3 移除对应 TODO

## 6. 迭代记录

- 2026-07-23（测评切块冻结约定）：
  - 拍板：另建物理表 `rag_eval_chunk_freezes` / `rag_eval_chunk_snapshot_items`，**必要时手动打一版**；不用 VIEW
  - 主路径仍为稳定证据键映射当期 chunks；快照用于门禁可复现（`07` §3.2.2；DDL 已写入 `mysql_schema.sql`，代码待第二轮落地）
- 2026-07-23（**构建高质量测评集第二轮** · 必加语料）：
  - 新增 4 份 PDF：长文手册（约 10 页）、运政交换报表规范（大表/续表/嵌套列表）、淘汰指导意见、2026 修订细则
  - 脚本 `scripts/generate_eval_round2_pdfs.py`；操作手册补充第二轮 extract/chunks curl
  - 出题 / L1 金标 / 新 baseline 仍待完成（`07` §3.4.2）
- 2026-07-23（**构建高质量测评集第一轮** · 完成）：
  - **方向**：同域干扰 + 异域噪声
  - **优化**：语料 10 份 / 50 题；`top_k=10`；runs.top_k 回显修复；校正测评关键词与 chunk 不一致导致的误判未命中（空格/全角括号等）；同期章节软上限等切块增强
  - **baseline**：`run_id=8`（`avg_hit=0.98`，`avg_mrr=0.910`，`top_k=10`）；P0 全中；仅余 `eval-obd-data-encoding`
  - 设计写入 `07` §3.4.1；**第二轮**仍为 TODO（`07` §3.4.2 / `06` §5.2）
  - 过程 run：`run_id=5`（修复前 0.94）、`run_id=6`（无效）、`run_id=7`（与 8 同指标）可忽略作正式门禁
- 2026-07-23（章节软上限）：
  - 有标题同节总长 ≤ `section_soft_max`（默认 1000）整节一块，允许超过 `chunk_size`
  - 超过软上限再切时，**每一块** `chunk_text` 均带标题前缀，避免续块检索偏弱
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
- 2026-07-17（文档抽取与文本切块解耦 / spec v0.5）：
  - 将文档抽取与文本切块解耦：抽取产出独立落 `rag_documents`，切块再消费抽取结果
  - 新增 `08_document_extraction.md`：Unstructured 抽取、TextCleaner 清洗、表格 HTML、续表合并
  - 流程拆为三阶段：抽取（`rag_documents`）→ 切块（`full_text`）→ 索引（`rag_chunks`）
  - 同步更新 `01`/`02`/`03`/`04`；切块逻辑 spec 明确保持不变
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
- 2026-07-14（spec v0.4 瘦身）：
  - 删减当时不落地的规划内容（阈值过滤、分数降级等后置能力）
  - 监控与测评范围收敛为「本轮可实现」；差距项 `rag_retrieval_empty_reg_001` 明确留待后续
- 2026-07-13（监控与测评设计 v0.4）：
  - 新增子文档 `07_observability_and_eval.md`
  - 同步更新接口、数据模型、流程、非功能与测试计划（监控/测评接口与表设计）
- 2026-07-13（MySQL 落地 + 回归）：
  - 代码落地：`/rag/chunks`（切分入库）与 `/rag/index/build`（读库建索引）拆分
  - MySQL `rag_chunks` 持久化；服务重启后需重新 `index/build`（内存向量索引）
  - 回归测试与契约对齐；接口命名与目标态一致
- 2026-07-13（spec v0.3 重构）：
  - 明确 MySQL 只存 chunk 与 metadata，不存原始文档
  - 明确切分入库与索引构建必须拆分为两个阶段
  - spec 重构为主文档 + 子文档结构（渐进式披露）：`01`–`06` 拆出
- 2026-07-12（首版闭环 + 测试）：
  - spec 补充 Embedding：`API_KEY_ALI` + `text-embedding-v4`（阿里云百炼）
  - 添加三份 PDF 语料；新增本地调试操作手册
  - 首版代码跑通：FastAPI `/rag/index`、`/rag/query`、`/rag/health`
  - LlamaIndex 切分 + 内存向量索引 + Qwen Embedding 召回闭环（当时切分与建索引尚未拆分）
  - spec v0.2 同步现状（入库改为本地 `file_path`）并完善测试用例
  - 自动化测试落地并通过，修复相关代码问题
- 2026-07-11（项目启动 / spec v0.1）：
  - 仓库初始化（`.gitignore` / `LICENSE` / `README`）
  - 首版规格：本地 RAG 检索服务（PDF 入库、向量 Top-K 召回）
  - 技术栈约定：Python + LlamaIndex + FastAPI；接口草案 `/rag/index`、`/rag/query`、`/rag/health`
  - 明确非目标：多租户/鉴权、rerank、在线热更新、前端、答案生成
