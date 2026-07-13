# 测试计划与用例清单

> 本文档沉淀 RAG 服务测试策略、覆盖目标与回归用例。  
> 适用场景：测试设计、发布前验收、缺陷回归。

## 1. 测试分层

- 单元测试：切分、参数校验、召回结果格式化逻辑
- 集成测试：切分入库 -> 索引构建 -> 查询召回链路
- 回归测试：固定问答样例集合，迭代后必须全通过

## 2. 覆盖目标

- 接口覆盖：`/rag/chunks`、`/rag/index/build`、`/rag/query`、`/rag/health`
- 规则覆盖：空输入、非法 `top_k`、索引未初始化、召回为空
- 结果覆盖：召回结构完整、上下文数量与质量符合约束

## 3. 测试用例清单

> 覆盖结论（当前代码）：测试用例维度覆盖完整（接口、边界、回归均有）。  
> 最近一次执行结果（2026-07-12）：共 12 条，`通过 11`，`预期失败 1`（已知差距）。

| case_id | 类型 | 场景 | 输入 | 期望 | 执行状态 | 备注 |
|---|---|---|---|---|---|---|
| `rag_index_ok_001` | integration | 正常入库 2 个本地 PDF | `documents=[{doc_id,file_path}, ...]` | `200`；`indexed_count=2`；`chunk_count>0` | 已执行-通过 | 返回 `200`，`indexed_count=2`，`chunk_count=26` |
| `rag_index_fail_empty_001` | integration | 空文档数组入库 | `documents=[]` | `422` | 已执行-通过 | 返回 `422`，与预期一致 |
| `rag_index_fail_non_pdf_001` | integration | 非 PDF 路径入库 | `file_path="docs/a.txt"` | `422` | 已执行-通过 | 返回 `422`，与预期一致 |
| `rag_index_fail_file_not_found_001` | integration | 本地文件不存在 | `file_path="docs/not_exist.pdf"` | `422` | 已执行-通过 | 返回 `422`，与预期一致 |
| `rag_query_fail_empty_001` | integration | 空查询 | `query=""` | `422` | 已执行-通过 | 返回 `422`，与预期一致 |
| `rag_query_fail_no_index_001` | integration | 未建索引直接查询 | `query="什么是RAG"` | `400` | 已执行-通过 | 返回 `400`，错误码 `INDEX_NOT_READY` |
| `rag_query_ok_001` | integration | 正常查询并返回证据 | `query="..." , top_k=3` | `200`；`contexts` 长度 `<=3` | 已执行-通过 | 返回 `200`，`contexts` 数量不超过 `3` |
| `rag_query_ok_topk_001` | integration | 自定义 top_k 生效 | `query="..." , top_k=5` | `200`；`contexts` 长度 `<=5` | 已执行-通过 | 返回 `200`，`contexts` 数量不超过 `5` |
| `rag_query_fail_topk_001` | integration | 非法 top_k | `top_k=0` 或负数 | `422` | 已执行-通过 | 返回 `422`，与预期一致 |
| `rag_health_ok_001` | integration | 健康检查 | `GET /rag/health` | `200`；`status=ok` | 已执行-通过 | 返回 `200`，`status=ok` |
| `rag_retrieval_reg_001` | regression | 关键问答命中验证 | 固定 query + 固定语料 | 命中期望证据片段（关键词命中） | 已执行-通过 | 返回 `200`，召回文本命中 `11009` 与 `30s/30秒` 关键线索 |
| `rag_retrieval_empty_reg_001` | regression | 低相关查询返回空召回 | 固定低相关 query + 固定语料 | `contexts=[]` | 已执行-预期失败 | 实际返回非空 `contexts`，当前实现缺少低相关阈值过滤（已在测试中 xfail 标记） |

## 4. 测试沉淀规则

- 每新增一个功能点，至少新增 1 条成功用例 + 1 条失败用例
- 每修复一个缺陷，必须新增对应回归用例
- 回归用例按 `case_id` 长期保留，不允许随意删除
- 任何发布前，回归集必须全量通过

## 5. 变更同步要求

- 接口变更后，必须同步更新本页覆盖目标与用例清单
- 流程变更后，必须新增阶段间联动测试用例
