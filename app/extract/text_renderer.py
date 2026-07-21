from app.extract.models import ContentBlock

_TEXT_TYPES = {"title", "paragraph", "list_item"}


def render_full_text(blocks: list[ContentBlock]) -> str:
    """按块顺序渲染 full_text，供切块回退路径读取。"""
    parts: list[str] = []
    for block in blocks:
        if block.block_type in _TEXT_TYPES:
            text = (block.text or "").strip()
            if text:
                parts.append(text)
            continue
        if block.block_type == "table":
            html = (block.html or "").strip()
            if html:
                parts.append(html)
    return "\n\n".join(parts).strip()
