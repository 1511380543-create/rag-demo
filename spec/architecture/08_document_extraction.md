# 文档抽取设计说明（MinerU）

> PDF 抽取能力规范（权威）。流程见 `03`；表结构见 `02`；接口见 `01`；切块见 `09`。  
> 本阶段以 **MinerU** 为唯一本地抽取引擎，`extract_version=mineru-v1`。

## 1. 目标与边界

- 将本地 PDF 抽取为 MySQL 中间层 `rag_documents`（`blocks` + `full_text`），与切块解耦
- **引擎**：MinerU（本地解析）；禁止默认走公网 SaaS；LlamaIndex 不参与抽取
- **表格**：
  - `blocks` / 中间层：MinerU 产出 **HTML**（保真，禁止自研 PDF→HTML）
  - `rag_chunks.chunk_text`：切块时转为 **Markdown**（见 `09` §3.2）
- **质量**：清洗消除脏数据（半截重复句、单符号碎片、明显乱码行、不可读表格、水印噪声）
- **结构**：保留 `title` / `paragraph` / `list_item` / `table`，不得全部打成 `paragraph`
- 切块只消费 `blocks`/`full_text`，不读 PDF（切块规则见 `09`）

## 2. 引擎选型要点

MinerU 满足本项目企业侧抽取诉求：

- 按阅读序输出结构化内容
- 自动去页眉页脚
- 表格转 HTML，并支持跨页表合并
- 中文场景友好，可落地为本地 CLI / Python API

本阶段不引入第二套抽取引擎。

## 3. 处理步骤（必须按此顺序）

```text
本地 PDF
  → MinerU 解析（按阅读序的结构化结果）
  → 映射为内部 ContentBlock[]
  → 企业级清洗链（见 §5）
  → 表格质量门禁 + 可选续表兜底合并
  → 渲染 full_text，写 rag_documents（覆盖同 doc_id）
```

1. **加载**：调用本地 MinerU（官方 CLI 或 Python API，二选一，行为等价）解析 PDF  
2. **映射**：MinerU 内容列表 → `ContentBlock`（见 §4）  
3. **清洗**：执行 §5 清洗链，统计丢弃数  
4. **表格**：质量门禁（§6）；优先信任 MinerU 已合并的跨页表；相邻表兜底合并仅作补充  
5. **持久化**：`blocks` + `full_text` + `extract_report` + `content_hash`；`extract_version=mineru-v1`

## 4. 元素映射

### 4.1 MinerU → ContentBlock

| MinerU 语义（按官方 content 类型对齐） | `blocks[].type` | 写入字段 |
|----------------------------------------|-----------------|----------|
| 标题（title / heading） | `title` | `text` + `page_idx` + 可选 `bbox` / `text_level` |
| 正文（text / paragraph） | `paragraph` | `text` + `page_idx` + 可选 `bbox` |
| 列表项（list） | `list_item` | `text` + `page_idx` + 可选 `bbox` |
| 表格（table） | `table` | `html` + `page_idx` + 可选 `bbox` / `logical_table_id` |
| 其他（公式、图片说明等） | 本阶段：**丢弃**（计入 report），不进 blocks |

- 每个 block 必有递增 `order`（从 0）
- `table` 可带 `logical_table_id`（如 `tbl-000`）
- **溯源字段必须尽量保留**（切块合规页码依赖此，见 `09` §3.6）：
  - `page_idx`：MinerU 页索引，**0-based**；有则写入 block
  - `bbox`：可选，页面坐标 `[x0,y0,x1,y1]`
  - `text_level`：标题层级（MinerU 原样写入）；切块构造 `full_section_path` 时**编号启发优先于本字段**（见 `09` §3.6）
- `extract_version`：固定 `mineru-v1`

### 4.2 `blocks` JSON 形状

| 字段 | title / paragraph / list_item | table |
|------|-------------------------------|-------|
| `type` | `"title"` / `"paragraph"` / `"list_item"` | `"table"` |
| `order` | int | int |
| `text` | 纯文本 | — |
| `html` | — | 表格 HTML |
| `logical_table_id` | — | 可选 |
| `page_idx` | 建议必有（0-based） | 建议必有 |
| `bbox` | 可选 | 可选 |
| `text_level` | title 建议有 | — |

### 4.3 与切块的约定

- 切块层把 `title`、`paragraph`、`list_item` 都当作可拼接的文本块
- `table` 的 `html` 仅作切块输入；**写入 `rag_chunks` 前必须转为 Markdown**（见 `09`）
- `page_idx` / `bbox` / `text_level` 供切块写入 `page_num`、`full_section_path` 等（切块**不**再读 PDF；路径层级以 `09` 章节栈规则为准）
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
- **兜底**：若仍出现「相邻 table、中间无文本块」，且列结构一致 / 续表信号明确，则合并为一个 HTML，`merged_continuations` +1

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

- 抽取引擎：`mineru[pipeline]`（版本在实现时锁定，写入 `requirements.txt`）
- 运行环境：conda `rag-demo`；按 MinerU 官方文档安装模型与系统依赖（国内可用 `MINERU_MODEL_SOURCE=modelscope`）
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
- 对 MinerU 已合成的段落做脆弱启发式强拆（如示意句与小标题粘连）

## 10. 验收标准（企业级）

至少满足：

1. 引擎为 MinerU，`extract_version=mineru-v1`  
2. `blocks` 中存在 `title` / `paragraph` / `list_item` / `table` 区分（有标题的文档不得「全是 paragraph」）  
3. 不出现「完整句 + 半截后缀残留」成对入库（C5）  
4. 不出现单独 `°` 或明显拉丁乱码短行入库（C3/C4）  
5. 不合格表格不以乱码 HTML 入库（§6.2）  
6. 合格表格为可读中文（或源语言）HTML，可供 `09` 转 Markdown 并做行组切分  
7. title 章节号与正文间空格规范（覆盖单级/多级编号，C2）  
8. 源 PDF 水印 / AI 免责声明不入库（C9）  
9. 同 `doc_id` 重复抽取覆盖 `rag_documents`  
10. 切块仍不读 PDF；`/rag/extract` 请求字段保持不变  
11. 切块后表格 `chunk_text` 为 Markdown（验收见 `09` §8）

## 11. 重抽约定

- 抽取规则或 `extract_version` 变更后，已有文档须重新执行：`/rag/extract` → `/rag/chunks` → `/rag/index/build`  
- 新旧 `blocks` schema 不混用同一评测基线；重抽后重跑评测并更新 `06` baseline
