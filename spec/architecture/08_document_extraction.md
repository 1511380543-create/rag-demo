# 文档抽取设计说明

> PDF 抽取能力规范。流程阶段见 `03`；表结构见 `02`；接口见 `01`。

## 1. 目标与边界

- 将 PDF 抽取为 MySQL 中间层 `rag_documents`，与切块解耦
- 切块层只读 `full_text`，沿用现有 `SentenceSplitter`，本阶段不改切块逻辑
- 表格以 HTML 存储，来源为 Unstructured，不自研 PDF→HTML 转换
- 跨页续表在抽取阶段合并后再持久化
- **抽取加载**：直接使用原生 `unstructured` API，不经过 LlamaIndex Reader（避免版本兼容问题）

## 2. 处理步骤

1. **加载**：`unstructured.partition.pdf.partition_pdf`（`strategy=hi_res`，`infer_table_structure=True`），逐元素输出
2. **映射**：Unstructured `Element` → 内部节点（段落 / 表格），表格 HTML 取自 `metadata.text_as_html`
3. **清洗**：TextCleaner 链（项目内实现，见 `cleaners.py`），仅处理段落元素
4. **续表**：相邻 Table 元素合并为单个 HTML
5. **持久化**：写入 `blocks` + `full_text`，覆盖同 `doc_id` 旧记录

## 3. 关键规则

### 3.1 元素映射

| Unstructured 类型 | 写入字段 |
|-------------------|---------|
| 正文（Title / NarrativeText 等） | `block.text` |
| 表格（Table） | `block.html`（取自 `metadata.text_as_html`） |

- `extract_version`：`unstructured-v1`

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

## 4. 依赖说明

- Python 包（项目声明）：`unstructured==0.18.32`、`unstructured-inference>=1.5.2,<1.7`（推荐 `1.6.11`）
- PDF 解析相关包（本机按需安装）：`pdfminer.six`、`pdf2image`、`pillow`、`pillow-heif`、`unstructured-pytesseract` 等
- 系统依赖（hi_res 常用）：`poppler` 等，按 Unstructured 官方文档在本机安装
- 不使用 `unstructured[pdf]` 额外依赖组；LlamaIndex（`llama-index-core`）仅用于切块与向量索引
- 版本对齐：`unstructured 0.24.x` 需 `unstructured-inference>=1.6.12`；inference 若限定在 1.5–1.6 段，应使用 `unstructured 0.18.32`

## 5. 非目标

- 切块层 HTML 感知切分
- 扫描件 OCR
- pdfplumber / 自研表格转换
- 在线增量热更新索引
- LlamaIndex `UnstructuredReader` / `SimpleDirectoryReader` 集成路径

## 6. 验收标准

- 抽取走原生 `unstructured.partition_pdf` 路径
- 表格 HTML 来自 Unstructured，跨页续表合并为单个 HTML
- TextCleaner 不破坏 Table 元素
- 切块只读 `full_text`，行为与现网一致
- 同 `doc_id` 重复抽取覆盖 `rag_documents`
