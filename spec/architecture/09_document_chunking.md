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
| 上限 | 正常文本/表格 chunk：`len(chunk_text) ≤ chunk_size` |
| 整句/整行例外 | **单个**句子或**单行**表格数据本身超过 `chunk_size` 时，允许整句/整行单独成块 |
| 标题粘性 | `title`（可连续多个）与紧随正文/列表必须落在**同一文本 chunk 的开头**，禁止「上块只留标题、下块从正文起」 |
| 表前标题 | 表格前的连续 `title` **一律**挂到该表首个 chunk 前缀（不限长度），表与标题不得拆成「纯标题文本块 + 无标题表」 |
| 下限 | 长度 &lt; `min_chunk_chars`（默认 20）不得单独入库：优先并入前一块文本 |
| 去重 | 相邻文本 chunk 若存在明显前后缀重叠，去掉下一块开头的重复前缀 |

### 3.3 兜底递归切分（权威）

对每个**章节段**（连续 title 作 header + 随后正文/列表作 body）：

```text
若有 title_header：
  → 先按 (chunk_size - header预留) 递归切 body
  → 将 title_header 粘到第一个 body 分片开头
否则：
  → 对 body 直接递归切分
递归层级：空行（\n\n）→ 句子（。！？；.!?;）→ 字符硬切（overlap 默认 20）
```

`full_text` 回退路径无结构化 title，仅做递归切分。

### 3.4 表格 → Markdown 行组

1. `block.html` → Markdown 管道表  
2. 无 `<thead>` 时首行当表头；拆块时**每块重复表头**  
3. 按 `chunk_size` 对数据行分组（预算含表头/caption/前缀标题）  
4. **禁止** HTML 标签进入 `chunk_text`

| metadata | 说明 |
|----------|------|
| `block_type` | `"table"` |
| `chunk_kind` | `"table_rows"` / `"table_fallback"` |
| `table_format` | `"markdown"` |
| `logical_table_id` | 有则透传 |
| `table_row_start` / `table_row_end` | 数据行范围 |

### 3.5 文本 chunk metadata

| 字段 | 值 |
|------|-----|
| `block_type` | `"paragraph"` |
| `chunk_kind` | `"paragraph"` |
| `section_title` | 本组最近 `title`（建议写入） |

## 4. 配置

| 参数 | 默认 | 说明 |
|------|------|------|
| `chunk_size` | 500 | 文本与表格共用上限 |
| `chunk_overlap` | 20 | **仅**字符硬切层使用；装箱层默认无 overlap |
| `min_chunk_chars` | 20 | 过短合并阈值 |

## 5. 非目标（本阶段）

- 父子分层索引（parent/child 两级检索）
- 用正则猜标题
- chunk 存 HTML 表
- 切块读 PDF
- mock / 臆造原文

## 6. 验收标准

1. `title` / `list_item` / `paragraph` 均进入文本流，关键事实可命中  
2. 表格均为 Markdown，无 `<table>`  
3. 拆表每块带表头（含无 thead）  
4. 标题与紧随正文不拆块；表前 title 出现在对应表格 chunk 前缀中  
5. 无 &lt; `min_chunk_chars` 的孤立无信息文本块  
6. 除整句/整行例外外，chunk 长度 ≤ `chunk_size`  
7. 相邻文本块无明显大段前后缀重复  
8. 同 `doc_id` 覆盖写；`/rag/chunks` 契约不变  

## 7. 实现对齐清单

| # | 要求 | 优先级 |
|---|------|--------|
| A | 文本流含 title/list_item/paragraph | P0 |
| B | 表格 Markdown + 重复表头 | P0 |
| C | 递归切分（空行→句→字） | P0 |
| D | 标题粘性；表前 title 挂表前缀 | P0 |
| E | 过短合并；长度上限 + 相邻去重 | P1 |
| F | section_title metadata | P2 |
