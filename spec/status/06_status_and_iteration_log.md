# 状态与迭代记录

> 本文档记录当前实现状态、已知差距与迭代轨迹。  
> 适用场景：版本评估、排期沟通、上线前核对。

## 1. 当前状态

- 核心接口已实现：`/rag/chunks`、`/rag/index/build`、`/rag/query`、`/rag/health` 及监控/测评接口
- **当前实现**：`/rag/chunks` 仍为一站式「读 PDF + 切块」（旧流程）
- **spec 目标**（v0.5，待实现）：抽取/切块分离，见 `08_document_extraction.md`

## 2. 目标状态（spec 目标 v0.5）

- 目标接口：`/rag/extract`、`/rag/chunks`、`/rag/index/build`、`/rag/query`、`/rag/health`
- 目标流程：
  - 阶段一：`SimpleDirectoryReader` + `UnstructuredReader` 抽取 → TextCleaner 清洗 → 续表合并 → `rag_documents`
  - 阶段二：读 `full_text` → 现有 `SentenceSplitter` 切块 → `rag_chunks`
  - 阶段三：从 `rag_chunks` 构建向量索引
- 目标存储：
  - `rag_documents`：抽取中间层（blocks + full_text，表格为 HTML）
  - `rag_chunks`：切块结果
  - 原始 PDF 不入 MySQL

## 3. 已知差距

- **抽取链路未实现**（spec 已定义，代码仍为 pypdf 一站式入库）
- 当前向量索引为内存态（服务重启后需重新调用 `/rag/index/build`）
- 回归用例 `rag_retrieval_empty_reg_001` 仍为已知差距（低相关阈值过滤未实现）
- 监控与测评能力已实现：监控埋点、指标聚合、评测集管理与评测执行

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
  - 监控：4 条自动化用例已实现并通过（见 `05` §3.1）
  - 测评：13 条自动化用例已实现并通过（见 `05` §3.2）

## 5. 测评 baseline 与门禁

- **语料**：`docs/` 下三份 PDF；种子集 `spec/eval/eval_dataset.json`（18 条）
- **导入**：PDF 入库 + 建索引后，`POST /rag/eval/dataset` 导入 JSON
- **baseline**（`run_id=3`）：`avg_hit=0.333`，`avg_mrr=0.333`，`avg_latency_ms=186.5`
- **主指标**：`avg_hit`；辅指标：`avg_mrr`；性能观测：`avg_latency_ms`（环比，不单独阻断）
- **迭代门禁**：`avg_hit`、`avg_mrr` 不低于 baseline
- **P0 样本**（发布前逐条 `hit=1`）：`eval-obd-port-heartbeat`、`eval-obd-fault-report-id`、`eval-emission-scope`、`eval-heavy-diesel-obd-terminal`、`eval-heavy-diesel-data-rate`
- **标注要点**：用语料内唯一锚点短语；多词共现设 `keyword_match_mode=all`

## 6. 迭代记录

- 2026-07-17（文档抽取 spec v0.5）：
  - 新增 `08_document_extraction.md`：LlamaIndex + Unstructured 抽取、TextCleaner 清洗、表格 HTML、续表合并
  - 流程拆为三阶段：抽取（`rag_documents`）→ 切块（`full_text`）→ 索引（`rag_chunks`）
  - 同步更新 `01`/`02`/`03`/`04` API 与数据模型；切块逻辑 spec 明确保持不变
  - 代码尚未实现，当前仍为旧版一站式 `/rag/chunks`
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
