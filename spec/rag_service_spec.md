# RAG 服务规格（主文档）

> 本文档是 RAG 项目的规格入口，采用“主文档 + 子文档”的渐进式披露结构。  
> 阅读顺序建议：先看本页，再按角色进入对应子文档。

## 1. 文档定位

- 目标：统一 RAG 能力边界，降低实现与测试阶段的理解偏差
- 结构：主文档只保留导航与关键约束，细节放到子文档
- 约束：先更新 spec，再进行代码开发与测试沉淀

## 2. 项目目标与范围（摘要）

### 2.1 核心目标

- 文档抽取入库：从本地 PDF 抽取正文与表格（blocks 内表格为 HTML），写入 MySQL `rag_documents`
- 文档切块入库：文本块先拼再切；表格 HTML→Markdown 行组切分后写入 `rag_chunks`
- 索引构建：从 MySQL 读取 `chunks/metadata` 构建向量索引
- 查询检索：基于向量索引进行 `Top-K` 召回
- 监控观测：采集查询链路的延迟、召回与分数指标并聚合暴露
- 检索测评：基于评测集离线量化检索质量，支持迭代前后对比

### 2.2 本阶段范围

- 文档类型：`pdf`
- 抽取引擎：**MinerU**（本地解析 → 结构化 JSON/内容列表 → 内部 blocks）；企业级清洗与表格质量门禁见 `08`；LlamaIndex 仅用于切块与向量索引
- 数据存储：MySQL 存抽取结果（`rag_documents`）与 chunk（`rag_chunks`），不存原始 PDF
- 索引构建数据源：固定为 MySQL `rag_chunks`

### 2.3 非目标范围

- 暂不支持多租户与鉴权
- 暂不支持复杂重排（rerank）
- 暂不支持在线增量热更新索引
- 暂不做前端页面与答案生成
- 监控暂不引入异步采集与外部可观测系统（Prometheus/OpenTelemetry 等）
- 测评暂不做自动化定时评测与答案质量（生成层）评估

## 3. 阅读路径（渐进式披露）

- 产品/需求：先看 `spec/architecture/03_pipeline_design.md`，再看 `spec/contracts/01_api_contract.md`
- 后端开发：先看 `spec/architecture/02_data_model_mysql.md`，再看 `spec/contracts/01_api_contract.md`；切块细节看 `09_document_chunking.md`
- 监控与测评：先看 `spec/architecture/07_observability_and_eval.md`，再看 `spec/contracts/01_api_contract.md`
- 测试与验收：先看 `spec/testing/05_test_plan_and_cases.md`
- 迭代排期：看 `spec/status/06_status_and_iteration_log.md`

## 4. 子文档索引

- `spec/contracts/01_api_contract.md`：接口契约、请求响应、错误码、字段校验
- `spec/architecture/02_data_model_mysql.md`：MySQL 配置、表结构、索引与数据覆盖规则
- `spec/architecture/03_pipeline_design.md`：抽取、切块与索引构建解耦后的流程设计
- `spec/architecture/08_document_extraction.md`：MinerU 抽取、企业级清洗、表格 HTML 与质量门禁（权威文档）
- `spec/architecture/09_document_chunking.md`：文本块先拼再切；表格 chunk 为 Markdown 行组（权威文档）
- `spec/architecture/04_non_functional_and_boundaries.md`：关键规则、边界条件、非功能约束
- `spec/architecture/07_observability_and_eval.md`：监控与测评（权威）；两轮测评集 §3.4 已完成；设计债 §3.5
- `spec/eval/eval_dataset.json`：测评种子（约 82 条 / 十四份 PDF；第一轮 baseline `run_id=8`，第二轮 `run_id=11`，见 `06` §5）
- `spec/testing/05_test_plan_and_cases.md`：测试分层、覆盖目标、回归用例清单
- `spec/status/06_status_and_iteration_log.md`：当前状态、里程碑、已知差距与迭代记录

## 5. 全局一致性约束

- 接口与数据模型变更，必须同步更新 `01`、`02`、`03` 三份子文档
- 抽取能力变更，必须同步更新 `08` 文档，并联动 `01`、`02`、`03`
- 切块能力变更，必须同步更新 `09` 文档，并联动 `01`、`02`、`03`
- 监控与测评能力变更，必须同步更新 `07` 文档，并联动 `01`、`02`
- 测试策略与回归用例变更，必须同步更新 `05` 文档
- 版本状态与实际实现差异，必须同步更新 `06` 文档

## 6. 版本记录

- `v0.7`（2026-07-20）：抽取推倒重做——引擎改为 MinerU；保留 title/paragraph/list_item/table；企业级清洗与表格质量门禁；**chunks 内表格为 Markdown**（blocks 仍 HTML）；废弃 Unstructured；同步 `01`/`02`/`03`/`08`/`09`
- `v0.6`（2026-07-20）：新增文档切块设计（`09`）：1C 优先 `blocks` / 回退 `full_text`；2B 表格按行组切并携带 caption/thead；同步 `01`/`02`/`03`/`04`/`08`
- `v0.5`（2026-07-17）：新增文档抽取阶段设计（`08`），抽取/切块/API/数据模型同步调整；表格存 HTML，续表在抽取层合并；切块逻辑保持不变
- `v0.4`（2026-07-13）：新增监控与测评能力设计（子文档 `07`），同步更新接口、数据模型与测试计划
- `v0.3`（2026-07-13）：重构为主文档 + 子文档结构，支持渐进式披露
