from app.extract.models import ContentBlock


def render_full_text(blocks: list[ContentBlock]) -> str:
    """按块顺序渲染 full_text，供切块层读取。"""
    parts: list[str] = []
    for block in blocks:
        if block.block_type == "paragraph":
            text = (block.text or "").strip()
            if text:
                parts.append(text)
            continue
        html = (block.html or "").strip()
        if html:
            parts.append(html)
    return "\n\n".join(parts).strip()
