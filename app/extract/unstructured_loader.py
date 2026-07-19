from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from unstructured.documents.elements import Element

EXTRACT_VERSION = "unstructured-v1"


def load_pdf_elements(file_path: str) -> list["Element"]:
    """通过 unstructured.partition_pdf 加载 PDF 元素。"""
    normalized = file_path.strip()
    if not normalized.lower().endswith(".pdf"):
        raise ValueError("仅支持 PDF 文档抽取，请传入 .pdf 文件路径")

    pdf_path = Path(normalized)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {normalized}")

    from unstructured.partition.pdf import partition_pdf

    return partition_pdf(
        filename=str(pdf_path),
        strategy="hi_res",
        infer_table_structure=True,
    )
