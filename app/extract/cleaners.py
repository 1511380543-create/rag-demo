"""企业级文本清洗链（C1–C9）与表格质量门禁。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from html import unescape

from app.extract.nodes import ExtractNode

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_ALNUM = re.compile(r"[0-9A-Za-z]")
_LATIN = re.compile(r"[A-Za-z]")
_SYMBOL_ONLY = re.compile(r"^[\W_]+$", re.UNICODE)
_TOC_DOT_LINE = re.compile(r"^.{0,40}[\.·…\s]{3,}.{0,20}\d+\s*$")
_TAG = re.compile(r"<[^>]+>")
_HEADER_FOOTER_MAX_LEN = 30
# OCR 常见：汉字之间被插入空格（如「目 的」）
_CJK_GAP = re.compile(
    r"(?<=[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff])"
    r"\s+"
    r"(?=[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff])"
)
# 章节号与标题正文粘连（如「1.3协议」「3.通用」→ 补空格），仅用于 title
_TITLE_NUM_GAP = re.compile(r"^(\d+(?:\.\d+)*\.?)(?=[^\s\d.])")
# 正文被当成 paragraph 的列表项前缀（bullet / 编号）
_LIST_PREFIX = re.compile(
    r"^(?:"
    r"[•·●○◆▪►➤]\s*"
    r"|[-–—]\s+"
    r"|\d+[\.、．]\s*"
    r"|[（(]\d+[）)]\s*"
    r"|[一二三四五六七八九十]+[、．.]\s*"
    r")"
)
# 源 PDF / 生成工具水印与免责声明（整块丢弃）
_WATERMARK_PATTERNS = (
    re.compile(r"^\(?\s*注\s*[:：].*AI\s*生成", re.IGNORECASE),
    re.compile(r"文档部分内容可能由\s*AI\s*生成", re.IGNORECASE),
    re.compile(r"本(?:文档|内容).{0,20}由\s*AI\s*(?:生成|撰写)", re.IGNORECASE),
)


@dataclass
class CleanStats:
    """清洗与门禁计数。"""

    dropped_elements: int = 0
    dropped_fragments: int = 0
    dropped_garbled: int = 0
    table_quality_failed: int = 0
    discarded_other: int = 0


def is_table_node(node: ExtractNode) -> bool:
    return node.node_type == "table"


def apply_text_cleaners(nodes: list[ExtractNode], stats: CleanStats) -> list[ExtractNode]:
    """按 C1→C9 顺序清洗文本类节点；表格原样保留，供后续门禁处理。"""
    current = [_normalize_node_unicode(node) for node in nodes]  # C1
    current = _whitespace_and_empty(current, stats)  # C2（含汉字断字空格修复）
    current = _drop_junk_fragments(current, stats)  # C3
    current = _drop_garbled_lines(current, stats)  # C4
    current = _drop_suffix_duplicates(current, stats)  # C5
    current = _drop_header_footer(current, stats)  # C6
    current = _drop_toc(current, stats)  # C7
    current = _reclassify_list_items(current)  # C8
    current = _drop_watermarks(current, stats)  # C9
    return current


def filter_tables_by_quality(
    nodes: list[ExtractNode],
    stats: CleanStats,
) -> list[ExtractNode]:
    """表格质量门禁：不合格 HTML 丢弃，不入库。"""
    kept: list[ExtractNode] = []
    for node in nodes:
        if not is_table_node(node):
            kept.append(node)
            continue
        html = str(node.metadata.get("table_html") or node.text or "").strip()
        if not html:
            stats.table_quality_failed += 1
            stats.dropped_elements += 1
            continue
        if _is_garbled_table(html):
            stats.table_quality_failed += 1
            stats.dropped_elements += 1
            continue
        kept.append(node)
    return kept


def _normalize_node_unicode(node: ExtractNode) -> ExtractNode:
    if is_table_node(node):
        return node
    text = unicodedata.normalize("NFKC", node.text or "")
    if text == node.text:
        return node
    return ExtractNode(
        text=text,
        node_type=node.node_type,
        metadata=dict(node.metadata),
        node_id=node.node_id,
    )


def _whitespace_and_empty(nodes: list[ExtractNode], stats: CleanStats) -> list[ExtractNode]:
    cleaned: list[ExtractNode] = []
    for node in nodes:
        if is_table_node(node):
            cleaned.append(node)
            continue
        text = " ".join((node.text or "").split()).strip()
        text = _CJK_GAP.sub("", text)
        if node.node_type == "title":
            text = _TITLE_NUM_GAP.sub(r"\1 ", text)
        if not text:
            stats.dropped_elements += 1
            continue
        cleaned.append(
            ExtractNode(
                text=text,
                node_type=node.node_type,
                metadata=dict(node.metadata),
                node_id=node.node_id,
            )
        )
    return cleaned


def _reclassify_list_items(nodes: list[ExtractNode]) -> list[ExtractNode]:
    """
    C8：MinerU 常把 bullet/编号列表打成 paragraph，按行首标记回标为 list_item。
    不改动 title（避免把「1. 手册总则」误标成列表）。
    """
    cleaned: list[ExtractNode] = []
    for node in nodes:
        if node.node_type != "paragraph":
            cleaned.append(node)
            continue
        text = node.text or ""
        if _LIST_PREFIX.match(text):
            cleaned.append(
                ExtractNode(
                    text=text,
                    node_type="list_item",
                    metadata=dict(node.metadata),
                    node_id=node.node_id,
                )
            )
            continue
        cleaned.append(node)
    return cleaned


def _drop_watermarks(nodes: list[ExtractNode], stats: CleanStats) -> list[ExtractNode]:
    """C9：丢弃源 PDF 水印 / AI 生成免责声明等噪声块。"""
    cleaned: list[ExtractNode] = []
    for node in nodes:
        if is_table_node(node):
            cleaned.append(node)
            continue
        text = (node.text or "").strip()
        if any(pattern.search(text) for pattern in _WATERMARK_PATTERNS):
            stats.dropped_elements += 1
            continue
        cleaned.append(node)
    return cleaned


def _drop_junk_fragments(nodes: list[ExtractNode], stats: CleanStats) -> list[ExtractNode]:
    cleaned: list[ExtractNode] = []
    for node in nodes:
        if is_table_node(node):
            cleaned.append(node)
            continue
        text = node.text or ""
        if _is_junk_fragment(text):
            stats.dropped_fragments += 1
            stats.dropped_elements += 1
            continue
        cleaned.append(node)
    return cleaned


def _is_junk_fragment(text: str) -> bool:
    if len(text) <= 1:
        return True
    if _SYMBOL_ONLY.match(text):
        return True
    # 过短且无中文、无字母数字
    if len(text) <= 3 and not _CJK.search(text) and not _ALNUM.search(text):
        return True
    return False


def _drop_garbled_lines(nodes: list[ExtractNode], stats: CleanStats) -> list[ExtractNode]:
    cleaned: list[ExtractNode] = []
    for node in nodes:
        if is_table_node(node):
            cleaned.append(node)
            continue
        if _is_garbled_text(node.text or ""):
            stats.dropped_garbled += 1
            stats.dropped_elements += 1
            continue
        cleaned.append(node)
    return cleaned


def _is_garbled_text(text: str) -> bool:
    """短文本中拉丁占比异常高、几乎无中日韩 → 视为乱码行。"""
    if len(text) > 80:
        return False
    cjk = len(_CJK.findall(text))
    latin = len(_LATIN.findall(text))
    if cjk >= 2:
        return False
    if latin >= 8 and latin >= max(cjk * 4, 1) and cjk == 0:
        return True
    # 典型版权/乱码碎片：大量拉丁 + 符号，几乎无 CJK
    if len(text) <= 40 and latin >= 6 and cjk == 0 and not re.search(r"[\u4e00-\u9fff]", text):
        # 保留正常英文短句：至少有空格分隔的词且不太像乱码
        words = [w for w in text.split() if w]
        if len(words) <= 1 and latin >= 8:
            return True
        if re.search(r"[A-Z]{3,}/[A-Z]{2,}", text):
            return True
    return False


def _drop_suffix_duplicates(nodes: list[ExtractNode], stats: CleanStats) -> list[ExtractNode]:
    cleaned: list[ExtractNode] = []
    last_text = ""
    for node in nodes:
        if is_table_node(node):
            cleaned.append(node)
            last_text = ""
            continue
        text = node.text or ""
        if last_text and _is_suffix_duplicate(last_text, text):
            stats.dropped_fragments += 1
            stats.dropped_elements += 1
            continue
        cleaned.append(node)
        last_text = text
    return cleaned


def _is_suffix_duplicate(previous: str, current: str) -> bool:
    """当前块是上一文本块的后缀，或上一块以当前块结尾且当前明显更短。"""
    if not current or not previous:
        return False
    if current == previous:
        return True
    if len(current) >= len(previous):
        return False
    # 当前是上一块后缀
    if previous.endswith(current) and len(current) <= max(len(previous) // 2, 8):
        return True
    # 上一块以当前结尾，且当前明显更短（断行残留）
    if previous.endswith(current) and len(current) < 40 and len(current) < len(previous) * 0.6:
        return True
    return False


def _drop_header_footer(nodes: list[ExtractNode], stats: CleanStats) -> list[ExtractNode]:
    text_counts: dict[str, int] = {}
    for node in nodes:
        if is_table_node(node):
            continue
        normalized = " ".join((node.text or "").split())
        if not normalized or len(normalized) > _HEADER_FOOTER_MAX_LEN:
            continue
        text_counts[normalized] = text_counts.get(normalized, 0) + 1

    repeated = {text for text, count in text_counts.items() if count >= 2}
    if not repeated:
        return nodes

    cleaned: list[ExtractNode] = []
    for node in nodes:
        if is_table_node(node):
            cleaned.append(node)
            continue
        normalized = " ".join((node.text or "").split())
        if normalized in repeated:
            stats.dropped_elements += 1
            continue
        cleaned.append(node)
    return cleaned


def _drop_toc(nodes: list[ExtractNode], stats: CleanStats) -> list[ExtractNode]:
    cleaned: list[ExtractNode] = []
    for node in nodes:
        if is_table_node(node):
            cleaned.append(node)
            continue
        text = (node.text or "").strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) >= 4:
            dot_lines = sum(1 for line in lines if _TOC_DOT_LINE.match(line))
            if dot_lines / len(lines) >= 0.6:
                stats.dropped_elements += 1
                continue
        # 单行点线目录
        looks_like_toc = bool(_TOC_DOT_LINE.match(text)) or (
            ("…" in text or re.search(r"\.{4,}", text)) and bool(re.search(r"\d+\s*$", text))
        )
        if looks_like_toc and len(text) < 80:
            stats.dropped_elements += 1
            continue
        cleaned.append(node)
    return cleaned


def _is_garbled_table(html: str) -> bool:
    plain = unescape(_TAG.sub(" ", html))
    plain = " ".join(plain.split())
    if not plain:
        return True
    row_count = len(re.findall(r"<tr\b", html, flags=re.IGNORECASE))
    cjk = len(_CJK.findall(plain))
    latin = len(_LATIN.findall(plain))
    # 多行表但几乎无中日韩、拉丁乱码特征明显 → 不合格
    if row_count >= 2 and cjk < 4 and latin >= 20 and latin > cjk * 5:
        return True
    if row_count >= 3 and cjk == 0 and latin >= 15:
        return True
    return False
