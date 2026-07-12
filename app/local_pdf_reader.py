from pathlib import Path

from pypdf import PdfReader


def read_pdf_text(pdf_path: str) -> str:
    """读取本地 PDF 并拼接为纯文本。"""
    file_path = Path(pdf_path)
    if not file_path.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

    reader = PdfReader(str(file_path))
    page_texts: list[str] = []
    for page in reader.pages:
        page_texts.append((page.extract_text() or "").strip())
    return "\n".join(text for text in page_texts if text).strip()
