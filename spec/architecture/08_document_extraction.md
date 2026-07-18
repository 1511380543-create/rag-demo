# 文档抽取设计说明

> PDF 抽取能力规范。流程阶段见 `03`；表结构见 `02`；接口见 `01`。

## 1. 目标与边界

- 将 PDF 抽取为 MySQL 中间层 `rag_documents`，与切块解耦
- 切块层只读 `full_text`，沿用现有 `SentenceSplitter`，本阶段不改切块逻辑
- 表格以 HTML 存储，来源为 Unstructured，不自研 PDF→HTML 转换
- 跨页续表在抽取阶段合并后再持久化

## 2. 处理步骤

1. **加载**：LlamaIndex `SimpleDirectoryReader` + `UnstructuredReader`（`split_documents=True`，`strategy=hi_res`，开启表格结构推断）
2. **清洗**：TextCleaner 链（LlamaIndex `TransformComponent`），仅处理段落元素
3. **续表**：相邻 Table 元素合并为单个 HTML
4. **持久化**：写入 `blocks` + `full_text`，覆盖同 `doc_id` 旧记录

## 3. 关键规则

### 3.1 元素映射

| 类型 | 写入字段 |
|------|---------|
| 正文（Title / NarrativeText 等） | `block.text` |
| 表格（Table） | `block.html`（取自 `metadata.text_as_html`） |

- `extract_version`：`llamaindex-unstructured-v1`

### 3.2 清洗（TextCleaner）

| 规则 | 适用范围 |
|------|---------|
| 页眉页脚去除 | 非 Table |
| 目录页跳过 | 非 Table |
| 中文断行合并 | 非 Table |
| 空元素丢弃 | 全部 |

Table 元素跳过文本类清洗。清洗统计写入 `extract_report`。

### 3.3 表格与续表

- 存储格式：HTML，表标题用 `<caption>`，不用 JSON 二维数组
- 续表判定：相邻 Table 之间无段落，且满足「续表」字样 / 重复表头 / 列结构一致等信号
- 合并结果：保留首个 `<caption>` 与 `<thead>`，后续行追加到同一 `<tbody>`，输出一个 table block

### 3.4 与切块的关系

- `full_text`：由 blocks 按序拼接（段落文本 + 表格 HTML），是切块唯一输入
- `blocks`：结构化存档，供后续迭代；本阶段切块不直接读 blocks

## 4. 非目标

- 切块层 HTML 感知切分
- 扫描件 OCR
- pdfplumber / 自研表格转换
- 在线增量热更新索引

## 5. 验收标准

- 抽取走 LlamaIndex + Unstructured 集成路径
- 表格 HTML 来自 Unstructured，跨页续表合并为单个 HTML
- TextCleaner 不破坏 Table 元素
- 切块只读 `full_text`，行为与现网一致
- 同 `doc_id` 重复抽取覆盖 `rag_documents`
