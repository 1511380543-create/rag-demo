# 非功能与边界约束

> 本文档定义服务运行边界、输入输出约束与非目标范围。  
> 适用场景：实现校验、代码评审、回归验收。

## 1. 输入与参数边界

- `query` 去除首尾空白后不能为空
- `top_k` 必须为正整数，且范围 `1-20`
- `file_path` 仅支持本地可读取 `.pdf` 文件（仅 `/rag/extract` 使用）
- `/rag/chunks` 只接受 `doc_ids`，不得传入 `file_path`
- `doc_id` 去空白后长度必须在 `1-128`
- `window_minutes` 若传入必须为正整数
- 评测 `case_id` 去空白后长度必须在 `1-128`
- 评测样本 `relevant_chunk_ids`、`expected_keywords`、`evidence_keys` 至少提供其一

## 2. 输出与结果约束

- 返回 `contexts` 的数量不超过 `top_k`
- 召回为空时返回空数组 `contexts=[]`
- `chunk_id` 对应 `rag_chunks.id` 的字符串值
- 相似度低于 `min_score`（默认 `0.5`，环境变量 `RAG_MIN_SCORE`）的候选不进入 `contexts`；若无一达标则空召回
- 监控聚合指标中的比率字段范围为 `0-1`
- 评测指标 `hit/recall/mrr` 范围为 `0-1`（本轮不启用 `nDCG`）

## 3. 数据一致性约束

- 同一 `doc_id` 重复抽取必须覆盖 `rag_documents` 旧记录
- 同一 `doc_id` 重复切块必须覆盖 `rag_chunks` 旧数据
- `doc_id + chunk_index` 必须唯一
- 索引构建数据源固定为 `rag_chunks`，不直接读取本地 PDF
- 切块数据源优先 `rag_documents.blocks`，回退 `full_text`，不直接读取本地 PDF

## 4. 稳定性约束

- 缺少 `API_KEY_ALI` 时，服务启动应失败并给出明确提示
- 构建索引前若 MySQL 中无可用 chunk，应阻止构建并返回业务错误
- 未构建索引时，查询接口应返回 `INDEX_NOT_READY`
- 监控写库异常不得影响 `/rag/query` 的正常响应
- 评测集为空时，`/rag/eval/run` 应返回 `EVAL_DATASET_EMPTY`
- 未构建索引时，`/rag/eval/run` 应返回 `INDEX_NOT_READY`

## 5. 监控与测评非功能约束

- 检索对 `score` 应用 `min_score`（默认 `0.5`）过滤；监控仍记录 `top_score`/`min_score_value`/`avg_score`（空召回时可回填阈值前最高分便于诊断）
- 监控采用请求内同步写库，不引入异步队列与降级逻辑
- 监控埋点仅挂在 `/rag/query`；`/rag/eval/run` 不写入 `rag_query_logs`
- 评测为离线主动触发，不在查询链路中自动执行
- 监控与测评均不修改现有四个核心接口的既有成功语义（空召回仍为 `200` + `contexts=[]`）
- 范围外能力见 `07` §4

## 6. 非目标范围

- 暂不支持多租户与鉴权
- 暂不支持复杂重排（rerank）
- 暂不支持在线增量热更新索引
- 暂不做前端页面
- 暂不支持扫描件 OCR 表格抽取
