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
- 监控与测评能力当前仅完成 spec 设计，代码尚未实现

## 4. 监控与测评（设计完成，待实现）

- 设计状态：已完成 spec 设计，范围与后续设想以 `spec/architecture/07_observability_and_eval.md` §5、§6 为准
- 监控：新增 `GET /rag/metrics` 与 `rag_query_logs` 表
- 测评：新增 `/rag/eval/dataset`、`/rag/eval/run`、`/rag/eval/runs` 接口与 `rag_eval_dataset`、`rag_eval_runs`、`rag_eval_run_items` 表
- 实现状态：待实现（本轮仅更新 spec，待提交 git 云端后再进入代码实现）

## 5. 迭代记录

- 2026-07-13：
  - 明确 MySQL 只存 chunk 与 metadata，不存原始文档
  - 明确切分入库与索引构建必须拆分为两个阶段
  - spec 重构为主文档 + 子文档结构，支持渐进式披露
  - 新增监控与测评能力设计（子文档 `07`），同步更新接口、数据模型、流程、非功能与测试计划
