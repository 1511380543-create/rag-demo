# 监控与测评设计

> 检索链路监控与离线测评规范。接口见 `01`，表结构见 `02`，baseline 见 `06`。

## 1. 目标与边界

- **监控**：观察 `/rag/query` 的延迟、召回量、分数分布
- **测评**：离线量化检索质量，支持迭代对比
- **范围**：仅检索链路；不含答案生成
- **约束**：测评复用内部检索逻辑（含 `min_score`），不经过 `/rag/query`，不写入 `rag_query_logs`

## 2. 监控

- **采集**：每次 `/rag/query` 同步写入 `rag_query_logs`（成功与失败均记录）
- **字段**：`query_text`、`top_k`、延迟拆分（`embed_ms`/`retrieve_ms`/`total_ms`）、召回数量、分数统计（`top_score`/`min_score_value`/`avg_score`）、`error_code`
- **规则**：候选 `score < min_score`（默认 `0.5`）丢弃，全部不达标则空召回；写库失败不影响查询响应
- **聚合**：`GET /rag/metrics`（可选 `window_minutes`）

## 3. 测评

### 3.1 数据与接口

| 表 | 用途 |
|---|---|
| `rag_eval_dataset` | 评测样本 |
| `rag_eval_runs` / `rag_eval_run_items` | 轮次汇总与明细 |

接口：`POST/GET /rag/eval/dataset`、`POST /rag/eval/run`、`GET /rag/eval/runs`（详见 `01`）。

### 3.2 样本约束

- `relevant_chunk_ids` 与 `expected_keywords` 至少提供其一
- `keyword_match_mode`：`any`（默认）或 `all`
- 默认仅执行 `enabled=true` 样本；传 `case_ids` 时不受 `enabled` 限制

### 3.2.1 标注质量层级（企业约定）

| 层级 | 标注方式 | 定位 | 当前状态 |
|---|---|---|---|
| **L1 金标（企业标准）** | 显式 `relevant_chunk_ids`（可多块、可跨文档） | 判定「召回了哪条证据块」；可算真实 `recall@k` / 精确 `mrr` | **种子未直接书写**（0 条显式 chunk id） |
| **L1 过渡** | `evidence_keys`（`doc_id` + 锚点/`content_hash`） | 测评前映射到当期 `rag_chunks.id`，再走 chunk 判分与 `recall@k` | **两轮种子主过渡路径**（约 77/82 条） |
| **L0 启发式** | `expected_keywords`（+ 可选 `all`） | 快速冒烟；子串命中 ≠ 证据块正确 | **两轮种子仍普遍保留**（82/82 条；可与证据键并存） |

企业发布门禁应以 **块级标注为主**（显式 `relevant_chunk_ids`，或等价的 `evidence_keys` 映射结果）；关键词仅作辅助。  
本版双标注判分仍为 OR（见 §3.3）；未收紧为「chunk 必须命中」。  
L0 固有缺陷：易被同域近义句误命中；**仅有关键词、无证据键/chunk 标注时** `avg_recall` 恒为 0；切块改写后关键词仍可能「碰巧命中」造成虚高。有 `evidence_keys` 时 `recall@k` 可算（如第二轮 baseline `run_id=11` 的 `avg_recall≈0.892`），但仍受锚点匹配过脆等限制（见 §3.5）。  
L1 与切块迭代冲突的解法见 **§3.2.2**（已拍板）：稳定证据键（主）+ **另建物理快照表、必要时手动打版**（辅）。**禁止**用 MySQL VIEW 充当冻结。

### 3.2.2 切块冻结与金标对齐（已拍板）

**问题**：业务侧会持续改切块以提升召回；测评金标若只存现行 `rag_chunks.id`，一重切即失效。

**决策**：

| 能力 | 方案 | 说明 |
|---|---|---|
| 跨重切对齐（主） | **稳定证据键** | 金标存 `doc_id` + 锚点句/`content_hash`（可选 `section_path`）；测评前映射到**当期** `rag_chunks.id` |
| 可复现门禁（辅） | **另建物理快照表** | 把某次 `rag_chunks` **拷贝**进快照表；不是 VIEW |
| 打版节奏 | **必要时手动打一版** | 切块策略实质变更、发版对比、标定新 baseline 时打版；不强制周更/月更 |
| 明确不做 | 业务表堆多版本 / VIEW 冻结 | `rag_chunks` 保持「仅现行生效」；VIEW 会随重切变，无法钉死 |

**表设计（见 `02` / `mysql_schema.sql`）**：

- `rag_eval_chunk_freezes`：一版元数据（`freeze_id`/`freeze_label`/`note`/`created_at`/可选 pipeline 版本）
- `rag_eval_chunk_snapshot_items`：该版下的 chunk 拷贝（`freeze_id`,`doc_id`,`chunk_index`,`chunk_text`,`content_hash`,`source_chunk_id`）

**使用约定**：

- **当前阶段（demo / 日常迭代）**：`/rag/index/build` **只从现行 `rag_chunks` 构建一套索引**即可；冻结表是某一刻的文本参照（金标对齐、可复现门禁），**不要求**为此常驻第二套索引
- 日常迭代测评：可不绑 freeze，走证据键 → 当期 chunks → 现行索引检索
- 发布门禁 / 切块前后对比：`rag_eval_runs` 记录所用 `freeze_id`（字段待加）；若要对「当时那版切块」做检索指标，再**按需**从快照明细临时 build/加载冻结索引（非默认路径）
- 快照只增不改；作废用 `note`/停用标记，不覆盖历史版

**落地状态（TODO-0 已完成）**：

- DDL + 表：`rag_eval_chunk_freezes` / `rag_eval_chunk_snapshot_items`；`rag_eval_dataset.evidence_keys`
- API：`POST /rag/eval/chunk-freeze`、`GET /rag/eval/chunk-freezes`、`GET /rag/eval/chunk-freezes/{id}`
- 测评：`evidence_keys` → 当期 `rag_chunks.id`，并与 `relevant_chunk_ids` 合并后算指标
- 种子：`eval_dataset.json` 已带过渡 `evidence_keys`（锚点多与关键词对齐）；正式完整证据句 / 显式 `relevant_chunk_ids` 仍可后续加强（本版匹配过脆见 §3.5）
- 现行索引仍只从 `rag_chunks` 构建

### 3.3 命中与指标

- **chunk 标注**：召回 `chunk_id` 命中即相关（含由 `evidence_keys` 映射得到的 id）
- **关键词标注**：在召回文本中子串匹配（`any`/`all`）
- **证据键**：测评前映射到当期 chunk_id，再并入 chunk 标注路径
- **双标注并存**：`hit@k`/`mrr@k` 取 OR；`recall@k` 仅基于 chunk 标注（含证据键映射结果）
- **负样本**：`expect_hit=false` 时，top_k 内未出现标注证据则 `hit=1`，出现则 `hit=0`；`recall`/`mrr` 记 0
- **样本级 filters**：与 `/rag/query.filters` 同语义，测评检索时生效

| 指标 | 含义 |
|---|---|
| `hit@k` | top_k 内至少命中 1 条 |
| `mrr@k` | 首个相关结果的倒数排名 |
| `recall@k` | 命中相关 chunk 数 / 标注总数（仅 chunk 标注） |
| `latency_ms` | 单条检索耗时 |

`top_k` 优先级：请求级 > 样本级 > 默认 `3`。

`rag_eval_runs.top_k` / 响应 `top_k` 为**本轮实际检索窗口回显**：有请求级覆盖记请求值；否则记各样本实际 `top_k` 的众数（并列取较大值）。历史 bug：未传请求级时曾误记为 `3`，与真实检索无关。

**第一轮约定**：十份语料下样本级统一 **`top_k=10`**（见 `eval_dataset.json`）。`top_k=5` 窗口过窄时，同域干扰题的 hit 易因排名抖动虚低/虚高，不适合作为本轮主对比口径；若需压测「窄窗排序」，可在第二轮另设对照 run（请求级覆盖），勿与主 baseline 混用。

### 3.4 高质量测评集建设（两轮）

名称固定，避免与日常切块/抽取迭代混淆：

| 轮次 | 名称 | 状态 | 主攻方向 |
|---|---|---|---|
| 第一轮 | **构建高质量测评集第一轮** | **已完成**（baseline `run_id=8`） | **同域干扰**、**异域噪声** |
| 第二轮 | **构建高质量测评集第二轮** | **已完成**（baseline `run_id=11`） | 见 §3.4.2 |

权威验收与数值门禁见 `06` §5；种子见 `spec/eval/eval_dataset.json`。

#### 3.4.1 构建高质量测评集第一轮（已完成）

##### 测评方向（本轮重点）

| 方向 | 目标 | 语料手段 |
|---|---|---|
| **同域干扰** | 在 top_k 窗口内制造「术语近、答案不同」的竞争，检验排序是否串文档 | 国四补贴、汽油车年检、新能源监控、危货监控、健康档案等与主干同场景/同术语文档 |
| **异域噪声** | 检验无关制度块是否污染召回窗 | 信息安全手册、园区门禁规范 |

典型易混对照（跨文档）：

- 国三危货年限 vs 危货监控规定年限；国三补贴 vs 国四补贴
- 809 心跳/端口/缓存 vs 新能源监控心跳/端口/缓存
- 免年检（柴油）vs 汽油车年检；809「GB2312」vs 健康档案「UTF-8」

##### 本轮做了哪些优化

1. **语料扩容**：由 3 份 PDF / 18 题 → **10 份 PDF / 50 题**（主干 3 + 同域 5 + 异域 2）
2. **虚拟文档生成**：`scripts/generate_eval_virtual_pdfs.py`；正文「够支撑锚点题」即可，不追求手册完整篇幅
3. **召回窗口**：样本统一 **`top_k=10`**（十份语料下废弃主口径 `top_k=5`，降低命中抖动）
4. **测评回显修复**：`rag_eval_runs.top_k` 改为记录实际检索窗口（请求级或样本众数），不再在未传请求级时误记为 `3`
5. **L0 锚点校正**：关键词须与 chunk **逐字一致**（修复空格 / 全角括号导致的假阴性）
6. **切块侧增强（同期，支撑检索质量）**：章节软上限整节保留、续块带标题、硬切优先软边界（见 `09`）
7. **工程配套**：操作手册十份 extract/chunks/种子导入 curl；`05`/`06`/`rag_service_spec` 同步

##### 交付与口径

- 种子：`spec/eval/eval_dataset.json`（`iteration=构建高质量测评集第一轮`，`focus=[同域干扰,异域噪声]`）
- 标注：**L0 `expected_keywords`**（过渡态，**非企业金标**）；`avg_recall` 恒为 0
- baseline / P0 / 未命中清单：以 `06` §5.1 为准（正式 run：`run_id=8`）

#### 3.4.2 构建高质量测评集第二轮（已完成）

在第一轮语料之上覆盖长文/结构/负样本/多跳/效力/同实体/filters：

##### 语料（必加 4 份）

| doc_id | 文件 | 用途 |
|---|---|---|
| `pdf-emission-long` | `机动车排放监管综合技术手册（虚拟长文）.pdf`（约 10 页） | 长文切块压测 |
| `pdf-transport-xch` | `道路运政数据交换与报表规范（虚拟技术手册）.pdf` | 大表/续表/嵌套列表 |
| `pdf-diesel-retire-guidance` | `老旧柴油车淘汰更新指导意见（虚拟政策文档）.pdf` | 原则篇 |
| `pdf-diesel-retire-rules-2026` | `老旧柴油车淘汰更新实施细则（2026修订版）（虚拟政策文档）.pdf` | 细则/现行版（与原则冲突） |

生成脚本：`scripts/generate_eval_round2_pdfs.py`；入库 curl 见操作手册（十四份主路径）。

##### 进度

> 权威门禁：`06` §5.2。

| 状态 | 编号 | 项 | 说明 |
|---|---|---|---|
| **已完成** | 0 | **标注升级 L1 能力（P0）** | `evidence_keys` + 冻结打版 API；种子过渡证据键 |
| **已完成** | 1 | **长文切块压测题** | `pdf-emission-long` |
| **已完成** | 2 | **结构多样性题** | `pdf-transport-xch` |
| **已完成** | 3 | **负样本题** | `expect_hit=false` |
| **已完成** | 4 | **多跳 / 组合证据** | 跨 `doc_id` 的 `evidence_keys` |
| **已完成** | 5 | **层级与效力题** | 指导意见 vs 2026 细则 |
| **已完成** | 6 | **同实体跨文档条件** | 报废/免检等并读 |
| **已完成** | 7 | **权限与类目过滤** | 样本级 `filters`；policy/ops metadata |
| **已完成** | 8 | **种子/手册/baseline 收口** | 十四份 curl；baseline `run_id=11`（`06` §5.2） |

### 3.5 本版收官保留的设计债

> 只记问题，不展开方案；后续迭代再议。门禁未命中清单见 `06` §5.2。

1. **关键词 / 证据键匹配过脆**  
   判分依赖连续子串；表格 Markdown 等结构化正文中，标注短语常与「单元格 + 分隔符」形态不一致，导致已召回正确块仍判未命中（典型：`eval-xch-field-vrd019`、`eval-xch-speed-close-rate`、`eval-obd-data-encoding`）。

2. **实体主导检索**  
   问句同时带「文档壳」与「答案实体」时，稠密检索易被实体词主导，文档约束失效（典型挂壳负样本：`eval-neg-park-no-scrap-age`、`eval-neg-infosec-no-obd-port`、`eval-neg-health-no-retire-subsidy`）。低相关 `min_score` 管不到此类高分串扰。

## 4. 非目标

- `nDCG`、外部可观测框架（OpenTelemetry / Prometheus 等）
- 自动化定时评测
- 复杂重排（rerank）与动态阈值自适应（当前固定 `min_score`，可配）

## 5. 验收标准

- `/rag/query` 每次请求写入监控日志；`/rag/eval/run` 不污染监控计数
- 评测集 upsert、执行、历史查询可用
- 指标计算符合 §3.3；自动化用例见 `05`
- 离线 baseline 与发布门禁见 `06` §5：第一轮 `run_id=8`；第二轮 `run_id=11`
- 测评集建设以 `07` §3.4 为准：两轮均已完成；设计债见 §3.5
