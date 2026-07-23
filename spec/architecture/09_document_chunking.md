# 文档切块设计说明

> 切块能力规范（权威）。流程见 `03`；表结构见 `02`；接口见 `01`；抽取产出见 `08`。  
> 实现必须以本文为准；与代码不一致时，**先改代码对齐本文**，不得以降级验收绕过。  
> **本阶段策略**：长度约束 + 兜底递归切分；**父子分层索引本阶段不做**。

## 1. 目标与边界

- 从 `rag_documents` 切分写入 `rag_chunks`，与抽取、索引构建解耦
- **有 blocks**：连续文本块（`title` / `paragraph` / `list_item`）先拼再切；表格单独按行组切
- **无 blocks**：整篇 `full_text` 走同一套递归切分（仅兜底）
- **表格进 chunk 的格式：Markdown**；`blocks` 里仍是 HTML（见 `08`）
- 切块不读本地 PDF
- **不得丢弃** `title` / `list_item`

## 2. 路径选择

1. 读 `blocks` 与 `full_text`
2. `blocks` 非空 → 走第 3 节
3. `blocks` 空且 `full_text` 非空 → 整篇递归切分（`chunk_kind=full_text_fallback`）
4. 两者皆空 → `CHUNK_INGEST_ERROR`

## 3. 有 blocks 时怎么切

### 3.0 文本块类型（硬约束）

| `blocks[].type` | 是否进入文本流 | 说明 |
|-----------------|----------------|------|
| `title` | **必须** | 章节/报文标题 |
| `paragraph` | **必须** | 正文 |
| `list_item` | **必须** | 列表项 |
| `table` | 否 | 走 §3.4，不与文本混块 |

### 3.1 扫描与刷新规则

按 `order` 从前往后扫：

1. **遇到文本块**：追加到临时列表，此时不生成 chunk。
2. **遇到表格**：
   - 先处理临时列表（§3.2 / §3.3）；
   - 再切表格（§3.4）。
3. **文档结束**：处理剩余临时列表。

文本与表格严格分离：文本 chunk 不含表；表格 chunk 为 Markdown。

### 3.2 长度约束（权威）

| 规则 | 要求 |
|------|------|
| 硬上限 | 表格行组、无标题兜底文本：优先 `len(chunk_text) ≤ chunk_size` |
| 章节软上限 | 有 `title` 的同节（标题+正文）：总长 ≤ `section_soft_max`（默认 1000）时**整节一块**，允许超过 `chunk_size` |
| 整句/整行例外 | **单个**句子或**单行**表格数据本身超过上限时，允许整句/整行单独成块 |
| 标题粘性 | `title`（可连续多个）与紧随正文/列表必须落在**同一文本 chunk 的开头**；同节被切开时，**每一块** `chunk_text` 都必须带标题前缀 |
| 表前标题 | 表格前的连续 `title` **一律**挂到该表首个 chunk 前缀（不限长度），表与标题不得拆成「纯标题文本块 + 无标题表」 |
| 下限 | 长度 &lt; `min_chunk_chars`（默认 20）不得单独入库：优先并入前一块文本 |
| 去重 | 相邻文本 chunk 若存在明显前后缀重叠，去掉下一块开头的重复前缀 |

### 3.3 兜底递归切分（权威）

对每个**章节段**（连续 title 作 header + 随后正文/列表作 body）：

```text
若有 title_header：
  → 整节长度 ≤ section_soft_max：整节一块（可超过 chunk_size）
  → 否则：按 (section_soft_max - header预留) 递归切 body
  → 将 title_header 粘到**每一个** body 分片开头
否则：
  → 对 body 直接按 chunk_size 递归切分
递归层级：空行（\n\n）→ 句子（。！？；.!?;）→ 软标点（，、；：换行）→ 字符硬切（overlap 默认 20）
硬切规则：在窗口内优先回看软边界落刀；找不到再按字符切；长度 &lt; 20 的尾块并入上一块（可轻微超限）
```

`full_text` 回退路径无结构化 title，仅做递归切分。

### 3.4 表格 → Markdown 行组

1. `block.html` → Markdown 管道表  
2. 无 `<thead>` 时首行当表头；拆块时**每块重复表头**  
3. 按 `chunk_size` 对数据行分组（预算含表头/caption/前缀标题）  
4. **禁止** HTML 标签进入 `chunk_text`

表格专用 metadata 见 §3.6（`chunk_kind=table_rows|table_fallback`）。

### 3.5 文本 chunk 类型

文本路径写入 `chunk_kind=paragraph`（含 title/list_item 粘连后的文本块）。  
章节与页码等通用字段见 §3.6。

### 3.6 Chunk metadata（企业级约定，权威）

> 切块**仍不读 PDF**。页码/坐标来自 `rag_documents.blocks`（见 `08`）；文档归档属性权威在 `rag_documents`，切块冗余拷贝便于向量侧过滤。  
> 类型统一用 `chunk_kind`（含 `paragraph` / `table_rows` / `table_fallback` / `full_text_fallback`），便于文本与表格路径共用一套过滤约定。

#### 3.6.1 字段总表

**A. 核心定位（始终）**

| 字段 | 类型 | 说明 |
|------|------|------|
| `doc_id` | string | 业务文档 ID |
| `source` / `category` | string | 有则透传文档 metadata；本地 PDF 建议 `source=local_pdf`、`category=pdf` |
| `file_path` | string | 源 PDF 路径 |
| `chunk_index` | int | 文档内序号 |
| `chunk_kind` | string | `paragraph` / `table_rows` / `table_fallback` / `full_text_fallback` |
| `section_title` | string \| null | 当前叶子标题；**表前 title 挂表时须与 `chunk_text` 前缀一致** |
| `char_count` | int | `len(chunk_text)`，不依赖分词器，调优/过滤首选 |
| `token_count` | int | 估算 token（算法名 `cjk_char_latin_word_v1`：CJK 按字、拉丁按空白分词） |
| `chunk_overlap` | int | 本块实际 overlap 字符数；装箱层多为 `0`，硬切层为配置值 |
| `prev_chunk_index` | int \| null | 同文档上一块；首块 `null`（整篇切完后回填） |
| `next_chunk_index` | int \| null | 同文档下一块；末块 `null` |
| `has_protocol_code` | bool | 是否含协议报文/十六进制片段（启发式，始终写入） |

**B. 溯源与章节**

| 字段 | 类型 | 说明 |
|------|------|------|
| `page_num` | int \| null | 起始页，PDF **1-based**（blocks.`page_idx`+1） |
| `page_end` | int \| null | 结束页；单页时等于 `page_num` |
| `is_cross_page` | bool | `page_end > page_num`（无页信息时为 `false`） |
| `bbox` | number[4] \| null | `[x0,y0,x1,y1]`；单 block 有坐标则透传，跨 block 合并时可为 `null` |
| `full_section_path` | string[] | 完整章节路径；无标题时 `[]` |
| `parent_section` | string \| null | 上一级父章节；无父为 `null` |

章节栈规则（权威）：

1. 扫描 `title` 维护栈；能匹配 `1` / `1.1` / `4.2.1` 等形式时，**编号启发优先于** blocks.`text_level`（避免 MinerU 扁平 level 把中间层弹出）
2. 无编号标题在栈空时作为文档根（level=0），例如手册总标题
3. 遇表格：先 flush 表前正文段，再将表前连续 `title` 入栈，再写表格 chunk 的 `section_title` / `full_section_path`（与 `chunk_text` 前缀一致）

**C. 文档属性（冗余拷贝，权威在 `rag_documents`）**

| 字段 | 类型 | 说明 |
|------|------|------|
| `doc_version` | string \| null | 手册版本（文档 metadata 有则透传） |
| `create_time` | string \| null | 入库时间 ISO-8601，取自 `rag_documents.created_at` |
| `update_time` | string \| null | 更新时间 ISO-8601，取自 `rag_documents.updated_at` |
| `access_group` | string[] | 权限分组，缺省 `["rd"]`；约定：`rd` / `ops` / `after_sales` |

**D. 表格专用（仅 `table_*`）**

| 字段 | 类型 | 说明 |
|------|------|------|
| `table_format` | string | 固定 `"markdown"` |
| `logical_table_id` | string \| null | 透传 |
| `table_row_start` / `table_row_end` | int | 数据行范围（0-based，含端点） |
| `table_cols` | int \| null | 列数（表头解析；失败为 `null`） |

#### 3.6.2 示例 JSON（文本）

```json
{
  "doc_id": "pdf-obd-809",
  "source": "local_pdf",
  "category": "pdf",
  "file_path": "docs/OBD设备JT_T 809协议虚拟技术手册.pdf",
  "chunk_kind": "paragraph",
  "chunk_index": 15,
  "section_title": "4.2.1 车辆OBD工况数据上报(0x6001)",
  "char_count": 980,
  "token_count": 426,
  "chunk_overlap": 180,
  "prev_chunk_index": 14,
  "next_chunk_index": 16,
  "page_num": 36,
  "page_end": 36,
  "is_cross_page": false,
  "bbox": [58, 240, 540, 780],
  "full_section_path": [
    "OBD设备JT/T 809协议虚拟技术手册",
    "4. 核心报文指令定义(OBD设备专用)",
    "4.2 OBD车辆业务报文",
    "4.2.1 车辆OBD工况数据上报(0x6001)"
  ],
  "parent_section": "4.2 OBD车辆业务报文",
  "has_protocol_code": true,
  "doc_version": "V2.3",
  "create_time": "2026-06-01T09:00:00",
  "update_time": "2026-06-15T10:20:00",
  "access_group": ["rd", "after_sales"]
}
```

表格 chunk：在以上字段上增加 `table_format` / `logical_table_id` / `table_row_start` / `table_row_end` / `table_cols`，`chunk_kind` 为 `table_rows` 或 `table_fallback`；若有表前 title，则 `section_title` 为该 title，且出现在 `chunk_text` 开头。

## 4. 配置

| 参数 | 默认 | 说明 |
|------|------|------|
| `chunk_size` | 500 | 无标题文本与表格行组的装箱上限 |
| `chunk_overlap` | 20 | **仅**字符硬切层使用；装箱层默认无 overlap |
| `min_chunk_chars` | 20 | 过短合并阈值 |
| `section_soft_max` | 1000 | 有标题的同节软上限；≤ 此值整节一块（可超过 `chunk_size`） |

## 5. 非目标（本阶段）

- 父子分层索引（parent/child 两级检索）
- 用正则**臆造不存在的**正文标题（允许对已有 title 文本做编号层级启发，不得伪造正文）
- chunk 存 HTML 表
- 切块读 PDF（页码只来自 blocks）
- mock / 臆造原文
- 在 chunk 内另建与 `rag_documents` 冲突的权限/版本真相源

## 6. 验收标准

1. `title` / `list_item` / `paragraph` 均进入文本流，关键事实可命中  
2. 表格均为 Markdown，无 `<table>`  
3. 拆表每块带表头（含无 thead）  
4. 标题与紧随正文不拆块；表前 title 出现在对应表格 chunk 前缀中，且 `section_title` / `full_section_path` 与该前缀一致  
5. 无 &lt; `min_chunk_chars` 的孤立无信息文本块  
6. 有标题同节：总长 ≤ `section_soft_max` 时整节一块（可超过 `chunk_size`）；超过后切开时**每一块**均带标题前缀；表格/无标题路径除整句整行例外外 ≤ `chunk_size`  
7. 相邻文本块无明显大段前后缀重复  
8. 同 `doc_id` 覆盖写；`/rag/chunks` 契约不变  
9. metadata 必有 `chunk_kind` / `char_count` / `token_count` / `prev_chunk_index` / `next_chunk_index` / `has_protocol_code` / `access_group`  
10. 有页信息时带 `page_num` / `page_end` / `is_cross_page`；多层编号标题下 `full_section_path` 须保留中间层（不得恒为仅「文档标题 + 叶子」）  

## 7. 实现对齐清单

| # | 要求 | 状态 |
|---|------|------|
| A–E | 文本流 / 表 MD / 递归 / 标题粘性 / 过短合并 | 已落地 |
| G–L | §3.6 metadata（含编号优先章节栈、表前 title 同步） | 已落地 |
