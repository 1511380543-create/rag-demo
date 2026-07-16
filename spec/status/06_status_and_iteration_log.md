# 状态与迭代记录

> 本文档记录当前实现状态、已知差距与迭代轨迹。  
> 适用场景：版本评估、排期沟通、上线前核对。

## 1. 当前状态

- 核心接口已完成实现：`/rag/chunks`、`/rag/index/build`、`/rag/query`、`/rag/health`
- 入库模式已实现：通过本地 `file_path` 读取 PDF，切分后写入 MySQL `rag_chunks`
- 索引构建已实现：从 MySQL 读取 `chunks/metadata` 构建向量索引
- Embedding 模型已实现：`text-embedding-v4`（阿里云百炼兼容 OpenAI 接口）

## 2. 目标状态（spec 目标）

- 目标接口：`/rag/chunks`、`/rag/index/build`、`/rag/query`、`/rag/health`
- 目标流程：
  - 阶段一：本地读取与切分，写入 MySQL `rag_chunks`
  - 阶段二：从 MySQL 读取 `chunks/metadata` 构建向量索引
- 目标存储：
  - MySQL 只存 `chunks/metadata`
  - 原始文档不入 MySQL

## 3. 已知差距

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
  - 种子集：`spec/eval/eval_dataset.json`（18 条；标准见 `07` §4）
  - baseline：`run_id=3`，`avg_hit=0.333`，`avg_mrr=0.333`（18 条种子集，标注收紧后）
- 测试状态：
  - 监控：4 条自动化用例已实现并通过（见 `05` §3.1）
  - 测评：13 条自动化用例已实现并通过（见 `05` §3.2）

## 5. 迭代记录

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
