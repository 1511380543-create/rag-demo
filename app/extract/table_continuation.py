import re
from html import escape, unescape

from app.extract.models import ContentBlock

_CONTINUATION_MARKERS = ("续表", "（续）", "(续)")
_TABLE_TAG = re.compile(r"<table\b[^>]*>.*?</table>", re.IGNORECASE | re.DOTALL)
_THEAD = re.compile(r"<thead\b[^>]*>.*?</thead>", re.IGNORECASE | re.DOTALL)
_TBODY = re.compile(r"<tbody\b[^>]*>(?P<body>.*?)</tbody>", re.IGNORECASE | re.DOTALL)
_TR = re.compile(r"<tr\b[^>]*>.*?</tr>", re.IGNORECASE | re.DOTALL)
_TH = re.compile(r"<th\b[^>]*>(?P<text>.*?)</th>", re.IGNORECASE | re.DOTALL)
_TD = re.compile(r"<td\b[^>]*>(?P<text>.*?)</td>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


def merge_table_continuations(blocks: list[ContentBlock]) -> tuple[list[ContentBlock], int]:
    """合并相邻 table block，返回新 blocks 与合并次数。"""
    if not blocks:
        return [], 0

    merged: list[ContentBlock] = []
    merged_count = 0
    index = 0
    table_seq = 0

    while index < len(blocks):
        current = blocks[index]
        if current.block_type != "table" or not current.html:
            merged.append(current)
            index += 1
            continue

        combined_html = current.html
        logical_id = current.logical_table_id or f"tbl-{table_seq:03d}"
        page_idx = current.page_idx
        bbox = list(current.bbox) if current.bbox is not None else None
        table_seq += 1
        index += 1

        while index < len(blocks) and blocks[index].block_type == "table" and blocks[index].html:
            next_html = blocks[index].html or ""
            if not _should_merge(combined_html, next_html):
                break
            next_block = blocks[index]
            combined_html = _merge_table_html(combined_html, next_html)
            # 跨页合并：保留起始页，坐标不再单点有效
            if (
                page_idx is not None
                and next_block.page_idx is not None
                and next_block.page_idx != page_idx
            ):
                bbox = None
            elif bbox is not None and next_block.bbox != bbox:
                bbox = None
            merged_count += 1
            index += 1

        merged.append(
            ContentBlock(
                block_type="table",
                order=current.order,
                html=combined_html,
                logical_table_id=logical_id,
                page_idx=page_idx,
                bbox=bbox,
            )
        )

    for order, block in enumerate(merged):
        block.order = order
    return merged, merged_count


def _should_merge(first_html: str, second_html: str) -> bool:
    score = 40
    if any(marker in second_html for marker in _CONTINUATION_MARKERS):
        score += 60
    if _extract_header_signature(first_html) and _extract_header_signature(first_html) == _extract_header_signature(
        second_html
    ):
        score += 40
    return score >= 80


def _merge_table_html(first_html: str, second_html: str) -> str:
    first_table = _TABLE_TAG.search(first_html)
    second_table = _TABLE_TAG.search(second_html)
    if not first_table or not second_table:
        return first_html + "\n" + second_html

    first_body = _extract_tbody_rows(first_table.group(0))
    second_body = _extract_tbody_rows(second_table.group(0))
    merged_rows = first_body + second_body
    page_span = _merge_page_span(first_table.group(0), second_table.group(0))

    caption = _extract_caption(first_table.group(0))
    thead = _extract_thead(first_table.group(0))
    tbody = "".join(merged_rows)
    return (
        f'<table data-logical-id="{_extract_attr(first_table.group(0), "data-logical-id")}" '
        f'data-page-span="{page_span}" data-continued="true">'
        f"{caption}{thead}<tbody>{tbody}</tbody></table>"
    )


def _extract_tbody_rows(table_html: str) -> list[str]:
    tbody_match = _TBODY.search(table_html)
    if tbody_match:
        return _TR.findall(tbody_match.group("body"))
    rows = _TR.findall(table_html)
    if rows and _TH.search(rows[0]):
        return rows[1:]
    return rows


def _extract_caption(table_html: str) -> str:
    match = re.search(r"<caption\b[^>]*>.*?</caption>", table_html, re.IGNORECASE | re.DOTALL)
    return match.group(0) if match else ""


def _extract_thead(table_html: str) -> str:
    match = _THEAD.search(table_html)
    return match.group(0) if match else ""


def _extract_header_signature(table_html: str) -> tuple[str, ...]:
    thead = _extract_thead(table_html)
    if not thead:
        first_row = _TR.search(table_html)
        if not first_row:
            return tuple()
        thead = first_row.group(0)
    headers = _TH.findall(thead) or _TD.findall(thead)
    normalized = tuple(_strip_tags(item).strip() for item in headers)
    return tuple(item for item in normalized if item)


def _strip_tags(value: str) -> str:
    return unescape(_TAG.sub("", value)).strip()


def _extract_attr(table_html: str, attr_name: str) -> str:
    match = re.search(rf'{attr_name}="([^"]*)"', table_html)
    return match.group(1) if match else ""


def _merge_page_span(first_html: str, second_html: str) -> str:
    first_span = _extract_attr(first_html, "data-page-span")
    second_span = _extract_attr(second_html, "data-page-span")
    if first_span and second_span:
        return f"{first_span.split('-')[0]}-{second_span.split('-')[-1]}"
    return first_span or second_span or ""


def wrap_table_html(html: str, logical_table_id: str) -> str:
    """为 table HTML 补充逻辑表标识。"""
    table_match = _TABLE_TAG.search(html)
    if not table_match:
        safe_html = escape(html)
        return (
            f'<table data-logical-id="{logical_table_id}"><tbody>'
            f"<tr><td>{safe_html}</td></tr></tbody></table>"
        )
    table_html = table_match.group(0)
    if 'data-logical-id="' in table_html:
        return table_html
    updated = re.sub(
        r"<table\b",
        f'<table data-logical-id="{logical_table_id}"',
        table_html,
        count=1,
        flags=re.IGNORECASE,
    )
    return updated
