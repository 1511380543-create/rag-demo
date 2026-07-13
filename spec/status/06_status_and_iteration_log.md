# 状态与迭代记录

> 本文档记录当前实现状态、已知差距与迭代轨迹。  
> 适用场景：版本评估、排期沟通、上线前核对。

## 1. 当前状态

- 核心接口已完成实现：`/rag/index`、`/rag/query`、`/rag/health`
- 入库模式已实现：通过本地 `file_path` 读取 PDF 后构建索引
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

- 当前实现接口与目标接口命名不一致（`/rag/index` vs `/rag/chunks` + `/rag/index/build`）
- 当前实现流程未完全拆分（切分与索引构建尚未彻底解耦）
- 当前实现尚未完成 MySQL chunk 持久化主链路

## 4. 迭代记录

- 2026-07-13：
  - 明确 MySQL 只存 chunk 与 metadata，不存原始文档
  - 明确切分入库与索引构建必须拆分为两个阶段
  - spec 重构为主文档 + 子文档结构，支持渐进式披露
