# 文档抽取设计说明（MinerU）

> PDF 抽取能力规范（权威）。流程见 `03`；表结构见 `02`；接口见 `01`；切块见 `09`。  
> **v0.7 起**：抽取引擎由 Unstructured 切换为 **MinerU**，抽取与清洗推倒重做，目标为企业级可用质量。

## 1. 目标与边界

- 将本地 PDF 抽取为 MySQL 中间层 `rag_documents`（`blocks` + `full_text`），与切块解耦
- **引擎**：MinerU（本地解析），不使用 Unstructured / LlamaIndex Reader
- **表格**：
  - `blocks` / 中间层：MinerU 产出 **HTML**（保真，禁止自研 PDF→HTML）
  - `rag_chunks.chunk_text`：切块时转为 **Markdown**（见 `09` §3.2）
- **质量**：清洗必须消除已知脏数据（半截重复句、单符号碎片、明显乱码行、不可读表格）
- **结构**：保留标题 / 正文 / 列表项类型，不再全部打成 `paragraph`
- 切块仍只消费 `blocks`/`full_text`，不读 PDF（切块规则见 `09`）

## 2. 为什么换 MinerU

当前 Unstructured `hi_res` 在本语料上暴露的硬伤（必须在新方案中消除）：

| 问题 | 表现 |
|------|------|
| 断行残留 | 如完整句后再多一块「输，具备高可靠…」 |
| 无意义碎片 | 如单独 `°`、乱码行 |
| 表格不可读 | HTML 单元格变成拉丁乱码，表头掉成普通段落 |
| 结构类型丢失 | Title / ListItem 全写成 `paragraph` |

MinerU 为企业侧常用的 PDF→Markdown/JSON 方案：阅读序、去页眉页脚、表格转 HTML、跨页表合并、中文场景更友好。本阶段以 **MinerU 为唯一抽取引擎**。

## 3. 处理步骤（必须按此顺序）

```text
本地 PDF
  → MinerU 解析（得到按阅读序的结构化结果）
  → 映射为内部 ContentBlock[]
  → 企业级清洗链（见 §5）
  → 表格质量门禁 + 可选续表兜底合并
  → 渲染 full_text，写 rag_documents（覆盖同 doc_id）
```

1. **加载**：调用本地 MinerU（官方 CLI 或 Python API，实现二选一，行为等价）解析 PDF  
2. **映射**：MinerU 内容列表 → `ContentBlock`（见 §4）  
3. **清洗**：执行 §5 清洗链，统计丢弃数  
4. **表格**：质量门禁（§6）；MinerU 已合并的跨页表优先信任；相邻表兜底合并仅作补充  
5. **持久化**：`blocks` + `full_text` + `extract_report` + `content_hash`；`extract_version=mineru-v1`

## 4. 元素映射

### 4.1 MinerU → ContentBlock

| MinerU 语义（按官方 content 类型对齐） | `blocks[].type` | 写入字段 |
|----------------------------------------|-----------------|----------|
| 标题（title / heading） | `title` | `text` |
| 正文（text / paragraph） | `paragraph` | `text` |
| 列表项（list） | `list_item` | `text` |
| 表格（table） | `table` | `html`（MinerU 表格 HTML） |
| 其他（公式、图片说明等） | 本阶段：**丢弃**（计入 report），不进 blocks |

- 每个 block 必有递增 `order`（从 0）
- `table` 可带 `logical_table_id`（如 `tbl-000`）
- `extract_version`：固定 `mineru-v1`

### 4.2 `blocks` JSON 形状

| 字段 | title / paragraph / list_item | table |
|------|-------------------------------|-------|
| `type` | `"title"` / `"paragraph"` / `"list_item"` | `"table"` |
| `order` | int | int |
| `text` | 纯文本 | — |
| `html` | — | 表格 HTML |
| `logical_table_id` | — | 可选 |

### 4.3 与切块的约定

- 切块层把 `title`、`paragraph`、`list_item` 都当作可拼接的文本块
- `table` 的 `html` 仅作切块输入；**写入 `rag_chunks` 前必须转为 Markdown**（见 `09`）
- `full_text` 拼接时：文本用原文；表格可用 HTML 或简化占位——**检索主路径以 chunks 为准**，不以 full_text 内嵌 HTML 表作为向量化目标

## 5. 企业级清洗链（权威规则）

清洗只处理文本类 block（`title` / `paragraph` / `list_item`）。`table` 走 §6，不走文本清洗。

按顺序执行：

| 序号 | 规则 | 动作 |
|------|------|------|
| C1 | Unicode 规范化 | 对文本做 NFKC，减少「⼿/手」「⻋/车」兼容区字形分裂 |
| C2 | 空白归一 | 去掉首尾空白；压缩连续空白；**去掉汉字之间 OCR 断字空格**（如「目 的」→「目的」）；title 补章节号与正文间空格（覆盖单级/多级，如「3.通用」「1.3协议」→「3. 通用」「1.3 协议」）；空文本直接丢弃 |
| C3 | 垃圾碎片丢弃 | 丢弃：单字符/纯符号（如单独 `°`、`©`）；长度过短且无中文/无字母数字的块 |
| C4 | 乱码行丢弃 | 短文本中拉丁字母占比异常高、几乎无中日韩字符 → 丢弃（抑制 `© SK/WUER...` 类） |
| C5 | 半截重复丢弃 | 若当前块文本是**上一文本块的后缀**，或上一块以当前块结尾且当前块明显更短 → 丢弃当前块（抑制「传/输」断行残留） |
| C6 | 页眉页脚（兜底） | MinerU 已去页眉页脚；本规则仅作兜底：跨页重复的超短行丢弃 |
| C7 | 目录页（兜底） | 点线+页码密度过高的块丢弃 |
| C8 | 列表类型回标 | 若 `paragraph` 行首为 bullet/`1.`/`（1）` 等列表标记 → 改为 `list_item`；**不改 title**（避免「1. 手册总则」误标） |
| C9 | 水印/免责声明丢弃 | 丢弃源 PDF 噪声块，如「(注:文档部分内容可能由AI 生成)」 |

清洗统计写入 `extract_report`（至少：`dropped_elements`，并细分见 §7）。

**原则**：宁可少一块脏数据，也不把碎片、乱码送进切块。禁止用 mock/假文本填补。

## 6. 表格规则

### 6.1 存储（中间层）

- `blocks[].html`：HTML（可含 `<caption>` / `<thead>` / `<tbody>`）
- 来源：MinerU，不自研 PDF→HTML
- **不在抽取层把表改成 Markdown**；Markdown 转换发生在切块写入 `rag_chunks` 时（`09`）

### 6.2 质量门禁（企业硬要求）

对每个 table 的 HTML 抽纯文本后评估：

- 若表格声称有多行内容，但中日韩字符过少且拉丁乱码特征明显 → **判定不合格**
- 不合格表：**丢弃该 table block**（不入库），`table_quality_failed` +1  
- 不得把乱码表「假装成功」写入 `blocks`

若文档在 MinerU 原始结果中存在表格，但清洗后门禁后 `table_count=0` 且 `table_quality_failed>0`：抽取仍可成功（保留正文），但 report 必须体现失败表数量，便于验收打回。

### 6.3 跨页续表

- **优先**：信任 MinerU 自带跨页表合并结果  
- **兜底**：若仍出现「相邻 table、中间无文本块」，且列结构一致 / 续表信号明确，则合并为一个 HTML（逻辑同旧版续表合并），`merged_continuations` +1

## 7. `extract_report` 字段

| 字段 | 说明 |
|------|------|
| `dropped_elements` | 清洗丢弃的文本块总数 |
| `dropped_fragments` | 半截重复 + 垃圾碎片丢弃数 |
| `dropped_garbled` | 乱码行丢弃数 |
| `table_count` | 最终入库的表格块数 |
| `table_quality_failed` | 质量门禁未通过的表格数 |
| `merged_continuations` | 兜底续表合并次数 |
| `title_count` / `paragraph_count` / `list_item_count` | 最终文本类块计数 |

API `ExtractReport` 对外字段见 `01`（可先暴露核心计数，细则与库内 JSON 一致）。

## 8. 依赖与运行

- 抽取引擎：`mineru`（版本在实现时锁定，写入 `requirements.txt`）
- 运行环境：conda `rag-demo`；需按 MinerU 官方文档安装模型与系统依赖
- **移除**：`unstructured`、`unstructured-inference` 作为抽依赖（实现阶段从 `requirements.txt` 删除）
- LlamaIndex 仅用于切块与向量索引，不参与抽取
- 集成方式（实现约束）：
  - 允许：MinerU CLI 写临时目录再读 JSON；或官方 Python API  
  - 禁止：调用外部公网 SaaS 作为默认路径（本阶段默认本地）

## 9. 非目标（本阶段）

- 扫描件手写体极致优化（MinerU OCR 可用，但不单独做调参专项）
- 图片/公式进检索库（映射阶段丢弃）
- DOCX/PPTX/XLSX（本阶段仍只接 PDF 接口）
- 在线增量热更新索引
- 切块算法本身（见 `09`）

## 10. 验收标准（企业级）

对标本文 §1 问题清单，至少满足：

1. 引擎为 MinerU，`extract_version=mineru-v1`  
2. `blocks` 中存在 `title` / `paragraph` / `list_item` / `table` 区分（有标题的文档不得再「全是 paragraph」）  
3. 不再出现「完整句 + 半截后缀残留」成对入库（C5）  
4. 不再出现单独 `°` 或明显拉丁乱码短行入库（C3/C4）  
5. 不合格表格不得以乱码 HTML 入库（§6.2）  
6. 合格表格为可读中文（或源语言）HTML，可供 `09` 转 Markdown 并做行组切分  
7. 同 `doc_id` 重复抽取覆盖 `rag_documents`  
8. 切块仍不读 PDF；`/rag/extract` 请求字段保持不变  
9. 切块后表格 `chunk_text` 为 Markdown（验收见 `09` §8）

## 11. 迁移说明

- 已有 `unstructured-v1` 文档须 **重新 `/rag/extract` → `/rag/chunks` → `/rag/index/build`**  
- 旧 blocks（仅 `paragraph`/`table`）与新 schema 不兼容混用同一评测基线；重抽后重跑评测并更新 `06` baseline  
- 代码落地前：本 spec 为唯一真相；实现不得继续调用 Unstructured
